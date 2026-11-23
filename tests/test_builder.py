"""The resume builder (candidate/builder.py) for people without a resume: the form, writing the resume from their answers
with the AI, making it the main resume, saving the standard answers among them, the copy in Settings, Resumes, and the
routes."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from jobportal.ai import client as ai
from jobportal.candidate import builder, onboarding, profile
from jobportal.core import db

# A fictional high school senior with no resume yet.
ANSWERS = {"name": "Riley Morgan", "email": "riley.morgan@example.com", "phone": "(555) 010-0142", "city": "Dayton",
           "state": "Ohio", "target_roles": ["Pharmacy Technician", "Retail Associate"], "education_level": "high_school",
           "school": "Example High School", "graduation": "June 2027", "skills": ["Cash handling", "Customer service"],
           "languages": "English, Spanish", "projects": "Volunteer of the Month, Dayton Food Pantry, March 2026",
           "licenses": ["CPR and First Aid, American Red Cross, 2026"], "not_a_field": "dropped"}
JOBS = [{"role": "Cashier", "organization": "Corner Market", "place": "Dayton, OH", "dates": "June 2025 to now",
         "details": "Ran the register on busy weekends\nTrained two new hires"}, {"role": "", "organization": "", "details": ""}]
RESUME = """# Riley Morgan
riley.morgan@example.com | (555) 010-0142 | Dayton, OH

## Experience
**Corner Market**, Cashier, Dayton, OH || June 2025 - Present
- Ran the register during busy weekend shifts
- Trained two new hires on store procedures

## Education
**Example High School** || Expected June 2027
"""


def test_the_form_reuses_the_standard_questions():
    form = builder.form()
    ids = [f["id"] for f in form["questions"]]
    assert ids == builder.STANDARD_IDS and form["required"] == ["name", "email", "city", "target_roles"]
    assert form["questions"][0] == onboarding.FIELDS["name"] and {f["id"] for f in form["job"]} >= {"role", "details"}
    db.kv_set("profile.answers", {"name": "Riley Morgan", "phone": "(555) 010-0142"})
    assert builder.form()["answers"] == {"name": "Riley Morgan", "phone": "(555) 010-0142"}  # starts from saved answers


def test_missing_required_answers_are_named():
    with pytest.raises(ValueError, match="Fill in Full name, Target jobs"):
        asyncio.run(builder.write_resume({"answers": {"email": "x@example.com", "city": "Dayton"}}))


def test_the_resume_is_written_from_their_own_answers(fake_ai):
    fake_ai.responses["resume-builder"] = {"resume_md": RESUME, "notes": ["Add how many customers you help on a busy day."]}
    out = asyncio.run(builder.write_resume({"answers": ANSWERS, "jobs": JOBS}))
    call = fake_ai.calls[0]
    assert call["stage"] == "profile" and "Use ONLY what their answers say" in call["system"]
    assert "Ran the register on busy weekends" in call["prompt"] and "Pharmacy Technician" in call["prompt"]
    assert "RESUME PLAYBOOK" in call["prompt"] and "dropped" not in call["prompt"]
    assert out["notes"] == ["Add how many customers you help on a busy day."] and out["markdown"].startswith("# Riley Morgan")
    # It's the main resume now, and the standard answers it covers are saved, with nothing to check.
    assert profile.resume()["filename"] == onboarding.BUILDER_FILENAME and profile.resume()["text"] == RESUME.strip()
    answers = profile.standard_answers()
    assert answers["name"] == "Riley Morgan" and answers["target_roles"] == ["Pharmacy Technician", "Retail Associate"]
    assert answers["licenses"] == ["CPR and First Aid, American Red Cross, 2026"] and not answers.get("_from_resume")
    assert onboarding.state()["resume_from_builder"]
    # What they wrote is kept, without the empty job, so the form fills in again next time.
    saved = db.kv_get("onboarding.builder")
    assert saved["jobs"] == [JOBS[0]] and "not_a_field" not in saved["answers"]
    assert builder.form()["jobs"] == [JOBS[0]]


def test_a_reply_that_isnt_a_resume_fails(fake_ai):
    fake_ai.responses["resume-builder"] = {"resume_md": "Too short.", "notes": []}
    with pytest.raises(ai.AIError, match="usable resume"):
        asyncio.run(builder.write_resume({"answers": ANSWERS, "jobs": JOBS}))
    assert profile.resume() is None  # nothing changed


def test_the_builder_routes_keep_one_copy_in_settings_resumes(fake_ai):
    from jobportal.web.server import app
    fake_ai.responses["resume-builder"] = {"resume_md": RESUME, "notes": []}
    with TestClient(app) as client:
        assert client.get("/api/onboarding/builder").json()["required"] == builder.REQUIRED_IDS
        bad = client.post("/api/onboarding/builder", json={"answers": {"name": "Riley Morgan"}})
        assert bad.status_code == 400 and "Email" in bad.json()["detail"]
        first = client.post("/api/onboarding/builder", json={"answers": ANSWERS, "jobs": JOBS})
        assert first.status_code == 200 and first.json()["building"] is False  # work eligibility and levels are still unanswered
        fake_ai.responses["resume-builder"] = {"resume_md": RESUME.replace("busy weekend shifts", "weekend rushes"), "notes": []}
        assert client.post("/api/onboarding/builder", json={"answers": ANSWERS, "jobs": JOBS}).status_code == 200
    copies = db.q("SELECT name, md, source FROM resume_library")
    assert len(copies) == 1 and copies[0]["source"] == "builder" and "weekend rushes" in copies[0]["md"]
