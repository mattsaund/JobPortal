"""The AI: every provider JobPortal can run on, connecting one (a sign-in, a key or an address), and the model list.
ai/providers.py and ai/signin.py do the work. These routes serve the Connect popup: they save and check a connection,
start each sign-in, receive the provider's redirect back to this computer, and report the result."""
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

# The page the browser shows after a provider sends it back. It opens in the user's normal browser rather than in JobPortal,
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
    """The AI in use and whether it's ready, the signed-in account, which providers have a key (never the keys or tokens
    themselves), tokens used since startup, and whether web search works."""
    return {**providers.status(), "tokens": bus.state.get("tokens", 0), "web_search": ai.web_search_ok}


@router.get("/api/ai/providers")
def ai_providers():
    """Every AI JobPortal can run on, for the Connect popup."""
    return {"providers": providers.listing(), "status": providers.status()}


def _switched() -> dict:
    """After the provider or its key changed: forget what was learned about the old one, tell the dashboards, and let
    documents added while the AI wasn't ready get their AI reading."""
    ai.reset_provider_state()
    providers.publish()
    if not providers.problem():
        background.spawn(documents.parse_pending())
    return providers.status()


@router.put("/api/ai/key")
async def connect(body: dict):
    """Connect a provider by key or address, {"provider": id, "key": "...", "endpoint": {field: value}, "model": "..."}, and
    switch to it. An empty key keeps the one already saved. The connection is checked first by asking the provider for its
    model list, so a wrong key or address is caught now rather than in the middle of a search. One the provider refuses is
    not kept (401 with the reason). A provider with no model list answers 409 until a model is named, and is then checked
    with one small real request. Returns the status and the models."""
    pid = str(body.get("provider") or "")
    key = str(body.get("key") or "").strip()
    if pid not in providers.PROVIDERS or providers.PROVIDERS[pid]["auth"] != "key":
        raise HTTPException(400, "That AI doesn't connect with a key.")
    state = providers.saved_state(pid)
    try:
        if isinstance(body.get("endpoint"), dict):
            providers.set_endpoint(pid, body["endpoint"])
        if key:
            providers.save_key(pid, key)
        providers.set_provider(pid)
        problem = providers.problem()
        if problem:
            raise ValueError(problem)
    except ValueError as e:
        providers.restore(state)
        _switched()
        raise HTTPException(400, str(e))
    ai.reset_provider_state()
    model = str(body.get("model") or "").strip()
    try:
        try:
            found = await ai.models(force=True)
        except ai.NoModelList:
            if not model:
                providers.restore(state)
                _switched()
                raise HTTPException(409, "Model name needed.")
            providers.set_model(model)
            await ai.check_connection()
            found = [model]
    except ai.AIError as e:  # put things back the way they were
        providers.restore(state)
        _switched()
        raise ai_error(e)
    return {**_switched(), "models": found}


@router.delete("/api/ai/connection")
async def disconnect(provider: str):
    """Stop using one provider: sign out of ChatGPT, or forget its key. A key stays valid at the provider, where the user
    can delete it."""
    await providers.disconnect(provider)
    return {**_switched(), "key_page": providers.PROVIDERS.get(provider, {}).get("key_url", "")}


@router.post("/api/ai/signin")
def start_signin(body: dict | None = None):
    """Start a provider's sign-in, {"provider": id}. The dashboard opens the returned address in the system browser."""
    pid = str((body or {}).get("provider") or "")
    if pid == "chatgpt":
        return {"url": signin.start(PORT)}
    if pid in providers.KEY_SIGNINS:
        return {"url": providers.key_signin_start(pid, PORT)}
    raise HTTPException(400, "That AI doesn't have a sign-in.")


@router.get(providers.KEY_SIGNINS["openrouter"]["callback"])
@router.get(providers.KEY_SIGNINS["pollinations"]["callback"])
async def key_signin_callback(request: Request):
    """A provider sends the browser back here after the user approves JobPortal. Finishing turns the one-time code into the
    user's key and switches to that provider, so the dashboard updates by itself."""
    provider = request.url.path.rsplit("/", 1)[-1]
    try:
        await providers.key_signin_finish(provider, dict(request.query_params))
        _switched()
        title, body = "Connected", "You can close this tab."
    except ValueError as e:
        title, body = "Sign-in didn't finish", str(e)
    return HTMLResponse(CALLBACK_PAGE.substitute(title=html.escape(title), body=html.escape(body)))


@router.get(signin.CALLBACK_PATH)
async def ai_callback(request: Request):
    """OpenAI sends the browser back here after the user signs in. Finishing the sign-in publishes the new status, so the
    dashboard updates by itself."""
    try:
        await signin.finish(dict(request.query_params))
        title, body = "Connected", "You can close this tab."
        if providers.current() != "chatgpt" or not providers.settings_mod.get()["ai"].get("provider"):  # signing in means using it
            providers.set_provider("chatgpt")
        _switched()
    except signin.AuthError as e:
        message = str(e)
        # Most of signin's messages already say what to do next; add it only to the ones that don't.
        hint = "" if "again" in message.lower() else " Go back to JobPortal and try again."
        title, body = "Sign-in didn't finish", message + hint
    return HTMLResponse(CALLBACK_PAGE.substitute(title=html.escape(title), body=html.escape(body)))


@router.get("/api/ai/models")
async def ai_models(refresh: int = 0):
    """The models the account can use with the provider in use, best default first, for the model menus in Settings."""
    try:
        return {"models": await ai.models(force=bool(refresh))}
    except ai.AIError as e:
        raise ai_error(e)
