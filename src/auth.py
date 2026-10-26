"""
Google OAuth 2.0 authentication for SaveVault.

SaveVault uses the 'drive.file' scope so it can ONLY access files it
created — it never has access to the rest of the user's Drive.

Credentials are embedded directly so the app works as a standalone .exe.
If a client_secrets.json file is placed next to the exe (or next to
main.py when running from source) it takes priority — useful when
rotating credentials without a rebuild.

NOTE FOR DEVELOPERS
-------------------
Replace _EMBEDDED_CLIENT_ID and _EMBEDDED_CLIENT_SECRET with your own
values from Google Cloud Console before distributing.  The secret is safe
to embed in a desktop app — see Google's own documentation:
https://developers.google.com/identity/protocols/oauth2/native-app
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_FILE = Path.home() / ".savevault" / "token.json"

# ---------------------------------------------------------------------- #
# Embedded OAuth credentials — baked into the .exe at build time.        #
# Replace these after resetting your secret in Google Cloud Console.     #
# ---------------------------------------------------------------------- #
_EMBEDDED_CLIENT_ID     = "CLIENT_ID_HERE"
_EMBEDDED_CLIENT_SECRET = "CLIENT_SECRET_HERE"
# ---------------------------------------------------------------------- #

_EMBEDDED_CONFIG: dict = {
    "installed": {
        "client_id":                  _EMBEDDED_CLIENT_ID,
        "client_secret":              _EMBEDDED_CLIENT_SECRET,
        "auth_uri":                   "https://accounts.google.com/o/oauth2/auth",
        "token_uri":                  "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris":              ["http://localhost"],
    }
}


def _find_secrets_file() -> Optional[Path]:
    """
    Look for an override client_secrets.json next to the exe / main.py.
    Returns None if not found (the embedded config is used instead).
    """
    candidates = [
        Path(sys.executable).parent / "client_secrets.json",
        Path(__file__).parent.parent / "client_secrets.json",
        Path.cwd() / "client_secrets.json",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _load_client_config() -> dict:
    """
    Return the OAuth client config dict.

    Priority:
      1. client_secrets.json on disk (override / dev use)
      2. Embedded constants compiled into the exe

    Raises:
        RuntimeError: If the embedded credentials are still placeholders
                      and no secrets file is present.
    """
    override = _find_secrets_file()
    if override is not None:
        with override.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    if _EMBEDDED_CLIENT_ID.startswith("REPLACE_WITH"):
        raise RuntimeError(
            "OAuth credentials not configured.\n\n"
            "Open src/auth.py and set _EMBEDDED_CLIENT_ID and\n"
            "_EMBEDDED_CLIENT_SECRET to your values from Google Cloud Console,\n"
            "or place a client_secrets.json file next to main.py.\n\n"
            "See README.md for step-by-step instructions."
        )

    return _EMBEDDED_CONFIG


class AuthManager:
    """
    Manages the OAuth 2.0 lifecycle: initial sign-in, token refresh,
    and sign-out.
    """

    def __init__(self) -> None:
        self._credentials: Optional[Credentials] = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def is_authenticated(self) -> bool:
        """True when a valid (or refreshable) credential is loaded."""
        return self._credentials is not None and (
            self._credentials.valid
            or (self._credentials.expired and self._credentials.refresh_token)
        )

    @property
    def account_email(self) -> Optional[str]:
        """Return the authenticated account e-mail, or None."""
        if self._credentials is None:
            return None
        try:
            # The id_token is a JWT; decode the payload without verifying
            # (we trust our own token that was just fetched from Google).
            import base64 as _b64

            raw = self._credentials.id_token
            if not raw:
                return None
            payload_b64 = raw.split(".")[1]
            # Add padding
            padding = 4 - len(payload_b64) % 4
            payload_b64 += "=" * padding
            payload = json.loads(_b64.urlsafe_b64decode(payload_b64))
            return payload.get("email")
        except Exception:
            return None

    def load_or_refresh(self) -> bool:
        """
        Try to load an existing token from disk and refresh it if expired.

        Returns:
            True if a valid credential is now available, False otherwise.
        """
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)

        if TOKEN_FILE.exists():
            try:
                self._credentials = Credentials.from_authorized_user_file(
                    str(TOKEN_FILE), SCOPES
                )
            except (ValueError, KeyError):
                self._credentials = None
                return False

            if self._credentials and self._credentials.expired and self._credentials.refresh_token:
                try:
                    self._credentials.refresh(Request())
                    self._save_token()
                except RefreshError:
                    self._credentials = None
                    TOKEN_FILE.unlink(missing_ok=True)
                    return False

            return self._credentials is not None and self._credentials.valid

        return False

    def sign_in(self) -> bool:
        """
        Launch the browser-based OAuth consent flow.

        Loads client_secrets.json from disk, opens a local HTTP server on
        a random port to receive the redirect, and blocks until the user
        completes authentication.

        Returns:
            True on success, False if the user cancelled or an error occurred.

        Raises:
            RuntimeError: If client_secrets.json cannot be found.
        """
        client_config = _load_client_config()  # raises RuntimeError if missing

        try:
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            self._credentials = flow.run_local_server(port=0, open_browser=True)
            self._save_token()
            return True
        except Exception:
            self._credentials = None
            return False

    def sign_out(self) -> None:
        """Clear credentials and delete the stored token from disk."""
        self._credentials = None
        TOKEN_FILE.unlink(missing_ok=True)

    def get_credentials(self) -> Optional[Credentials]:
        """Return the current credentials object (may be None)."""
        return self._credentials

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _save_token(self) -> None:
        """Persist the current credentials to disk."""
        if self._credentials is None:
            return
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        token_data = {
            "token": self._credentials.token,
            "refresh_token": self._credentials.refresh_token,
            "token_uri": self._credentials.token_uri,
            "client_id": self._credentials.client_id,
            "client_secret": self._credentials.client_secret,
            "scopes": list(self._credentials.scopes or SCOPES),
            "id_token": getattr(self._credentials, "id_token", None),
        }
        with TOKEN_FILE.open("w", encoding="utf-8") as fh:
            json.dump(token_data, fh, indent=2)
