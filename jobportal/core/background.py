"""Background work: building a package, updating the profile, an AI analysis. API routes start most of it, and the
profile starts its own follow-ups.

Whoever starts a task returns right away. The dashboard hears about progress and results over the live event stream
(core/bus.py), so nothing here sends a reply. Every task is tracked so the server can cancel what's still running when it
shuts down (web/server.py calls cancel_all)."""
import asyncio

from jobportal.core import bus

_tasks: set[asyncio.Task] = set()


def spawn(coro, *, error_title: str | None = None, lead_id: int | None = None) -> asyncio.Task:
    """Run a coroutine in the background without making the request wait.

    When it fails and error_title is given, the dashboard shows an error toast with that title (linked to the lead, if
    any). Without error_title the error is dropped. Use that for work that already reports its own errors."""

    async def guarded():
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 (background work must never take the server down)
            if error_title:
                bus.publish("toast", {"title": error_title, "body": str(e)[:300], "level": "error", "lead_id": lead_id})

    task = asyncio.create_task(guarded())
    _tasks.add(task)  # asyncio only keeps weak references to tasks, so hold one until it finishes
    task.add_done_callback(_tasks.discard)
    return task


def cancel_all() -> None:
    """Called at shutdown: stop every background task that's still running."""
    for task in list(_tasks):
        task.cancel()
