"""
Single source of truth for where TriFlow keeps its data.

Two modes:
  DEV (running from the repo): everything stays where it always was —
      backend/data, backend/.tokens, backend/.secrets — so development is
      unchanged and nothing in the repo layout moves.
  PACKAGED (PyInstaller exe, sys.frozen): per-user OS app-data dir —
      Windows  %APPDATA%\\TriFlow
      macOS    ~/Library/Application Support/TriFlow
      Linux    $XDG_DATA_HOME/TriFlow (or ~/.local/share/TriFlow)

TRIFLOW_DATA overrides the root in either mode (tests use it).
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

APP_NAME = "TriFlow"
_BACKEND_DIR = Path(__file__).parent


def is_frozen() -> bool:
    """True when running as a PyInstaller-packaged executable."""
    return bool(getattr(sys, "frozen", False))


def _os_app_data_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))


def data_dir() -> Path:
    """Root folder for profile + plan DB (created on demand by callers)."""
    override = os.environ.get("TRIFLOW_DATA")
    if override:
        return Path(override)
    if is_frozen():
        return _os_app_data_root() / APP_NAME
    return _BACKEND_DIR / "data"


def profile_path() -> Path:
    return data_dir() / "profile.json"


def plan_db_path() -> Path:
    return data_dir() / "plan.db"


def garmin_token_dir() -> Path:
    if os.environ.get("TRIFLOW_DATA") or is_frozen():
        return data_dir() / "tokens" / "garmin"
    return _BACKEND_DIR / ".tokens" / "garmin"  # dev: historical location


def google_secrets_dir() -> Path:
    if os.environ.get("TRIFLOW_DATA") or is_frozen():
        return data_dir() / "secrets"
    return _BACKEND_DIR / ".secrets"  # dev: historical location


def frontend_dist_dir() -> Path:
    """Where the built frontend lives (served by FastAPI in the desktop app)."""
    if is_frozen():
        # PyInstaller unpacks bundled data next to the executable (onedir) or
        # into _MEIPASS (onefile); we add the dist as "frontend" either way.
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "frontend"
    return _BACKEND_DIR.parent / "frontend" / "dist"
