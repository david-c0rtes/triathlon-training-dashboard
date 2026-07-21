"""
Checks GitHub Releases for a newer TriFlow than the one bundled — the whole
update mechanism for a locally-installed app with no backend server of its
own. Purely informational: on a hit, the UI links the user to the release
page to download and run the new installer themselves; nothing auto-updates.
"""
from __future__ import annotations
import httpx

from version import VERSION

_REPO = "david-c0rtes/triathlon-training-dashboard"
_RELEASES_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"


def _parse(v: str) -> tuple[int, ...]:
    """'v1.2.3' / '1.2.3' -> (1, 2, 3); non-numeric parts read as 0."""
    parts = []
    for p in v.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def check_for_update(timeout: float = 3.0) -> dict:
    """Best-effort: any failure (offline, rate-limited, no releases yet) just
    means 'nothing to report', never an error the UI has to handle."""
    result = {"current": VERSION, "latest": None, "latest_url": None, "update_available": False}
    try:
        resp = httpx.get(_RELEASES_URL, timeout=timeout,
                         headers={"Accept": "application/vnd.github+json"})
        if resp.status_code != 200:
            return result
        data = resp.json()
        latest = data.get("tag_name", "")
        if latest:
            result["latest"] = latest
            result["latest_url"] = data.get("html_url")
            result["update_available"] = _parse(latest) > _parse(VERSION)
    except Exception:
        pass
    return result
