"""웹캠 영상에서 눈 좌표와 EAR을 구해 C에 전달할 입력을 만든다."""

from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
import time
import sys
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = ROOT / "models" / "face_landmarker.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "float16/1/face_landmarker.task")

# 각 눈의 바깥쪽, 윗눈꺼풀, 안쪽, 아랫눈꺼풀 좌표 번호다.
LEFT_EYE = (33, 160, 158, 133, 153, 144)
RIGHT_EYE = (362, 385, 387, 263, 373, 380)


@dataclass
class EyeSample:
    frame: object
    landmarks: object
    face_detected: bool
    left: float
    right: float
    measurement_valid: bool
    timestamp_ms: int
    local_time: str
    timing: object


def eye_aspect_ratio(landmarks, indices, width, height):
    points = [(landmarks[i].x * width, landmarks[i].y * height) for i in indices]
    vertical = math.dist(points[1], points[5]) + math.dist(points[2], points[4])
    horizontal = 2 * math.dist(points[0], points[3])
    # 가로 길이가 0이면 비율을 계산할 수 없다.
    return vertical / horizontal if horizontal > 0 else float("nan")


def draw_eye_points(cv2, frame, landmarks):
    height, width = frame.shape[:2]
    for index in LEFT_EYE + RIGHT_EYE:
        point = landmarks[index]
        if math.isfinite(point.x) and math.isfinite(point.y):
            x = min(width - 1, max(0, int(point.x * width)))
            y = min(height - 1, max(0, int(point.y * height)))
            cv2.circle(frame, (x, y), 2, (80, 210, 80), -1)


def ensure_model(path):
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    print("MediaPipe 얼굴 모델을 처음 한 번 내려받습니다...")
    try:
        with urlopen(MODEL_URL, timeout=30) as response, temporary.open("wb") as target:
            while block := response.read(1024 * 1024):
                target.write(block)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"모델을 내려받지 못했습니다. {MODEL_URL} 파일을 받아 {path}에 저장하세요.") from None
    return path


def open_camera(cv2, camera):
    capture = cv2.VideoCapture(camera)
    if not capture.isOpened() and sys.platform == "win32":
        capture.release()
        capture = cv2.VideoCapture(camera, cv2.CAP_DSHOW)
    if not capture.isOpened() and sys.platform == "win32":
        capture.release()
        capture = cv2.VideoCapture(camera, cv2.CAP_MSMF)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError("웹캠을 열지 못했습니다. 카메라 권한과 --camera 번호를 확인하세요.")
    return capture


def read_eye_sample(cv2, mp, landmarker, capture, previous_timestamp, frame_rate):
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError("웹캠 영상을 읽지 못했습니다.")
    frame = cv2.flip(frame, 1)
    now_ns = time.monotonic_ns()
    timing = frame_rate.update(now_ns)
    local_time = datetime.now().astimezone().isoformat(timespec="milliseconds")
    timestamp = max(now_ns // 1_000_000, previous_timestamp + 1)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    detection = landmarker.detect_for_video(image, timestamp)
    face = bool(detection.face_landmarks)
    landmarks = detection.face_landmarks[0] if face else None
    left = right = float("nan")
    if face:
        height, width = frame.shape[:2]
        left = eye_aspect_ratio(landmarks, LEFT_EYE, width, height)
        right = eye_aspect_ratio(landmarks, RIGHT_EYE, width, height)
    valid = face and math.isfinite(left) and math.isfinite(right) and left >= 0 and right >= 0
    return EyeSample(frame, landmarks, face, left, right, valid, timestamp, local_time, timing)
