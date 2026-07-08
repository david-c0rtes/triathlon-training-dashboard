from datetime import date
from fastapi import APIRouter, HTTPException

from domain.profile_store import load_profile
from domain.workout import Workout
from api.routes import workouts_in_range
from integrations.google import calendar as gcal

router = APIRouter(prefix="/api/v1/google")


@router.get("/status")
def google_status():
    """Whether Google Calendar is set up (client secret present) and connected."""
    return gcal.status()


@router.post("/connect")
def google_connect():
    """Run the one-time OAuth consent flow (opens a browser on the server machine)."""
    if not gcal.is_configured():
        raise HTTPException(
            status_code=400,
            detail="Missing backend/.secrets/google_client_secret.json — complete the Google setup first.",
        )
    try:
        gcal.connect()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Google connect failed: {e}")
    return gcal.status()


@router.post("/disconnect")
def google_disconnect():
    gcal.disconnect()
    return gcal.status()


@router.post("/push")
def google_push(start: date, end: date):
    """Publish all planned workouts in [start, end] to the TriFlow Training calendar."""
    if not gcal.is_configured():
        raise HTTPException(status_code=400, detail="Google Calendar isn't set up yet.")
    profile = load_profile()
    workouts = workouts_in_range(profile, start, end)
    payload = [{
        "date": w.scheduled_date.isoformat(),
        "title": w.title,
        "duration_min": w.total_duration_minutes,
        "description": _describe(w),
    } for w in workouts]
    try:
        return gcal.push_workouts(payload)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Google push failed: {e}")


# ── event description formatting ─────────────────────────────────────────────

_METRIC_LABEL = {"power_zone": "Power", "hr_zone": "HR", "pace_zone": "Pace"}


def _fmt_target(t: dict | None) -> str:
    if not t or t.get("type") == "open":
        return "free"
    if t.get("type") == "power_pct":
        return f"{round((t.get('pct_of_anchor') or 0) * 100)}%FTP"
    return f"{_METRIC_LABEL.get(t.get('type'), t.get('type'))} Z{t.get('zone')}"


def _fmt_step(s: dict) -> str:
    dur = s.get("duration_seconds") or 0
    m, sec = divmod(dur, 60)
    when = f"{s['distance_meters']} m" if s.get("distance_meters") else f"{m}:{sec:02d}"
    return f"• {s.get('name', 'Step')} — {when} @ {_fmt_target(s.get('target'))}"


def _describe(w: Workout) -> str:
    d = w.detail()
    lines = [f"{d['sport']} · {d['duration_min']} min · {d['planned_tss']} TSS"]
    if d.get("description"):
        lines.append(d["description"])
    lines.append("")
    for s in d["steps"]:
        if s.get("kind") == "repeat":
            lines.append(f"{s.get('repeat_count', 1)}×")
            lines.extend("  " + _fmt_step(sub) for sub in s.get("steps", []))
        else:
            lines.append(_fmt_step(s))
    lines.append("\n— TriFlow")
    return "\n".join(lines)
