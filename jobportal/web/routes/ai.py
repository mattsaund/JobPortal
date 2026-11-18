"""The AI: which provider JobPortal runs on, Sign in with ChatGPT and with OpenRouter, the API keys, and the model list.
ai/providers.py and ai/signin.py do the work. These routes switch providers, save and check keys, start each sign-in,
receive the provider's redirect back to this computer, and report the result."""
import html
from string import Template

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from jobportal.ai import client as ai, providers, signin
from jobportal.candidate import documents
from jobportal.core import background, bus
from jobportal.core.config import PORT
from jobportal.web.common import ai_error

router = APIRouter()

# The page the browser shows after OpenAI sends it back. It opens in the user's normal browser rather than in JobPortal,
# so it's one self-contained page in the dashboard's colors (light or dark, following the system setting) with the logo.
# $title and $body are filled in with string.Template, because the CSS braces would trip up str.format().
CALLBACK_PAGE = Template("""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>JobPortal</title>
<link rel="icon" type="image/png" href="/static/favicon.png">
<style>
:root { color-scheme: light; --page: #f5f5f5; --surface: #ffffff; --border: #dddddd; --text: #252525; --muted: #686868; --green: #007d63; }
@media (prefers-color-scheme: dark) {
  :root { color-scheme: dark; --page: #242424; --surface: #303030; --border: #484848; --text: #f3f3f3; --muted: #bcbcbc; --green: #45edb5; }
}
body { display: grid; place-items: center; min-height: 100vh; margin: 0; background: var(--page); color: var(--text); font: 15px/1.6 Arial, Helvetica, sans-serif; }
main { max-width: 520px; margin: 16px; padding: 28px; border: 1px solid var(--border); border-radius: 11px; background: var(--surface); }
img { display: block; width: 180px; height: auto; margin-bottom: 18px; padding: 8px 12px; border-radius: 8px; background: #252525; }
h1 { margin: 0 0 10px; color: var(--green); font-size: 22px; }
p { margin: 0; color: var(--muted); }
</style>
<main><img src="/static/logo.png" alt="JobPortal"><h1>$title</h1><p>$body</p></main></html>""")


@router.get("/api/ai/status")
def ai_status():
    """The AI in use and whether it's ready, who is signed in with ChatGPT, which providers have a key (never the keys or
    tokens themselves), tokens used since startup, and whether web search works."""
    return {**providers.status(), "tokens": bus.state.get("tokens", 0), "web_search": ai.web_search_ok}


@router.get("/api/ai/providers")
def ai_providers():
    """Every AI JobPortal can run on, for the picker in Settings, AI and on the welcome screen."""
    return {"providers": providers.listing(), "status": providers.status()}


def _switched() -> dict:
    """After the provider or its key changed: forget what was learned about the old one, tell the dashboards, and let
    documents added while the AI wasn't ready get their AI reading."""
    ai.reset_provider_state()
    providers.publish()
    if not providers.problem():
        background.spawn(documents.parse_pending())
    return providers.status()


@router.post("/api/ai/provider")
def choose_provider(body: dict):
    """Run the AI on another provider, {"provider": id}, with {"custom_url": "..."} for another service. The model choices
    go back to that provider's default."""
    try:
        providers.set_provider(str(body.get("provider") or ""), body.get("custom_url"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _switched()


@router.put("/api/ai/key")
async def save_key(body: dict):
    """Save a provider's API key, {"provider": id, "key": "..."}, and switch to that provider. The key is checked first by
    asking the provider for its model list, so a wrong key is caught now rather than in the middle of a search. A key the
    provider refuses is not saved (401 with the reason). Returns the status and the models."""
    pid = str(body.get("provider") or "")
    try:
        before = providers.current()
        previous = providers.get_key(pid)
        providers.save_key(pid, str(body.get("key") or ""))
        providers.set_provider(pid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    ai.reset_provider_state()
    try:
        found = await ai.models(force=True)
    except ai.AIError as e:  # put things back the way they were
        if previous:
            providers.save_key(pid, previous)
        else:
            providers.forget_key(pid)
        if before != pid:
            providers.set_provider(before)
        _switched()
        raise ai_error(e)
    return {**_switched(), "models": found}


@router.delete("/api/ai/key")
def forget_key(provider: str):
    """Forget one provider's saved key. It stays valid at the provider: the user can delete it there."""
    providers.forget_key(provider)
    return {**_switched(), "key_page": providers.PROVIDERS.get(provider, {}).get("key_url", "")}


@router.post("/api/ai/openrouter/signin")
def openrouter_signin():
    """Start Sign in with OpenRouter. The dashboard opens the returned address in the system browser."""
    return {"url": providers.openrouter_start(PORT)}


@router.get(providers.OPENROUTER_CALLBACK)
async def openrouter_callback(request: Request):
    """OpenRouter sends the browser back here after the user approves JobPortal. Finishing turns the one-time code into
    the user's key and switches to OpenRouter, so the dashboard updates by itself."""
    try:
        await providers.openrouter_finish(dict(request.query_params))
        _switched()
        title, body = "You're signed in", "JobPortal can now use your OpenRouter account. You can close this tab and go back to JobPortal."
    except ValueError as e:
        title, body = "Sign-in didn't finish", str(e)
    return HTMLResponse(CALLBACK_PAGE.substitute(title=html.escape(title), body=html.escape(body)))


@router.post("/api/ai/signin")
def ai_signin():
    """Start Sign in with ChatGPT. The dashboard opens the returned OpenAI address in the system browser."""
    return {"url": signin.start(PORT)}


@router.get(signin.CALLBACK_PATH)
async def ai_callback(request: Request):
    """OpenAI sends the browser back here after the user signs in. Finishing the sign-in publishes the new status, so the
    dashboard updates by itself."""
    try:
        status = await signin.finish(dict(request.query_params))
        who = f" ({status['email']})" if status.get("email") else ""
        title, body = "You're signed in", f"JobPortal can now use your ChatGPT plan{who}. You can close this tab and go back to JobPortal."
        if providers.current() != "chatgpt":  # signing in with ChatGPT means using it
            providers.set_provider("chatgpt")
        _switched()
    except signin.AuthError as e:
        message = str(e)
        # Most of signin's messages already say what to do next; add it only to the ones that don't.
        hint = "" if "again" in message.lower() else " Go back to JobPortal and try again."
        title, body = "Sign-in didn't finish", message + hint
    return HTMLResponse(CALLBACK_PAGE.substitute(title=html.escape(title), body=html.escape(body)))


@router.post("/api/ai/signout")
async def ai_signout():
    """Sign out of ChatGPT: revoke the sign-in at OpenAI when it can be reached, and forget the tokens either way."""
    out = await signin.sign_out()
    return {**providers.status(), "note": out.get("note", "")}


@router.get("/api/ai/models")
async def ai_models(refresh: int = 0):
    """The models the account can use with the provider in use, best default first, for the model menus in Settings."""
    try:
        return {"models": await ai.models(force=bool(refresh))}
    except ai.AIError as e:
        raise ai_error(e)
