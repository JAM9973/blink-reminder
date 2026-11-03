"""Webcam + MediaPipe frontend for the C blink decision engine."""

import argparse
from datetime import datetime
import math
import os
from pathlib import Path
import sys
import time
from urllib.request import urlopen

from engine import BlinkEngine
from measurement_log import DEFAULT_RECORD_DIR, FrameRate, SessionRecorder


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = ROOT / "models" / "face_landmarker.task"
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache" / "matplotlib"))

# MediaPipe's 478-point face layout: outer corner, upper lid points,
# inner corner, lower lid points. Values are scaled to image pixels.
LEFT_EYE = (33, 160, 158, 133, 153, 144)
RIGHT_EYE = (362, 385, 387, 263, 373, 380)


def eye_aspect_ratio(landmarks, indices, width, height):
    points = [(landmarks[i].x * width, landmarks[i].y * height) for i in indices]
    vertical = math.dist(points[1], points[5]) + math.dist(points[2], points[4])
    horizontal = 2 * math.dist(points[0], points[3])
    return vertical / horizontal if horizontal > 0 else float("nan")


def draw_eye_points(cv2, frame, landmarks):
    height, width = frame.shape[:2]
    for index in LEFT_EYE + RIGHT_EYE:
        point = landmarks[index]
        if math.isfinite(point.x) and math.isfinite(point.y):
            x = min(width - 1, max(0, int(point.x * width)))
            y = min(height - 1, max(0, int(point.y * height)))
            cv2.circle(frame, (x, y), 2, (80, 210, 80), -1)


def draw_preview_buttons(cv2, frame, landmarks_enabled):
    """Mouse alternatives to shortcuts, in image coordinates."""
    height, width = frame.shape[:2]
    margin = 8
    button_width = min(150, max(1, (width - margin * 3) // 2))
    top = max(0, height - 36)
    regions = {}
    for column, (action, label) in enumerate((
            ("points", "Points ON" if landmarks_enabled else "Points OFF"),
            ("quit", "Exit"))):
        left = margin + column * (button_width + margin)
        right, bottom = min(width - 1, left + button_width), min(height - 1, top + 28)
        regions[action] = (left, top, right, bottom)
        cv2.rectangle(frame, (left, top), (right, bottom), (45, 45, 45), -1)
        cv2.putText(frame, label, (left + 6, bottom - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1)
    return regions


def ensure_model(path):
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print("MediaPipe 얼굴 모델을 처음 한 번 내려받습니다...")
    temporary = path.with_suffix(".part")
    try:
        with urlopen(MODEL_URL, timeout=30) as response, temporary.open("wb") as target:
            while block := response.read(1024 * 1024):
                target.write(block)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"모델을 내려받지 못했습니다. {MODEL_URL} 파일을 받아 {path}에 저장하세요."
        ) from None
    return path


class EyeNotice:
    def __init__(self):
        self.root = None
        self.window = None
        self.hide_at = 0
        try:
            import tkinter as tk
            self.root = tk.Tk()
            self.root.withdraw()
            self.window = tk.Toplevel(self.root)
            self.window.withdraw()
            self.window.overrideredirect(True)
            self.window.attributes("-topmost", True)
            tk.Label(self.window, text="👀 잠깐 눈을 쉬어 주세요", font=("Segoe UI Emoji", 15),
                     bg="#fff4cc", fg="#202020", padx=18, pady=12).pack()
        except Exception as exc:
            print(f"팝업을 사용할 수 없어 콘솔에 알림을 표시합니다: {exc}")
            if self.root:
                self.root.destroy()
            self.root = None

    def show(self):
        print("👀 최근 60초 깜빡임이 설정 기준보다 적습니다.")
        if self.window:
            self.window.update_idletasks()
            width, height = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
            x = self.window.winfo_screenwidth() - width - 30
            self.window.geometry(f"+{x}+40")
            self.window.deiconify()
            self.window.lift()
            self.hide_at = time.monotonic() + 5

    def update(self):
        if self.root:
            if self.hide_at and time.monotonic() >= self.hide_at:
                self.window.withdraw()
                self.hide_at = 0
            self.root.update()

    def close(self):
        if self.root:
            self.root.destroy()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="웹캠 눈 깜빡임 알림 프로토타입")
    parser.add_argument("--camera", type=int, default=0, help="웹캠 번호 (기본 0)")
    parser.add_argument("--min-blinks", type=int, default=12,
                        help="최근 60초의 최소 깜빡임 횟수 (기본 12, 의학 기준 아님)")
    parser.add_argument("--closed-ear", type=float, default=0.18,
                        help="양쪽 눈 감김 판정 EAR 상한")
    parser.add_argument("--open-ear", type=float, default=0.23,
                        help="양쪽 눈 열림 판정 EAR 하한")
    parser.add_argument("--low-seconds", type=float, default=10,
                        help="기준 미달 지속 시간 (초)")
    parser.add_argument("--cooldown", type=float, default=60,
                        help="알림 사이 최소 시간 (초)")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL,
                        help="MediaPipe face_landmarker.task 파일")
    parser.add_argument("--no-landmarks", action="store_true",
                        help="눈 좌표 표시를 끄고 시작 (실행 중 L로 전환)")
    parser.add_argument("--no-csv", action="store_true", help="수치 CSV 기록 끄기")
    parser.add_argument("--csv-dir", type=Path, default=DEFAULT_RECORD_DIR,
                        help="CSV·설정 기록 저장 폴더 (기본 data/records)")
    return parser.parse_args(argv)


def run(args):
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
    except ImportError as exc:
        raise RuntimeError("필요한 패키지가 없습니다. python -m pip install -r requirements.txt") from exc

    model = ensure_model(args.model)
    options = vision.FaceLandmarkerOptions(
        # Pass bytes: the native MediaPipe runtime may reject Korean file paths.
        base_options=mp_python.BaseOptions(model_asset_buffer=model.read_bytes()),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    capture = cv2.VideoCapture(args.camera)
    if not capture.isOpened() and sys.platform == "win32":
        capture.release()
        capture = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not capture.isOpened() and sys.platform == "win32":
        capture.release()
        capture = cv2.VideoCapture(args.camera, cv2.CAP_MSMF)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError("웹캠을 열지 못했습니다. 카메라 권한과 --camera 번호를 확인하세요.")
    notice = EyeNotice()
    previous_timestamp = -1
    frame_rate = FrameRate()
    show_landmarks = not args.no_landmarks
    recorder = None
    recording_error = False
    button_regions = {}
    mouse_actions = []
    mouse_registered = False

    def on_mouse(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONUP:
            for action, (left, top, right, bottom) in button_regions.items():
                if left <= x <= right and top <= y <= bottom:
                    mouse_actions.append(action)
                    break

    print("키 조작: 영상 창을 클릭하고 영문 입력 상태에서 L(좌표), Q/Esc(종료)를 누르세요.")
    print("영상 아래 Points / Exit 버튼으로도 좌표 전환과 종료를 할 수 있습니다.")
    try:
        with BlinkEngine(args.min_blinks, args.closed_ear, args.open_ear,
                         args.low_seconds, args.cooldown) as engine, \
                vision.FaceLandmarker.create_from_options(options) as landmarker:
            if not args.no_csv:
                try:
                    recorder = SessionRecorder(args.csv_dir, dict(
                        camera=args.camera, target=args.min_blinks,
                        closed_ear=args.closed_ear, open_ear=args.open_ear,
                        stable_frames=2, low_seconds=args.low_seconds,
                        cooldown_seconds=args.cooldown, model=str(model),
                        landmarks_initial=show_landmarks))
                    print(f"수치 기록 파일: {recorder.path}")
                except OSError as exc:
                    recording_error = True
                    print(f"CSV 기록을 시작하지 못했습니다. 측정은 계속합니다: {exc}")
            while True:
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError("웹캠 영상을 읽지 못했습니다.")
                frame = cv2.flip(frame, 1)
                now_ns = time.monotonic_ns()
                timing = frame_rate.update(now_ns)
                local_time = datetime.now().astimezone().isoformat(timespec="milliseconds")
                now_ms = now_ns // 1_000_000
                timestamp = max(now_ms, previous_timestamp + 1)
                previous_timestamp = timestamp
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                detection = landmarker.detect_for_video(image, timestamp)
                face = bool(detection.face_landmarks)
                left = right = float("nan")
                if face:
                    landmarks = detection.face_landmarks[0]
                    height, width = frame.shape[:2]
                    left = eye_aspect_ratio(landmarks, LEFT_EYE, width, height)
                    right = eye_aspect_ratio(landmarks, RIGHT_EYE, width, height)
                measurement_valid = (face and math.isfinite(left) and math.isfinite(right)
                                     and left >= 0 and right >= 0)
                result = engine.update(left, right, measurement_valid, timestamp)
                if result.blink:
                    print(f"깜빡임 감지: 최근 60초 {result.count_60s}회")
                if result.alert:
                    notice.show()

                if recorder:
                    try:
                        recorder.write(local_time=local_time, timestamp_ms=timestamp,
                            timing=timing, face_detected=face, left=left, right=right,
                            result=result, target=engine.target, landmarks_visible=show_landmarks)
                    except OSError as exc:
                        recording_error = True
                        print(f"CSV 기록 중 오류가 발생했습니다. 측정은 계속합니다: {exc}")
                        try:
                            recorder.close()
                        except OSError:
                            pass
                        recorder = None

                if measurement_valid and show_landmarks:
                    draw_eye_points(cv2, frame, landmarks)

                state = "NO FACE" if not face else "INVALID EAR" if not measurement_valid else (
                        "CLOSED" if result.state == 2 else
                        "OPEN" if result.state == 1 else "CHECKING")
                lines = [f"Eyes: {state}",
                         f"60s blinks: {result.count_60s} / target {engine.target}",
                         f"Observed: {result.active_ms // 1000}s"]
                if measurement_valid:
                    lines.append(f"EAR L/R: {left:.2f} / {right:.2f}")
                fps_text = f"{timing.fps:.1f}" if timing.fps is not None else "--"
                csv_text = "ERROR" if recording_error else "ON" if recorder else "OFF"
                lines.extend([f"FPS: {fps_text}   CSV: {csv_text}",
                              "+/- target; click video, L points, Q/Esc quit"])
                for index, line in enumerate(lines):
                    cv2.putText(frame, line, (16, 34 + 30 * index),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
                button_regions = draw_preview_buttons(cv2, frame, show_landmarks)
                cv2.imshow("Blink reminder", frame)
                if not mouse_registered:
                    cv2.setMouseCallback("Blink reminder", on_mouse)
                    mouse_registered = True
                notice.update()
                key = cv2.waitKey(1) & 0xFF
                try:
                    window_closed = cv2.getWindowProperty("Blink reminder", cv2.WND_PROP_VISIBLE) < 1
                except cv2.error:
                    # Some backends raise once the user destroys the window.
                    window_closed = True
                actions = mouse_actions[:]
                mouse_actions.clear()
                if window_closed or "quit" in actions or key in (ord("q"), ord("Q"), 27):
                    break
                if (actions.count("points") + int(key in (ord("l"), ord("L")))) % 2:
                    show_landmarks = not show_landmarks
                if key in (ord("+"), ord("=")):
                    engine.set_target(engine.target + 1)
                elif key in (ord("-"), ord("_")):
                    engine.set_target(max(0, engine.target - 1))
    finally:
        if recorder:
            try:
                recorder.close()
                print(f"수치 기록 저장 완료: {recorder.path}")
            except OSError as exc:
                print(f"CSV 파일을 마무리하지 못했습니다: {exc}")
        capture.release()
        cv2.destroyAllWindows()
        notice.close()


if __name__ == "__main__":
    try:
        run(parse_args())
    except KeyboardInterrupt:
        print("프로그램을 종료했습니다.")
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(f"실행 오류: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
