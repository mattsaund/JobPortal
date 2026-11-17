"""Performance benchmarks: each test times one heavy, everyday job and fails when it takes longer than its limit.

The limits are the minimum acceptable performance, set well above what a normal laptop needs (see LIMITS), so a slower CI
machine still passes while a real slowdown (an accidental query per row, a regex compiled in a loop) fails the build. The
data is fictional and made up in bulk, at the size a heavy user reaches: a few thousand postings per search and 2,000
saved leads.

With JOBPORTAL_BENCHMARK_REPORT set to a file path, the module writes a Markdown table of every timing and its limit
there. CI adds that table to the run's summary page, so each run shows the numbers."""
import json
import os
import time

import pytest
from conftest import STANDARD_ANSWERS
from fastapi.testclient import TestClient

from jobportal.core import db, settings, textutil
from jobportal.insights import analysis
from jobportal.search.collectors.base import RawJob
from jobportal.search.pipeline import RuleFilters

# Seconds each benchmark may take at most.
LIMITS = {
    "rule filters, 5,000 postings": 5.0,
    "location matching, 20,000 places": 2.0,
    "keyword extraction, 300 postings": 3.0,
    "Leads page, 2,000 saved leads": 2.0,
    "Tracker board, 2,000 saved leads": 2.0,
    "Analysis numbers, 2,000 leads and 3,000 waiting postings": 5.0,
}
RESULTS: list[tuple[str, float]] = []

TITLES = ["Registered Nurse", "Line Cook", "Software Engineer", "Electrician Apprentice", "Elementary School Teacher",
          "Accounting Clerk", "Graphic Designer", "Warehouse Associate", "Medical Assistant", "Customer Service Representative"]
PLACES = ["Columbus, OH", "Cleveland, Ohio", "Pittsburgh, PA", "Austin, TX", "Remote", "Remote (US)", "Dayton, OH | Remote",
          "Kansas City, Missouri", "New York, NY", "Hybrid in Cincinnati, OH"]
POSTING = ("We are hiring a {title} to join our team. Requirements: two years of experience, strong communication, "
           "Microsoft Excel, customer service and scheduling. Preferred: CPR certification, a valid driver's license, "
           "bilingual Spanish, ServSafe, OSHA 10 or a CompTIA A+ certification. You will work with Python, SQL and "
           "Salesforce reports, manage inventory, and train new staff. ") * 6


def timed(name: str, work):
    """Run work() once, record how long it took, and fail when it's over its limit."""
    start = time.perf_counter()
    result = work()
    seconds = time.perf_counter() - start
    RESULTS.append((name, seconds))
    assert seconds <= LIMITS[name], f"{name} took {seconds:.2f}s; the limit is {LIMITS[name]}s"
    return result


@pytest.fixture(scope="module", autouse=True)
def report():
    """After the last benchmark, write the timings to JOBPORTAL_BENCHMARK_REPORT when it's set."""
    yield
    path = os.environ.get("JOBPORTAL_BENCHMARK_REPORT")
    if not path or not RESULTS:
        return
    lines = ["| Benchmark | Time | Limit |", "|---|---|---|"]
    lines += [f"| {name} | {seconds * 1000:.0f} ms | {LIMITS[name]:.0f} s |" for name, seconds in RESULTS]
    with open(path, "w", encoding="utf-8") as f:
        f.write("### Performance benchmarks\n\n" + "\n".join(lines) + "\n")


def seed_leads(count: int) -> None:
    """Save `count` fictional leads in one transaction, spread over every stage and Tracker column."""
    stages = ["ready", "qualified", "filtered", "ready", "closed"]
    statuses = ["new", "ready", "applied", "interviewing", "accepted", "rejected", "new", "new"]
    now = db.now()
    rows = []
    for i in range(count):
        title = TITLES[i % len(TITLES)]
        triage = {"summary": "A close match.", "reasons": ["Relevant experience"], "red_flags": [], "genres": [], "industry": "Other"}
        package = {"coverage": {"hit": ["communication", "Excel"], "miss": ["CPR", "scheduling"][: i % 3]}}
        rows.append((f"bench-{i}", title, f"Example Employer {i % 150}", PLACES[i % len(PLACES)], "linkedin", 40 + i % 60,
                     stages[i % len(stages)], statuses[i % len(statuses)], "Healthcare" if i % 2 else "Education",
                     json.dumps(triage), json.dumps(package), POSTING.format(title=title)[:600], now, now))
    db.ex_many("INSERT INTO leads(fingerprint, title, company, location, source, score, stage, app_status, industry, triage, "
               "package, description, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)


def test_rule_filters_on_a_big_search():
    cfg = settings.get()
    cfg["locations"]["allowed"] = ["Ohio", "Pittsburgh, PA", "Remote"]
    jobs = [RawJob("ats", TITLES[i % len(TITLES)], f"Example Employer {i % 300}", f"https://jobs.example.com/{i}",
                   location=PLACES[i % len(PLACES)], description=POSTING.format(title=TITLES[i % len(TITLES)])[:1500])
            for i in range(5000)]
    filters = RuleFilters(cfg)
    results = timed("rule filters, 5,000 postings", lambda: [filters.check(job) for job in jobs])
    assert any(passed for passed, _, _ in results) and not all(passed for passed, _, _ in results)


def test_location_matching():
    places = [f"{PLACES[i % len(PLACES)]} {i % 7}" for i in range(20000)]
    states = timed("location matching, 20,000 places", lambda: [textutil.state_of(place) for place in places])
    assert "OH" in states


def test_keyword_extraction():
    postings = [POSTING.format(title=TITLES[i % len(TITLES)]) for i in range(300)]
    terms = timed("keyword extraction, 300 postings", lambda: [textutil.extract_terms(text) for text in postings])
    assert all(terms)


def test_leads_page_with_many_leads():
    from jobportal.web.server import app
    seed_leads(2000)
    with TestClient(app) as client:
        reply = timed("Leads page, 2,000 saved leads", lambda: client.get("/api/leads?tab=all&sort=score"))
    assert reply.status_code == 200 and len(reply.json()["leads"]) == 400  # one page of the list


def test_tracker_with_many_leads():
    from jobportal.web.server import app
    seed_leads(2000)
    with TestClient(app) as client:
        reply = timed("Tracker board, 2,000 saved leads", lambda: client.get("/api/tracker"))
    assert reply.status_code == 200 and reply.json()["columns"]["applied"]


def test_analysis_numbers_with_a_big_backlog():
    db.kv_set("profile.answers", {**STANDARD_ANSWERS, "target_roles": ["Registered Nurse", "Medical Assistant"]})
    seed_leads(2000)
    now = db.now()
    backlog = [(f"wait-{i}", json.dumps({"source": "linkedin", "title": TITLES[i % len(TITLES)], "company": "Example Employer",
                                         "url": f"https://jobs.example.com/w{i}", "kind": "posting"}), 10.0, now, now)
               for i in range(3000)]
    db.ex_many("INSERT INTO candidates(fingerprint, data, rule_score, first_seen, last_seen) VALUES(?,?,?,?,?)", backlog)
    numbers = timed("Analysis numbers, 2,000 leads and 3,000 waiting postings", lambda: analysis.get())
    assert numbers["roles"] and numbers["market"]["funnel"]
