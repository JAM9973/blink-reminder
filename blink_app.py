"""실행 옵션을 읽고 앱을 시작한다."""

import argparse
import os
from pathlib import Path
import sys

from app_runtime import BlinkApplication
from engine import ENGINE_MODES
from measurement_log import DEFAULT_RECORD_DIR
from notification_settings import MODES as NOTIFICATION_MODES

# 예전 검증 자료에서도 같은 이름으로 입력 함수를 부를 수 있게 둔다.
from input_tracking import DEFAULT_MODEL, MODEL_URL, LEFT_EYE, RIGHT_EYE
from input_tracking import eye_aspect_ratio, draw_eye_points, ensure_model, open_camera
from preview_window import draw_preview_buttons
from notifications import NotificationManager as EyeNotice

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache" / "matplotlib"))


def parse_args(argv=None):
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
    parser.add_argument("--no-landmarks", action="store_true",
                        help="눈 좌표 표시를 끄고 시작 (실행 중 L로 전환)")
    parser.add_argument("--no-csv", action="store_true", help="날짜별 통계와 프레임별 CSV 기록 끄기")
    parser.add_argument("--csv-dir", type=Path, default=DEFAULT_RECORD_DIR,
                        help="CSV·설정 기록 저장 폴더 (기본 data/records)")
    parser.add_argument("--mode", choices=ENGINE_MODES, default="baseline",
                        help="baseline: 기존 판정, rebound-conservative: 보수형 검증 판정")
    parser.add_argument("--desktop", action="store_true", help="Windows 제어 창·트레이·일시정지 사용")
    parser.add_argument("--background", action="store_true", help="제어 창과 영상 창을 숨긴 상태로 시작")
    parser.add_argument("--preview", action="store_true", help="데스크톱 시작 시 카메라 미리보기 켜기")
    parser.add_argument("--notification", choices=tuple(NOTIFICATION_MODES), default=None,
                        help="알림 방식 pill/edge/blink (미지정 시 저장된 선택 사용)")
    return parser.parse_args(argv)


def run(args):
    BlinkApplication(args).run()


if __name__ == "__main__":
    try:
        run(parse_args())
    except KeyboardInterrupt:
        print("프로그램을 종료했습니다.")
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(f"실행 오류: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
