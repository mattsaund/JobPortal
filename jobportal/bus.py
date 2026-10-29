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
    "cost_usd": 0.0,
    "usage": None,  # latest Claude subscription utilization snapshot
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
