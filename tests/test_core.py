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


def test_keywords_for_any_field():
    # Whole words only: "c" isn't found inside "c++", and "go" isn't found inside "google".
    tech = textutil.extract_terms("We use Python and C++ at Google, with some Go. C is a plus.")
    assert {"Python", "C++", "Go", "C"} <= set(tech)
    # Tech words that are everyday words don't count in a posting that isn't about tech.
    assert textutil.extract_terms("Go the extra mile, rest assured, and test the web forms.") == []
    # Credentials and licenses come first, then every field's vocabulary, then what the requirement lines ask for.
    nursing = textutil.extract_terms("CNA certification and BLS required. Experience with patient care and vital signs.")
    assert nursing[:2] == ["CNA", "BLS"] and {"patient care", "vital signs"} <= set(nursing)
    trucking = textutil.extract_terms("Valid Class A CDL and OSHA 10. Ability to operate a forklift and pallet jack.")
    assert {"CDL Class A", "OSHA 10", "forklift", "pallet jack"} <= set(trucking) and "CDL" not in trucking  # no repeats
    kitchen = textutil.extract_terms("ServSafe required. Experience with point of sale systems and cash handling.")
    assert {"ServSafe", "POS systems", "cash handling"} <= set(kitchen)
    assert "Pharmacy Technician Certification" in textutil.extract_terms("Must hold a Pharmacy Technician Certification.")
    office = textutil.extract_terms("Proficient in Microsoft Excel and QuickBooks. You will excel in a fast-paced environment.")
    assert office[:2] == ["Microsoft Excel", "QuickBooks"] and not any("environment" in term for term in office)


def test_target_roles_match_leniently():
    nurse = textutil.TargetMatcher(["Registered Nurse", "new grad RN Columbus OH"], places=["Columbus, OH"])
    assert nurse.matches("RN - Med Surg") and nurse.matches("Nursing Assistant") and nurse.matches("Charge Nurse")
    assert not nurse.matches("Software Engineer") and not nurse.matches("Columbus Store Manager")  # places never count
    assert nurse.matches("Clinician II", "Join our RN team providing nursing care.")  # two target words in the description
    tech = textutil.TargetMatcher(["Software Engineer"])
    assert tech.matches("Backend Developer") and not tech.matches("Cashier")
    trades = textutil.TargetMatcher(["Apprentice Electrician"])
    assert trades.matches("Journeyman Electrician") and trades.matches("Electrical Helper") and not trades.matches("Election Clerk")
    assert textutil.TargetMatcher(["Assistant Manager"]).matches("Assistant Store Manager")  # only generic words: they count
    it_support = textutil.TargetMatcher(["IT Support Specialist"])
    assert it_support.matches("IT Help Desk Technician")  # "IT" counts in a title...
    assert not it_support.matches("Line Cook", "It is a busy kitchen. It pays $18 per hr and it has a network of cafes.")  # ...not here
    assert not textutil.TargetMatcher([]) and textutil.TargetMatcher([]).matches("Anything")  # no targets: everything passes


def test_keywords_and_coverage():
    resume = "Wrote Python services on GCP with Kubernetes. Added unit tests."
    share, hit, miss = textutil.coverage(["Python", "AWS / GCP", "Kubernetes (K8s)", "unit testing", "Rust"], resume)
    assert share == 0.8 and miss == ["Rust"] and "unit testing" in hit  # "tests" counts for "testing"
    assert textutil.coverage([], resume) == (0.0, [], [])


def test_genres_and_industries():
    assert genres.classify("Site Reliability Engineer") == ["cloud_devops"]
    assert genres.classify("Registered Nurse") == ["nursing"] and genres.classify("Electrician Apprentice") == ["skilled_trades"]
    assert genres.classify("Barista") == ["food_hospitality"] and genres.classify("Paralegal") == ["legal"]
    assert genres.classify("Lorem ipsum") == []
    assert genres.classify("Data Engineer", genres=[{"id": "x", "label": "X", "keywords": "data(("}]) == []  # a bad regex doesn't raise
    assert {genres.group_of(g) for g in genres.DEFAULT_GENRES} == set(genres.GROUPS)  # every field group has genres
    assert genres.classify_industry("Example Aerospace", "Software Intern") == "Aerospace & Defense"
    assert genres.classify_industry("Example Bank", "Data Analyst") == "Finance & Insurance"
    assert genres.classify_industry("Riverside Hospital", "Registered Nurse") == "Healthcare & Biotech"
    assert genres.classify_industry("Example Co", "Line Cook", "Our restaurant serves brunch.") == "Restaurants & Food Service"
    # Benefits boilerplate, and big employers' names that are also ordinary words, don't decide the industry.
    assert genres.classify_industry("Example Co", "Analyst", "Health insurance, medical and dental. Meet your targets.") == "Other"
    assert genres.classify_industry("Example Co", "Barista", industries=["Technology & Software", "Other"]) == "Other"
    assert set(genres.OLD_INDUSTRIES.values()) <= set(genres.DEFAULT_INDUSTRIES)  # every old name has a home


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
    assert (github["industry"], linkedin["industry"]) == ("Aerospace & Defense", "Finance & Insurance")
    assert github["dream_manual"] is None and github["tokens"] == 0
    upgraded = {t: columns(t) for t in ("leads", "runs", "ai_calls", "candidates")}

    db.close()  # a brand-new database ends up with exactly the same columns
    config.DB_PATH.unlink()
    assert {t: columns(t) for t in upgraded} == upgraded
    db.close()
    db.conn()  # opening again changes nothing and doesn't fail


def test_old_industry_names_are_renamed():
    lead_id = db.ex("INSERT INTO leads(fingerprint, title, company, industry) VALUES('fp', 'Analyst', 'Example Co', 'Fintech & Finance')")
    db.close()  # reopening runs the migration
    assert db.one("SELECT industry FROM leads WHERE id=?", (lead_id,))["industry"] == "Finance & Insurance"


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


def test_new_default_boards_are_offered_once(monkeypatch):
    # No company boards ship by default (each person adds their own), so pretend a later version added two.
    defaults = [{"name": "Example Health", "ats": "greenhouse", "slug": "examplehealth"},
                {"name": "Example Builders", "ats": "lever", "slug": "example-builders"}]
    monkeypatch.setitem(config.DEFAULT_SETTINGS["sources"]["ats_boards"], "boards", defaults)
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


def test_tech_only_defaults_from_older_versions_are_retired():
    from jobportal.core.genres import LEGACY_INDUSTRIES
    old_genres = [{"id": "swe", "label": "Software Engineering", "keywords": "software"}, {"id": "cyber", "label": "Cybersecurity"}]
    db.kv_set("settings", {"analysis": {"genres": old_genres}, "industries": LEGACY_INDUSTRIES,
                           "filters": {"require_tech_title": False, "tech_title": ["software"], "exclude_companies": ["Example Staffing"]},
                           "sources": {"reddit": {"enabled": True, "subreddits": ["forhire", "jobbit", "hiring", "cscareerquestions",
                                                                                "internships", "EngineeringStudents", "remotejs", "techjobs"]},
                                       "mastodon": {"enabled": True, "instances": ["mastodon.social", "example.social"]}}})
    assert "genres for every field" in settings.migrate_defaults()
    cfg = settings.get()
    assert cfg["analysis"]["genres"] == config.DEFAULT_SETTINGS["analysis"]["genres"]
    assert cfg["industries"] == config.DEFAULT_SETTINGS["industries"]
    assert cfg["filters"]["require_target_match"] is False and "tech_title" not in cfg["filters"]  # the user had it off
    assert cfg["filters"]["exclude_companies"] == ["Example Staffing"]  # their own choices stay
    assert cfg["sources"]["reddit"]["subreddits"] == config.DEFAULT_SETTINGS["sources"]["reddit"]["subreddits"]
    assert cfg["sources"]["mastodon"]["instances"] == ["mastodon.social", "example.social"]  # edited, so kept
    assert settings.migrate_defaults() == []  # nothing left to change
    db.kv_set("settings", {"industries": ["Fintech & Finance", "Education", "Finance & Insurance"]})  # a list the user edited
    settings.migrate_defaults()
    assert settings.get()["industries"] == ["Finance & Insurance", "Education"]


def test_untouched_built_in_missions_get_the_new_wording(monkeypatch):
    import hashlib

    from jobportal.ai.prompts import DEFAULT_MISSIONS
    current = {m["id"]: m for m in DEFAULT_MISSIONS}
    old_prompt = "Find openings, especially at tech startups."  # stands in for a built-in prompt from an older version
    monkeypatch.setitem(settings._LEGACY_MISSION_PROMPTS, "research", hashlib.sha1(old_prompt.encode()).hexdigest()[:16])
    monkeypatch.setitem(settings._LEGACY_MISSION_PROMPTS, "social", hashlib.sha1(old_prompt.encode()).hexdigest()[:16])
    db.kv_set("settings", {"sources": {"ai_hunt": {"missions": [
        {"id": "research", "name": "My labs", "enabled": False, "prompt": old_prompt},
        {"id": "social", "name": "Social", "prompt": "My own social search."}]}}})
    assert "1 built-in AI missions reworded for every field" in settings.migrate_defaults()
    missions = {m["id"]: m for m in settings.get()["sources"]["ai_hunt"]["missions"]}
    assert missions["research"]["prompt"] == current["research"]["prompt"]
    assert missions["research"]["only_groups"] == current["research"]["only_groups"]
    assert (missions["research"]["name"], missions["research"]["enabled"]) == ("My labs", False)  # the user's choices stay
    assert missions["social"]["prompt"] == "My own social search."  # an edited mission stays as the user wrote it
    assert "apprenticeships" in missions  # the new built-in mission is offered too
    assert settings.migrate_defaults() == []


def test_the_legacy_mission_hashes_match_the_old_prompts():
    """The hashes in settings._LEGACY_MISSION_PROMPTS must be those of the prompts v0.2.0 shipped, or no saved mission
    would ever get the new wording. Checked against git history when this is a full source checkout."""
    import ast
    import hashlib
    import subprocess

    import pytest
    try:
        old_source = subprocess.run(["git", "show", "1c4efe2:jobportal/ai/prompts.py"], capture_output=True, text=True,
                                    check=True, cwd=Path(__file__).parent).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("this checkout has no git history to compare with")
    node = next(n for n in ast.parse(old_source).body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "DEFAULT_MISSIONS")
    old = {m["id"]: hashlib.sha1(m["prompt"].encode()).hexdigest()[:16] for m in ast.literal_eval(node.value)}
    assert old == settings._LEGACY_MISSION_PROMPTS


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
