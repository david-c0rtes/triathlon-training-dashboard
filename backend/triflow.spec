# PyInstaller spec for the TriFlow desktop app.
#
# Build (from backend/, with frontend already built):
#   cd frontend && npm run build
#   cd ../backend && .venv/Scripts/pyinstaller.exe triflow.spec --noconfirm
#
# Output: backend/dist/TriFlow/TriFlow.exe (onedir — faster startup and far
# fewer antivirus false-positives than onefile; the installer zips it up).
from pathlib import Path

BACKEND = Path(SPECPATH)
FRONTEND_DIST = BACKEND.parent / "frontend" / "dist"
if not FRONTEND_DIST.is_dir():
    raise SystemExit("frontend/dist not found — run `npm run build` in frontend/ first")

a = Analysis(
    ["desktop.py"],
    pathex=[str(BACKEND)],
    binaries=[],
    # Ship the built frontend inside the app; apppaths.frontend_dist_dir()
    # resolves to <bundle>/frontend when frozen.
    datas=[(str(FRONTEND_DIST), "frontend")],
    hiddenimports=[
        # uvicorn's import-by-string internals
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        # pywebview's Windows backend (EdgeChromium/WebView2 via pythonnet)
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TriFlow",
    console=False,  # windowed app — no terminal
    icon=None,      # TODO: add an .ico when brand assets exist
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="TriFlow",
)
