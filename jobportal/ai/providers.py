"""Which AI JobPortal runs on, and the user's sign-in or key for it.

The user picks a provider in the Connect popup (web/static/js/components/connect.js). There is no default: JobPortal works
with any of them, and nothing runs until one is connected. Each connects one of three ways:
- a sign-in in the browser (ChatGPT through ai/signin.py, OpenRouter and Pollinations through OAuth PKCE here);
- an API key, with the page where the user gets one;
- an address, for a service with its own URL or a model server on this computer (the "fields" of its entry).

Key ideas:
- PROVIDERS is data (ai/provider_list.py). A provider that speaks one of the three request formats ("wires": OpenAI's Responses API, the chat
  completions API most services share, or Anthropic's Messages API) needs only an entry here. ai/client.py sends every
  request the provider's way.
- Keys live only in ai_keys.json in the data folder, created readable by the owner alone (on macOS and Linux; Windows
  keeps the data folder private to the user). They never reach the dashboard: status() names the providers that have a
  key and shows its last four characters.
- The chosen provider is the "ai.provider" setting, and "ai.endpoints" holds each provider's address parts. Switching
  providers clears the model choices, since model names differ between providers (set_provider).
- OpenRouter and Pollinations sign in with OAuth PKCE and no app registration: the provider sends the browser back to this
  computer with a one-time code, and the code becomes a key on the user's own account (key_signin_start, key_signin_finish).
  That key can't be deleted from here, so forgetting it points the user to their key page.

Who calls it: ai/client.py (credential, current, info), web/routes/ai.py (status, listing, keys, endpoints, the sign-ins),
ai/signin.py (publish, after a ChatGPT sign-in change) and app/doctor.py (status)."""
import base64
import hashlib
import json
import os
import re
import secrets
import time
from urllib.parse import urlencode

import httpx

from jobportal.ai import signin
from jobportal.ai.provider_list import PROVIDERS
from jobportal.core import bus, settings as settings_mod
from jobportal.core.config import DATA

KEYS = DATA / "ai_keys.json"  # the saved API keys: {provider id: {"key", "added_at", "via"}}
# Providers whose browser sign-in hands back a key: where the user approves JobPortal, where the one-time code is traded for
# the key, and where the browser comes back to on JobPortal's own server. Both promise any port on "localhost".
KEY_SIGNINS = {
    "openrouter": {"authorize": "https://openrouter.ai/auth", "token": "https://openrouter.ai/api/v1/auth/keys", "callback": "/auth/openrouter"},
    "pollinations": {"authorize": "https://enter.pollinations.ai/authorize", "token": "https://enter.pollinations.ai/api/oauth/token",
                     "callback": "/auth/pollinations"},
}
SIGN_IN_TIMEOUT = 900  # a started sign-in must be finished within 15 minutes
POLLINATIONS_KEY_DAYS = 30  # how long a key from Sign in with Pollinations lasts (it has no refresh, and the default is 7)

NO_PROVIDER = {"name": "AI", "wire": "chat", "base": "", "auth": "none"}  # stands in until one is connected
NOT_CONNECTED = "Connect an AI first."
LOCAL_KEY = "local"  # sent to a server that needs no key

# Key sign-ins started but not finished, keyed by their state value: {provider, verifier, callback, created}. In memory only,
# so a sign-in can't outlive the server process that started it.
_pending: dict[str, dict] = {}

class NoCredential(Exception):
    """The chosen provider has no sign-in or key yet. ai/client.py turns this into its NotSignedIn."""


# ---------------------------------------------------------------- the chosen provider

def current(cfg: dict | None = None) -> str:
    """The id of the provider in use, or "" when none is connected yet. Someone signed in with ChatGPT before providers
    could be picked has no stored choice and keeps ChatGPT."""
    chosen = str(((cfg or settings_mod.get()).get("ai") or {}).get("provider") or "")
    if chosen in PROVIDERS:
        return chosen
    return "chatgpt" if signin.status().get("signed_in") else ""


def _endpoint(pid: str, cfg: dict) -> dict:
    """The address parts saved for a provider, with each field's default where nothing is saved."""
    ai = cfg.get("ai") or {}
    saved = dict((ai.get("endpoints") or {}).get(pid) or {})
    if pid == "custom" and not saved.get("url") and ai.get("custom_url"):  # saved by v0.4.0
        saved["url"] = ai["custom_url"]
    return {f["id"]: str(saved.get(f["id"]) or f.get("default") or "").strip() for f in PROVIDERS[pid].get("fields", [])}


def _base(entry: dict, cfg: dict) -> str:
    """The provider's API address. One with fields gets it from them, and it's "" until the required ones are filled in."""
    fields = entry.get("fields")
    if not fields:
        return entry["base"]
    values = _endpoint(entry["id"], cfg)
    if any(f.get("required", True) and not values[f["id"]] for f in fields):
        return ""
    return values["url"].rstrip("/") if "url" in values else entry["base"].format(**values)


def info(provider: str | None = None, cfg: dict | None = None) -> dict:
    """The provider's entry from PROVIDERS plus its id and its address. With no provider connected, a stand-in entry whose
    requests stop at "Connect an AI"."""
    cfg = cfg or settings_mod.get()
    pid = current(cfg) if provider is None else provider
    if not pid:
        return {**NO_PROVIDER, "id": ""}
    entry = {**PROVIDERS[pid], "id": pid}
    entry["base"] = _base(entry, cfg)
    if entry.get("headers"):  # a header can carry an address part, such as a project id
        values = _endpoint(pid, cfg)
        entry["headers"] = {name: value.format(**values) for name, value in entry["headers"].items()}
    return entry


def set_provider(provider: str) -> dict:
    """Switch to another provider and return the settings. The model choices go back to the provider's default, since a
    model name from one provider means nothing to another. "" means none."""
    if provider and provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    cfg = settings_mod.get()
    ai = cfg["ai"]
    if current(cfg) != provider:
        ai["model"] = ""
        for stage in ai["stages"].values():
            stage["model"] = ""
    ai["provider"] = provider
    return settings_mod.save(cfg)


def set_endpoint(provider: str, values: dict) -> None:
    """Save a provider's address parts. A "url" must be http(s), and the others (a resource name, a region, an account id)
    go into its address, so they may hold only letters, digits, dots, dashes and underscores. Raises ValueError."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    clean = {}
    for field in PROVIDERS[provider].get("fields", []):
        value = str(values.get(field["id"]) or "").strip().rstrip("/")
        if field["id"] == "url":
            if value and (not value.lower().startswith(("http://", "https://")) or re.search(r"\s", value)):
                raise ValueError("The address must start with http:// or https://")
        elif value and not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", value):
            raise ValueError(f"{field['label']} has characters it can't have.")
        clean[field["id"]] = value
    cfg = settings_mod.get()
    cfg["ai"].setdefault("endpoints", {})[provider] = clean
    settings_mod.save(cfg)


def set_model(model: str) -> None:
    """Make this the default model, for a provider that has no model list to pick from."""
    cfg = settings_mod.get()
    cfg["ai"]["model"] = model.strip()
    settings_mod.save(cfg)


def saved_state(provider: str) -> dict:
    """What's saved now for a provider, for restore() to put back when a new connection fails its check."""
    cfg = settings_mod.get()
    return {"provider": provider, "current": current(cfg), "key": get_key(provider), "model": cfg["ai"].get("model", ""),
            "endpoint": ((cfg["ai"].get("endpoints") or {}).get(provider))}


def restore(state: dict) -> None:
    """Put back what saved_state() recorded."""
    pid = state["provider"]
    if state["key"]:
        save_key(pid, state["key"])
    else:
        forget_key(pid)
    cfg = settings_mod.get()
    endpoints = cfg["ai"].setdefault("endpoints", {})
    if state["endpoint"] is None:
        endpoints.pop(pid, None)
    else:
        endpoints[pid] = state["endpoint"]
    settings_mod.save(cfg)
    if current() != state["current"]:
        set_provider(state["current"])
    set_model(state["model"])


# ---------------------------------------------------------------- keys

def _load_keys() -> dict:
    """The saved keys, or {} when there are none (or the file can't be read)."""
    try:
        data = json.loads(KEYS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_keys(data: dict) -> None:
    """Write the keys the same way ai/signin.py writes the ChatGPT sign-in: to an owner-only temporary file that then
    replaces the real one, so other users can never read a key and a crash can't leave half a file."""
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = KEYS.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=1))
    try:
        os.chmod(tmp, 0o600)  # a .tmp left by a crash keeps its old mode, since os.open only sets it on new files
    except OSError:
        pass
    os.replace(tmp, KEYS)


def get_key(provider: str) -> str:
    """The saved key for a provider, or ""."""
    entry = _load_keys().get(provider) or {}
    return str(entry.get("key") or "")


def save_key(provider: str, key: str, via: str = "pasted") -> None:
    """Keep a provider's key (via: "pasted", or "sign-in" for Sign in with OpenRouter) and tell the dashboards."""
    key = key.strip()
    if provider not in PROVIDERS or PROVIDERS[provider]["auth"] != "key":
        raise ValueError(f"{provider} doesn't take a key")
    if not key or len(key) > 500 or any(ch.isspace() for ch in key):
        raise ValueError("That doesn't look like an API key.")
    keys = _load_keys()
    keys[provider] = {"key": key, "added_at": time.time(), "via": via}
    _save_keys(keys)
    publish()


def forget_key(provider: str) -> None:
    """Delete a provider's saved key and tell the dashboards. The key itself stays valid at the provider."""
    keys = _load_keys()
    if keys.pop(provider, None) is not None:
        _save_keys(keys)
    publish()


def _hint(key: str) -> str:
    """The last four characters of a key, for the dashboard to show which one is saved."""
    return f"ending in {key[-4:]}" if len(key) >= 8 else "saved"


# ---------------------------------------------------------------- credentials and status

async def credential(provider: str | None = None) -> str:
    """What authorizes a request to the provider: the ChatGPT access token (refreshed when needed) or the saved key.
    Raises NoCredential when there is none yet, and lets ai/signin.py's own errors through for ChatGPT."""
    pid = current() if provider is None else provider
    if not pid:
        raise NoCredential(NOT_CONNECTED)
    entry = PROVIDERS[pid]
    if entry["auth"] == "chatgpt":
        return await signin.access_token()
    key = get_key(pid)
    if key:
        return key
    if entry.get("needs_key") is False:
        return LOCAL_KEY  # a server with no keys ignores it, and some clients and servers still want the header
    raise NoCredential(f"Add your {entry['name']} key.")


def problem(cfg: dict | None = None) -> str:
    """Why the AI can't run right now, worded for the user, or "" when it can."""
    entry = info(cfg=cfg)
    if not entry["id"]:
        return NOT_CONNECTED
    if entry["auth"] == "chatgpt":
        return "" if signin.status().get("signed_in") else "Sign in with ChatGPT."
    if entry.get("fields") and not entry["base"]:
        return f"Add the {entry['name']} address."
    if entry.get("needs_key") is False:
        return ""
    return "" if get_key(entry["id"]) else f"Add your {entry['name']} key."


def status(cfg: dict | None = None) -> dict:
    """The AI's status, safe to send to the dashboard: the provider in use, whether it's ready, the signed-in account (name
    and email, when that's the provider), which providers have a saved key (shown by their last four characters), and
    each provider's saved address parts. "signed_in" means ready too. Never includes a key."""
    cfg = cfg or settings_mod.get()
    entry = info(cfg=cfg)
    account = signin.status() if entry["auth"] == "chatgpt" else {}
    keys = _load_keys()
    ready = not problem(cfg)
    return {"provider": entry["id"], "provider_name": entry["name"], "auth": entry["auth"], "ready": ready, "signed_in": ready,
            "name": account.get("name", ""), "email": account.get("email", ""), "chatgpt_signed_in": signin.status().get("signed_in", False),
            "keys": {pid: _hint(str(k.get("key") or "")) for pid, k in keys.items() if pid in PROVIDERS and k.get("key")},
            "endpoints": {pid: _endpoint(pid, cfg) for pid, p in PROVIDERS.items() if p.get("fields")}}


def listing() -> list[dict]:
    """Every provider for the Connect popup, by name within each group: how it connects ("signin" or "key"), its group
    (signin, key, local or custom), its address fields, where to get a key, a note when one matters, and whether it has a
    free tier or web search."""
    def group(p: dict) -> str:
        if p["auth"] == "chatgpt" or p.get("signin"):
            return "signin"
        return "custom" if p.get("custom") else "local" if p.get("local") else "key"

    rows = [{"id": pid, "name": p["name"], "group": group(p), "connect": "signin" if group(p) == "signin" else "key",
             "fields": p.get("fields", []), "needs_key": p.get("needs_key", p["auth"] == "key"), "key_url": p.get("key_url", ""),
             "key_prefix": p.get("key_prefix", ""), "note": p.get("note", ""), "free": bool(p.get("free")),
             "search": bool(p.get("search")), "aliases": p.get("aliases", "")} for pid, p in PROVIDERS.items()]
    return sorted(rows, key=lambda row: row["name"].lower())


def publish() -> None:
    """Send the AI's status to every open dashboard (live event "ai") and keep it in bus.state."""
    bus.state["ai"] = status()
    bus.publish("ai", bus.state["ai"])


async def disconnect(provider: str) -> None:
    """Stop using a provider: sign out of ChatGPT, or forget the saved key. When it's the one in use, no AI is in use."""
    if provider == "chatgpt":
        await signin.sign_out()
    else:
        forget_key(provider)
    if current() == provider:
        set_provider("")
    publish()


# ---------------------------------------------------------------- browser sign-ins that hand back a key

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def key_signin_start(provider: str, port: int) -> str:
    """Start a provider's sign-in: the address of its approval page, for the dashboard to open in the browser. PKCE (S256)
    means only this process can trade the code that comes back, and the state value ties the callback to this sign-in, so
    a forged callback is refused."""
    flow = KEY_SIGNINS[provider]
    now = time.time()
    for state in [s for s, p in _pending.items() if now - p["created"] > SIGN_IN_TIMEOUT]:
        _pending.pop(state, None)
    verifier = _b64url(secrets.token_bytes(48))
    state = _b64url(secrets.token_bytes(24))
    callback = f"http://localhost:{port}{flow['callback']}"
    _pending[state] = {"provider": provider, "verifier": verifier, "callback": callback, "created": now}
    challenge = {"code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256", "state": state}
    if provider == "openrouter":
        return f"{flow['authorize']}?" + urlencode({"callback_url": callback, **challenge, "key_label": "JobPortal"})
    return f"{flow['authorize']}?" + urlencode({"response_type": "code", "redirect_uri": callback, **challenge, "expiry": POLLINATIONS_KEY_DAYS})


async def key_signin_finish(provider: str, params: dict) -> None:
    """Finish a sign-in from the callback's query parameters: check the state, trade the code for the key, save it and
    switch to that provider. Raises ValueError with a message for the user when anything is off. Network call."""
    name = PROVIDERS[provider]["name"]
    pending = _pending.get(str(params.get("state") or ""))
    if not pending or pending["provider"] != provider or time.time() - pending["created"] > SIGN_IN_TIMEOUT:
        raise ValueError("This sign-in link is old. Start again from JobPortal.")
    _pending.pop(str(params["state"]), None)
    code = str(params.get("code") or "")
    if not code:
        raise ValueError(f"{name} didn't approve the sign-in.")
    url = KEY_SIGNINS[provider]["token"]
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if provider == "openrouter":
                r = await client.post(url, json={"code": code, "code_verifier": pending["verifier"], "code_challenge_method": "S256"})
            else:
                r = await client.post(url, data={"grant_type": "authorization_code", "code": code, "redirect_uri": pending["callback"],
                                                 "code_verifier": pending["verifier"]})
    except httpx.HTTPError as e:
        raise ValueError(f"Couldn't reach {name} ({type(e).__name__}). Try again.") from None
    try:
        reply = r.json() if r.status_code == 200 else {}
    except ValueError:
        reply = {}
    key = reply.get("key") or reply.get("access_token") if isinstance(reply, dict) else None
    if not isinstance(key, str) or not key:
        raise ValueError(f"{name} didn't hand over a key (HTTP {r.status_code}). Try again.")
    save_key(provider, key, via="sign-in")
    if current() != provider:
        set_provider(provider)
    publish()


def openrouter_key_page() -> str:
    """The OpenRouter page for the saved key, where its owner can see its use, change its limit or delete it."""
    key = get_key("openrouter")
    return f"https://openrouter.ai/keys/{hashlib.sha256(key.encode()).hexdigest()}" if key else "https://openrouter.ai/settings/keys"
