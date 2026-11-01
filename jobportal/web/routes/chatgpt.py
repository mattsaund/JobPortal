"""Sign in with ChatGPT and the model list. ai/signin.py does the actual sign-in. These routes start it, receive OpenAI's
redirect back to this computer, and report the result."""
import html
from string import Template

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from jobportal.ai import client as ai, signin
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
img { display: block; width: 180px; height: auto; margin-bottom: 18px; border-radius: 8px; }
h1 { margin: 0 0 10px; color: var(--green); font-size: 22px; }
p { margin: 0; color: var(--muted); }
</style>
<main><img src="/static/logo.png" alt="JobPortal"><h1>$title</h1><p>$body</p></main></html>""")


@router.get("/api/ai/status")
def ai_status():
    """Who is signed in (never the tokens themselves), tokens used since startup, and whether web search works."""
    return {**signin.status(), "tokens": bus.state.get("tokens", 0), "web_search": ai.web_search_ok}


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
        background.spawn(documents.parse_pending())  # documents added while signed out get their AI reading now
    except signin.AuthError as e:
        message = str(e)
        # Most of signin's messages already say what to do next; add it only to the ones that don't.
        hint = "" if "again" in message.lower() else " Go back to JobPortal and try again."
        title, body = "Sign-in didn't finish", message + hint
    return HTMLResponse(CALLBACK_PAGE.substitute(title=html.escape(title), body=html.escape(body)))


@router.post("/api/ai/signout")
async def ai_signout():
    """Sign out of ChatGPT: revoke the sign-in at OpenAI when it can be reached, and forget the tokens either way."""
    return await signin.sign_out()


@router.get("/api/ai/models")
async def ai_models(refresh: int = 0):
    """The models this ChatGPT account can use, for the model menus in Settings."""
    try:
        return {"models": await ai.models(force=bool(refresh))}
    except ai.AIError as e:
        raise ai_error(e)
