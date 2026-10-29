"""In-process pub/sub feeding the dashboard's Server-Sent Events stream."""
import asyncio
import json

_subscribers: set[asyncio.Queue] = set()
state = {
    "running": False,
    "run_id": None,
    "mode": None,
    "phase": "idle",
    "counts": {},
    "tokens": 0,  # AI tokens used since JobPortal started
    "ai": None,  # ChatGPT sign-in status
    "active_agents": {},  # id -> label
}


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def publish(kind: str, data) -> None:
    msg = json.dumps({"kind": kind, "data": data}, default=str)
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


def set_state(**kw) -> None:
    state.update(kw)
    publish("state", state)
