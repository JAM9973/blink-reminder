"""Python에서 C 판정 함수를 부르기 위한 연결 코드다."""

import ctypes
from pathlib import Path
from build import library_path


ENGINE_MODES = ("baseline", "rebound-conservative")
BLINK_REASONS = {0: "none", 1: "normal_reopen", 2: "relative_reclosure"}


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
                 low_seconds=10, cooldown_seconds=60, stable_frames=2, mode="baseline"):
        if mode not in ENGINE_MODES:
            raise ValueError("판정 모드는 baseline 또는 rebound-conservative이어야 합니다.")
        root = Path(__file__).resolve().parent
        path = library_path()
        sources = [root / "blink_engine.c", root / "blink_engine.h"]
        if not path.exists() or any(p.stat().st_mtime_ns > path.stat().st_mtime_ns
                                     for p in sources):
            from build import build
            build()
        self._lib = ctypes.CDLL(str(path))
        self._lib.be_api_version.argtypes = []
        self._lib.be_api_version.restype = ctypes.c_int
        if self._lib.be_api_version() != 2:
            raise RuntimeError("C 라이브러리 API 버전이 맞지 않습니다. python build.py를 실행하세요.")
        self._lib.be_set_rebound_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._lib.be_set_rebound_enabled.restype = ctypes.c_int
        self._lib.be_get_blink_reason.argtypes = [ctypes.c_void_p]
        self._lib.be_get_blink_reason.restype = ctypes.c_int
        self._lib.be_rebound_parameter.argtypes = [ctypes.c_int]
        self._lib.be_rebound_parameter.restype = ctypes.c_double
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
        if not self._lib.be_set_rebound_enabled(self._handle, int(mode == "rebound-conservative")):
            self.close()
            raise ValueError("C 판정 모드를 적용하지 못했습니다.")
        self.mode = mode
        names = ("rise", "fall", "floor", "rise_frames", "fall_frames",
                 "min_closed_ms", "max_closed_ms", "max_rise_ms")
        self.rebound_parameters = {
            name: (self._lib.be_rebound_parameter(i) if i < 3
                   else int(self._lib.be_rebound_parameter(i)))
            for i, name in enumerate(names)}
        self.target = target

    def set_target(self, value):
        if not self._lib.be_set_target(self._handle, value):
            raise ValueError("기준 횟수는 0 이상이어야 합니다.")
        self.target = value

    def update(self, left_ear, right_ear, face_visible, monotonic_ms):
        """눈 입력을 C에 보내고 판정 결과를 받는다.

        잘못된 EAR은 측정 시간을 멈추며, 이미 센 횟수는 유지한다.
        """
        result = BlinkOutput()
        ok = self._lib.be_update(self._handle, left_ear, right_ear,
                                 int(face_visible), int(monotonic_ms),
                                 ctypes.byref(result))
        if not ok:
            raise ValueError("C 엔진에 잘못된 시간 또는 입력이 전달됐습니다.")
        result.blink_reason = BLINK_REASONS[self._lib.be_get_blink_reason(self._handle)]
        result.engine_mode = self.mode
        return result

    def close(self):
        if getattr(self, "_handle", None):
            self._lib.be_destroy(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
