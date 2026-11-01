"""Sign in with ChatGPT and the model list. ai/signin.py does the actual sign-in. These routes start it, receive OpenAI's
redirect back to this computer, and report the result."""
import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from jobportal.ai import client as ai, signin
from jobportal.candidate import documents
from jobportal.core import background, bus
from jobportal.core.config import PORT
from jobportal.web.common import ai_error

router = APIRouter()

# The page the browser shows after OpenAI sends it back. Plain HTML in the dashboard's colors, since it opens in the
# user's normal browser rather than in JobPortal.
CALLBACK_PAGE = """<!doctype html><meta charset="utf-8"><title>JobPortal</title>
<body style="background:#0c0d10;color:#ecebe7;font:15px/1.6 ui-monospace,Menlo,Consolas,monospace;display:grid;place-items:center;height:100vh;margin:0">
<div style="max-width:520px;padding:28px;border:1px solid #262b34;border-radius:12px;background:#13151a">
<h1 style="font-size:20px;margin:0 0 10px">{title}</h1><p style="margin:0">{body}</p></div></body>"""


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
        title, body = "Sign-in didn't finish", f"{e} Go back to JobPortal and try again."
    return HTMLResponse(CALLBACK_PAGE.format(title=html.escape(title), body=html.escape(body)))


@router.post("/api/ai/signout")
async def ai_signout():
    return await signin.sign_out()


@router.get("/api/ai/models")
async def ai_models(refresh: int = 0):
    """The models this ChatGPT account can use, for the model menus in Settings."""
    try:
        return {"models": await ai.models(force=bool(refresh))}
    except ai.AIError as e:
        raise ai_error(e)
