"""마지막으로 선택한 알림 방식만 저장하고 다시 읽는다."""

import json
from pathlib import Path
import tempfile


MODES = {"pill": "팝업", "edge": "화면 테두리", "blink": "눈 아이콘"}
DEFAULT_MODE = "pill"
SETTINGS_PATH = Path(__file__).resolve().parent / "data" / "notification_settings.json"


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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"schema_version": 1, "mode": mode}, stream, ensure_ascii=False, indent=2)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
