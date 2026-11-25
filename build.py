"""C 판정 코드를 Python에서 부를 수 있는 라이브러리로 만든다."""

from pathlib import Path
import os
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "blink_engine.c"


def library_path() -> Path:
    system = platform.system()
    if system == "Windows":
        return ROOT / "blink_engine_v2.dll"
    elif system == "Darwin":
        return ROOT / "libblink_engine_v2.dylib"
    return ROOT / "libblink_engine_v2.so"


def build() -> Path:
    system = platform.system()
    output = library_path()

    compiler = shutil.which("gcc") or shutil.which("clang")
    if compiler:
        # 한글 폴더에서도 빌드되도록 파일 이름만 넘긴다.
        command = [compiler, "-std=c11", "-O2", "-shared",
                   SOURCE.name, "-o", output.name]
        if system != "Windows":
            command.extend(["-fPIC", "-lm"])
        subprocess.run(command, check=True, cwd=ROOT)
    elif system == "Windows":
        roots = [Path(os.environ.get("ProgramFiles", "C:/Program Files")),
                 Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))]
        scripts = []
        for root in roots:
            scripts.extend((root / "Microsoft Visual Studio").glob(
                "*/**/VC/Auxiliary/Build/vcvars64.bat"))
        if not scripts:
            raise RuntimeError("C 컴파일러가 없습니다. Visual Studio C++ 빌드 도구를 설치하세요.")
        script = sorted(scripts, reverse=True)[0]
        command = f'call "{script}" >nul && cl /nologo /O2 /LD /Fe:"{output.name}" "{SOURCE.name}"'
        subprocess.run(command, check=True, cwd=ROOT, shell=True)
    else:
        raise RuntimeError("gcc 또는 clang 컴파일러가 필요합니다.")
    print(f"빌드 완료: {output}")
    return output


if __name__ == "__main__":
    try:
        build()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"빌드 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
