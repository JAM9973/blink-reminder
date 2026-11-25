"""입력, C 판정, 화면, 기록을 순서대로 연결한다."""

from datetime import datetime
import time

from daily_log import DEFAULT_LOG_DIR, DailyRecorder
from desktop_controls import DesktopControls
from engine import BlinkEngine
from input_tracking import ensure_model, open_camera, read_eye_sample, draw_eye_points
from measurement_log import FrameRate, SessionRecorder
from notifications import NotificationManager as EyeNotice
from notification_settings import MODES as NOTIFICATION_MODES, load_mode, save_mode
from preview_window import PreviewWindow


class BlinkApplication:
    def __init__(self, args):
        self.args = args
        self.desktop = args.desktop or args.background
        self.window_hidden = args.background
        self.preview_requested = args.preview if self.desktop else True
        self.preview_visible = self.preview_requested and not self.window_hidden
        self.show_landmarks = not args.no_landmarks
        self.paused = False
        self.last_result = None
        self.last_frame = None
        self.previous_timestamp = -1
        self.frame_rate = FrameRate()
        self.capture = self.notice = self.controls = self.recorder = None
        self.daily_recorder = None if args.no_csv else DailyRecorder(DEFAULT_LOG_DIR)
        self.daily_recording_error = False
        self.recording_error = False
        self.pending_actions = []
        self.notification_mode, self.notification_warning = (
            load_mode() if args.notification is None else (args.notification, ""))

    def run(self):
        try:
            import cv2
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
        except ImportError as exc:
            raise RuntimeError("필요한 패키지가 없습니다. python -m pip install -r requirements.txt") from exc
        self.cv2, self.mp = cv2, mp
        self.preview = PreviewWindow(cv2)
        model = ensure_model(self.args.model)
        options = vision.FaceLandmarkerOptions(
            # 한글 경로도 읽을 수 있도록 모델 파일의 내용을 전달한다.
            base_options=mp_python.BaseOptions(model_asset_buffer=model.read_bytes()),
            running_mode=vision.RunningMode.VIDEO, num_faces=1,
            min_face_detection_confidence=.5, min_face_presence_confidence=.5,
            min_tracking_confidence=.5)
        self.capture = open_camera(cv2, self.args.camera)
        print("키 조작: 영상 창을 클릭하고 영문 입력 상태에서 L(좌표), Q/Esc(종료)를 누르세요.")
        print("영상 아래 Points / Exit 버튼으로도 좌표 전환과 종료를 할 수 있습니다.")
        if self.desktop:
            print("Pause는 측정을 멈추고, Hide나 기본 창 X는 트레이로 숨깁니다.")
        print(f"판정 모드: {self.args.mode}")
        try:
            self.notice = EyeNotice()
            self.notice.set_mode(self.notification_mode)
            if self.desktop:
                self.controls = DesktopControls(self.notice.root, hidden=self.args.background)
            with BlinkEngine(self.args.min_blinks, self.args.closed_ear, self.args.open_ear,
                             self.args.low_seconds, self.args.cooldown, mode=self.args.mode) as engine, \
                    vision.FaceLandmarker.create_from_options(options) as landmarker:
                self.engine, self.landmarker = engine, landmarker
                self._open_recording(model)
                self._save_control("start")
                self._loop()
        finally:
            self._close()

    def _loop(self):
        while True:
            self.notice.update()
            actions = self.pending_actions + (self.controls.poll() if self.controls else [])
            self.pending_actions = []
            if "quit" in actions:
                self._save_control("quit")
                break
            for action in actions:
                self._handle_action(action)
            self._update_controls()
            if self.paused:
                self._record_daily(datetime.now().astimezone())
                self._show_paused_frame()
                self._read_preview_input(paused=True)
                time.sleep(.02)
                continue
            sample = self._measure_frame()
            self._show_frame(sample)
            if self._read_preview_input(paused=False):
                break

    def _handle_action(self, action):
        if action.startswith("notification:"):
            self._change_notification(action.partition(":")[2])
        elif action == "notification_test":
            self.notice.show(preview=True)
            self._save_control("notification_test")
        elif action == "statistics":
            self.controls.open_statistics(DEFAULT_LOG_DIR)
        elif action == "points":
            self.show_landmarks = not self.show_landmarks
            self._save_control("points")
        elif action in ("target_up", "target_down"):
            value = self.engine.target + 1 if action == "target_up" else max(0, self.engine.target - 1)
            self.engine.set_target(value)
            self._save_control(action)
        elif action in ("hide", "show"):
            self.window_hidden = action == "hide"
            self.preview_visible = self.preview_requested and not self.window_hidden
            self.controls.set_visible(not self.window_hidden)
            if not self.preview_visible:
                self.preview.close()
            self._save_control(action)
        elif action in ("preview_toggle", "preview_off"):
            self.preview_requested = not self.preview_requested if action == "preview_toggle" else False
            self.preview_visible = self.preview_requested and not self.window_hidden
            if not self.preview_visible:
                self.preview.close()
            self._save_control("preview_on" if self.preview_requested else "preview_off")
        elif action == "pause_toggle":
            if self.paused:
                self._resume()
            else:
                self._pause()

    def _change_notification(self, selected):
        if selected not in NOTIFICATION_MODES:
            return
        self.notice.set_mode(selected)
        self.notification_mode = selected
        try:
            save_mode(selected)
            self.notification_warning = ""
        except OSError as exc:
            self.notification_warning = "이번 실행에 적용됨 · 알림 선택 저장 실패"
            print(f"알림 설정 저장 오류: {exc}")
        self._save_control("notification_mode")

    def _observation_boundary(self):
        # 정지 직전과 재개 직후의 눈 상태를 이어서 세지 않는다.
        now = max(time.monotonic_ns() // 1_000_000, self.previous_timestamp + 1)
        self.previous_timestamp = now
        self.last_result = self.engine.update(0, 0, False, now)

    def _pause(self):
        self._observation_boundary()
        self._record_daily(datetime.now().astimezone())
        self.capture.release()
        self.capture = None
        self.paused = True
        self.notice.hide()
        self._save_control("pause")

    def _resume(self):
        try:
            self.capture = open_camera(self.cv2, self.args.camera)
        except RuntimeError as exc:
            print(exc)
            self.window_hidden = False
            self.preview_visible = self.preview_requested
            self.controls.set_visible(True)
            self._save_control("resume_failed")
            from tkinter import messagebox
            messagebox.showerror("카메라 연결 실패", str(exc), parent=self.controls.window)
            return
        self._observation_boundary()
        self.paused = False
        self.frame_rate.samples.clear()
        self._save_control("resume")

    def _measure_frame(self):
        sample = read_eye_sample(self.cv2, self.mp, self.landmarker, self.capture,
                                 self.previous_timestamp, self.frame_rate)
        self.previous_timestamp = sample.timestamp_ms
        previous_active_ms = self.last_result.active_ms if self.last_result is not None else 0
        self.last_result = self.engine.update(sample.left, sample.right,
                                              sample.measurement_valid, sample.timestamp_ms)
        self.last_frame = sample.frame.copy() if self.desktop else None
        if self.last_result.blink:
            print(f"깜빡임 감지: 최근 60초 {self.last_result.count_60s}회 ({self.last_result.blink_reason})")
        shown = bool(self.last_result.alert and self.notice.show())
        if self.daily_recorder:
            self._record_daily(datetime.fromisoformat(sample.local_time),
                self.last_result.active_ms - previous_active_ms, tracked=sample.measurement_valid,
                blink=self.last_result.blink, alert=shown)
        self._save_frame(sample)
        return sample

    def _show_frame(self, sample):
        if not self.preview_visible:
            return
        if sample.measurement_valid and self.show_landmarks:
            draw_eye_points(self.cv2, sample.frame, sample.landmarks)
        result = self.last_result
        state = "NO FACE" if not sample.face_detected else "INVALID EAR" if not sample.measurement_valid else (
            "CLOSED" if result.state == 2 else "OPEN" if result.state == 1 else "CHECKING")
        lines = [f"Mode: {'VERIFY' if self.args.mode != 'baseline' else 'BASELINE'}   Eyes: {state}",
                 f"60s blinks: {result.count_60s} / target {self.engine.target}",
                 f"Observed: {result.active_ms // 1000}s"]
        if sample.measurement_valid:
            lines.append(f"EAR L/R: {sample.left:.2f} / {sample.right:.2f}")
        fps = f"{sample.timing.fps:.1f}" if sample.timing.fps is not None else "--"
        csv_status = "ERROR" if self.recording_error else "ON" if self.recorder else "OFF"
        lines.extend([f"FPS: {fps}   CSV: {csv_status}",
                      "P pause; H hide; L points; Q/Esc quit" if self.desktop else
                      "+/- target; click video, L points, Q/Esc quit"])
        for index, line in enumerate(lines):
            self.cv2.putText(sample.frame, line, (16, 34 + 30 * index),
                             self.cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 2)
        self.preview.show(sample.frame, self.show_landmarks, desktop=self.desktop)

    def _show_paused_frame(self):
        if not self.preview_visible:
            return
        if self.last_frame is None:
            import numpy as np
            self.last_frame = np.zeros((360, 640, 3), dtype=np.uint8)
        frame = self.last_frame.copy()
        self.cv2.putText(frame, "PAUSED - camera off", (16, 34),
                         self.cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 2)
        self.preview.show(frame, self.show_landmarks, desktop=True, paused=True)

    def _read_preview_input(self, *, paused):
        key, actions, closed = self.preview.read_events(30 if paused else 1)
        quit_key = key in (ord("q"), ord("Q"), 27)
        if paused:
            self.pending_actions.extend(actions)
            if quit_key:
                self.pending_actions.append("quit")
            elif key in (ord("p"), ord("P")):
                self.pending_actions.append("pause_toggle")
            elif key in (ord("l"), ord("L")):
                self.pending_actions.append("points")
            if closed:
                self.pending_actions.append("preview_off")
            return False
        if "quit" in actions or quit_key or (closed and not self.desktop):
            self._save_control("quit")
            return True
        if self.desktop:
            self.pending_actions.extend(a for a in actions if a in ("pause_toggle", "hide"))
            if closed:
                self.pending_actions.append("preview_off")
            if key in (ord("p"), ord("P")):
                self.pending_actions.append("pause_toggle")
            elif key in (ord("h"), ord("H")):
                self.pending_actions.append("hide")
        if (actions.count("points") + int(key in (ord("l"), ord("L")))) % 2:
            self.show_landmarks = not self.show_landmarks
        if key in (ord("+"), ord("=")):
            self.engine.set_target(self.engine.target + 1)
        elif key in (ord("-"), ord("_")):
            self.engine.set_target(max(0, self.engine.target - 1))
        return False

    def _update_controls(self):
        if self.controls:
            self.controls.update(paused=self.paused, result=self.last_result, target=self.engine.target,
                recording="오류" if self.recording_error or self.daily_recording_error else
                    "켜짐" if self.recorder or self.daily_recorder else "꺼짐",
                mode=self.engine.mode, preview_enabled=self.preview_requested,
                landmarks_visible=self.show_landmarks, notification_mode=self.notification_mode,
                notification_warning=self.notice.last_error or self.notification_warning)

    def _record_daily(self, observed_at, valid_ms=0, *, tracked=False, blink=False, alert=False):
        if self.daily_recorder is None:
            return
        try:
            saved = self.daily_recorder.observe(observed_at, valid_ms, tracked=tracked, blink=blink, alert=alert)
        except OSError as exc:
            self.daily_recording_error = True
            self.daily_recorder = None
            print(f"날짜별 CSV 기록 오류: {exc}")
            return
        if saved and self.controls:
            self.controls.refresh_statistics()

    def _open_recording(self, model):
        if self.args.no_csv:
            return
        args = self.args
        settings = dict(camera=args.camera, target=args.min_blinks, closed_ear=args.closed_ear,
            open_ear=args.open_ear, stable_frames=2, low_seconds=args.low_seconds,
            cooldown_seconds=args.cooldown, model=str(model), landmarks_initial=self.show_landmarks,
            engine_mode=self.engine.mode, desktop=self.desktop, background_initial=args.background,
            preview_initial=self.preview_requested, notification_mode=self.notification_mode,
            rebound_parameters=self.engine.rebound_parameters if args.mode != "baseline" else None)
        try:
            self.recorder = SessionRecorder(args.csv_dir, settings)
            print(f"수치 기록 파일: {self.recorder.path}")
        except OSError as exc:
            self.recording_error = True
            print(f"CSV 기록을 시작하지 못했습니다. 측정은 계속합니다: {exc}")

    def _disable_recording(self, message, exc):
        # 저장에 실패해도 측정과 알림은 계속 사용할 수 있게 한다.
        self.recording_error = True
        print(f"{message}: {exc}")
        try:
            self.recorder.close()
        except OSError:
            pass
        self.recorder = None

    def _save_control(self, action):
        if not self.desktop or self.recorder is None:
            return
        try:
            self.recorder.write_control(action, timestamp_ms=self.previous_timestamp,
                active_ms=self.last_result.active_ms if self.last_result is not None else 0,
                paused=self.paused, preview_visible=self.preview_visible, target=self.engine.target,
                landmarks_visible=self.show_landmarks, notification_mode=self.notification_mode)
        except OSError as exc:
            self._disable_recording("조작 기록 오류", exc)

    def _save_frame(self, sample):
        if self.recorder is None:
            return
        try:
            self.recorder.write(local_time=sample.local_time, timestamp_ms=sample.timestamp_ms,
                timing=sample.timing, face_detected=sample.face_detected, left=sample.left, right=sample.right,
                result=self.last_result, target=self.engine.target, landmarks_visible=self.show_landmarks,
                preview_visible=self.preview_visible, notification_mode=self.notification_mode)
        except OSError as exc:
            self._disable_recording("CSV 기록 중 오류가 발생했습니다. 측정은 계속합니다", exc)

    def _close(self):
        if self.daily_recorder:
            try:
                self.daily_recorder.close()
            except OSError as exc:
                print(f"날짜별 CSV 파일을 마무리하지 못했습니다: {exc}")
        if self.recorder:
            try:
                self.recorder.close()
                print(f"수치 기록 저장 완료: {self.recorder.path}")
            except OSError as exc:
                print(f"CSV 파일을 마무리하지 못했습니다: {exc}")
        if self.capture is not None:
            self.capture.release()
        self.cv2.destroyAllWindows()
        try:
            if self.controls:
                self.controls.close()
        finally:
            if self.notice:
                self.notice.close()
