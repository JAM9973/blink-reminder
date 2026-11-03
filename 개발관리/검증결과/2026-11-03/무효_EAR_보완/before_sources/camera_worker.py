"""Camera and C-engine work; no Tk calls are made from this thread."""

import csv
from datetime import datetime
import logging
import math
from pathlib import Path
import queue
import threading
import time
from urllib.request import urlopen

from app_settings import DATA_DIR, ROOT
from engine import BlinkEngine


MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")
LEFT_EYE = (33, 160, 158, 133, 153, 144)
RIGHT_EYE = (362, 385, 387, 263, 373, 380)


def eye_aspect_ratio(landmarks, indices, width, height):
    points = [(landmarks[i].x * width, landmarks[i].y * height) for i in indices]
    vertical = math.dist(points[1], points[5]) + math.dist(points[2], points[4])
    horizontal = 2 * math.dist(points[0], points[3])
    return vertical / horizontal if horizontal > 0 else float("nan")


def put_latest(target, value):
    try:
        target.put_nowait(value)
    except queue.Full:
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        try:
            target.put_nowait(value)
        except queue.Full:
            pass


class CameraWorker(threading.Thread):
    def __init__(self, settings):
        super().__init__(name="blink-camera", daemon=True)
        self.settings = settings
        self.commands = queue.Queue()
        self.events = queue.Queue()
        self.snapshots = queue.Queue(maxsize=1)
        self.frames = queue.Queue(maxsize=1)
        self.shutdown = threading.Event()
        self.running = False
        self.paused = False
        self.preview_visible = True
        self.capture = None
        self.detector = None
        self.engine = None
        self.csv_file = None
        self.csv_writer = None
        self.csv_path = ""
        self.last_flush = 0
        self.last_snapshot = 0
        self.last_preview = 0
        self.last_frame_time = 0
        self.fps = 0.0
        self.timestamp = -1
        self.last_result = None
        self.cv2 = None

    def command(self, name, value=None):
        self.commands.put((name, value))

    def stop(self):
        self.shutdown.set()
        self.command("shutdown")

    def emit(self, name, value=None):
        self.events.put((name, value))

    def _model_path(self):
        path = Path(self.settings.model).expanduser() if self.settings.model else (
            ROOT / "models" / "face_landmarker.task")
        if not path.is_absolute():
            path = ROOT / path
        if path.exists():
            return path
        self.emit("message", "얼굴 인식 모델을 처음 한 번 내려받고 있습니다…")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".part")
        try:
            with urlopen(MODEL_URL, timeout=15) as source, temporary.open("wb") as target:
                while not self.shutdown.is_set():
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    target.write(block)
            if self.shutdown.is_set():
                raise RuntimeError("모델 준비가 취소되었습니다.")
            temporary.replace(path)
            return path
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("얼굴 인식 모델을 준비하지 못했습니다. 인터넷 연결이나 모델 경로를 확인하세요.") from exc

    def _new_engine(self):
        if self.engine:
            self.engine.close()
        self.engine = BlinkEngine(
            target=self.settings.min_blinks, closed_ear=self.settings.closed_ear,
            open_ear=self.settings.open_ear, low_seconds=self.settings.low_seconds,
            cooldown_seconds=self.settings.cooldown, stable_frames=self.settings.stable_frames)
        self.last_result = None
        self.last_snapshot = 0

    def _open_camera(self):
        import sys
        backends = [self.cv2.CAP_DSHOW, self.cv2.CAP_MSMF, self.cv2.CAP_ANY] if (
            sys.platform == "win32") else [self.cv2.CAP_ANY]
        for backend in backends:
            capture = self.cv2.VideoCapture(self.settings.camera, backend)
            if capture.isOpened():
                capture.set(self.cv2.CAP_PROP_FRAME_WIDTH, 640)
                capture.set(self.cv2.CAP_PROP_FRAME_HEIGHT, 480)
                capture.set(self.cv2.CAP_PROP_FPS, self.settings.max_fps)
                self.capture = capture
                self.last_frame_time = 0
                self.fps = 0.0
                return
            capture.release()
        raise RuntimeError("웹캠을 열지 못했습니다. 카메라 번호·Windows 카메라 권한을 확인하고 다른 카메라 앱을 종료하세요.")

    def _start_measurement(self):
        self.emit("state", "loading")
        self.emit("message", "카메라와 판정 엔진을 준비하고 있습니다…")
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
        self.cv2 = cv2
        self.mp = mp
        cv2.setNumThreads(1)
        model = self._model_path()
        self._new_engine()
        options = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_buffer=model.read_bytes()),
            running_mode=vision.RunningMode.VIDEO, num_faces=1,
            min_face_detection_confidence=0.5, min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5)
        self.detector = vision.FaceLandmarker.create_from_options(options)
        self._open_camera()
        self.running = True
        self.paused = False
        self.timestamp = -1
        self.last_preview = 0
        self._open_csv()
        self.emit("state", "running")
        self.emit("message", "측정을 시작했습니다. 얼굴이 보인 누적 시간 60초 후부터 알림 조건을 확인합니다.")

    def _open_csv(self):
        self._close_csv()
        if not self.settings.csv_enabled:
            return
        folder = DATA_DIR / "records"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"blink_{datetime.now():%Y%m%d_%H%M%S_%f}.csv"
        self.csv_file = path.open("w", newline="", encoding="utf-8-sig")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(("local_time", "monotonic_ms", "active_ms", "face_visible",
                                  "left_ear", "right_ear", "eye_state", "blink",
                                  "count_60s", "alert", "target", "fps",
                                  "closed_ear", "open_ear", "stable_frames"))
        self.csv_path = str(path)
        self.emit("recording", self.csv_path)
        self.last_flush = time.monotonic()

    def _close_csv(self):
        if self.csv_file:
            self.csv_file.close()
        self.csv_file = None
        self.csv_writer = None
        self.csv_path = ""

    def _release_camera(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def _release(self):
        self._release_camera()
        if self.detector:
            self.detector.close()
            self.detector = None
        if self.engine:
            self.engine.close()
            self.engine = None
        self._close_csv()
        self.running = False
        self.paused = False
        put_latest(self.frames, None)

    def _commands(self):
        while True:
            try:
                name, value = self.commands.get_nowait()
            except queue.Empty:
                return
            if name == "shutdown":
                self.shutdown.set()
                return
            if name == "start" and not self.running:
                self._start_measurement()
            elif name == "stop":
                self._release()
                self.emit("state", "idle")
                self.emit("message", "측정을 종료하고 카메라를 해제했습니다.")
            elif name == "pause" and self.running and not self.paused:
                now = time.monotonic_ns() // 1_000_000
                self.engine.update(0, 0, False, now)
                self._release_camera()
                self.paused = True
                put_latest(self.frames, None)
                self.emit("state", "paused")
                self.emit("message", "일시정지 중입니다. 카메라가 해제되며 측정 시간과 횟수는 유지됩니다.")
            elif name == "resume" and self.running and self.paused:
                self._open_camera()
                self.paused = False
                self.emit("state", "running")
                self.emit("message", "측정을 재개했습니다.")
            elif name == "reset":
                if self.running:
                    self._new_engine()
                    self.emit("reset")
                    self.emit("message", "횟수와 측정 시간을 초기화했습니다.")
            elif name == "preview":
                self.preview_visible = bool(value)
            elif name == "settings":
                previous = self.settings
                self.settings = value
                if self.running and previous.engine_key() != value.engine_key():
                    paused = self.paused
                    self._release()
                    self._start_measurement()
                    self.emit("reset")
                    if paused:
                        self.engine.update(0, 0, False, time.monotonic_ns() // 1_000_000)
                        self._release_camera()
                        self.paused = True
                        self.emit("state", "paused")
                    self.emit("message", "판정 설정을 적용하고 측정 시간을 새로 시작했습니다.")
                elif self.running and previous.csv_enabled != value.csv_enabled:
                    self._open_csv()

    def _frame(self):
        started = time.monotonic()
        ok, frame = self.capture.read()
        if not ok:
            raise RuntimeError("카메라 영상을 읽지 못했습니다. USB 연결이나 카메라 사용 앱을 확인한 뒤 다시 시작하세요.")
        frame = self.cv2.flip(frame, 1)
        now = time.monotonic()
        if self.last_frame_time:
            instantaneous = 1 / max(now - self.last_frame_time, 0.001)
            self.fps = instantaneous if not self.fps else self.fps * 0.9 + instantaneous * 0.1
        self.last_frame_time = now
        now_ms = time.monotonic_ns() // 1_000_000
        self.timestamp = max(now_ms, self.timestamp + 1)
        rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        detection = self.detector.detect_for_video(image, self.timestamp)
        face = bool(detection.face_landmarks)
        left = right = float("nan")
        if face:
            landmarks = detection.face_landmarks[0]
            height, width = frame.shape[:2]
            left = eye_aspect_ratio(landmarks, LEFT_EYE, width, height)
            right = eye_aspect_ratio(landmarks, RIGHT_EYE, width, height)
            face = math.isfinite(left) and math.isfinite(right)
        result = self.engine.update(left, right, face, now_ms)
        self.last_result = result
        if result.alert:
            self.emit("alert", result.count_60s)
        if self.csv_writer:
            self.csv_writer.writerow((datetime.now().astimezone().isoformat(timespec="milliseconds"),
                now_ms, result.active_ms, int(face), round(left, 5) if face else "",
                round(right, 5) if face else "", result.state, result.blink,
                result.count_60s, result.alert, self.settings.min_blinks, round(self.fps, 1),
                self.settings.closed_ear, self.settings.open_ear, self.settings.stable_frames))
            if now - self.last_flush >= 1:
                self.csv_file.flush()
                self.last_flush = now
        if now - self.last_snapshot >= 0.15:
            put_latest(self.snapshots, {
                "face": face, "left": left, "right": right, "state": result.state,
                "count": result.count_60s, "active_ms": result.active_ms,
                "low_ms": result.low_for_ms, "fps": self.fps,
                "target": self.settings.min_blinks})
            self.last_snapshot = now
        if self.settings.preview and self.preview_visible and now - self.last_preview >= 0.10:
            if face and self.settings.landmarks:
                for index in LEFT_EYE + RIGHT_EYE:
                    point = landmarks[index]
                    self.cv2.circle(frame, (int(point.x * width), int(point.y * height)),
                                    3, (80, 210, 80), -1)
            put_latest(self.frames, self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB))
            self.last_preview = now
        self.shutdown.wait(max(0, 1 / self.settings.max_fps - (time.monotonic() - started)))

    def run(self):
        try:
            while not self.shutdown.is_set():
                try:
                    self._commands()
                    if self.shutdown.is_set():
                        break
                    if self.running and not self.paused:
                        self._frame()
                    else:
                        self.shutdown.wait(0.06)
                except Exception as exc:
                    logging.exception("Measurement failed")
                    self._release()
                    self.emit("state", "idle")
                    self.emit("error", str(exc))
        finally:
            self._release()
