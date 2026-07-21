"""
Google Calendar integration (OAuth 2.0 installed-app flow).

The app is single-user today, so we use the Desktop/installed OAuth flow: the
user clicks "Connect", a browser opens for one-time consent, and the resulting
token is cached in backend/.secrets/. Workouts are written to a dedicated
"TriFlow Training" calendar so they stay isolated from personal events.

Setup (user, one time):
  1. Google Cloud project → enable Google Calendar API.
  2. OAuth consent screen (External) + add yourself as a test user, scope
     https://www.googleapis.com/auth/calendar.
  3. Create a Desktop OAuth client, download it as
     backend/.secrets/google_client_secret.json.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta

import apppaths


def _secrets_dir():
    return apppaths.google_secrets_dir()


def _client_secret_path():
    return _secrets_dir() / "google_client_secret.json"


def _token_path():
    return _secrets_dir() / "google_token.json"


def _cal_id_path():
    return _secrets_dir() / "google_calendar_id.txt"

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_CALENDAR_NAME = "TriFlow Training"
_TAG = "triflow"  # extendedProperties key marking events this app created


def is_configured() -> bool:
    """True once the user has dropped in their OAuth client secret."""
    return _client_secret_path().exists()


def status() -> dict:
    """Lightweight connection status for the UI (no network call beyond a refresh)."""
    configured = is_configured()
    connected = False
    if configured and _token_path().exists():
        try:
            _load_service()
            connected = True
        except Exception:
            connected = False
    return {"configured": configured, "connected": connected}


def connect() -> None:
    """
    Run the interactive OAuth consent flow (opens a browser on this machine)
    and cache the resulting token. Blocks until the user approves.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not is_configured():
        raise RuntimeError(f"Missing {_client_secret_path()}.")
    flow = InstalledAppFlow.from_client_secrets_file(str(_client_secret_path()), SCOPES)
    creds = flow.run_local_server(port=0)
    _secrets_dir().mkdir(parents=True, exist_ok=True)
    _token_path().write_text(creds.to_json())


def disconnect() -> None:
    """Forget the cached token (and calendar id) — user must reconnect to push again."""
    for f in (_token_path(), _cal_id_path()):
        f.unlink(missing_ok=True)


def _load_service():
    """Build an authorized Calendar API service, refreshing the token if needed."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    if not _token_path().exists():
        raise RuntimeError("Google Calendar not connected — connect first.")
    creds = Credentials.from_authorized_user_file(str(_token_path()), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _token_path().write_text(creds.to_json())
        else:
            raise RuntimeError("Google Calendar token invalid — reconnect.")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _account_timezone(service) -> str:
    """The user's actual Google account timezone (e.g. 'Europe/Madrid')."""
    try:
        return service.settings().get(setting="timezone").execute().get("value", "UTC")
    except Exception:
        return "UTC"


def _training_calendar_id(service) -> str:
    """Find (or create) the dedicated 'TriFlow Training' calendar; cache its id."""
    if _cal_id_path().exists():
        return _cal_id_path().read_text().strip()

    page = None
    while True:
        resp = service.calendarList().list(pageToken=page).execute()
        for item in resp.get("items", []):
            if item.get("summary") == _CALENDAR_NAME:
                _cal_id_path().write_text(item["id"])
                return item["id"]
        page = resp.get("nextPageToken")
        if not page:
            break

    # New calendars default to UTC unless a timeZone is given — use the
    # account's own timezone so events land at the intended local time.
    created = service.calendars().insert(body={
        "summary": _CALENDAR_NAME,
        "description": "Workouts planned in TriFlow.",
        "timeZone": _account_timezone(service),
    }).execute()
    _secrets_dir().mkdir(parents=True, exist_ok=True)
    _cal_id_path().write_text(created["id"])
    return created["id"]


def push_workouts(workouts: list[dict], start_time: str = "06:00") -> dict:
    """
    Idempotently publish workouts to the TriFlow Training calendar. Any existing
    TriFlow events within the pushed date range are cleared first, then each
    workout is inserted as a timed event (default 06:00, lasting its duration).

    Each workout dict needs: date (ISO), title, duration_min, description.
    """
    if not workouts:
        return {"pushed": 0, "deleted": 0}

    service = _load_service()
    cal_id = _training_calendar_id(service)
    tz = service.calendars().get(calendarId=cal_id).execute().get("timeZone", "UTC")

    dates = sorted(date.fromisoformat(w["date"]) for w in workouts)
    time_min = f"{dates[0].isoformat()}T00:00:00Z"
    time_max = f"{(dates[-1] + timedelta(days=1)).isoformat()}T00:00:00Z"

    # Clear previously-pushed TriFlow events in this window (idempotent re-push).
    deleted = 0
    existing = service.events().list(
        calendarId=cal_id, privateExtendedProperty=f"{_TAG}=1",
        timeMin=time_min, timeMax=time_max, singleEvents=True, maxResults=2500,
    ).execute()
    for ev in existing.get("items", []):
        service.events().delete(calendarId=cal_id, eventId=ev["id"]).execute()
        deleted += 1

    hh, mm = (int(x) for x in start_time.split(":"))
    pushed = 0
    for w in workouts:
        d = date.fromisoformat(w["date"])
        start_dt = datetime(d.year, d.month, d.day, hh, mm)
        end_dt = start_dt + timedelta(minutes=max(1, int(w.get("duration_min", 60))))
        service.events().insert(calendarId=cal_id, body={
            "summary": w["title"],
            "description": w.get("description", ""),
            "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": tz},
            "extendedProperties": {"private": {_TAG: "1"}},
        }).execute()
        pushed += 1

    return {"pushed": pushed, "deleted": deleted, "calendar": _CALENDAR_NAME, "timezone": tz}
