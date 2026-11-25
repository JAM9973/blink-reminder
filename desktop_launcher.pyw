"""콘솔 없이 실행하고, 오류가 나면 로그와 안내 창을 남긴다."""

from datetime import datetime
from pathlib import Path
import sys
import traceback

from blink_app import parse_args, run


def main():
    folder = Path(__file__).resolve().parent / ".cache" / "desktop-logs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"desktop_{datetime.now():%Y%m%d_%H%M%S_%f}.log"
    previous_streams = sys.stdout, sys.stderr
    with path.open("w", encoding="utf-8", buffering=1) as stream:
        sys.stdout = sys.stderr = stream
        try:
            run(parse_args(["--desktop"] + sys.argv[1:]))
        except Exception:
            traceback.print_exc()
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                f"프로그램을 실행하거나 계속 측정하지 못했습니다.\n카메라를 사용하는 다른 앱을 종료한 뒤 다시 실행하세요.\n\n오류 기록: {path}",
                "눈 깜빡임 알림", 0x10)
            return 1
        finally:
            sys.stdout, sys.stderr = previous_streams
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
