"""Tests for jobportal/core: location matching, duplicate detection, dates, keywords, the database and its upgrades,
settings, live events and the PDF engine lookup. Every test starts from an empty data folder (see conftest.py)."""
import asyncio
import json
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobportal.core import bus, config, db, genres, osutil, settings, textutil
from jobportal.core.textutil import LocationMatcher

# ---------------------------------------------------------------- the search area

def test_states_and_cities():
    m = LocationMatcher(["Ohio", "Pittsburgh, PA", "  ", ""])
    assert m.states == {"OH"} and not m.anywhere_us and not m.allow_remote
    assert m.match("Columbus, OH") is True
    assert m.match("Cleveland, Ohio, United States") is True
    assert m.match("Pittsburgh") is True  # a chosen city, even without its state
    assert m.match("Remote, OH") is True  # remote words are ignored when reading the state
    assert m.match("Austin, TX") is False
    assert m.match("London, UK") is False
    assert m.match("Remote") is False  # Remote isn't allowed
    assert m.match("Multiple Locations") is None  # can't tell


def test_remote():
    m = LocationMatcher(["Remote"])
    assert m.match("Remote - US") is True
    assert m.match("Remote, USA or Canada") is True
    assert m.match("Remote (Canada)") is False
    assert m.match("Columbus, OH") is False
    assert m.match("TBD") is None


def test_anywhere_in_the_us():
    m = LocationMatcher(["Anywhere in the US"])
    assert m.anywhere_us and not m.allow_remote
    assert m.match("Austin, TX") is True
    assert m.match("United States") is True
    assert m.match("Toronto, ON") is False
    assert m.match("Remote") is False  # remote jobs need Remote as well
    assert LocationMatcher(["Anywhere in the US", "Remote"]).match("Remote") is True


def test_tricky_state_names():
    assert LocationMatcher(["Virginia"]).match("Charleston, West Virginia") is False
    assert LocationMatcher(["Virginia"]).match("Richmond, Virginia") is True
    assert LocationMatcher(["Washington"]).match("Seattle, WA") is True
    assert LocationMatcher(["Washington"]).match("Washington, DC") is False
    assert LocationMatcher(["DC"]).match("Washington, D.C.") is True


def test_jobs_with_several_locations():
    m = LocationMatcher(["Ohio"])
    assert m.match("Austin, TX / Columbus, OH") is True  # any one location is enough
    assert m.match(["Austin, TX", "Denver, CO"]) is False  # every location is outside
    assert m.match(["Austin, TX", "TBD"]) is None  # one unknown keeps it open
    assert m.match([]) is None


def test_state_of():
    assert textutil.state_of("Columbus, OH 43215") == "OH"
    assert textutil.state_of("USA - TX") == "TX"
    assert textutil.state_of("Charleston, West Virginia") == "WV"
    assert textutil.state_of("Washington, D.C.") == "DC"
    assert textutil.state_of("Seattle") == "WA"
    assert textutil.state_of("Remote, Canada") == "REMOTE"
    assert textutil.state_of("Toronto, ON") == "FOREIGN"
    assert textutil.state_of("Somewhere") is None
    assert textutil.state_of("") is None


# ---------------------------------------------------------------- duplicates, dates, text and keywords

def test_fingerprint_is_stable():
    # Existing databases hold fingerprints made this way. If this value changes, every known job comes back as new.
    assert textutil.fingerprint("Example Robotics, Inc.", "Software Engineer Intern", "Columbus, OH") == "68a4f2cd3c7f5803a722"
    assert textutil.fingerprint("EXAMPLE ROBOTICS", "Software Engineer - Intern", "Columbus, Ohio") == "68a4f2cd3c7f5803a722"


def test_url_key():
    assert textutil.url_key("https://www.linkedin.com/jobs/view/software-engineer-at-example-1234567890/?trk=abc") == "linkedin:1234567890"
    assert textutil.url_key("https://linkedin.com/jobs/view/1234567890") == "linkedin:1234567890"
    assert textutil.url_key("https://boards.greenhouse.io/example/jobs/4012345?gh_jid=4012345&utm_source=feed") == \
        "boards.greenhouse.io/example/jobs/4012345?gh_jid=4012345"
    assert textutil.url_key("https://WWW.Example.com/Careers/Job-42/?utm_campaign=x") == "example.com/careers/job-42"
    assert textutil.url_key("") is None and textutil.url_key("http://[::1") is None


def test_parse_date():
    def days_ago(n):
        return (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()

    assert textutil.parse_date(1700000000) == "2023-11-14"
    assert textutil.parse_date("1700000000000") == "2023-11-14"  # milliseconds
    assert textutil.parse_date("2026-10-01T12:00:00Z") == "2026-10-01"
    assert textutil.parse_date("Thu, 01 Oct 2026 10:00:00 GMT") == "2026-10-01"
    assert textutil.parse_date("October 1, 2026") == textutil.parse_date("10/01/2026") == "2026-10-01"
    assert textutil.parse_date("Posted 3 Days Ago") in (days_ago(3), days_ago(2))  # the date may roll over mid-test
    assert textutil.parse_date("2 weeks ago") in (days_ago(14), days_ago(13))
    assert textutil.parse_date("garbage") is None and textutil.parse_date(None) is None and textutil.parse_date(0) is None


def test_html_to_text():
    twice_escaped = "&lt;p&gt;Hello&amp;nbsp;there&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;li&gt;SQL&lt;/li&gt;&lt;/ul&gt;"
    assert textutil.html_to_text(twice_escaped) == "Hello there\n\n• Python\n• SQL"
    assert textutil.html_to_text("<script>x=1</script><p>Line" + chr(0xA0) + "one<br>two" + chr(0x200B) + "</p>") == "Line one\ntwo"
    assert textutil.html_to_text(None) == ""


def test_keywords_and_coverage():
    assert textutil.extract_terms("We use C++ and Go at Google. C is a plus.") == ["c", "c++", "go"]
    resume = "Wrote Python services on GCP with Kubernetes. Added unit tests."
    share, hit, miss = textutil.coverage(["Python", "AWS / GCP", "Kubernetes (K8s)", "unit testing", "Rust"], resume)
    assert share == 0.8 and miss == ["Rust"] and "unit testing" in hit  # "tests" counts for "testing"
    assert textutil.coverage([], resume) == (0.0, [], [])


def test_genres_and_industries():
    assert genres.classify("Site Reliability Engineer") == ["cloud_devops"]
    assert genres.classify("Barista") == []
    assert genres.classify("Data Engineer", genres=[{"id": "x", "label": "X", "keywords": "data(("}]) == []  # a bad regex doesn't raise
    assert genres.classify_industry("Example Aerospace", "Software Intern") == "Space & Aerospace"
    assert genres.classify_industry("Example Bank", "Data Analyst") == "Fintech & Finance"
    assert genres.classify_industry("Example Co", "Barista", industries=["Cybersecurity", "Other"]) == "Other"


# ---------------------------------------------------------------- the database

# The tables as the first development versions created them: no tokens, found, dream_manual or industry columns.
OLD_SCHEMA = """
CREATE TABLE leads (id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, url_key TEXT, url TEXT, apply_url TEXT, title TEXT,
  company TEXT, location TEXT, kind TEXT DEFAULT 'posting', category TEXT, source TEXT, sources TEXT DEFAULT '[]',
  source_detail TEXT, posted_at TEXT, deadline TEXT, description TEXT, score INTEGER, verdict TEXT, triage TEXT DEFAULT '{}',
  stage TEXT DEFAULT 'discovered', stage_error TEXT, app_status TEXT DEFAULT 'new', package TEXT DEFAULT '{}', resume_md TEXT,
  cover_md TEXT, ats_coverage REAL, follow_up_at TEXT, applied_at TEXT, notes TEXT DEFAULT '', dream INTEGER DEFAULT 0,
  cost_usd REAL DEFAULT 0, run_id INTEGER, created_at TEXT, updated_at TEXT);
CREATE TABLE runs (id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, mode TEXT, status TEXT, stats TEXT DEFAULT '{}',
  cost_usd REAL DEFAULT 0);
CREATE TABLE ai_calls (id INTEGER PRIMARY KEY, ts TEXT, run_id INTEGER, lead_id INTEGER, purpose TEXT, model TEXT, effort TEXT,
  cost_usd REAL, duration_ms INTEGER, ok INTEGER, error TEXT);
"""


def columns(table: str) -> set[str]:
    return {r["name"] for r in db.q(f"PRAGMA table_info({table})")}


def test_old_databases_are_upgraded():
    old = sqlite3.connect(config.DB_PATH)
    old.executescript(OLD_SCHEMA)
    old.execute("INSERT INTO leads(fingerprint, url, title, company, source, source_detail, description) VALUES(?,?,?,?,?,?,?)",
                ("a", "https://example.com/apply/1", "Software Intern", "Example Aerospace", "github",
                 "GitHub SimplifyJobs/Summer2027-Internships, Software", "flight software"))
    old.execute("INSERT INTO leads(fingerprint, url, title, company, source, source_detail) VALUES(?,?,?,?,?,?)",
                ("b", "https://example.com/jobs/2", "Data Analyst", "Example Bank", "linkedin", "LinkedIn search"))
    old.commit()
    old.close()

    github, linkedin = [db.lead_row(r) for r in db.q("SELECT * FROM leads ORDER BY id")]
    assert github["found"] == [{"source": "github", "label": "GitHub SimplifyJobs/Summer2027-Internships, Software",
                                "url": "https://github.com/SimplifyJobs/Summer2027-Internships"}]
    assert linkedin["found"] == [{"source": "linkedin", "label": "LinkedIn search", "url": "https://example.com/jobs/2"}]
    assert (github["industry"], linkedin["industry"]) == ("Space & Aerospace", "Fintech & Finance")
    assert github["dream_manual"] is None and github["tokens"] == 0
    upgraded = {t: columns(t) for t in ("leads", "runs", "ai_calls", "candidates")}

    db.close()  # a brand-new database ends up with exactly the same columns
    config.DB_PATH.unlink()
    assert {t: columns(t) for t in upgraded} == upgraded
    db.close()
    db.conn()  # opening again changes nothing and doesn't fail


def test_lead_helpers():
    lead_id = db.ex("INSERT INTO leads(fingerprint, title, company) VALUES('fp', 'Software Intern', 'Example Robotics')")
    db.update_lead(lead_id, package={"keywords": ["Python"]}, found=[{"source": "manual"}], notes="Applied online")
    row = db.lead_row(db.one("SELECT * FROM leads WHERE id=?", (lead_id,)))
    assert row["package"] == {"keywords": ["Python"]} and row["found"] == [{"source": "manual"}] and row["updated_at"]
    damaged = db.lead_row({"sources": "{oops", "found": "[oops", "triage": "oops", "package": "oops"})
    assert damaged == {"sources": [], "found": [], "triage": {}, "package": {}}  # list columns stay lists
    assert db.kv_get("missing", "fallback") == "fallback"


# ---------------------------------------------------------------- settings

def test_settings_merge_over_defaults():
    fresh = settings.get()
    assert fresh["run"] == config.DEFAULT_SETTINGS["run"] and fresh["sources"]["ai_hunt"]["missions"]  # missions filled in
    settings.save({"run": {"min_score": 70}, "filters": {"exclude_companies": ["Example Staffing"]}})
    cfg = settings.get()
    assert cfg["run"]["min_score"] == 70 and cfg["run"]["max_triage"] == config.DEFAULT_SETTINGS["run"]["max_triage"]
    assert cfg["filters"]["exclude_companies"] == ["Example Staffing"]  # a saved list replaces the default list
    assert settings.reset_section("run")["run"]["min_score"] == config.DEFAULT_SETTINGS["run"]["min_score"]
    assert settings.resume_playbook({"resume_playbook": "  My rules  "}) == "My rules"
    assert settings.resume_playbook({"resume_playbook": ""}) == settings.default_playbook()


def test_new_default_boards_are_offered_once():
    defaults = config.DEFAULT_SETTINGS["sources"]["ats_boards"]["boards"]
    assert settings.migrate_defaults() == []  # nothing saved yet, so the defaults already apply
    cfg = settings.get()
    cfg["sources"]["ats_boards"]["boards"] = [dict(defaults[0]), {"name": "Example Robotics", "ats": "lever", "slug": "example-robotics"}]
    settings.save(cfg)
    added = settings.migrate_defaults()
    boards = settings.get()["sources"]["ats_boards"]["boards"]
    assert len(added) == len(defaults) - 1 and len(boards) == len(defaults) + 1
    cfg = settings.get()
    cfg["sources"]["ats_boards"]["boards"] = [b for b in boards if b["name"] != defaults[1]["name"]]  # the user deletes one
    settings.save(cfg)
    assert settings.migrate_defaults() == []
    assert defaults[1]["name"] not in {b["name"] for b in settings.get()["sources"]["ats_boards"]["boards"]}


# ---------------------------------------------------------------- live events

def test_publish_from_another_thread_reaches_the_dashboard():
    def worker():  # like a FastAPI worker thread running a plain `def` route
        time.sleep(0.3)  # long enough for the event loop to be asleep, waiting for the queue
        bus.publish("toast", {"title": "Saved"})

    async def dashboard():
        q = bus.subscribe()
        try:
            started = time.monotonic()
            threading.Thread(target=worker).start()
            message = await asyncio.wait_for(q.get(), timeout=5)
            return json.loads(message), time.monotonic() - started
        finally:
            bus.unsubscribe(q)

    message, waited = asyncio.run(dashboard())
    assert message == {"kind": "toast", "data": {"title": "Saved"}}
    assert waited < 2  # the loop was woken at once, not left asleep until its next timer (5 s here)


def test_state_and_full_queues(monkeypatch):
    monkeypatch.setitem(bus.state, "phase", "idle")  # put back after the test
    q = bus.subscribe()
    try:
        assert bus.listeners() == 1
        bus.set_state(phase="triaging")
        event = json.loads(q.get_nowait())
        assert event["kind"] == "state" and event["data"]["phase"] == "triaging" == bus.state["phase"]
        for _ in range(bus.MAX_QUEUED + 5):  # a dashboard that stopped reading misses events, and nothing raises
            bus.publish("log", {"msg": "line"})
        assert q.qsize() == bus.MAX_QUEUED
    finally:
        bus.unsubscribe(q)
        bus.unsubscribe(q)
    assert bus.listeners() == 0


# ---------------------------------------------------------------- operating system helpers

def test_a_missing_chrome_override_falls_back_to_the_bundled_engine(tmp_path, monkeypatch):
    engine = tmp_path / "pdf-engine" / ("chrome-headless-shell.exe" if osutil.IS_WIN else "chrome-headless-shell")
    engine.parent.mkdir()
    engine.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "JobPortal"))
    monkeypatch.setenv("JOBPORTAL_CHROME", str(tmp_path / "no-such-browser"))
    assert Path(osutil.find_pdf_engine()).resolve() == engine.resolve()


def test_quoting_for_notifications():
    assert osutil._ps_str("Jordan's offer") == "'Jordan''s offer'"
    assert osutil._applescript_str('Say "hi" \\ bye') == '"Say \\"hi\\" \\\\ bye"'


def test_location_edge_cases_that_used_to_drop_good_jobs():
    from jobportal.core.textutil import LocationMatcher, state_of
    nationwide = LocationMatcher(["Anywhere in the US"])
    assert nationwide.match_one("Hybrid Remote - Austin, TX") is True  # partly on-site in Texas
    assert nationwide.match_one("Remote (US)") is False  # fully remote still needs Remote allowed
    assert LocationMatcher(["Remote"]).match_one("Remote - U.S. & Canada") is True
    assert LocationMatcher(["Remote"]).match_one("Remote, Canada") is False
    assert state_of("Columbus, OH, on-site") == "OH" and LocationMatcher(["Ohio"]).match_one("Columbus, OH, on-site") is True
    assert state_of("Toronto, ON") == "FOREIGN"  # real province codes are still foreign
