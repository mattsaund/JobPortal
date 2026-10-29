"""Sign in with ChatGPT: how JobPortal gets permission to run AI requests on the user's own ChatGPT plan (Go, Plus or Pro).

The flow is OAuth 2.0 with OpenID Connect. It runs between the user's browser, OpenAI's sign-in server (auth.openai.com)
and JobPortal's own server on 127.0.0.1:
1. start() builds the address of OpenAI's sign-in page, and the dashboard opens it in the user's browser
   (web/routes/chatgpt.py, POST /api/ai/signin).
2. The user signs in and approves JobPortal. On the first sign-in, OpenAI also registers this installation as a client
   of its own (dynamic client registration) and sends back the new client id.
3. OpenAI redirects the browser to http://127.0.0.1:<port>/auth/callback. The route there calls finish(), which checks
   the reply and trades its one-time code for tokens.
4. access_token() gives ai/client.py a valid access token for every request, and refreshes it shortly before it expires.
5. sign_out() asks OpenAI to revoke the refresh token, then deletes the local tokens.

The security checks, each explained where it happens:
- PKCE (S256): only the program that started a sign-in can trade its code for tokens.
- state: OpenAI's redirect must answer a sign-in this program started, so a forged callback is refused.
- nonce: the ID token must belong to this exact sign-in, so an old token can't be replayed.
- ID token claims: issuer, audience, nonce and expiry are all checked.
- Rotating refresh tokens: each refresh returns a new refresh token and retires the old one, so refreshes run one at a time.
- Storage: the tokens live only in chatgpt_auth.json in the data folder, readable by the owner alone on macOS and Linux.
  They never reach the dashboard. status() says who is signed in, never what the tokens are.

Who calls it: web/routes/chatgpt.py (start, finish, status, sign_out), ai/client.py (access_token, forget_tokens),
web/server.py (publish at startup) and app/doctor.py (status)."""
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

from jobportal.core import bus
from jobportal.core.config import DATA

ISSUER = "https://auth.openai.com"  # OpenAI's sign-in server. ID tokens must name it as their issuer.
AUTHORIZE_URL = f"{ISSUER}/api/accounts/authorize"  # the page the user signs in on
TOKEN_URL = f"{ISSUER}/api/accounts/oauth/token"  # trades a sign-in code or a refresh token for new tokens
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"  # lists the server's endpoints, including token revocation
RESOURCE = "https://api.openai.com/v1"  # the API the tokens are for (an OAuth resource indicator, RFC 8707)
# openid, profile and email give an ID token with the user's name and email. offline_access gives a refresh token. The
# last two let the tokens call the API on the user's plan.
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"  # the permission to use the user's plan. A sign-in without it is refused.
DYNAMIC_CLIENT = "dynamic_agent_client"  # the client id of a first sign-in, which asks OpenAI to register this installation
AGENT_NAME = "JobPortal"  # the name OpenAI registers this installation under
CALLBACK_PATH = "/auth/callback"  # where OpenAI sends the browser back to, on JobPortal's own server
STORE = DATA / "chatgpt_auth.json"  # the saved sign-in: tokens, client id, install id and account label
REFRESH_MARGIN = 300  # refresh the access token when less than 5 minutes remain
SIGN_IN_TIMEOUT = 900  # a started sign-in must be finished within 15 minutes
CLOCK_SKEW = 60  # seconds of difference allowed between this computer's clock and OpenAI's when checking expiry

# Sign-ins started but not finished yet, keyed by their state value: {verifier, nonce, redirect_uri, created}. They live in
# memory only, so a sign-in can't outlive the server process that started it.
_pending: dict[str, dict] = {}
_refresh_lock = asyncio.Lock()  # makes token refreshes take turns, see access_token()


class AuthError(Exception):
    """A sign-in step failed. The message is written for the user. `code` holds OpenAI's OAuth error code (for example
    "invalid_grant") when the token endpoint sent one, else ""."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


class NotSignedIn(AuthError):
    """Nobody is signed in, or the sign-in ended. The user has to sign in again."""


def _load() -> dict:
    """The saved sign-in data, or {} when there is none (or the file can't be read)."""
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    """Write the sign-in data to disk. It goes to a temporary file that then replaces the real one, so a crash halfway
    through can't leave a broken file. The temporary file is made owner-only first (on macOS and Linux, since Windows
    ignores it), so the real file never exists with looser permissions."""
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, STORE)


def _b64url(raw: bytes) -> str:
    """Base64url without "=" padding, the encoding PKCE uses."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def host_id() -> str:
    """A random id for this installation, made once and saved. It is sent with every sign-in, so OpenAI sees the same
    installation each time. Side effect: the first call writes it to chatgpt_auth.json."""
    data = _load()
    if not data.get("host_id"):
        data["host_id"] = f"urn:uuid:{uuid.uuid4()}"  # a URN UUID is one of the formats OpenAI accepts
        _save(data)
    return data["host_id"]


def redirect_uri(port: int) -> str:
    """The address OpenAI sends the browser back to. OpenAI requires 127.0.0.1, not localhost, and only the port may change."""
    return f"http://127.0.0.1:{port}{CALLBACK_PATH}"


def _forget_stale_sign_ins() -> None:
    """Drop started sign-ins older than SIGN_IN_TIMEOUT, so abandoned ones don't pile up in memory."""
    now = time.time()
    for state in [s for s, attempt in _pending.items() if now - attempt["created"] > SIGN_IN_TIMEOUT]:
        del _pending[state]


def start(port: int) -> str:
    """Begin a sign-in. Returns the address of OpenAI's sign-in page, which the dashboard opens in the user's browser.

    `port` is the port JobPortal's server listens on, for the redirect back. Side effect: the sign-in's secrets are kept
    in memory (_pending) until finish() uses them or they expire."""
    saved = _load()
    client_id = saved.get("client_id")
    callback = redirect_uri(port)
    # PKCE: a random secret (the verifier) stays here, and only its SHA-256 hash (the challenge) goes to OpenAI. Trading
    # the code for tokens requires the verifier, so a code intercepted on its way back is useless to anyone else.
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    # state ties OpenAI's redirect to this sign-in, and nonce ties the ID token to it. Both are unguessable.
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    _forget_stale_sign_ins()
    _pending[state] = {"verifier": verifier, "nonce": nonce, "redirect_uri": callback, "created": time.time()}
    params = {"client_id": client_id or DYNAMIC_CLIENT, "ext_agent_host_id": host_id(), "response_type": "code",
              "redirect_uri": callback, "scope": SCOPES, "resource": RESOURCE, "state": state, "nonce": nonce,
              "code_challenge": challenge, "code_challenge_method": "S256"}
    if not client_id:
        params["agent_name_hint"] = AGENT_NAME  # first sign-in: the name to register this installation under
    elif (saved.get("account") or {}).get("email"):
        params["login_hint"] = saved["account"]["email"]  # signing in again: suggest the account used last time
    # quote() writes the spaces in SCOPES as %20, where urlencode's default would write "+".
    return AUTHORIZE_URL + "?" + urlencode(params, quote_via=quote)


def _claims(jwt: str) -> dict:
    """The claims of a JWT: its middle part, which is base64url-encoded JSON. Returns {} when that part can't be read.
    The signature isn't checked here (see _check_id_token for why that is safe)."""
    try:
        payload = jwt.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}
    return claims if isinstance(claims, dict) else {}


def _check_id_token(id_token: str, client_id: str, nonce: str) -> dict:
    """Check the ID token, which says who signed in, and return its claims. Raises AuthError if any check fails.

    The token came straight from the token endpoint over HTTPS, so OpenID Connect allows trusting it without verifying
    its signature (OIDC Core 3.1.3.7, step 6). Its claims are still checked:
    - iss: it was issued by OpenAI's sign-in server.
    - aud: it was issued to this installation's client id.
    - nonce: it belongs to this sign-in, not an earlier one.
    - exp: it hasn't expired (allowing CLOCK_SKEW seconds of clock difference)."""
    claims = _claims(id_token)
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    try:
        expires = float(claims.get("exp") or 0)
    except (TypeError, ValueError):
        expires = 0.0  # an unreadable expiry fails the check below
    if (claims.get("iss") != ISSUER or client_id not in audiences or claims.get("nonce") != nonce
            or expires < time.time() - CLOCK_SKEW):
        raise AuthError("The sign-in response didn't check out. Please try again.")
    return claims


def _oauth_error(body: dict) -> tuple[str, str]:
    """The error code and description in an error reply from the token endpoint. Standard OAuth sends
    {"error": "<code>", "error_description": "..."}, but the error may also arrive as an object with a code and a message."""
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("code") or ""), str(err.get("message") or "")
    return str(err or ""), str(body.get("error_description") or "")


async def _token_request(form: dict) -> dict:
    """POST a form to OpenAI's token endpoint and return the JSON reply, which holds the new tokens. Network call.

    Raises AuthError when OpenAI refuses (with OpenAI's error code in AuthError.code), or when the reply has no access
    token."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(TOKEN_URL, data=form, headers={"Accept": "application/json"})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if r.status_code != 200:
        code, detail = _oauth_error(body)
        raise AuthError(": ".join(part for part in (code or f"HTTP {r.status_code}", detail) if part), code=code)
    if not body.get("access_token"):
        raise AuthError("OpenAI's sign-in server sent a reply without an access token.")
    return body


def _store_tokens(saved: dict, tokens: dict) -> None:
    """Copy a token reply into the sign-in data. The caller saves it to disk."""
    saved["access_token"] = tokens["access_token"]
    if tokens.get("refresh_token"):
        saved["refresh_token"] = tokens["refresh_token"]  # rotation: the new refresh token replaces the one just used
    saved["expires_at"] = time.time() + float(tokens.get("expires_in") or 3600)
    saved["scope"] = tokens.get("scope") or saved.get("scope", "")


async def finish(params: dict) -> dict:
    """Complete a sign-in when OpenAI redirects the browser back to CALLBACK_PATH. `params` is the redirect's query string.

    Checks the reply, trades the code for tokens, checks the ID token and the granted permissions, then saves it all.
    Returns status(). Raises AuthError, with a message for the user, when any step fails. Side effects: a network call to
    the token endpoint, a write to chatgpt_auth.json, and the new status published to the dashboard."""
    if params.get("error"):  # the user declined, or OpenAI refused the request
        raise AuthError(params.get("error_description") or params["error"])
    # The state must match a sign-in that start() made in this process, and pop() makes each one single-use.
    attempt = _pending.pop(params.get("state") or "", None)
    if not attempt or time.time() - attempt["created"] > SIGN_IN_TIMEOUT:
        raise AuthError("This sign-in link expired or was already used. Start again from JobPortal.")
    saved = _load()
    # On a first sign-in, OpenAI registers this installation and sends the new client id along with the code.
    client_id = params.get("client_id") or saved.get("client_id")
    if not params.get("code") or not client_id:
        raise AuthError("OpenAI didn't send back a sign-in code.")
    # The verifier proves this is the program that started the sign-in (PKCE). The redirect_uri must match the one in
    # start(), and resource names the API the tokens are for.
    tokens = await _token_request({"grant_type": "authorization_code", "client_id": client_id, "code": params["code"],
                                   "code_verifier": attempt["verifier"], "redirect_uri": attempt["redirect_uri"], "resource": RESOURCE})
    claims = _check_id_token(tokens.get("id_token", ""), client_id, attempt["nonce"])
    # The user can approve the sign-in but not the use of their plan. Every AI request would fail then, so stop here.
    if PLAN_SCOPE not in (tokens.get("scope") or "").split():
        raise AuthError("ChatGPT didn't allow JobPortal to use your plan. Try again and approve the request.")
    saved.update(client_id=client_id, account={"sub": claims.get("sub", ""), "email": claims.get("email", ""), "name": claims.get("name", "")})
    _store_tokens(saved, tokens)
    _save(saved)
    publish()
    return status()


def _signed_in() -> dict:
    """The saved sign-in data. Raises NotSignedIn when there is no refresh token (nobody is signed in)."""
    saved = _load()
    if not saved.get("refresh_token"):
        raise NotSignedIn("Sign in with ChatGPT first (Settings or the sidebar).")
    return saved


def _fresh(saved: dict) -> bool:
    """True if the saved access token is still good for more than REFRESH_MARGIN seconds."""
    return bool(saved.get("access_token")) and saved.get("expires_at", 0) - time.time() > REFRESH_MARGIN


async def access_token() -> str:
    """A valid access token for ai/client.py, refreshed first when it is about to expire.

    Raises NotSignedIn when nobody is signed in or OpenAI no longer accepts the refresh token, and AuthError for any other
    refresh failure. Side effects: a refresh calls the token endpoint and rewrites chatgpt_auth.json."""
    saved = _signed_in()
    if _fresh(saved):
        return saved["access_token"]
    # Refresh tokens rotate: each one works once, and the reply carries its replacement. Two refreshes at the same time
    # would send the same refresh token twice. The second would fail, and the server may even treat the reuse as theft
    # and end the sign-in. So refreshes take turns, and whoever waited reads the file again, since the task before it
    # may already have refreshed.
    async with _refresh_lock:
        saved = _signed_in()
        if _fresh(saved):
            return saved["access_token"]
        try:
            tokens = await _token_request({"grant_type": "refresh_token", "client_id": saved.get("client_id", ""),
                                           "refresh_token": saved["refresh_token"], "resource": RESOURCE})
        except AuthError as e:
            if e.code == "invalid_grant":  # the refresh token expired or was revoked, so the sign-in is over
                forget_tokens()
                raise NotSignedIn("Your ChatGPT sign-in ended. Sign in again.") from None
            raise
        _store_tokens(saved, tokens)
        _save(saved)
        return saved["access_token"]


def forget_tokens() -> None:
    """Delete the saved tokens, which signs the user out on this computer. The install id, the issued client id and the
    account label stay for the next sign-in. Side effects: rewrites chatgpt_auth.json and publishes the new status."""
    saved = _load()
    for key in ("access_token", "refresh_token", "expires_at", "scope"):
        saved.pop(key, None)
    _save(saved)
    publish()


async def sign_out() -> dict:
    """Sign out: ask OpenAI to revoke the refresh token, then delete the local tokens.

    Returns status() plus "note", which tells the user when OpenAI couldn't confirm the revocation ("" otherwise). The
    local tokens are deleted either way. Side effects: network calls to OpenAI, a rewrite of chatgpt_auth.json, and the
    new status published to the dashboard."""
    saved = _load()
    note = ""
    try:
        if saved.get("refresh_token"):
            note = await _revoke(saved["refresh_token"], saved.get("client_id", ""))
    finally:
        forget_tokens()  # always, so a failed revocation can't leave the user signed in on this computer
    return {**status(), "note": note}


async def _revoke(refresh_token: str, client_id: str) -> str:
    """Revoke a refresh token at OpenAI (OAuth token revocation, RFC 7009). Returns "" on success, or a note for the user
    when the revocation couldn't be confirmed. Network calls."""
    unconfirmed = "OpenAI didn't confirm the sign-out. You can also disconnect JobPortal in ChatGPT settings."
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # The revocation endpoint's address comes from the server's published OpenID configuration.
            config = (await client.get(DISCOVERY_URL)).json()
            endpoint = config.get("revocation_endpoint") if isinstance(config, dict) else None
            if not endpoint:
                return unconfirmed
            r = await client.post(endpoint, data={"token": refresh_token, "token_type_hint": "refresh_token", "client_id": client_id})
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return "Couldn't reach OpenAI to confirm the sign-out. You can also disconnect JobPortal in ChatGPT settings."
    return "" if r.status_code == 200 else unconfirmed


def status() -> dict:
    """Who is signed in, safe to send to the dashboard: {"signed_in", "email", "name"}. Never includes a token."""
    saved = _load()
    account = saved.get("account") or {}
    return {"signed_in": bool(saved.get("refresh_token")), "email": account.get("email", ""), "name": account.get("name", "")}


def publish() -> None:
    """Send the current sign-in status to every open dashboard (live event "ai") and keep it in bus.state."""
    bus.state["ai"] = status()
    bus.publish("ai", bus.state["ai"])
