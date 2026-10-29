"""Sign in with ChatGPT. JobPortal registers as an open-source local client. The user signs in on OpenAI's page in their own
browser, and OpenAI sends them back to JobPortal's server on 127.0.0.1. AI requests then run on the user's ChatGPT plan
(Go, Plus or Pro). Tokens stay in the data folder and never reach the dashboard."""
import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
import uuid
from urllib.parse import quote, urlencode

import httpx

from . import bus
from .config import DATA

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = f"{ISSUER}/api/accounts/authorize"
TOKEN_URL = f"{ISSUER}/api/accounts/oauth/token"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
AGENT_NAME = "JobPortal"
CALLBACK_PATH = "/auth/callback"
STORE = DATA / "chatgpt_auth.json"
REFRESH_MARGIN = 300  # refresh when less than 5 minutes remain

_pending: dict[str, dict] = {}  # state -> verifier, nonce, redirect_uri, created
_refresh_lock = asyncio.Lock()


class AuthError(Exception):
    pass


class NotSignedIn(AuthError):
    pass


def _load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)  # owner-only on macOS and Linux
    except OSError:
        pass
    os.replace(tmp, STORE)


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def host_id() -> str:
    """A stable id for this installation, in one of the formats OpenAI accepts."""
    d = _load()
    if not d.get("host_id"):
        d["host_id"] = f"urn:uuid:{uuid.uuid4()}"
        _save(d)
    return d["host_id"]


def redirect_uri(port: int) -> str:
    return f"http://127.0.0.1:{port}{CALLBACK_PATH}"  # OpenAI requires 127.0.0.1, not localhost; only the port may change


def start(port: int) -> str:
    """The authorization URL to open in the user's browser."""
    d = _load()
    verifier = _b64url(secrets.token_bytes(48))
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    now = time.time()
    for k in [k for k, v in _pending.items() if now - v["created"] > 900]:
        _pending.pop(k, None)
    _pending[state] = {"verifier": verifier, "nonce": nonce, "redirect_uri": redirect_uri(port), "created": now}
    params = {"client_id": d.get("client_id") or "dynamic_agent_client", "ext_agent_host_id": host_id(), "response_type": "code",
              "redirect_uri": redirect_uri(port), "scope": SCOPES, "resource": RESOURCE, "state": state, "nonce": nonce,
              "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"}
    if not d.get("client_id"):
        params["agent_name_hint"] = AGENT_NAME  # first registration only
    elif (d.get("account") or {}).get("email"):
        params["login_hint"] = d["account"]["email"]
    return AUTHORIZE_URL + "?" + urlencode(params, quote_via=quote)


def _claims(jwt: str) -> dict:
    try:
        payload = jwt.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


def _check_id_token(id_token: str, client_id: str, nonce: str) -> dict:
    # The ID token comes straight from the token endpoint over TLS, so OpenID Connect allows checking its claims without
    # verifying the signature (OIDC Core 3.1.3.7, step 6).
    c = _claims(id_token)
    aud = c.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if c.get("iss") != ISSUER or client_id not in auds or c.get("nonce") != nonce or float(c.get("exp") or 0) < time.time() - 60:
        raise AuthError("The sign-in response didn't check out. Please try again.")
    return c


async def _token_request(form: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(TOKEN_URL, data=form, headers={"Accept": "application/json"})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200:
        err = body.get("error") or f"HTTP {r.status_code}"
        raise AuthError(f"{err}: {body.get('error_description', '')}".strip(": "))
    return body


def _store_tokens(d: dict, tok: dict) -> None:
    d["access_token"] = tok["access_token"]
    if tok.get("refresh_token"):
        d["refresh_token"] = tok["refresh_token"]
    d["expires_at"] = time.time() + float(tok.get("expires_in") or 3600)
    d["scope"] = tok.get("scope") or d.get("scope", "")


async def finish(params: dict) -> dict:
    """Handle OpenAI's redirect back to JobPortal: check it, exchange the code and save the tokens."""
    if params.get("error"):
        raise AuthError(params.get("error_description") or params["error"])
    pend = _pending.pop(params.get("state") or "", None)
    if not pend:
        raise AuthError("This sign-in link expired or was already used. Start again from JobPortal.")
    d = _load()
    client_id = params.get("client_id") or d.get("client_id")
    if not params.get("code") or not client_id:
        raise AuthError("OpenAI didn't send back a sign-in code.")
    tok = await _token_request({"grant_type": "authorization_code", "client_id": client_id, "code": params["code"],
                                "code_verifier": pend["verifier"], "redirect_uri": pend["redirect_uri"], "resource": RESOURCE})
    claims = _check_id_token(tok.get("id_token", ""), client_id, pend["nonce"])
    if PLAN_SCOPE not in (tok.get("scope") or "").split():
        raise AuthError("ChatGPT didn't allow JobPortal to use your plan. Try again and approve the request.")
    d.update(client_id=client_id, account={"sub": claims.get("sub", ""), "email": claims.get("email", ""), "name": claims.get("name", "")})
    _store_tokens(d, tok)
    _save(d)
    publish()
    return status()


async def access_token() -> str:
    """A valid access token, refreshed near expiry. Refreshes are serialized because refresh tokens rotate."""
    d = _load()
    if not d.get("refresh_token"):
        raise NotSignedIn("Sign in with ChatGPT first (Settings or the sidebar).")
    if d.get("expires_at", 0) - time.time() > REFRESH_MARGIN:
        return d["access_token"]
    async with _refresh_lock:
        d = _load()
        if d.get("expires_at", 0) - time.time() > REFRESH_MARGIN:
            return d["access_token"]
        try:
            tok = await _token_request({"grant_type": "refresh_token", "client_id": d["client_id"], "refresh_token": d["refresh_token"],
                                        "resource": RESOURCE})
        except AuthError as e:
            if "invalid_grant" in str(e):
                forget_tokens()
                raise NotSignedIn("Your ChatGPT sign-in ended. Sign in again.") from None
            raise
        _store_tokens(d, tok)
        _save(d)
        return d["access_token"]


def forget_tokens() -> None:
    """Drop the tokens but keep the host id, issued client id and account label for the next sign-in."""
    d = _load()
    for k in ("access_token", "refresh_token", "expires_at", "scope"):
        d.pop(k, None)
    _save(d)
    publish()


async def sign_out() -> dict:
    d = _load()
    note = ""
    if d.get("refresh_token"):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                endpoint = (await client.get(DISCOVERY_URL)).json().get("revocation_endpoint")
                if endpoint:
                    r = await client.post(endpoint, data={"token": d["refresh_token"], "token_type_hint": "refresh_token",
                                                          "client_id": d.get("client_id", "")})
                    if r.status_code != 200:
                        note = "OpenAI didn't confirm the sign-out. You can also disconnect JobPortal in ChatGPT settings."
        except (httpx.HTTPError, ValueError):
            note = "Couldn't reach OpenAI to confirm the sign-out. You can also disconnect JobPortal in ChatGPT settings."
    forget_tokens()
    return {**status(), "note": note}


def status() -> dict:
    d = _load()
    acct = d.get("account") or {}
    return {"signed_in": bool(d.get("refresh_token")), "email": acct.get("email", ""), "name": acct.get("name", "")}


def publish() -> None:
    bus.state["ai"] = status()
    bus.publish("ai", bus.state["ai"])
