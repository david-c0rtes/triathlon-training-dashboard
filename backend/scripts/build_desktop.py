"""
One-command release build: frontend -> PyInstaller bundle -> Inno Setup
installer. Windows-only (Inno Setup).

Run:  cd backend && .venv/Scripts/python.exe -m scripts.build_desktop
"""
from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).parent.parent
FRONTEND = BACKEND.parent / "frontend"

_ISCC_CANDIDATES = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    str(Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe"),
]


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}  (in {cwd})")
    subprocess.run(cmd, cwd=cwd, check=True)


def _find_iscc() -> str:
    for c in _ISCC_CANDIDATES:
        if Path(c).exists():
            return c
    found = shutil.which("ISCC.exe") or shutil.which("iscc")
    if found:
        return found
    raise SystemExit("Inno Setup's ISCC.exe not found — install Inno Setup 6 first.")


def main() -> None:
    sys.path.insert(0, str(BACKEND))
    from version import VERSION

    print(f"=== Building TriFlow {VERSION} ===")

    print("\n[1/3] Building frontend…")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise SystemExit("npm not found on PATH.")
    _run([npm, "run", "build"], cwd=FRONTEND)

    print("\n[2/3] Running PyInstaller…")
    pyinstaller = Path(sys.executable).parent / "pyinstaller.exe"
    _run([str(pyinstaller), "triflow.spec", "--noconfirm"], cwd=BACKEND)

    print("\n[3/3] Building installer…")
    iscc = _find_iscc()
    _run([iscc, f"/DMyAppVersion={VERSION}", "installer.iss"], cwd=BACKEND)

    out = BACKEND / "installer_output" / f"TriFlow-Setup-{VERSION}.exe"
    print(f"\nDone: {out}")


if __name__ == "__main__":
    main()
