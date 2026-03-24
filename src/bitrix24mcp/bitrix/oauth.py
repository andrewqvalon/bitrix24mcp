"""Bitrix24 OAuth 2.0 authorization flow.

Typical usage
-------------
1. Register a Bitrix24 application at https://www.bitrix24.ru/apps/add.php
   and obtain ``client_id`` (APP.ID) and ``client_secret``.

2. Call :meth:`Bitrix24OAuthManager.get_authorization_url` to build the URL
   that the user must visit.

3. The user logs in and Bitrix24 redirects to ``redirect_uri`` with a
   ``code`` query parameter.

4. Call :meth:`Bitrix24OAuthManager.exchange_code` with that code to get
   ``access_token`` and ``refresh_token``.

5. Tokens are saved to the local DB; the client auto-refreshes them when
   they expire.

Bitrix24 OAuth endpoints
------------------------
* Authorization : ``https://oauth.bitrix.info/oauth/authorize/``
* Token         : ``https://oauth.bitrix.info/oauth/token/``
* REST calls    : ``https://<domain>/rest/<method>?auth=<access_token>``
"""
from __future__ import annotations

import logging
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

logger = logging.getLogger(__name__)

_OAUTH_TOKEN_URL = "https://oauth.bitrix.info/oauth/token/"
_OAUTH_AUTHORIZE_URL = "https://oauth.bitrix.info/oauth/authorize/"

# Token lifetime that Bitrix24 issues (seconds).  We subtract a safety margin.
_TOKEN_LIFETIME_S = 3600
_REFRESH_MARGIN_S = 120  # refresh when less than 2 minutes remain


class OAuthError(Exception):
    """Raised when an OAuth operation fails."""


class Bitrix24OAuthManager:
    """Manages the Bitrix24 OAuth 2.0 authorization code flow.

    Parameters
    ----------
    client_id:
        Your Bitrix24 application ID (APP.ID).
    client_secret:
        Your Bitrix24 application secret.
    redirect_uri:
        URI that Bitrix24 will redirect to after login.
        For the interactive local-server flow this should be
        ``http://localhost:<PORT>/oauth/callback``.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str = "http://localhost:8765/oauth/callback",
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._http = httpx.Client(timeout=30)

    # ------------------------------------------------------------------
    # Build authorization URL
    # ------------------------------------------------------------------

    def get_authorization_url(self, domain: Optional[str] = None) -> str:
        """Return the URL the user must open to log in.

        Parameters
        ----------
        domain:
            Bitrix24 portal domain (e.g. ``mycompany.bitrix24.ru``).
            When provided, the user is taken directly to their portal's
            login page.  When omitted, Bitrix24 will ask for the domain.
        """
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
        }
        base = (
            f"https://{domain}/oauth/authorize/"
            if domain
            else _OAUTH_AUTHORIZE_URL
        )
        return f"{base}?{urlencode(params)}"

    # ------------------------------------------------------------------
    # Exchange authorization code for tokens
    # ------------------------------------------------------------------

    def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchange an authorization *code* for access / refresh tokens.

        Returns the full token response dict from Bitrix24.
        """
        resp = self._http.post(
            _OAUTH_TOKEN_URL,
            params={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise OAuthError(f"{data['error']}: {data.get('error_description', '')}")
        return data

    # ------------------------------------------------------------------
    # Refresh access token
    # ------------------------------------------------------------------

    def refresh_token(self, refresh_tok: str) -> Dict[str, Any]:
        """Use *refresh_tok* to obtain a new access token.

        Returns the full token response dict from Bitrix24.
        """
        resp = self._http.post(
            _OAUTH_TOKEN_URL,
            params={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_tok,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise OAuthError(f"{data['error']}: {data.get('error_description', '')}")
        return data

    # ------------------------------------------------------------------
    # Interactive browser-based flow
    # ------------------------------------------------------------------

    def authorize_interactive(
        self,
        domain: Optional[str] = None,
        port: int = 8765,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """Run the full interactive OAuth flow.

        1. Starts a temporary local HTTP server on ``localhost:<port>``.
        2. Opens the Bitrix24 login page in the default browser.
        3. Waits (up to *timeout* seconds) for the redirect callback.
        4. Exchanges the authorization code for tokens.
        5. Returns the token response dict.

        Parameters
        ----------
        domain:
            Optional Bitrix24 portal domain to pre-fill.
        port:
            Local port for the callback HTTP server.
        timeout:
            Seconds to wait for the user to complete login.
        """
        auth_url = self.get_authorization_url(domain)
        result: Dict[str, Any] = {}
        error_holder: Dict[str, str] = {}
        event = threading.Event()

        manager = self

        class _CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query)
                if "code" in qs:
                    code = qs["code"][0]
                    try:
                        token_data = manager.exchange_code(code)
                        result.update(token_data)
                        self._respond(200, "Authorization successful! You can close this tab.")
                    except Exception as exc:
                        error_holder["msg"] = str(exc)
                        self._respond(400, f"Authorization failed: {exc}")
                elif "error" in qs:
                    error_holder["msg"] = qs.get("error_description", ["Unknown error"])[0]
                    self._respond(400, f"Authorization denied: {error_holder['msg']}")
                else:
                    self._respond(400, "Unexpected callback parameters.")
                event.set()

            def _respond(self, status: int, body: str) -> None:
                html = (
                    f"<html><body style='font-family:sans-serif;padding:40px'>"
                    f"<h2>{'✅' if status == 200 else '❌'} Bitrix24 MCP</h2>"
                    f"<p>{body}</p>"
                    f"</body></html>"
                )
                encoded = html.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, fmt: str, *args: Any) -> None:  # suppress access log
                pass

        httpd = HTTPServer(("localhost", port), _CallbackHandler)
        server_thread = threading.Thread(target=httpd.handle_request, daemon=True)
        server_thread.start()

        logger.info("Opening browser for Bitrix24 authorization: %s", auth_url)
        webbrowser.open(auth_url)

        completed = event.wait(timeout=timeout)
        httpd.server_close()

        if not completed:
            raise OAuthError(
                f"Authorization timed out after {timeout} seconds. "
                "Please retry the authorization process."
            )
        if error_holder:
            raise OAuthError(error_holder["msg"])
        if not result:
            raise OAuthError("No token received from Bitrix24.")

        return result

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Bitrix24OAuthManager":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


# ------------------------------------------------------------------
# Token persistence helpers (use DB session)
# ------------------------------------------------------------------

def save_token(session: Any, client_id: str, token_data: Dict[str, Any]) -> None:
    """Persist OAuth token data to the ``oauth_tokens`` table."""
    from bitrix24mcp.db.models import OAuthToken

    expires_in = int(token_data.get("expires_in", _TOKEN_LIFETIME_S))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - _REFRESH_MARGIN_S)

    obj = session.get(OAuthToken, client_id)
    if obj is None:
        obj = OAuthToken(client_id=client_id)
        session.add(obj)

    obj.domain = token_data.get("domain", "")
    obj.member_id = token_data.get("member_id", "")
    obj.access_token = token_data["access_token"]
    obj.refresh_token = token_data["refresh_token"]
    obj.expires_at = expires_at
    obj.scope = token_data.get("scope", "")


def load_token(session: Any, client_id: str) -> Optional[Any]:
    """Load the saved OAuth token for *client_id* from the DB."""
    from bitrix24mcp.db.models import OAuthToken

    return session.get(OAuthToken, client_id)


def get_valid_access_token(
    session: Any,
    client_id: str,
    client_secret: str,
) -> Optional[str]:
    """Return a valid access token, refreshing if it has expired.

    Returns ``None`` when no token is stored.
    Raises :class:`OAuthError` when refresh fails.
    """
    token = load_token(session, client_id)
    if token is None:
        return None

    now = datetime.now(timezone.utc)
    expires_at = token.expires_at
    # Make expires_at timezone-aware if stored as naive
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now < expires_at:
        return token.access_token

    # Token expired – refresh
    logger.info("Access token expired, refreshing …")
    manager = Bitrix24OAuthManager(client_id=client_id, client_secret=client_secret)
    try:
        new_data = manager.refresh_token(token.refresh_token)
    finally:
        manager.close()

    save_token(session, client_id, new_data)
    session.flush()
    return new_data["access_token"]
