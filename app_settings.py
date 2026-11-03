"""User settings for the desktop application."""

from dataclasses import asdict, dataclass, fields, replace
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"


@dataclass(frozen=True)
class AppSettings:
    camera: int = 0
    min_blinks: int = 12
    closed_ear: float = 0.18
    open_ear: float = 0.23
    stable_frames: int = 2
    low_seconds: float = 10.0
    cooldown: float = 60.0
    max_fps: int = 30
    alert_seconds: float = 5.0
    alert_opacity: float = 0.85
    alert_size: int = 200
    alert_position: str = "오른쪽 위"
    alert_text: bool = True
    alert_sound: bool = False
    preview: bool = True
    landmarks: bool = True
    csv_enabled: bool = False
    auto_start: bool = False
    start_minimized: bool = False
    model: str = ""

    def validate(self):
        integer_ranges = {
            "camera": (0, 20, "카메라 번호"),
            "min_blinks": (0, 120, "기준 횟수"),
            "stable_frames": (1, 10, "연속 확인 프레임"),
            "max_fps": (5, 60, "최대 처리 FPS"),
            "alert_size": (120, 360, "알림 크기"),
        }
        for name, (low, high, label) in integer_ranges.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{label}: {low}~{high} 사이의 정수를 입력하세요.")
        numeric_ranges = {
            "closed_ear": (0.01, 1.0, "감김 EAR"),
            "open_ear": (0.01, 1.0, "열림 EAR"),
            "low_seconds": (0, 300, "기준 미달 지속 시간"),
            "cooldown": (1, 3600, "재알림 간격"),
            "alert_seconds": (1, 30, "알림 표시 시간"),
            "alert_opacity": (0.35, 1.0, "알림 불투명도"),
        }
        for name, (low, high, label) in numeric_ranges.items():
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not low <= value <= high):
                raise ValueError(f"{label}: {low}~{high} 범위로 입력하세요.")
        if self.closed_ear >= self.open_ear:
            raise ValueError("감김 EAR은 열림 EAR보다 작아야 합니다.")
        if self.alert_position not in ("오른쪽 위", "오른쪽 아래", "왼쪽 위", "왼쪽 아래"):
            raise ValueError("알림 위치를 목록에서 선택하세요.")
        for name in ("alert_text", "alert_sound", "preview", "landmarks", "csv_enabled",
                     "auto_start", "start_minimized"):
            if type(getattr(self, name)) is not bool:
                raise ValueError("체크박스 설정값이 올바르지 않습니다.")
        if not isinstance(self.model, str):
            raise ValueError("모델 경로는 문자열이어야 합니다.")
        return self

    def with_changes(self, **changes):
        return replace(self, **changes).validate()

    def engine_key(self):
        return (self.camera, self.min_blinks, self.closed_ear, self.open_ear,
                self.stable_frames, self.low_seconds, self.cooldown, self.model)


def load_settings(path=SETTINGS_FILE):
    if not path.exists():
        return AppSettings(), ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("설정 파일의 형식이 올바르지 않습니다.")
        allowed = {item.name for item in fields(AppSettings)}
        return AppSettings(**{k: v for k, v in raw.items() if k in allowed}).validate(), ""
    except (OSError, ValueError, TypeError) as exc:
        return AppSettings(), f"저장된 설정을 읽지 못해 기본값으로 시작했습니다: {exc}"


def save_settings(settings, path=SETTINGS_FILE):
    settings.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2),
                         encoding="utf-8")
    temporary.replace(path)
