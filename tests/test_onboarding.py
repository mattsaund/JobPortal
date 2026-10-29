import asyncio

import pytest
from conftest import STANDARD_ANSWERS

from jobportal.candidate import onboarding, profile
from jobportal.core import settings


def test_questions_are_well_formed():
    ids = [f["id"] for s in onboarding.QUESTIONS for f in s["fields"]]
    assert len(ids) == len(set(ids))
    for f in onboarding.FIELDS.values():
        assert f["type"] in ("text", "email", "tel", "url", "select", "multi", "list", "textarea")
        if f["type"] in ("select", "multi"):
            assert f["options"] and all(len(o) == 2 for o in f["options"])
    assert {"name", "email", "target_roles", "levels", "work_authorized", "sponsorship"} <= set(onboarding.REQUIRED)


def test_regex_prefill(sample_resume):
    pre = onboarding.regex_prefill(sample_resume)
    assert pre["email"] == "jordan.rivera@example.com"
    assert pre["name"] == "Jordan Rivera"
    assert pre["linkedin"].startswith("https://") and "linkedin.com/in/jordan-rivera-example" in pre["linkedin"]
    assert "github.com/jordan-rivera-example" in pre["github"]
    assert "555" in pre["phone"]


def test_required_answers():
    with pytest.raises(ValueError, match="Full name"):
        onboarding.save_answers({**STANDARD_ANSWERS, "name": ""})


def test_answers_drive_settings_facts_and_kit():
    onboarding.save_answers(STANDARD_ANSWERS)
    cfg = settings.get()
    assert cfg["search"]["levels"] == ["internship", "entry"]
    assert cfg["locations"]["allowed"] == ["Ohio", "Pittsburgh, PA", "Remote"]
    assert cfg["dream_companies"] == ["Example Robotics"]
    assert any("clearance" in k for k in cfg["filters"]["exclude_keywords"])
    assert cfg["filters"]["title_include"]  # early career -> titles must look early career
    facts = profile.get("facts")
    assert facts["name"] == "Jordan Rivera" and facts["school"] == "Example State University"
    assert "Bachelor's degree in Computer Science" == facts["degree"]
    assert "no visa sponsorship needed" in facts["work_authorization"]
    qa = profile.get("qa")
    assert {"q": "Are you legally authorized to work in the United States?", "a": "Yes"} in qa
    assert all(x.get("eeo") for x in qa if x["q"] in ("Gender", "Disability status"))
    prompt_text = onboarding.answers_for_prompt()
    assert "Gender" not in prompt_text and "Software Engineer" in prompt_text


def test_anywhere_and_remote_only_locations():
    assert onboarding.allowed_locations({"anywhere_us": "yes", "work_modes": ["remote"]}) == ["Anywhere in the US", "Remote"]
    assert onboarding.allowed_locations({"state": "Ohio", "work_modes": ["onsite"]}) == ["Ohio"]


def test_import_resume_stores_file_and_prefills(fake_ai, sample_resume):
    fake_ai.responses["onboarding-prefill"] = {"name": "Jordan Rivera", "city": "Columbus", "state": "OH",
                                                    "target_roles": ["Software Engineer"], "levels": ["entry"], "email": ""}
    out = asyncio.run(onboarding.import_resume("Jordan Rivera.md", data=sample_resume.encode()))
    assert out["prefill"]["city"] == "Columbus"
    assert out["prefill"]["email"] == "jordan.rivera@example.com"  # the AI left it empty, the regex found it
    assert profile.resume()["filename"] == "Jordan Rivera.md"
    from jobportal.core.config import RESUME_DIR
    assert any(RESUME_DIR.iterdir())


def test_prefill_survives_ai_failure(fake_ai, sample_resume):
    out = asyncio.run(onboarding.prefill(sample_resume))  # no fake response -> AIError -> regex only
    assert out["email"] == "jordan.rivera@example.com" and "_error" in out
