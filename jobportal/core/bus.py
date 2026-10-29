"""Live updates for the dashboard: a small publish and subscribe hub inside the server process.

Every open dashboard keeps one connection to GET /api/events (web/routes/system.py), a Server-Sent Events stream. That
route calls subscribe() to get a queue and forwards everything put on the queue to the browser. Any code can call
publish() to send an event to every open dashboard: run progress, new leads, toasts, sign-in changes. The dashboard's
js/live.js decides what to redraw for each kind of event.

Key ideas:
- An event is JSON: {"kind": ..., "data": ...}. The dashboard reads both by name, so keep kind names and data fields
  stable. Kinds in use: state, log, lead, toast, ai, tokens, agents, run_done, profile, profile_status, questions and
  analysis.
- `state` is one shared snapshot of what the app is doing. A dashboard gets it first when it connects, and set_state()
  sends it again after every change.
- publish() never waits and never fails. It can be called from any thread, and FastAPI runs plain `def` routes in worker
  threads. An asyncio queue may only be touched from the thread running its event loop, so publish() hands the event to
  that loop when it runs on another thread.
- Nothing is saved. Events reach only the dashboards that are open right now."""
import asyncio
import json

MAX_QUEUED = 2000  # events waiting for one dashboard; a full queue means it stopped reading, so new events are dropped

# Each open dashboard's queue, with the event loop that reads it (None when it was made outside a running loop).
_subscribers: dict[asyncio.Queue, asyncio.AbstractEventLoop | None] = {}

state = {
    "running": False,  # a search run is in progress (search/pipeline.py)
    "run_id": None,  # that run's id in the runs table
    "mode": None,  # the run's mode: "full", "boards", "hunt" or "backlog"
    "phase": "idle",  # what the run is doing: idle, collecting, triaging or packaging
    "counts": {},  # the run's counters: found, candidates, triaged, qualified, packaged and a few more
    "tokens": 0,  # AI tokens used since JobPortal started (ai/client.py adds to it)
    "ai": None,  # ChatGPT sign-in status (ai/signin.py)
    "active_agents": {},  # AI requests running now, id -> label (ai/client.py)
}
# Other modules add keys as they go: search/pipeline.py sets started_at and run_tokens_start when a run begins, and
# candidate/profile.py sets profile (the profile's build status).


def subscribe() -> asyncio.Queue:
    """Register one listener (an open dashboard) and return the queue its events arrive on. Call unsubscribe() when it
    disconnects."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUED)
    _subscribers[queue] = _running_loop()
    return queue


def unsubscribe(q: asyncio.Queue) -> None:
    """Forget the listener that owns queue `q`. Calling it twice is fine."""
    _subscribers.pop(q, None)


def listeners() -> int:
    """How many dashboards are connected to the live event stream. app/desktop.py uses it to notice the app window
    closing."""
    return len(_subscribers)


def publish(kind: str, data) -> None:
    """Send one event to every open dashboard. `data` should be JSON-friendly; anything else is sent as its str().
    Never waits and never raises, so it's safe to call from anywhere."""
    message = json.dumps({"kind": kind, "data": data}, default=str)
    here = _running_loop()
    for queue, loop in list(_subscribers.items()):  # a copy, because dashboards may connect or leave meanwhile
        if loop is None or loop is here:
            _offer(queue, message)
            continue
        # Another thread: ask the queue's own loop to add the event. call_soon_threadsafe also wakes that loop, so the
        # dashboard gets the event right away.
        try:
            loop.call_soon_threadsafe(_offer, queue, message)
        except RuntimeError:  # that loop is closed, so its dashboard is gone
            pass


def set_state(**kw) -> None:
    """Update the shared `state` snapshot (for example set_state(phase="triaging")) and send the whole of it to every
    dashboard."""
    state.update(kw)
    publish("state", state)


def _offer(queue: asyncio.Queue, message: str) -> None:
    """Add a message to one dashboard's queue, or drop it if that dashboard has fallen too far behind."""
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:
        pass  # dropping one dashboard's events is better than making the whole app wait for it


def _running_loop() -> asyncio.AbstractEventLoop | None:
    """The event loop running in this thread, or None in plain (non-async) code."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None
