"""Searching on a schedule (search/schedule.py): the clock rules, starting and skipping scheduled searches, the alert after a
scheduled search, the login item that starts JobPortal in the background on each system, handing the schedule to a
background server when the window closes, the settings migration from "every N hours", and the routes."""
import asyncio
import json
import os
import plistlib
from datetime import datetime

import pytest
from conftest import REAL_LOGIN_ITEM
from fastapi.testclient import TestClient

from jobportal.ai import client as ai
from jobportal.app import cli
from jobportal.core import db, osutil, settings
from jobportal.search import schedule

WEEKDAYS = {"enabled": True, "times": ["09:00", "17:30"], "days": [0, 1, 2, 3, 4]}  # Monday to Friday


def local(year, month, day, hour, minute=0) -> datetime:
    """A moment in this computer's local time. November 16, 2026 is a Monday."""
    return datetime(year, month, day, hour, minute).astimezone()


def turn_on(**changes) -> None:
    """Save settings with the schedule on, every day at 09:00 unless `changes` say otherwise."""
    cfg = settings.get()
    cfg["schedule"].update({"enabled": True, "times": ["09:00"], "days": list(range(7)), **changes})
    settings.save(cfg)


def today_at(hour, minute=0) -> datetime:
    return datetime.now().astimezone().replace(hour=hour, minute=minute, second=0, microsecond=0)


# ---------------------------------------------------------------- the clock

def test_times_are_checked_and_sorted():
    times = schedule.parse_times(["17:30", "9:05", "25:00", "noon", "", "09:05", 7])
    assert [t.strftime("%H:%M") for t in times] == ["09:05", "17:30"]
    assert schedule.parse_times("09:00") == []  # not a list


def test_the_last_and_next_times_follow_the_days():
    monday_noon = local(2026, 11, 16, 12)
    assert schedule.last_slot(WEEKDAYS, monday_noon) == local(2026, 11, 16, 9)
    assert schedule.next_slot(WEEKDAYS, monday_noon) == local(2026, 11, 16, 17, 30)
    saturday = local(2026, 11, 21, 10)
    assert schedule.last_slot(WEEKDAYS, saturday) == local(2026, 11, 20, 17, 30)  # Friday evening
    assert schedule.next_slot(WEEKDAYS, saturday) == local(2026, 11, 23, 9)  # Monday morning
    assert schedule.next_slot({**WEEKDAYS, "days": []}, saturday) is None
    assert schedule.next_slot({**WEEKDAYS, "times": []}, saturday) is None


def test_a_scheduled_time_is_due_once():
    now = local(2026, 11, 16, 9, 2)
    assert schedule.due_slot(WEEKDAYS, now) == local(2026, 11, 16, 9)
    assert schedule.due_slot({**WEEKDAYS, "enabled": False}, now) is None
    # Turned on after nine, so the nine o'clock time doesn't count and nothing starts right away.
    assert schedule.due_slot(WEEKDAYS, now, enabled_at=local(2026, 11, 16, 9, 1)) is None
    # Handled already, or covered by a search the user started after nine.
    assert schedule.due_slot(WEEKDAYS, now, handled=local(2026, 11, 16, 9).isoformat()) is None
    assert schedule.due_slot(WEEKDAYS, now, last_run=local(2026, 11, 16, 9, 1)) is None
    # A search that started before nine doesn't cover it.
    assert schedule.due_slot(WEEKDAYS, now, last_run=local(2026, 11, 16, 8, 59)) == local(2026, 11, 16, 9)


def test_missed_times_catch_up_with_one_search():
    """The computer was off from Friday morning to Tuesday morning: one search catches up, for the latest missed time."""
    tuesday = local(2026, 11, 17, 8)
    assert schedule.due_slot(WEEKDAYS, tuesday, handled=local(2026, 11, 13, 9)) == local(2026, 11, 16, 17, 30)


# ---------------------------------------------------------------- starting and skipping

def test_a_due_time_starts_one_search(monkeypatch):
    turn_on()
    started = []

    async def fake_start(mode="full", overrides=None):
        started.append(mode)
        return 7

    monkeypatch.setattr(schedule.pipeline, "start", fake_start)
    monkeypatch.setattr(schedule, "_not_ready", lambda: "")
    now = today_at(9, 5)
    record = asyncio.run(schedule.tick(now))
    assert started == ["full"] and record == {"slot": today_at(9).isoformat(timespec="minutes"), "run_id": 7}
    assert asyncio.run(schedule.tick(now)) is None  # the same time never starts a second search
    assert started == ["full"]


def test_a_time_that_comes_before_setup_is_skipped_with_the_reason():
    turn_on()
    now = today_at(9, 5)
    record = asyncio.run(schedule.tick(now))
    assert record["skipped"] == "Import your resume first: drop it on Home." and "run_id" not in record
    assert db.kv_get("schedule.last") == record
    assert asyncio.run(schedule.tick(now)) is None  # skipped, not tried again until the next time


def test_the_ai_must_be_ready_too(monkeypatch):
    monkeypatch.setattr(schedule.profile, "ready_to_search", lambda: "")
    assert schedule._not_ready() == ai.setup_problem() == "Connect an AI first."


def finished_run(stats: dict, status: str = "done") -> int:
    db.ex("INSERT INTO runs(started_at, finished_at, mode, status, stats) VALUES(?,?,?,?,?)",
          (db.now(), db.now(), "full", status, json.dumps(stats)))
    return db.one("SELECT id FROM runs ORDER BY id DESC LIMIT 1")["id"]


def alerts_on() -> None:
    cfg = settings.get()
    cfg["alerts"]["desktop"] = True
    settings.save(cfg)


def test_a_finished_scheduled_search_sends_one_alert(monkeypatch):
    sent = []
    monkeypatch.setattr(osutil, "notify", lambda title, body="", icon=None: sent.append((title, body)) or True)
    alerts_on()
    db.kv_set("schedule.last", {"slot": "2026-11-16T09:00-05:00", "run_id": finished_run({"packaged": 3, "qualified": 5})})
    assert schedule.alert_finished_run()
    assert sent == [("JobPortal found new jobs", "3 new applications ready to send. Open JobPortal to see them.")]
    assert not schedule.alert_finished_run() and len(sent) == 1  # once per search


def test_no_alert_while_a_window_shows_it_or_alerts_are_off(monkeypatch):
    from jobportal.core import bus
    sent = []
    monkeypatch.setattr(osutil, "notify", lambda title, body="", icon=None: sent.append(title) or True)
    db.kv_set("schedule.last", {"slot": "x", "run_id": finished_run({"qualified": 2})})
    assert not schedule.alert_finished_run()  # alerts are off
    alerts_on()
    db.kv_set("schedule.last", {"slot": "y", "run_id": finished_run({"qualified": 2})})
    queue = bus.subscribe()  # a dashboard is open, and it shows the result itself
    try:
        assert not schedule.alert_finished_run()
    finally:
        bus.unsubscribe(queue)
    db.kv_set("schedule.last", {"slot": "z", "run_id": finished_run({"qualified": 0, "packaged": 0})})
    assert not schedule.alert_finished_run()  # found nothing new
    db.kv_set("schedule.last", {"slot": "w", "run_id": finished_run({}, status="running")})
    assert not schedule.alert_finished_run()  # still searching
    assert sent == []


# ---------------------------------------------------------------- the login item and the background server

def test_turning_the_schedule_on_notes_the_time_and_adds_the_login_item(login_items):
    before = settings.get()
    turn_on()
    schedule.settings_saved(before, settings.get())
    assert db.kv_get("schedule.enabled_at")
    command = login_items[-1]
    assert command[-4:-2] == ["--background", "--scheduled"]
    assert command[command.index("--data-dir") + 1] == os.environ["JOBPORTAL_HOME"]
    before = settings.get()
    turn_on(background=False)  # searching only while the window is open
    schedule.settings_saved(before, settings.get())
    assert login_items[-1] is None


def test_only_the_data_folder_that_added_the_login_item_removes_it(login_items):
    schedule.sync_login_item()  # the schedule is off, and this data folder never added a login item
    assert login_items == []  # so another copy's login item is left alone
    turn_on()
    schedule.sync_login_item()
    cfg = settings.get()
    cfg["schedule"]["enabled"] = False
    settings.save(cfg)
    schedule.sync_login_item()
    assert login_items[-1] is None and db.kv_get("schedule.login_item") is False


def test_the_login_item_on_this_system(tmp_path, monkeypatch):
    """The real login item for this system: added, found and removed, under a name and home folder of the test's own, so
    the user's own login items are never touched."""
    set_item, has_item = REAL_LOGIN_ITEM
    monkeypatch.setattr(osutil, "LOGIN_ITEM_NAME", f"JobPortalTest{os.getpid()}")
    monkeypatch.setattr(osutil, "_home", lambda: tmp_path)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    command = [str(tmp_path / "Job Portal" / "app"), "--background", "--scheduled"]
    try:
        assert set_item(command) and has_item()
        if osutil.IS_MAC:
            agent = plistlib.loads(osutil.login_item_path().read_bytes())
            assert agent["ProgramArguments"] == command and agent["RunAtLoad"] and agent["AbandonProcessGroup"]
        elif not osutil.IS_WIN:
            entry = osutil.login_item_path().read_text(encoding="utf-8")
            assert f'Exec="{command[0]}" "--background" "--scheduled"' in entry and "NoDisplay=true" in entry
    finally:
        assert set_item(None)
    assert not has_item()
    assert set_item(None)  # removing one that isn't there is fine


def test_a_scheduled_background_server_is_marked(monkeypatch):
    from jobportal.app import desktop
    seen = {}
    answers = iter([False, True])  # nothing answers yet, then the new server does
    monkeypatch.setattr(desktop, "up", lambda: next(answers))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd, env=kw["env"]))
    assert cli.background(scheduled=True) == 0
    assert seen["env"]["JOBPORTAL_SCHEDULED"] == "1" and seen["cmd"][-3:] == ["--server", "--port", "8788"]
    assert cli.build_parser().parse_args(["--background", "--scheduled"]).scheduled


class FakeServer:
    should_exit = False


class FakeThread:
    def join(self, timeout=None):
        pass


def test_closing_the_window_hands_the_schedule_to_a_background_server(monkeypatch):
    from jobportal.app import desktop
    handed = []
    monkeypatch.setattr(desktop, "start_background_server", lambda: handed.append(True) or True)
    desktop.finish(FakeServer(), FakeThread())
    assert handed == []  # the schedule is off, so closing the window quits
    turn_on()
    server = FakeServer()
    desktop.finish(server, FakeThread())
    assert server.should_exit and handed == [True]
    desktop.finish(None, None)  # attached to another process's server: nothing to hand over
    assert handed == [True]


def test_a_schedule_server_quits_once_nothing_needs_it(monkeypatch):
    monkeypatch.setenv(schedule.SCHEDULED_ENV, "1")
    monkeypatch.setattr(schedule, "CHECK_SECONDS", 0.01)
    monkeypatch.setattr(schedule, "IDLE_QUIT_SECONDS", 0)
    stopped = []
    asyncio.run(asyncio.wait_for(schedule.runner(lambda: stopped.append(True)), 5))
    assert stopped == [True]


def test_a_schedule_server_keeps_running_while_the_schedule_needs_it(monkeypatch):
    monkeypatch.setenv(schedule.SCHEDULED_ENV, "1")
    monkeypatch.setattr(schedule, "CHECK_SECONDS", 0.01)
    monkeypatch.setattr(schedule, "IDLE_QUIT_SECONDS", 0)
    turn_on(times=[])  # on, in the background, but with nothing to start
    stopped = []
    with pytest.raises(TimeoutError):
        asyncio.run(asyncio.wait_for(schedule.runner(lambda: stopped.append(True)), 0.3))
    assert stopped == []


# ---------------------------------------------------------------- settings and routes

def test_every_n_hours_becomes_scheduled_times():
    db.kv_set("settings", {"run": {"auto_run_hours": 8, "min_score": 70}})
    assert "schedule every 8 hours" in settings.migrate_defaults()
    cfg = settings.get()
    assert cfg["schedule"]["enabled"] and cfg["schedule"]["times"] == ["00:00", "08:00", "16:00"]
    assert "auto_run_hours" not in cfg["run"] and cfg["run"]["min_score"] == 70
    db.kv_set("settings", {"run": {"auto_run_hours": 0}})
    settings.migrate_defaults()
    assert not settings.get()["schedule"]["enabled"] and "auto_run_hours" not in settings.get()["run"]


def test_schedule_routes_and_a_test_alert(monkeypatch, login_items):
    from jobportal.web.server import app
    sent = []
    monkeypatch.setattr(osutil, "notify", lambda title, body="", icon=None: sent.append(title) or True)
    with TestClient(app) as client:
        cfg = client.get("/api/settings").json()
        assert cfg["schedule"]["enabled"] is False and cfg["alerts"] == {"desktop": False}  # off until the user turns it on
        assert client.get("/api/schedule").json()["next"] is None
        cfg["schedule"].update(enabled=True, times=["07:30"])
        assert client.put("/api/settings", json=cfg).status_code == 200
        status = client.get("/api/schedule").json()
        assert status["enabled"] and "T07:30" in status["next"]
        assert status["login_item"] and "--scheduled" in login_items[-1]
        assert client.post("/api/alerts/test").json() == {"ok": True}
    assert sent == ["JobPortal test alert"]
