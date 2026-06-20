from __future__ import annotations
import os
from pathlib import Path

from garminconnect import Garmin

_TOKEN_DIR = Path(__file__).parent.parent.parent / ".tokens" / "garmin"


def _credentials() -> tuple[str, str]:
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        raise EnvironmentError("GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env")
    return email, password


def get_client() -> Garmin:
    """
    Return an authenticated Garmin Connect client.

    Resumes from a saved session in .tokens/garmin when possible (no password
    round-trip); otherwise logs in fresh with email/password and persists the
    session tokens for next time.

    In garminconnect 0.3.x the garth session is stored at client.client (not
    client.garth), and login() accepts tokenstore as a keyword argument.
    """
    tokenstore = str(_TOKEN_DIR)

    # Try to resume an existing session first
    if _TOKEN_DIR.exists():
        try:
            client = Garmin()
            client.login(tokenstore=tokenstore)
            return client
        except Exception:
            pass  # tokens expired or invalid — fall through to fresh login

    email, password = _credentials()
    client = Garmin(email=email, password=password)
    client.login()

    # Persist session tokens so future calls skip the password login
    _TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    client.client.dump(tokenstore)
    return client


def is_authenticated() -> bool:
    """True if saved Garmin session tokens exist on disk."""
    return _TOKEN_DIR.exists() and any(_TOKEN_DIR.iterdir())
