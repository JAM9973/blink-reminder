"""Webcam + MediaPipe frontend for the C blink decision engine."""

import argparse
import math
import os
from pathlib import Path
import sys
import time
from urllib.request import urlopen

from engine import BlinkEngine


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


def parse_args():
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
    return parser.parse_args()


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
    try:
        with BlinkEngine(args.min_blinks, args.closed_ear, args.open_ear,
                         args.low_seconds, args.cooldown) as engine, \
                vision.FaceLandmarker.create_from_options(options) as landmarker:
            while True:
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError("웹캠 영상을 읽지 못했습니다.")
                frame = cv2.flip(frame, 1)
                now_ms = time.monotonic_ns() // 1_000_000
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
                result = engine.update(left, right, face, timestamp)
                if result.blink:
                    print(f"깜빡임 감지: 최근 60초 {result.count_60s}회")
                if result.alert:
                    notice.show()

                state = "NO FACE" if not face else ("CLOSED" if result.state == 2 else
                        "OPEN" if result.state == 1 else "CHECKING")
                lines = [f"Eyes: {state}",
                         f"60s blinks: {result.count_60s} / target {engine.target}",
                         f"Observed: {result.active_ms // 1000}s  (+/- target, Q quit)"]
                if face:
                    lines.append(f"EAR L/R: {left:.2f} / {right:.2f}")
                for index, line in enumerate(lines):
                    cv2.putText(frame, line, (16, 34 + 30 * index),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
                cv2.imshow("Blink reminder", frame)
                notice.update()
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key in (ord("+"), ord("=")):
                    engine.set_target(engine.target + 1)
                elif key in (ord("-"), ord("_")):
                    engine.set_target(max(0, engine.target - 1))
    finally:
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
