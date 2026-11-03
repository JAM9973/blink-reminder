# WSL에서 개발하고 Windows에서 실행하는 시작 안내

기준: 2026-11-02. 실제 구현자는 조재민, 개발 도구는 WSL Ubuntu의 Codex CLI, 최종 실행 환경은 Windows다.

## 환경별 역할

| 환경 | 할 일 | 이 환경의 결과만으로 확정할 수 없는 내용 |
|---|---|---|
| WSL Ubuntu | 코드 편집, C 로직 빌드, 가상 입력 테스트, 관리 문서, 로컬 Git 기록 | Windows DLL·웹캠·알림 화면의 실제 동작 |
| Windows | Windows용 C 빌드, Python 연동, 웹캠, 설정·알림·일시정지, 실사용 검증 | WSL 실행 결과와 같은 코드인지 버전 확인 필요 |
| GitHub | 완성 후 코드·개발 기록·실행 안내 공유 | 실제 사용자 실험의 대체 근거가 아님 |

## 11/3 전달 전 확인 사항

현재 Windows 폴더에는 build.py·C·헤더·engine.py의 변경과 app_settings.py·camera_worker.py 등 새 파일이 있다. 아래 clone은 커밋된 v00만 가져오므로 최신 전달을 완료하지 못한다. 기존 변경을 보존하고 필요한 파일 목록을 검토해 커밋하거나 별도 전달한 뒤 양쪽 버전을 대조한다. 가상환경과 플랫폼별 빌드 결과물은 재사용하지 않는다.

11/3 Windows 빌드·기존 테스트 5개는 통과했다. WSL 조회는 `Wsl/E_ACCESSDENIED`로 실패했으므로 접근 가능한 일반 터미널에서 확인한다. 이번 결과를 WSL 미설치로 해석하지 않는다.

## 1. 현재 저장소를 WSL에 복제

기존 Windows 폴더에는 Git 저장소와 v00 커밋이 있다. 새로 초기화하는 대신 로컬 복제로 이력을 이어간다. WSL의 홈 디렉터리에 개발본을 두고, Windows에는 검증할 시점의 코드를 전달한다.

WSL과 파일 배치 근거: [OpenAI의 WSL 안내](https://learn.chatgpt.com/docs/windows/wsl), [Microsoft의 파일 시스템 안내](https://learn.microsoft.com/en-us/windows/wsl/filesystems). 두 문서는 Linux 도구로 작업할 때 Linux 파일 시스템에 프로젝트를 두는 방식을 권장한다.

먼저 Windows PowerShell에서 다음 명령으로 설치된 배포판과 WSL 버전을 확인한다.

```powershell
wsl --list --verbose
```

아래 시작 절차는 WSL2를 기준으로 한다. 표에 VERSION 1이 표시되면 변환 전에 현재 배포판 상태와 백업 방법을 확인한다. 현재 Codex의 WSL 지원 기준은 위 OpenAI 문서를 따른다.

Ubuntu 터미널에서는 다음 순서로 실행한다. 예시는 새 폴더 `~/projects/blink-reminder`를 사용한다. 같은 이름의 작업 폴더가 이미 있으면 기존 내용을 확인하고 이어간다.

```bash
mkdir -p ~/projects
git clone "/mnt/c/Users/alex6/Desktop/프기2_조별과제" ~/projects/blink-reminder
```

복제가 성공하면 아직 커밋되지 않은 최신 지침과 개발 문서를 복사한다. 이 안내 작성 시점에는 애플리케이션 소스의 추적된 변경이 없는 것을 확인했으며, 이후 소스를 수정했다면 그 변경도 별도로 전달해야 한다.

```bash
cp "/mnt/c/Users/alex6/Desktop/프기2_조별과제/AGENTS.md" "/mnt/c/Users/alex6/Desktop/프기2_조별과제/.gitignore" ~/projects/blink-reminder/
cp -r "/mnt/c/Users/alex6/Desktop/프기2_조별과제/개발관리" ~/projects/blink-reminder/
cd ~/projects/blink-reminder
git remote rename origin windows-source
git switch -c codex/implementation
codex
```

`windows-source`는 최초 Windows 저장소를 가리키는 로컬 원격 이름이다. GitHub 연결은 마지막에 추가한다. 두 작업 폴더를 동시에 수정하지 않고 WSL 개발본을 이후 변경의 기준으로 삼는다.

Codex는 프로젝트 루트에서 시작한다. 상위 Documents 폴더 전체를 프로젝트로 열면 다른 프로젝트의 지침과 파일이 섞일 수 있다. AGENTS.md는 자동으로 읽히는 지침이고, 나머지 관리 문서는 프롬프트에서 읽도록 지정한다. [공식 AGENTS.md 안내](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

## 2. 첫 구현 턴에 맡길 일

PROMPTS.md의 T01 프롬프트를 사용한다. 첫 턴에서는 다음을 확보한다.

1. Ubuntu·WSL·CPU·Python·컴파일러 버전과 아키텍처 확인.
2. WSL의 별도 Python 가상환경과 C 빌드·기초 테스트 실행.
3. 기존 Windows 빌드 실패를 Windows에서 재확인할 절차와 최소 수정.
4. Windows Python과 C 컴파일러의 아키텍처, MediaPipe·OpenCV 의존성 확인.
5. WSL 테스트 결과와 Windows에서 사용자가 확인할 절차를 분리해 기록.

WSL은 `.venv-linux`, Windows는 `.venv-win`처럼 가상환경을 나눈다. 기존 Windows `.venv`를 WSL에 복사하지 않는다. Linux는 `libblink_engine.so`, Windows는 `blink_engine.dll`을 각 환경에서 빌드한다. 실제 Python·C 컴파일러·라이브러리 아키텍처가 맞는지도 확인한다.

WSL의 C 가상 입력 테스트에는 카메라나 GUI가 필요하지 않다. Windows에서 사용할 영상 패키지를 WSL에도 모두 설치하는 일을 첫 목표로 삼지 않는다. 카메라·화면 검증은 Windows 네이티브 실행 결과를 남긴다.

## 3. 매 턴의 반복 절차

목표 지정 → 이번 범위 구현 → 관련 자동테스트 → Windows 확인이 필요한 항목 실행 → 기록 갱신 → 로컬 Git 커밋 순서로 진행한다.

- 한 턴에 기능 하나 또는 오류 하나를 주된 목표로 둔다.
- 실제 사용한 프롬프트, 변경 이유, 테스트 결과, 직접 실행한 판단을 DEVELOPMENT_LOG.md에 남긴다.
- 카메라와 사용자 실험은 직접 수행한 결과를 전달한 뒤 기록한다.
- Windows 확인이 남아 있으면 해당 항목은 미검증으로 유지한다.
- 커밋할 파일을 확인하고 이번 작업에 해당하는 소스·문서만 선택한다. 기존 README의 VERSION 증가·vNN 태그 규칙을 따른다.

GitHub 저장소가 없어도 로컬 커밋과 태그를 만들 수 있다. 중간 제출 시점의 커밋과 실제 진행률을 기록해 최종 버전과 구분한다.

## 4. Windows로 같은 코드 버전 전달

Windows 검증은 첫 빌드 단계와 주요 통합 단계마다 수행한다. WSL의 확인할 변경을 커밋한 뒤 그 커밋을 ZIP으로 내보내면 같은 코드 버전을 검증할 수 있다.

아래는 첫 체크포인트의 예시이며 실제 커밋 후 사용한다.

```bash
mkdir -p "/mnt/c/Users/alex6/Desktop/프기2_조별과제/windows-checkpoints"
git rev-parse HEAD
git archive --format=zip --output="/mnt/c/Users/alex6/Desktop/프기2_조별과제/windows-checkpoints/turn-01.zip" HEAD
```

Git archive에는 커밋한 파일만 들어간다. 전달해야 할 새 소스·관리 문서가 누락되지 않았는지 확인한다. 가상환경, 모델 캐시, Linux 빌드 결과물은 전달본에 의존하지 않도록 하고 Windows에서 필요한 환경과 DLL을 준비한다.

Windows에서는 ZIP을 별도 검증 폴더에 풀고 T01에서 확정한 Windows용 설치·빌드·실행 절차를 따른다. 기존 원본 폴더를 덮어쓰지 않는다. Windows용 Python 의존성, DLL 빌드, 기초 테스트, 웹캠·UI 순서로 확인한다.

Linux에서 성공한 결과와 Windows에서 실패한 결과는 함께 기록하고, 플랫폼 차이로 생긴 오류도 다음 수정 턴의 근거로 사용한다. Windows 검증 중 수정이 필요하면 WSL 개발본에 반영한 뒤 새 커밋으로 다시 전달한다.

## 5. 완성 후 GitHub 연결

현재 로컬 저장소 기록을 유지한 채 GitHub에 연결한다. 저장소 이름과 공개 범위를 정하고 기존 연결 상태를 먼저 확인한다. 새 빈 저장소라면 README·라이선스를 GitHub에서 따로 생성해 두지 않고 로컬 기록을 처음부터 올리는 방식이 단순하다.

확인된 저장소 주소를 origin으로 연결하고 현재 개발 브랜치를 올린다. 기본 브랜치 구성과 태그 업로드도 함께 정리한다. GitHub CLI를 사용할 경우 기존 폴더를 `--source`로 지정하는 저장소 생성 기능을 사용할 수 있다. [GitHub CLI 공식 안내](https://cli.github.com/manual/gh_repo_create)

완성 확인에는 Windows에서 실행 가능한 상태, 기본·경계 테스트, 실제 비교 결과, 설정·일시정지·종료, 실행 안내, 의존성·모델 준비 방법, 확인된 한계가 포함된다. 가상환경·컴파일 결과물·캐시·관계없는 수업 파일은 저장소에 넣지 않는다.

## 이번 안내에서 실제로 한 일

Windows 작업 폴더의 기존 코드·Git 상태를 읽고 안내와 관리 문서를 갱신했다. WSL로 복제하거나 Ubuntu에 패키지를 설치하거나 GitHub 저장소를 생성한 것은 아니다. T01 구현과 실제 환경 검증은 위 절차로 시작한다.
