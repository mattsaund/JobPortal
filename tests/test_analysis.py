"""The Analysis page (insights/analysis.py): the radar's role axes picked from the user's own data, the market numbers for
each role, the roles the user removes and adds, the AI assessment by role, and reading an assessment saved by the genre
version. Every person and employer here is made up."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from jobportal.candidate import profile
from jobportal.core import db, settings
from jobportal.insights import analysis
from jobportal.search import packages

NURSE_RECORD = """## Work Experience
### Example General Hospital - Registered Nurse
- Cared for 5 to 6 patients a shift on a medical-surgical unit
### Patient Care Technician, Example Community Clinic (2021 to 2023)
- Took vitals for 20+ patients a day
### Example Cafe - Barista
## Education
### Example State University - B.S. Nursing
## Licenses & Certifications
### Registered Nurse License - Ohio Board of Nursing"""

STEERING = {"emphasize": [], "deemphasize": [], "add_queries": [], "add_companies": [], "notes": ""}


@pytest.fixture
def client():
    from jobportal.web.server import app
    with TestClient(app) as c:
        yield c


def _nurse(targets=("Registered Nurse", "Charge Nurse")):
    """A fictional nurse: target roles in the standard answers, a search plan and a work history."""
    db.kv_set("profile.answers", {"target_roles": list(targets)})
    profile.save("search_plan", {"role_families": ["Nursing", "Hospice nursing"], "queries": ["new grad RN", "charge nurse jobs"],
                                 "dream_companies": [], "notes": ""})
    profile.save("project_bank", NURSE_RECORD)


def _lead(title, stage="qualified", score=85, status="new", kind="posting", missed=()):
    """Save a lead with this title. missed: keywords its tailored resume couldn't show."""
    n = db.one("SELECT COUNT(*) n FROM leads")["n"]
    package = {"coverage": {"hit": ["BLS"], "miss": list(missed)}} if missed else {}
    return packages.insert_lead({"fingerprint": f"test-{n}", "title": title, "company": "Example Health", "location": "Columbus, OH",
                                 "kind": kind, "source": "linkedin", "score": score, "stage": stage, "app_status": status,
                                 "package": json.dumps(package), "created_at": db.now(), "updated_at": db.now()})


def _backlog(title):
    """Put a posting in the triage backlog (postings that passed the filters and wait for AI scoring)."""
    n = db.one("SELECT COUNT(*) n FROM candidates")["n"]
    job = {"source": "linkedin", "title": title, "company": "Example Clinic", "url": f"https://jobs.example.com/{n}", "kind": "posting",
           "description": "A long posting. " * 50}
    db.ex("INSERT INTO candidates(fingerprint, data, rule_score, first_seen, last_seen) VALUES(?,?,?,?,?)",
          (f"backlog-{n}", json.dumps(job), 50, db.now(), db.now()))


def _ids(roles):
    return [r["id"] for r in roles]


def test_titles_that_name_the_same_role_are_one_role():
    same = ["RN", "Registered Nurse", "registered nurses", "New Grad RN", "R.N.", "Registered Nurse (RN)"]
    assert len({analysis.role_key(t) for t in same}) == 1
    assert {analysis.role_id(t) for t in ("RN", "New Grad RN", "Registered Nurse (RN)")} == {"registered-nurse"}
    assert analysis.role_key("Charge Nurse") != analysis.role_key("Registered Nurse")
    assert analysis.role_key("Software Engineering") == analysis.role_key("Senior Software Engineer II")
    assert analysis.role_key("Project Management") == analysis.role_key("Project Manager")
    assert analysis.role_key("IT Support Specialist") == analysis.role_key("IT Support")
    assert analysis.role_key("Physician") != analysis.role_key("Physical Therapist")
    assert analysis.role_id("C++ Developer") != analysis.role_id("C# Developer")
    assert analysis.role_key("Intern") == frozenset() == analysis.role_key("Part time")  # levels and job types aren't roles
    # Titles found in postings, the plan or the AI are cut down to the role itself.
    assert analysis.clean_title("Charge Nurse, Night Shift") == "Charge Nurse"
    assert analysis.clean_title("new grad RN") == "Registered Nurse"
    assert analysis.clean_title("Software Engineer II (Backend)") == "Software Engineer"
    assert analysis.clean_title("it support specialist") == "IT Support Specialist"
    assert analysis.clean_title("Hospice nursing") == "Hospice Nursing"
    assert analysis.clean_title("Med-Surg RN") == "Med-Surg RN"
    # The user's own words are only tidied.
    assert analysis.clean_title("RN", own=True) == "RN"
    assert analysis.clean_title("registered  nurse", own=True) == "Registered Nurse"


def test_job_titles_come_from_the_work_history():
    assert analysis.experience_titles(NURSE_RECORD) == ["Registered Nurse", "Patient Care Technician", "Barista"]
    record = """## Experience
### **Example Bistro**, Line Cook, Columbus, OH || Jun 2022 - Present
### Smith & Baker - Paralegal
### Example Builders LLC - Carpenter, Denver, CO
### Example Builders LLC - Intern
## Projects
### Example Garden - Volunteer Coordinator"""
    assert analysis.experience_titles(record) == ["Line Cook", "Paralegal", "Carpenter"]


def test_roles_come_from_the_users_own_data():
    _nurse(targets=("Registered Nurse", "RN", "Charge Nurse"))
    _lead("Clinic Nurse")
    _lead("School Nurse")
    _lead("Registered Nurse, Med-Surg")
    _lead("Line Cook", stage="filtered", score=12)  # one stray posting never becomes a role
    roles = analysis.pick_roles()["roles"]
    by_id = {r["id"]: r for r in roles}
    assert _ids(roles) == ["registered-nurse", "charge-nurse", "hospice-nursing", "patient-care-technician", "clinic-nurse",
                           "school-nurse"]  # the targets first, then the plan, the work history and the leads
    # RN and Registered Nurse are one role, and so are the plan's "Nursing", the query "new grad RN", the record's job and
    # the Med-Surg lead.
    assert by_id["registered-nurse"]["sources"] == ["target", "plan", "experience", "market"]
    assert by_id["charge-nurse"]["sources"] == ["target", "plan"]  # the query "charge nurse jobs"
    assert by_id["hospice-nursing"]["label"] == "Hospice Nursing" and by_id["patient-care-technician"]["source"] == "experience"
    assert analysis.ROLES_MIN <= len(roles) <= analysis.ROLES_MAX and not any(r["pinned"] for r in roles)


def test_many_target_roles_leave_room_for_other_sources():
    targets = ["Line Cook", "Prep Cook", "Sous Chef", "Pastry Cook", "Baker", "Catering Cook", "Banquet Cook", "Barista"]
    db.kv_set("profile.answers", {"target_roles": targets})
    profile.save("project_bank", "## Work Experience\n### Example Diner - Dishwasher")
    _lead("Kitchen Manager")
    picked = analysis.pick_roles()
    sources = [r["source"] for r in picked["roles"]]
    assert len(sources) == analysis.ROLES_MAX and sources.count("target") == analysis.ROLES_MAX - analysis.OTHER_SEATS
    assert sources[-2:] == ["experience", "market"] and picked["more"] == ["Banquet Cook", "Barista"]


def test_market_numbers_for_each_role(client):
    _nurse()
    _lead("Registered Nurse, Med-Surg", score=90, missed=["Telemetry"])
    _lead("RN - ICU", score=80, missed=["Telemetry", "ACLS"])
    _lead("Charge Nurse", stage="filtered", score=40)
    _lead("Nursing career fair", kind="event")  # an event isn't a posting
    _backlog("Registered Nurse (Nights)")
    _backlog("Hospice RN")
    d = client.get("/api/analysis").json()
    roles = {r["id"]: r for r in d["roles"]}
    rn = roles["registered-nurse"]
    assert (rn["demand_count"], rn["qualified"], rn["avg_score"], rn["demand_index"]) == (4, 2, 85, 100)
    assert rn["demand_share"] == 0.8 and rn["top_missing"] == ["Telemetry", "ACLS"]
    assert (roles["charge-nurse"]["demand_count"], roles["charge-nurse"]["qualified"], roles["charge-nurse"]["demand_index"]) == (1, 0, 25)
    assert roles["hospice-nursing"]["demand_count"] == 1  # "Hospice RN" in the backlog
    assert d["market"]["demand_total"] == 5 and d["market"]["demand_source"] == "3 leads and 2 postings waiting to be scored"
    # The parts of the page that aren't per role still work.
    assert d["market"]["sources"][0]["source"] == "linkedin" and d["market"]["funnel"][2]["n"] == 4
    assert d["market"]["gaps"][0] == {"skill": "Telemetry", "missing_in": 2, "requested_in": 2}


def test_the_user_removes_and_adds_roles(client):
    _nurse()
    removed = client.post("/api/analysis/roles/remove", json={"id": "charge-nurse"}).json()
    assert "charge-nurse" not in _ids(removed["roles"])
    assert removed["removed_roles"] == [{"id": "charge-nurse", "label": "Charge Nurse", "source": "target"}]
    assert settings.get()["analysis"]["hidden_roles"] == ["Charge Nurse"]
    _lead("Charge Nurse, Nights")  # a search finds the title again: it stays off the chart
    assert "charge-nurse" not in _ids(client.get("/api/analysis").json()["roles"])
    back = client.post("/api/analysis/roles/restore", json={"id": "charge-nurse"}).json()
    assert "charge-nurse" in _ids(back["roles"]) and back["removed_roles"] == []

    added = client.post("/api/analysis/roles/add", json={"title": "nurse educator"}).json()
    educator = next(r for r in added["roles"] if r["id"] == "nurse-educator")
    assert (educator["label"], educator["source"], educator["pinned"]) == ("Nurse Educator", "added", True)
    assert settings.get()["analysis"]["pinned_roles"] == ["Nurse Educator"]
    for bad in ("", "   ", "Intern", "x" * 81):
        r = client.post("/api/analysis/roles/add", json={"title": bad})
        assert r.status_code == 400 and r.json()["detail"]
    for title in ("Clinic Nurse", "School Nurse", "Hospice Nurse", "Travel Nurse", "Nurse Manager", "Case Manager", "Flight Nurse"):
        assert client.post("/api/analysis/roles/add", json={"title": title}).status_code == 200
    full = client.post("/api/analysis/roles/add", json={"title": "Clinical Research Nurse"})
    assert full.status_code == 400 and "up to 8" in full.json()["detail"]
    assert len(client.get("/api/analysis").json()["roles"]) == analysis.ROLES_MAX  # what the user added always shows

    gone = client.post("/api/analysis/roles/remove", json={"id": "nurse-educator"}).json()
    assert "nurse-educator" not in _ids(gone["roles"])
    cfg = settings.get()["analysis"]
    assert "Nurse Educator" not in cfg["pinned_roles"] and "Nurse Educator" in cfg["hidden_roles"]
    again = client.post("/api/analysis/roles/add", json={"title": "Nurse Educator"}).json()  # adding it brings it back
    assert "nurse-educator" in _ids(again["roles"]) and "Nurse Educator" not in settings.get()["analysis"]["hidden_roles"]


def test_a_removed_role_stays_hidden_under_another_spelling():
    db.kv_set("profile.answers", {"target_roles": ["Software Engineer", "IT Support Specialist", "Data Analyst"]})
    analysis.remove_role("software-engineer")
    db.kv_set("profile.answers", {"target_roles": ["Software Engineering", "IT Support", "Data Analysis"]})
    picked = analysis.pick_roles()
    assert _ids(picked["roles"]) == ["it-support", "data-analyst"]
    assert picked["removed"] == [{"id": "software-engineer", "label": "Software Engineering", "source": "target"}]


def test_a_new_user_sees_an_empty_chart(client):
    d = client.get("/api/analysis").json()
    assert d["roles"] == [] and d["limits"] == {"min": 3, "max": 8} and d["latest"] is None and not d["outdated"]
    assert d["market"]["demand_source"] == "no search results yet"
    db.kv_set("profile.answers", {"target_roles": ["carpenter"]})
    assert [r["label"] for r in client.get("/api/analysis").json()["roles"]] == ["Carpenter"]  # too few: the page asks for more


def test_the_ai_scores_roles_by_id_and_suggests_more(fake_ai):
    _nurse()
    fake_ai.responses["analysis"] = {
        "roles": [{"id": "registered-nurse", "fit": 140, "interest": 90, "confidence": "high", "evidence": ["Three years on med-surg"],
                   "gaps": [], "moves": []},
                  {"id": "Charge Nurse", "fit": "70", "interest": 80, "confidence": "medium", "evidence": [], "gaps": ["No charge shifts yet"],
                   "moves": [{"type": "course", "title": "A charge nurse course", "detail": "Online.", "effort": "days", "impact": "medium"}]},
                  {"id": "pilot", "fit": 50, "interest": 10, "confidence": "low", "evidence": [], "gaps": [], "moves": []}],
        "suggested_roles": [{"title": "Nurse Educator", "why": "Precepted four new graduate nurses.", "fit": 72, "interest": 75},
                            {"title": "RN", "why": "Already a target.", "fit": 90, "interest": 90},
                            {"title": "Case Manager", "why": "Plans discharges with families.", "fit": 61, "interest": 55}],
        "summary": "A strong bedside nurse.", "top_priorities": [], "profile_suggestions": [], "search_steering": STEERING}
    out = asyncio.run(analysis.run_ai("test"))
    prompt = next(c for c in fake_ai.calls if c["purpose"] == "analysis")["prompt"]
    assert "- registered-nurse: Registered Nurse (from their target roles, their search plan, their work history)" in prompt
    assert "- patient-care-technician: Patient Care Technician (from their work history)" in prompt
    result = out["result"]
    assert [(r["id"], r["fit"]) for r in result["roles"]] == [("registered-nurse", 100), ("charge-nurse", 70)]  # unknown ids dropped
    assert [s["title"] for s in result["suggested_roles"]] == ["Nurse Educator", "Case Manager"]  # one already on the chart dropped

    d = analysis.get()
    roles = {r["id"]: r for r in d["roles"]}
    educator = roles["nurse-educator"]  # a suggestion is a role now, with the scores it came with
    assert (educator["source"], educator["fit"], educator["interest"], educator["why"]) == ("suggested", 72, 75, "Precepted four new graduate nurses.")
    assert roles["charge-nurse"]["assessment"]["moves"][0]["title"] == "A charge nurse course"
    assert roles["registered-nurse"]["fit_before"] is None  # nothing earlier to compare with
    assert d["unscored"] == ["hospice-nursing", "patient-care-technician"]  # on the chart, but the AI skipped them

    # The next assessment keeps one suggestion and drops the other; fit change keys by role id.
    fake_ai.responses["analysis"] = {
        "roles": [{"id": "registered-nurse", "fit": 85, "interest": 90, "confidence": "high", "evidence": [], "gaps": [], "moves": []},
                  {"id": "nurse-educator", "fit": 78, "interest": 75, "confidence": "medium", "evidence": [], "gaps": [], "moves": []},
                  {"id": "hospice-nursing", "fit": 60, "interest": 50, "confidence": "low", "evidence": [], "gaps": [], "moves": []}],
        "suggested_roles": [{"title": "Nurse Educator", "why": "Still the closest next step.", "fit": 78, "interest": 75}],
        "summary": "", "top_priorities": [], "profile_suggestions": [], "search_steering": STEERING}
    asyncio.run(analysis.run_ai("again"))
    roles = {r["id"]: r for r in analysis.get()["roles"]}
    assert (roles["registered-nurse"]["fit"], roles["registered-nurse"]["fit_before"]) == (85, 100)
    assert (roles["nurse-educator"]["fit"], roles["nurse-educator"]["fit_before"]) == (78, 72)
    assert roles["hospice-nursing"]["fit_before"] is None and "case-manager" not in roles
    school = analysis.add_role("School Nurse")  # a role added after the assessment waits for the next one
    assert school == "school-nurse" and school in analysis.get()["unscored"]


def test_an_analysis_saved_by_the_genre_version_reads_as_not_analyzed(client):
    _nurse()
    old = {"genres": [{"id": "nursing", "fit": 80, "interest": 90, "confidence": "high", "evidence": [], "gaps": [], "moves": []}],
           "summary": "The old read.", "top_priorities": [{"title": "Get ACLS", "why": "Asked often.", "genre": "nursing", "type": "cert",
                                                          "detail": "A two-day course."}],
           "profile_suggestions": [], "search_steering": {**STEERING, "emphasize": ["nursing"]}}
    db.kv_set("analysis.latest", {"ts": "2026-10-30T12:00:00+00:00", "reason": "manual", "tokens": 1200, "result": old,
                                  "demand": {"nursing": 100}})
    db.kv_set("analysis.history", [{"ts": "2026-10-30T12:00:00+00:00", "fit": {"nursing": 80}, "interest": {"nursing": 90}}])
    r = client.get("/api/analysis")
    d = r.json()
    assert r.status_code == 200 and d["latest"] is None and d["outdated"] and d["history"] == [] and d["unscored"] == []
    assert d["roles"] and all(role["fit"] is None and role["fit_before"] is None for role in d["roles"])
    assert settings.get()["analysis"]["genres"]  # the genres stay in settings for triage and the search
