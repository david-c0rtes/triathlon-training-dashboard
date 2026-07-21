from __future__ import annotations
import os
import shutil

from garminconnect import Garmin

import apppaths


class GarminMFARequired(Exception):
    """Login needs a one-time MFA code — resubmit credentials with the code."""


def _token_dir():
    return apppaths.garmin_token_dir()


def _credentials() -> tuple[str, str]:
    # Dev fallback only — the app's real flow is link_account(), from Settings
    # or the onboarding wizard.
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        raise EnvironmentError("Garmin isn't linked yet — connect your account first.")
    return email, password


def link_account(email: str, password: str, mfa_code: str | None = None) -> None:
    """
    Exchange Garmin credentials for session tokens, once. The credentials are
    used for this single login and never persisted — only the resulting garth
    tokens are stored (in the app-data dir). If the account has MFA and no
    code was provided, raises GarminMFARequired so the UI can ask for one.
    """
    def _mfa() -> str:
        if mfa_code:
            return mfa_code
        raise GarminMFARequired()

    client = Garmin(email=email, password=password, prompt_mfa=_mfa)
    client.login()

    token_dir = _token_dir()
    token_dir.mkdir(parents=True, exist_ok=True)
    client.client.dump(str(token_dir))


def unlink() -> None:
    """Forget the stored Garmin session tokens."""
    shutil.rmtree(_token_dir(), ignore_errors=True)


def get_client() -> Garmin:
    """
    Return an authenticated Garmin Connect client.

    Resumes from a saved session in .tokens/garmin when possible (no password
    round-trip); otherwise logs in fresh with email/password and persists the
    session tokens for next time.

    In garminconnect 0.3.x the garth session is stored at client.client (not
    client.garth), and login() accepts tokenstore as a keyword argument.
    """
    token_dir = _token_dir()
    tokenstore = str(token_dir)

    # Try to resume an existing session first
    if token_dir.exists():
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
    token_dir.mkdir(parents=True, exist_ok=True)
    client.client.dump(tokenstore)
    return client


def is_authenticated() -> bool:
    """True if saved Garmin session tokens exist on disk."""
    token_dir = _token_dir()
    return token_dir.exists() and any(token_dir.iterdir())
