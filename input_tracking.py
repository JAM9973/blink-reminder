"""웹캠 영상에서 눈 좌표와 EAR을 구해 C에 전달할 입력을 만든다."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
import time
import sys
from urllib.request import urlopen

import numpy as np


ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = ROOT / "models" / "face_landmarker.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "float16/1/face_landmarker.task")
DEFAULT_HAND_MODEL = ROOT / "models" / "hand_landmarker.task"
HAND_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
                  "hand_landmarker/float16/1/hand_landmarker.task")

# 각 눈의 바깥쪽, 윗눈꺼풀, 안쪽, 아랫눈꺼풀 좌표 번호다.
LEFT_EYE = (33, 160, 158, 133, 153, 144)
RIGHT_EYE = (362, 385, 387, 263, 373, 380)
EYE_COLUMNS = np.linspace(.15, .85, 16, dtype=np.float32)[None, :, None]
EYE_ROWS = np.linspace(-.22, .22, 15, dtype=np.float32)[:, None, None]
MIN_EYE_WIDTH_PX = 12
MIN_EYE_EDGE_CONTRAST = 3
HAND_PALM = (0, 1, 5, 9, 13, 17)
HAND_FINGERS = ((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12),
                (13, 14, 15, 16), (17, 18, 19, 20))
MIN_HAND_COVERAGE = .20


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


def hand_mask(cv2, shape, hands):
    height, width = shape
    mask = np.zeros(shape, dtype=np.uint8)
    for hand in hands:
        points = np.array([(point.x * width, point.y * height) for point in hand])
        if not np.isfinite(points).all():
            continue
        pixels = points.round().astype(np.int32)
        palm = cv2.convexHull(pixels[list(HAND_PALM)])
        palm_width = max(math.dist(points[5], points[17]), .65 * math.dist(points[0], points[9]))
        cv2.fillConvexPoly(mask, palm, 1)
        # 손바닥과 각 손가락에 실제 두께를 근사해, 손가락 사이의 빈 공간을 유지한다.
        for finger in HAND_FINGERS:
            for start, end, fraction in zip(finger, finger[1:], (.25, .21, .17)):
                thickness = max(2, round(palm_width * fraction))
                cv2.line(mask, tuple(pixels[start]), tuple(pixels[end]), 1, thickness)
                cv2.circle(mask, tuple(pixels[end]), thickness // 2, 1, -1)
    return mask


def eye_region_visible(cv2, gray, landmarks, indices, occlusion_mask=None):
    height, width = gray.shape
    for index in indices:
        point = landmarks[index]
        if not (0 <= point.x < 1 and 0 <= point.y < 1):
            return False
        visibility = getattr(point, "visibility", None)
        if visibility is not None and not visibility >= .5:
            return False

    outer, inner = landmarks[indices[0]], landmarks[indices[3]]
    origin = np.array([outer.x * width, outer.y * height], dtype=np.float32)
    axis = np.array([(inner.x - outer.x) * width, (inner.y - outer.y) * height], dtype=np.float32)
    if math.hypot(*axis) < MIN_EYE_WIDTH_PX:
        return False
    normal = np.array([-axis[1], axis[0]], dtype=np.float32)
    sample_points = origin + EYE_COLUMNS * axis + EYE_ROWS * normal
    x, y = sample_points[:, :, 0], sample_points[:, :, 1]
    if x.min() < 0 or x.max() > width - 1 or y.min() < 0 or y.max() > height - 1:
        return False
    if occlusion_mask is not None:
        overlap = cv2.remap(occlusion_mask, x, y, cv2.INTER_NEAREST)
        if np.count_nonzero(overlap) >= overlap.size * MIN_HAND_COVERAGE:
            return False

    # 역광에서도 약한 눈꺼풀 경계를 허용하고, 평탄한 가림은 제외한다.
    patch = cv2.remap(gray, x, y, cv2.INTER_LINEAR).astype(np.int16)
    edges = np.abs(patch[2:] - patch[:-2]).max(axis=0)
    return bool(np.median(edges) >= MIN_EYE_EDGE_CONTRAST)


def draw_eye_points(cv2, frame, landmarks):
    height, width = frame.shape[:2]
    for index in LEFT_EYE + RIGHT_EYE:
        point = landmarks[index]
        if math.isfinite(point.x) and math.isfinite(point.y):
            x = min(width - 1, max(0, int(point.x * width)))
            y = min(height - 1, max(0, int(point.y * height)))
            cv2.circle(frame, (x, y), 2, (80, 210, 80), -1)


def ensure_model(path, *, url=MODEL_URL, label="얼굴"):
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    print(f"MediaPipe {label} 모델을 처음 한 번 내려받습니다...")
    try:
        with urlopen(url, timeout=30) as response, temporary.open("wb") as target:
            while block := response.read(1024 * 1024):
                target.write(block)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"{label} 모델을 내려받지 못했습니다. {url} 파일을 받아 {path}에 저장하세요.") from None
    return path


@contextmanager
def camera_session(camera):
    if sys.platform != "win32":
        yield
        return

    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateMutexW(None, False, f"Local\\BlinkReminder-camera-{camera}")
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    try:
        if error == 183:  # ERROR_ALREADY_EXISTS
            raise RuntimeError("같은 카메라로 눈 깜빡임 알림이 이미 실행 중입니다. 트레이에서 기존 앱을 종료하세요.")
        yield
    finally:
        kernel.CloseHandle(handle)


def open_camera(cv2, camera):
    backends = ((), (cv2.CAP_DSHOW,), (cv2.CAP_MSMF,)) if sys.platform == "win32" else ((),)
    for backend in backends:
        capture = cv2.VideoCapture(camera, *backend)
        if capture.isOpened():
            # 일부 Windows 드라이버는 영상이 들어오기 전에도 열림을 보고한다.
            for _ in range(3):
                if capture.grab():
                    ok, frame = capture.retrieve()
                    if ok and frame is not None and frame.size:
                        return capture
        capture.release()
    raise RuntimeError("웹캠 영상을 시작하지 못했습니다. 카메라 권한과 --camera 번호를 확인하세요.")


def read_eye_sample(cv2, mp, landmarker, capture, previous_timestamp, frame_rate, *, hand_landmarker):
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
    if valid:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hands = hand_landmarker.detect_for_video(image, timestamp).hand_landmarks
        mask = hand_mask(cv2, gray.shape, hands) if hands else None
        valid = (eye_region_visible(cv2, gray, landmarks, LEFT_EYE, mask) and
                 eye_region_visible(cv2, gray, landmarks, RIGHT_EYE, mask))
    return EyeSample(frame, landmarks, face, left, right, valid, timestamp, local_time, timing)
