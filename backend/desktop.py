"""
TriFlow desktop entrypoint — what the packaged app runs.

Starts the FastAPI backend on a random free localhost port (avoids clashes
with anything else on the user's machine) and opens a native window onto it
via pywebview. Closing the window shuts the server down.

Dev preview from the repo:
    cd frontend && npm run build      (bakes the same-origin API base)
    cd ../backend && PYTHONPATH=. .venv/Scripts/python.exe desktop.py
"""
from __future__ import annotations
import socket
import threading
import time
import webbrowser

import uvicorn
import webview

import apppaths
from main import app  # noqa: E402 — main runs load_dotenv() on import (dev convenience)


class DesktopApi:
    """Exposed to the frontend as window.pywebview.api — lets pages like the
    update banner open links in the user's real browser instead of the
    embedded webview swallowing the navigation."""

    def open_external(self, url: str) -> None:
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run() -> None:
    dist = apppaths.frontend_dist_dir()
    if not dist.is_dir():
        raise SystemExit(
            f"Frontend build not found (looked in {dist}).\n"
            "Run `npm run build` in frontend/ first."
        )

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):  # wait up to ~10s for the server to come up
        if server.started:
            break
        time.sleep(0.1)

    webview.create_window(
        apppaths.APP_NAME,
        f"http://127.0.0.1:{port}",
        width=1280,
        height=860,
        min_size=(960, 640),
        js_api=DesktopApi(),
    )
    webview.start()  # blocks until the window is closed

    server.should_exit = True
    thread.join(timeout=5)


if __name__ == "__main__":
    run()
