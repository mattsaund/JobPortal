"""Searching on a schedule: at the times of day the user picks (Settings, Search, "Search on a schedule"), JobPortal starts a
full search by itself. With "Keep searching in the background" on, that goes on after the window closes and after a
restart: JobPortal starts in the background when the user logs in.

How it fits: web/server.py runs runner() for as long as the server is up. Every CHECK_SECONDS it asks due_slot() whether a
scheduled time has come since the last search, starts one through search/pipeline.py, and after a scheduled search ends
it sends a desktop alert with what it found when no dashboard is open to show it (Settings, Appearance). The Settings
route calls settings_saved() after every save, which notes when the schedule was turned on and adds or removes the login
item (core/osutil.py). app/desktop.py hands the server to a background process when the window closes (see
keep_running_without_window()).

Key ideas:
- Times are the computer's local time, "HH:MM" on a 24-hour clock, on the chosen days (0 is Monday).
- Each scheduled time starts at most one search. A time missed while JobPortal was closed or the computer slept starts
  its search as soon as JobPortal runs again, and however many times were missed, only one search catches up.
- Times before the schedule was turned on don't count, so turning it on never starts a search right away. A search that
  started after the time (one the user started) counts for it.
- A time that comes while setup isn't finished or the AI isn't ready is skipped, not retried. status() says why.
- A server started for the schedule (`jobportal --background --scheduled`) quits by itself once searching in the
  background is turned off and no window has been open for IDLE_QUIT_SECONDS.

State in the kv table: "schedule.enabled_at" (when it was turned on), "schedule.last" (the last scheduled time handled:
its slot, the run it started or why it was skipped), "schedule.alerted_run" (the run its alert was sent for) and
"schedule.login_item" (this data folder added the login item, so it may remove it: another copy of JobPortal with a data
folder of its own, such as a test, never removes the login item of the one the user runs)."""
import asyncio
import json
import os
from datetime import date, datetime, time as dtime, timedelta

from jobportal.ai import client as ai
from jobportal.candidate import profile
from jobportal.core import bus, db, osutil, settings as settings_mod
from jobportal.search import pipeline

CHECK_SECONDS = 30  # how often runner() looks at the clock
IDLE_QUIT_SECONDS = 180  # how long a schedule-only server waits with no window and nothing to do before it quits
LOOKBACK_DAYS = 8  # how far back last_slot() looks for a missed time (a week of days, plus one)
SCHEDULED_ENV = "JOBPORTAL_SCHEDULED"  # set to "1" in a server started for the schedule (app/cli.py)


# ---------------------------------------------------------------- the clock

def parse_times(times) -> list[dtime]:
    """The valid "HH:MM" times in `times`, sorted, each once. Anything else (empty, "25:00", "noon") is left out."""
    out = set()
    for value in times if isinstance(times, list) else []:
        try:
            hours, minutes = (int(part) for part in str(value).strip().split(":"))
            out.add(dtime(hours, minutes))
        except ValueError:  # not two numbers, or a number out of range
            continue
    return sorted(out)


def _days(sched: dict) -> set[int]:
    """The chosen weekdays (0 is Monday). A missing or broken list means every day."""
    days = sched.get("days")
    if not isinstance(days, list):
        return set(range(7))
    return {d for d in days if isinstance(d, int) and 0 <= d <= 6}


def _slots_on(day: date, sched: dict) -> list[datetime]:
    """The scheduled times on one day, as local times that know their time zone (so a daylight saving change is right)."""
    if day.weekday() not in _days(sched):
        return []
    return [datetime.combine(day, t).astimezone() for t in parse_times(sched.get("times"))]


def last_slot(sched: dict, now: datetime) -> datetime | None:
    """The latest scheduled time at or before `now`, looking back LOOKBACK_DAYS, or None when there is none."""
    for back in range(LOOKBACK_DAYS):
        earlier = [slot for slot in _slots_on(now.date() - timedelta(days=back), sched) if slot <= now]
        if earlier:
            return max(earlier)
    return None


def next_slot(sched: dict, now: datetime) -> datetime | None:
    """The first scheduled time after `now`, looking ahead a week, or None when no time is set or no day is chosen."""
    for ahead in range(LOOKBACK_DAYS):
        later = [slot for slot in _slots_on(now.date() + timedelta(days=ahead), sched) if slot > now]
        if later:
            return min(later)
    return None


def _when(iso) -> datetime | None:
    """An ISO timestamp from the database as a datetime that knows its time zone, or None."""
    try:
        moment = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.astimezone()


def due_slot(sched: dict, now: datetime, *, enabled_at=None, handled=None, last_run=None) -> datetime | None:
    """The scheduled time a search should start for now, or None. A time is due when the schedule is on, it has come, it
    came after the schedule was turned on, and neither a scheduled search (`handled`, the last time handled) nor any other
    search (`last_run`, when the latest search started) has covered it yet. The three keyword arguments are ISO
    timestamps or datetimes."""
    if not sched.get("enabled"):
        return None
    slot = last_slot(sched, now)
    if slot is None:
        return None
    for covered in (enabled_at, handled, last_run):
        moment = covered if isinstance(covered, datetime) else _when(covered)
        if moment and moment >= slot:
            return None
    return slot


# ---------------------------------------------------------------- running it

def _schedule(cfg: dict | None = None) -> dict:
    """The schedule section of the settings."""
    return (cfg or settings_mod.get()).get("schedule") or {}


def keep_running_without_window(cfg: dict | None = None) -> bool:
    """Whether JobPortal should keep searching after its window closes: the schedule is on, with background searching."""
    sched = _schedule(cfg)
    return bool(sched.get("enabled") and sched.get("background"))


def _not_ready() -> str:
    """Why a search can't start now, worded for the user, or "" when it can: setup must be finished and the AI ready."""
    return profile.ready_to_search() or ai.setup_problem()


async def tick(now: datetime | None = None) -> dict | None:
    """One look at the clock: start the search for a due scheduled time, or record why it was skipped. Returns what was
    recorded for that time ({"slot", "run_id"} or {"slot", "skipped"}), or None when nothing was due."""
    now = now or datetime.now().astimezone()
    last = db.kv_get("schedule.last") or {}
    latest_run = db.one("SELECT started_at FROM runs ORDER BY id DESC LIMIT 1")
    slot = due_slot(_schedule(), now, enabled_at=db.kv_get("schedule.enabled_at"), handled=last.get("slot"),
                    last_run=latest_run["started_at"] if latest_run else None)
    if slot is None:
        return None
    record: dict = {"slot": slot.isoformat(timespec="minutes")}
    problem = _not_ready()
    if bus.state.get("running"):
        problem = problem or "A search was already running."
    if not problem:
        try:
            record["run_id"] = await pipeline.start("full")
        except (RuntimeError, ValueError) as e:  # a run already going, or setup undone a moment ago
            problem = str(e)
    if problem:
        record["skipped"] = problem
    db.kv_set("schedule.last", record)
    publish_status()
    return record


def alert_finished_run() -> bool:
    """When the last scheduled search has ended, and its alert hasn't gone out, send a desktop alert with what it found.
    Only when desktop alerts are on and no dashboard is open: an open dashboard shows the result itself. Returns whether
    an alert was sent."""
    run_id = (db.kv_get("schedule.last") or {}).get("run_id")
    if not run_id or db.kv_get("schedule.alerted_run") == run_id:
        return False
    row = db.one("SELECT status, stats FROM runs WHERE id=?", (run_id,))
    if not row or row["status"] == "running":
        return False
    db.kv_set("schedule.alerted_run", run_id)  # once per run, even when this one isn't shown
    if bus.listeners() or not settings_mod.get().get("alerts", {}).get("desktop"):
        return False
    stats = _stats(row["stats"])
    packaged, qualified = int(stats.get("packaged") or 0), int(stats.get("qualified") or 0)
    if not (packaged or qualified):
        return False  # nothing new is worth an interruption
    body = (f"{packaged} new application{'s' if packaged != 1 else ''} ready to send" if packaged
            else f"{qualified} new good match{'es' if qualified != 1 else ''} found")
    return osutil.notify("JobPortal found new jobs", f"{body}. Open JobPortal to see them.")


def _stats(raw) -> dict:
    """A run's stats column (JSON text) as a dict."""
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def status(cfg: dict | None = None) -> dict:
    """What Settings and Home show about the schedule: whether it's on, the next scheduled time (ISO, or None), the last
    time handled, whether JobPortal starts at login, and whether this server was started for the schedule."""
    sched = _schedule(cfg)
    upcoming = next_slot(sched, datetime.now().astimezone()) if sched.get("enabled") else None
    return {"enabled": bool(sched.get("enabled")), "background": bool(sched.get("background")),
            "next": upcoming.isoformat(timespec="minutes") if upcoming else None, "last": db.kv_get("schedule.last"),
            "login_item": osutil.has_login_item(), "background_server": os.environ.get(SCHEDULED_ENV) == "1"}


def publish_status() -> None:
    """Keep the schedule status in bus.state (dashboards get it when they connect) and send it as a "schedule" event."""
    bus.state["schedule"] = status()
    bus.publish("schedule", bus.state["schedule"])


def login_command() -> list[str]:
    """The command the login item runs: this copy of JobPortal as a schedule-only background server, with the same data
    folder and port as now."""
    command = [*osutil.self_command(), "--background", "--scheduled"]
    if os.environ.get("JOBPORTAL_HOME"):
        command += ["--data-dir", os.environ["JOBPORTAL_HOME"]]
    if os.environ.get("JOBPORTAL_PORT"):
        command += ["--port", os.environ["JOBPORTAL_PORT"]]
    return command


def sync_login_item(cfg: dict | None = None) -> bool:
    """Make the login item match the settings: there while the schedule runs in the background, gone otherwise. Also
    refreshes it, so it follows the app when the app moved or was updated. Only the data folder that added the login item
    removes it. Returns whether that worked."""
    if keep_running_without_window(cfg):
        added = osutil.set_login_item(login_command())
        if added:
            db.kv_set("schedule.login_item", True)
        return added
    if not db.kv_get("schedule.login_item"):
        return True  # this data folder never added one, so the login item (if any) belongs to another copy
    removed = osutil.set_login_item(None)
    if removed:
        db.kv_set("schedule.login_item", False)
    return removed


def settings_saved(before: dict, after: dict) -> None:
    """Called after every settings save. Turning the schedule on notes the moment, so earlier times don't count. The login
    item and the schedule status follow the new settings."""
    if _schedule(after).get("enabled") and not _schedule(before).get("enabled"):
        db.kv_set("schedule.enabled_at", db.now())
    if keep_running_without_window(before) != keep_running_without_window(after):
        sync_login_item(after)
    publish_status()


async def runner(stop_server=None) -> None:
    """The scheduler loop, run by web/server.py for the life of the server. Every CHECK_SECONDS: start a due search, send
    the alert for a finished one, and, in a server started for the schedule, quit (through `stop_server`) once background
    searching is off and nothing needs the server for IDLE_QUIT_SECONDS."""
    idle_since = None
    publish_status()
    while True:
        await asyncio.sleep(CHECK_SECONDS)
        try:
            await tick()
            alert_finished_run()
            if stop_server and os.environ.get(SCHEDULED_ENV) == "1":
                busy = bus.listeners() or bus.state.get("running") or keep_running_without_window()
                idle_since = None if busy else (idle_since or asyncio.get_running_loop().time())
                if idle_since is not None and asyncio.get_running_loop().time() - idle_since >= IDLE_QUIT_SECONDS:
                    stop_server()
                    return
        except Exception:  # noqa: BLE001 (the scheduler must keep running; a search that can't start waits for its next time)
            pass
