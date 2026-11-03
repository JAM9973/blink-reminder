"""Thin ctypes bridge; all blink, window, and alert decisions live in C."""

import ctypes
from pathlib import Path
import sys


class BlinkOutput(ctypes.Structure):
    _fields_ = [
        ("blink", ctypes.c_int),
        ("alert", ctypes.c_int),
        ("count_60s", ctypes.c_int),
        ("state", ctypes.c_int),
        ("face_visible", ctypes.c_int),
        ("low_for_ms", ctypes.c_int),
        ("active_ms", ctypes.c_int64),
    ]


class BlinkEngine:
    def __init__(self, target=12, closed_ear=0.18, open_ear=0.23,
                 low_seconds=10, cooldown_seconds=60, stable_frames=2):
        root = Path(__file__).resolve().parent
        name = "blink_engine.dll" if sys.platform == "win32" else (
            "libblink_engine.dylib" if sys.platform == "darwin" else "libblink_engine.so")
        path = root / name
        sources = [root / "blink_engine.c", root / "blink_engine.h"]
        if not path.exists() or any(p.stat().st_mtime_ns > path.stat().st_mtime_ns
                                     for p in sources):
            from build import build
            build()
        self._lib = ctypes.CDLL(str(path))
        self._lib.be_create.argtypes = [ctypes.c_int, ctypes.c_double, ctypes.c_double,
                                        ctypes.c_int, ctypes.c_int]
        self._lib.be_create.restype = ctypes.c_void_p
        self._lib.be_destroy.argtypes = [ctypes.c_void_p]
        self._lib.be_destroy.restype = None
        self._lib.be_set_target.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._lib.be_set_target.restype = ctypes.c_int
        self._lib.be_set_stable_frames.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._lib.be_set_stable_frames.restype = ctypes.c_int
        self._lib.be_update.argtypes = [ctypes.c_void_p, ctypes.c_double,
                                        ctypes.c_double, ctypes.c_int,
                                        ctypes.c_int64, ctypes.POINTER(BlinkOutput)]
        self._lib.be_update.restype = ctypes.c_int
        self._handle = self._lib.be_create(target, closed_ear, open_ear,
                                            int(low_seconds * 1000),
                                            int(cooldown_seconds * 1000))
        if not self._handle:
            raise ValueError("기준 횟수와 눈 비율·시간 설정을 확인하세요.")
        if not self._lib.be_set_stable_frames(self._handle, stable_frames):
            self.close()
            raise ValueError("연속 확인 프레임 수는 1~30이어야 합니다.")
        self.target = target

    def set_target(self, value):
        if not self._lib.be_set_target(self._handle, value):
            raise ValueError("기준 횟수는 0 이상이어야 합니다.")
        self.target = value

    def update(self, left_ear, right_ear, face_visible, monotonic_ms):
        result = BlinkOutput()
        ok = self._lib.be_update(self._handle, left_ear, right_ear,
                                 int(face_visible), int(monotonic_ms),
                                 ctypes.byref(result))
        if not ok:
            raise ValueError("C 엔진에 잘못된 시간 또는 입력이 전달됐습니다.")
        return result

    def close(self):
        if getattr(self, "_handle", None):
            self._lib.be_destroy(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
