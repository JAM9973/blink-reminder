"""콘솔 없이 실행하고, 오류가 나면 로그와 안내 창을 남긴다."""

from datetime import datetime
from pathlib import Path
import sys
import traceback

from daily_log import DEFAULT_LOG_DIR


def main():
    folder = (DEFAULT_LOG_DIR.parent if getattr(sys, "frozen", False) else
              Path(__file__).resolve().parent / ".cache") / "desktop-logs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"desktop_{datetime.now():%Y%m%d_%H%M%S_%f}.log"
    previous_streams = sys.stdout, sys.stderr
    with path.open("w", encoding="utf-8", buffering=1) as stream:
        sys.stdout = sys.stderr = stream
        try:
            from blink_app import parse_args, run
            run(parse_args(["--desktop"] + sys.argv[1:]))
        except Exception as exc:
            traceback.print_exc()
            import ctypes
            reason = str(exc) if isinstance(exc, RuntimeError) else "프로그램을 실행하거나 계속 측정하지 못했습니다."
            ctypes.windll.user32.MessageBoxW(None,
                f"{reason}\n\n오류 기록: {path}",
                "눈 깜빡임 알림", 0x10)
            return 1
        finally:
            sys.stdout, sys.stderr = previous_streams
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
