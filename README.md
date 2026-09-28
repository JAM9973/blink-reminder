# 눈 깜빡임 알림 프로토타입

현재 버전: **00** (`VERSION` 파일 기준). 이후 수정 사항을 커밋할 때마다 버전을 `01`, `02`처럼 1씩 올리고, 커밋 메시지에 변경 내용과 이유를 적습니다. 각 버전은 같은 번호의 Git 태그(`v00`, `v01` 등)로 표시합니다.

웹캠 영상은 Python과 MediaPipe가 읽고, **깜빡임 판정·최근 60초 집계·알림 결정은 C**가 처리합니다. 얼굴 영상은 저장하지 않습니다. 기본 기준인 12회/60초는 시연용 설정이며 의학적 기준이 아닙니다.

## 작업 순서와 현재 상태

1. **최소 기능 구현 완료**: 얼굴의 양쪽 눈 EAR 계산 → C 라이브러리 호출 → 60초 집계 → 👀 알림.
2. **판정 안정화 완료**: 연속 2프레임, 양쪽 눈 일치, 얼굴 미검출 시간 제외, 알림 대기 시간.
3. **현장 조정**: 조명·카메라에 따라 `--closed-ear`, `--open-ear`, 기준 횟수를 조정하고 실제 사람의 수기 기록과 비교.
4. **발표**: 아래 C 상태 변수, 배열, 조건문, 시간 계산을 실행 화면과 함께 설명.

## 실행

Windows 기준, 이 폴더에서 다음을 순서대로 실행합니다. 첫 실행은 Google의 얼굴 랜드마크 모델을 다운로드하므로 인터넷이 필요합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe build.py
.\.venv\Scripts\python.exe blink_app.py --min-blinks 12
```

`Q` 또는 `Esc`로 종료하고, 실행 중 `+`/`-`로 기준 횟수를 바꿀 수 있습니다. 다른 카메라는 `--camera 1`처럼 지정합니다. 모델을 직접 받은 경우 `--model 경로`로 지정할 수 있습니다. 팝업을 표시하지 못하는 환경에서는 콘솔에 같은 알림이 출력됩니다.

설치가 끝난 이 PC에서는 PowerShell을 **어느 폴더에서 열어도** 다음 명령으로 실행할 수 있습니다. `run.cmd`가 프로젝트 폴더로 이동한 뒤 프로그램을 시작합니다.

```powershell
& 'C:\Users\alex6\Desktop\프기2_조별과제\run.cmd'
```

프로그램 화면에 초점을 맞춘 뒤 `Q` 또는 `Esc`를 누르면 종료됩니다. 이 PC에서는 일반 실행 권한의 PowerShell로 실제 카메라 프레임과 깜빡임 집계를 확인했습니다. 카메라가 없다는 메시지가 **Codex의 제한된 도구 실행 환경에서만** 나타날 수 있으므로, 그 경우 일반 Windows PowerShell에서 위 명령을 사용하세요.

```powershell
.\.venv\Scripts\python.exe blink_app.py --min-blinks 8 --closed-ear 0.17 --open-ear 0.22 --low-seconds 10 --cooldown 60
```

`EAR`은 눈의 세로 길이 합을 가로 길이의 두 배로 나눈 값입니다. 눈을 뜨면 높고 감으면 낮아집니다. 화면의 `EAR L/R`를 보고 자신의 눈에 맞는 두 문턱값을 정하세요. `closed-ear`는 감김의 상한, `open-ear`는 열림의 하한이며, 두 값 사이에서는 상태를 바꾸지 않습니다.

## 단계별 확인

1. `.\.venv\Scripts\python.exe -m unittest test_engine.py`로 웹캠 없이 C 판정 로직을 확인합니다. 열린 눈→감긴 눈→열린 눈은 1회, 오래 감기와 한 프레임 잡음은 0회인지 검증합니다.
2. 카메라 화면에서 얼굴을 보이면 `Eyes`와 양쪽 `EAR`이 나오며, 한 번 깜빡일 때 `60s blinks`가 1씩 증가하는지 봅니다. 얼굴을 가리면 `NO FACE`가 표시됩니다.
3. 빠른 시연은 `--min-blinks 1 --low-seconds 0 --cooldown 10`으로 실행합니다. **얼굴이 보인 누적 시간 60초**가 지난 뒤 깜빡임이 0회라면 작은 👀 알림이 뜹니다. 알림 후 10초 이내에는 다시 뜨지 않습니다.

## C 코드 설명

- `state`는 `UNKNOWN(0)`, `OPEN(1)`, `CLOSED(2)` 중 하나입니다. 시작할 때 열린 상태를 두 프레임 확인해야 합니다.
- `candidate_frames`는 같은 상태가 연속으로 들어온 횟수입니다. 양쪽 눈이 다르거나 문턱값 사이면 후보를 지워 순간 오류를 무시합니다.
- `if (state == CLOSED && candidate == OPEN)`에서 **감김 뒤 열림**을 한 번만 셉니다. 감긴 동안은 상태가 그대로라 중복되지 않습니다.
- `events[]` 배열에는 각 깜빡임의 `active_ms`를 저장합니다. `prune()`은 60초보다 오래된 시각을 제거하고 `event_count`가 최근 횟수입니다.
- `active_ms`는 얼굴이 연속으로 보인 프레임의 시간차만 더합니다. 얼굴 미검출 또는 1초 넘는 프레임 공백은 집계 시간에 넣지 않습니다.
- 최근 횟수가 `target`보다 낮은 상태가 `low_duration_ms` 이상 이어지면 `alert=1`을 반환합니다. `last_alert_ms`와 `cooldown_ms`가 연속 알림을 막습니다.
- Python의 `engine.py`는 `ctypes`로 C 함수를 호출하고, `blink_app.py`는 입력 영상과 알림 UI만 담당합니다.

## 수기 비교 기록표

실제 촬영 전 결과를 임의로 채우지 않았습니다. 같은 60초 동안 사람이 센 값과 화면 값을 적어 기준 변경 전후를 비교하세요.

| 조건 | 수기 횟수 | 프로그램 횟수 | 차이(프로그램−수기) |
| --- | ---: | ---: | ---: |
| 기본값, 밝은 곳 |  |  |  |
| 기본값, 어두운 곳 |  |  |  |
| EAR 조정 후, 밝은 곳 |  |  |  |
| EAR 조정 후, 어두운 곳 |  |  |  |

발표는 **문제와 역할 분담 → Python에서 EAR 추출 → C 상태 전이와 배열 → 실제 시연 → 수기 비교와 한계** 순서로 구성하면 됩니다.

MediaPipe API 및 모델: [Google Face Landmarker 문서](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceLandmarker), [Google 모델 경로](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/tasks/web/vision/README.md).
