"""Build the small C decision engine as a library for ctypes."""

from pathlib import Path
import os
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "blink_engine.c"


def build() -> Path:
    system = platform.system()
    if system == "Windows":
        output = ROOT / "blink_engine.dll"
    elif system == "Darwin":
        output = ROOT / "libblink_engine.dylib"
    else:
        output = ROOT / "libblink_engine.so"

    compiler = shutil.which("gcc") or shutil.which("clang")
    if compiler:
        command = [compiler, "-std=c11", "-O2", "-shared", "-fPIC",
                   str(SOURCE), "-o", str(output)]
        if system != "Windows":
            command.append("-lm")
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
        command = f'call "{script}" >nul && cl /nologo /O2 /LD /Fe:"{output}" "{SOURCE}"'
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
