"""Which AI JobPortal runs on, and the user's sign-in or key for it.

The user picks one provider in Settings, AI (the welcome screen leads there too):
- ChatGPT: Sign in with ChatGPT, on the user's Go, Plus or Pro plan (ai/signin.py).
- OpenRouter: Sign in with OpenRouter, or a pasted OpenRouter key. One account reaches hundreds of models, some of them free
  within a daily limit.
- An API key from OpenAI, Anthropic (Claude), Google (Gemini, with a free tier), Mistral, Groq, DeepSeek or xAI (Grok), or
  from any other service that speaks OpenAI's chat completions API.
Those are the providers that let an app like this one work for the user. Anthropic and Google don't let other apps sign
people in with a Claude or Gemini subscription, and GitHub retired GitHub Models, so those come by API key or not at all.

Key ideas:
- PROVIDERS is data. Each provider has a name, the "wire" its requests travel on (OpenAI's Responses API, the chat
  completions API most services share, or Anthropic's Messages API), its address, how the user connects ("chatgpt" sign-in
  or a "key"), where to get a key, and whether it can search the web. ai/client.py sends every request the provider's way.
- Keys live only in ai_keys.json in the data folder, created readable by the owner alone (on macOS and Linux; Windows
  keeps the data folder private to the user). They never reach the dashboard: status() names the providers that have a
  key and shows its last four characters.
- The chosen provider is the "ai.provider" setting, with "ai.custom_url" for another service. Switching providers clears
  the model choices, since model names differ between providers (set_provider).
- Sign in with OpenRouter is OAuth PKCE with no app registration: OpenRouter sends the browser back to this computer with
  a one-time code, and the code becomes a key on the user's own account (openrouter_start, openrouter_finish). OpenRouter
  can't delete that key from here, so forgetting it points the user to their key page.

Who calls it: ai/client.py (credential, current, info), web/routes/ai.py (status, providers, keys, the OpenRouter
sign-in), ai/signin.py (publish, after a ChatGPT sign-in change) and app/doctor.py (status)."""
import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx

from jobportal.ai import signin
from jobportal.core import bus, settings as settings_mod
from jobportal.core.config import DATA

KEYS = DATA / "ai_keys.json"  # the saved API keys: {provider id: {"key", "added_at", "via"}}
OPENROUTER_AUTH = "https://openrouter.ai/auth"  # where the user approves JobPortal on OpenRouter
OPENROUTER_EXCHANGE = "https://openrouter.ai/api/v1/auth/keys"  # trades the one-time code for the user's key
OPENROUTER_CALLBACK = "/auth/openrouter"  # where OpenRouter sends the browser back to, on JobPortal's own server
SIGN_IN_TIMEOUT = 900  # a started OpenRouter sign-in must be finished within 15 minutes

# Every provider. wire: how requests are sent (ai/client.py). base: the API's address. auth: "chatgpt" (Sign in with
# ChatGPT) or "key". signin: also offers a sign-in that makes the key. search: can search the web itself. key_url: where
# the user gets a key. key_prefix: how its keys start, as a hint. models: the model list's path, when it isn't /models.
# effort: how the provider takes the reasoning effort ("reasoning" object, "reasoning_effort" field, or none).
# tool_name: tool replies name their tool (Mistral wants that). free: the provider has free models or a free tier.
PROVIDERS = {
    "chatgpt": {"name": "ChatGPT", "wire": "responses", "base": "https://api.openai.com/v1", "auth": "chatgpt", "search": True,
                "note": "Runs on your ChatGPT Go, Plus or Pro plan. Nothing else to buy or set up."},
    "openrouter": {"name": "OpenRouter", "wire": "chat", "base": "https://openrouter.ai/api/v1", "auth": "key", "signin": True,
                   "free": True, "models": "/models/user", "effort": "reasoning", "key_prefix": "sk-or-",
                   "key_url": "https://openrouter.ai/settings/keys",
                   "note": "One account for hundreds of models, including free ones with a daily limit. You pay as you go for the rest."},
    "openai": {"name": "OpenAI API", "wire": "responses", "base": "https://api.openai.com/v1", "auth": "key", "search": True,
               "key_prefix": "sk-", "key_url": "https://platform.openai.com/api-keys",
               "note": "Pay as you go with an OpenAI API key, separate from a ChatGPT plan."},
    "anthropic": {"name": "Claude (Anthropic)", "wire": "anthropic", "base": "https://api.anthropic.com/v1", "auth": "key",
                  "search": True, "key_prefix": "sk-ant-", "key_url": "https://platform.claude.com/settings/keys",
                  "note": "Pay as you go with an Anthropic API key. Claude.ai plans can't be used by other apps."},
    "gemini": {"name": "Gemini (Google)", "wire": "chat", "base": "https://generativelanguage.googleapis.com/v1beta/openai",
               "auth": "key", "free": True, "effort": "reasoning_effort", "key_prefix": "AIza",
               "key_url": "https://aistudio.google.com/apikey",
               "note": "A free tier with daily limits. On the free tier, Google may use what you send and people may review it, "
                       "so add billing to your key if you want your resume kept private."},
    "mistral": {"name": "Mistral", "wire": "chat", "base": "https://api.mistral.ai/v1", "auth": "key", "tool_name": True,
                "key_url": "https://console.mistral.ai/api-keys", "note": "Pay as you go with a Mistral API key."},
    "groq": {"name": "Groq", "wire": "chat", "base": "https://api.groq.com/openai/v1", "auth": "key", "free": True,
             "key_prefix": "gsk_", "key_url": "https://console.groq.com/keys",
             "note": "Fast open models, with a free tier that has tight limits."},
    "deepseek": {"name": "DeepSeek", "wire": "chat", "base": "https://api.deepseek.com", "auth": "key", "key_prefix": "sk-",
                 "key_url": "https://platform.deepseek.com/api_keys", "note": "Pay as you go with a DeepSeek API key."},
    "xai": {"name": "Grok (xAI)", "wire": "chat", "base": "https://api.x.ai/v1", "auth": "key", "key_prefix": "xai-",
            "key_url": "https://console.x.ai", "note": "Pay as you go with an xAI API key."},
    "custom": {"name": "Another service", "wire": "chat", "base": "", "auth": "key", "custom": True,
               "note": "Any service with an OpenAI-compatible chat completions API: give its address and a key."},
}
DEFAULT = "chatgpt"

# Sign-ins with OpenRouter started but not finished, keyed by their state value: {verifier, created}. In memory only, so a
# sign-in can't outlive the server process that started it.
_pending: dict[str, dict] = {}


class NoCredential(Exception):
    """The chosen provider has no sign-in or key yet. ai/client.py turns this into its NotSignedIn."""


# ---------------------------------------------------------------- the chosen provider

def current(cfg: dict | None = None) -> str:
    """The id of the provider in use (Settings, AI). An unknown id falls back to ChatGPT."""
    chosen = str(((cfg or settings_mod.get()).get("ai") or {}).get("provider") or DEFAULT)
    return chosen if chosen in PROVIDERS else DEFAULT


def info(provider: str | None = None, cfg: dict | None = None) -> dict:
    """The provider's entry from PROVIDERS plus its id, with "base" filled in for another service (ai.custom_url)."""
    cfg = cfg or settings_mod.get()
    pid = provider or current(cfg)
    entry = {**PROVIDERS[pid], "id": pid}
    if entry.get("custom"):
        entry["base"] = str((cfg.get("ai") or {}).get("custom_url") or "").strip().rstrip("/")
    return entry


def set_provider(provider: str, custom_url: str | None = None) -> dict:
    """Switch to another provider and return the settings. The model choices go back to the provider's default, since a
    model name from one provider means nothing to another. custom_url is the address of another service."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    cfg = settings_mod.get()
    ai = cfg["ai"]
    if ai.get("provider", DEFAULT) != provider:
        ai["model"] = ""
        for stage in ai["stages"].values():
            stage["model"] = ""
    ai["provider"] = provider
    if custom_url is not None:
        url = custom_url.strip().rstrip("/")
        if url and not url.lower().startswith(("http://", "https://")):
            raise ValueError("The address must start with http:// or https://")
        ai["custom_url"] = url
    return settings_mod.save(cfg)


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
        raise ValueError("That doesn't look like an API key. Copy the whole key, with no spaces.")
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
    pid = provider or current()
    if PROVIDERS[pid]["auth"] == "chatgpt":
        return await signin.access_token()
    key = get_key(pid)
    if not key:
        raise NoCredential(f"Add your {PROVIDERS[pid]['name']} key first (Settings, AI).")
    return key


def problem(cfg: dict | None = None) -> str:
    """Why the AI can't run right now, worded for the user, or "" when it can."""
    entry = info(cfg=cfg)
    if entry["auth"] == "chatgpt":
        return "" if signin.status().get("signed_in") else "Sign in with ChatGPT first (Settings, AI)."
    if entry.get("custom") and not entry["base"]:
        return "Give the address of your AI service first (Settings, AI)."
    return "" if get_key(entry["id"]) else f"Add your {entry['name']} key first (Settings, AI)."


def status(cfg: dict | None = None) -> dict:
    """The AI's status, safe to send to the dashboard: the provider in use, whether it's ready, the ChatGPT account (name
    and email, when that's the provider), which providers have a saved key (shown by their last four characters), and the
    custom address. "signed_in" means ready too, so older parts of the dashboard keep working. Never includes a key."""
    cfg = cfg or settings_mod.get()
    entry = info(cfg=cfg)
    account = signin.status() if entry["auth"] == "chatgpt" else {}
    keys = _load_keys()
    ready = not problem(cfg)
    return {"provider": entry["id"], "provider_name": entry["name"], "auth": entry["auth"], "ready": ready, "signed_in": ready,
            "name": account.get("name", ""), "email": account.get("email", ""), "chatgpt_signed_in": signin.status().get("signed_in", False),
            "keys": {pid: _hint(str(k.get("key") or "")) for pid, k in keys.items() if pid in PROVIDERS and k.get("key")},
            "custom_url": entry["base"] if entry.get("custom") else str((cfg.get("ai") or {}).get("custom_url") or "")}


def listing() -> list[dict]:
    """Every provider for the dashboard's picker: id, name, how to connect, where to get a key, the note, and whether it
    has free models and web search."""
    return [{"id": pid, "name": p["name"], "auth": p["auth"], "signin": bool(p.get("signin")), "key_url": p.get("key_url", ""),
             "key_prefix": p.get("key_prefix", ""), "note": p["note"], "free": bool(p.get("free")), "search": bool(p.get("search")),
             "custom": bool(p.get("custom"))} for pid, p in PROVIDERS.items()]


def publish() -> None:
    """Send the AI's status to every open dashboard (live event "ai") and keep it in bus.state."""
    bus.state["ai"] = status()
    bus.publish("ai", bus.state["ai"])


# ---------------------------------------------------------------- Sign in with OpenRouter

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def openrouter_start(port: int) -> str:
    """Start Sign in with OpenRouter: the address of OpenRouter's approval page, for the dashboard to open in the browser.
    PKCE (S256) means only this process can trade the code that comes back, and the state value ties the callback to this
    sign-in, so a forged callback is refused. The key OpenRouter makes is labeled JobPortal."""
    now = time.time()
    for state in [s for s, p in _pending.items() if now - p["created"] > SIGN_IN_TIMEOUT]:
        _pending.pop(state, None)
    verifier = _b64url(secrets.token_bytes(48))
    state = _b64url(secrets.token_bytes(24))
    _pending[state] = {"verifier": verifier, "created": now}
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    callback = f"http://127.0.0.1:{port}{OPENROUTER_CALLBACK}"
    return f"{OPENROUTER_AUTH}?" + urlencode({"callback_url": callback, "code_challenge": challenge, "code_challenge_method": "S256",
                                              "state": state, "key_label": "JobPortal"})


async def openrouter_finish(params: dict) -> None:
    """Finish Sign in with OpenRouter from the callback's query parameters: check the state, trade the code for the key,
    save it and switch to OpenRouter. Raises ValueError with a message for the user when anything is off. Network call."""
    pending = _pending.pop(str(params.get("state") or ""), None)
    if not pending or time.time() - pending["created"] > SIGN_IN_TIMEOUT:
        raise ValueError("This sign-in link is old or didn't come from JobPortal. Start again from JobPortal.")
    code = str(params.get("code") or "")
    if not code:
        raise ValueError("OpenRouter didn't approve the sign-in.")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(OPENROUTER_EXCHANGE, json={"code": code, "code_verifier": pending["verifier"],
                                                             "code_challenge_method": "S256"})
    except httpx.HTTPError as e:
        raise ValueError(f"Couldn't reach OpenRouter to finish signing in ({type(e).__name__}). Try again.") from None
    try:
        key = r.json().get("key") if r.status_code == 200 else None
    except ValueError:
        key = None
    if not isinstance(key, str) or not key:
        raise ValueError(f"OpenRouter didn't hand over a key (HTTP {r.status_code}). Try again.")
    save_key("openrouter", key, via="sign-in")
    if current() != "openrouter":
        set_provider("openrouter")
    publish()


def openrouter_key_page() -> str:
    """The OpenRouter page for the saved key, where its owner can see its use, change its limit or delete it."""
    key = get_key("openrouter")
    return f"https://openrouter.ai/keys/{hashlib.sha256(key.encode()).hexdigest()}" if key else "https://openrouter.ai/settings/keys"
