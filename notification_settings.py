"""알림 방식과 자동 알림의 켜짐 상태를 저장한다."""

import json
from pathlib import Path
import sys
import tempfile

from daily_log import DEFAULT_LOG_DIR

MODES = {"pill": "팝업", "edge": "화면 테두리", "blink": "눈 아이콘"}
DEFAULT_MODE = "pill"
SETTINGS_PATH = (DEFAULT_LOG_DIR.parent if getattr(sys, "frozen", False) else
                 Path(__file__).resolve().parent / "data") / "notification_settings.json"
MUTE_PATH = DEFAULT_LOG_DIR.parent / "notification_mute.json"
MUTE_OPTIONS = {"on": "알림 켜기", "10": "10분 동안 끄기", "60": "1시간 동안 끄기",
                "120": "2시간 동안 끄기", "1440": "24시간 동안 끄기", "off": "계속 끄기"}


def load_mode(path=SETTINGS_PATH):
    path = Path(path)
    try:
        if not path.exists():
            return DEFAULT_MODE, ""
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("mode") not in MODES:
            raise ValueError("알림 설정 형식 오류")
        return data["mode"], ""
    except (OSError, ValueError, TypeError):
        return DEFAULT_MODE, "저장값을 읽지 못해 기본 알림을 사용합니다."


def save_mode(mode, path=SETTINGS_PATH):
    if mode not in MODES:
        raise ValueError("지원하지 않는 알림 방식입니다.")
    _save_settings(path, {"schema_version": 1, "mode": mode})


def load_mute(path=MUTE_PATH):
    try:
        data = Path(path).read_text(encoding="utf-8")
        value = json.loads(data)
        if value is not None and value != "off" and (type(value) is not int or value <= 0):
            raise ValueError("알림 끄기 설정 형식 오류")
        return value, ""
    except FileNotFoundError:
        return None, ""
    except (OSError, ValueError):
        return None, "알림 끄기 설정을 읽지 못했습니다."


def save_mute(value, path=MUTE_PATH):
    _save_settings(path, value)


def _save_settings(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
