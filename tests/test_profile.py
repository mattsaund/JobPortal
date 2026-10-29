import asyncio
import copy

from conftest import PROFILE_OUT, STANDARD_ANSWERS

from jobportal.candidate import onboarding, profile
from jobportal.core import db
from jobportal.search import pipeline


def test_starts_with_zero_data():
    assert profile.get_all() == {k: profile.EMPTY[k] for k in profile.KEYS}
    assert profile.questions() == [] and profile.resume() is None and profile.standard_answers() == {}
    assert "Import your resume" in profile.ready_to_search()
    assert db.q("SELECT * FROM leads") == []


def _setup(fake_ai, sample_resume):
    fake_ai.responses["onboarding-prefill"] = {}
    fake_ai.responses["profile-build"] = copy.deepcopy(PROFILE_OUT)
    fake_ai.responses["analysis"] = {"genres": [], "summary": "", "top_priorities": [], "profile_suggestions": [],
                                         "search_steering": {"emphasize": [], "deemphasize": [], "add_queries": [], "add_companies": [], "notes": ""}}
    asyncio.run(onboarding.import_resume("resume.md", data=sample_resume.encode()))
    onboarding.save_answers(STANDARD_ANSWERS)


def test_build_from_resume_and_answers(fake_ai, sample_resume):
    _setup(fake_ai, sample_resume)
    out = asyncio.run(profile.build("test"))
    assert out["ok"] and profile.is_built()
    assert profile.ready_to_search() == ""
    facts = profile.get("facts")
    assert facts["email"] == "jordan.rivera@example.com"  # the standard answer beats what the AI read
    assert facts["skills"] == "Python, JavaScript, React, SQL"  # skills come from the build
    assert profile.get("search_plan")["queries"] == ["software engineer intern", "it support intern"]
    assert [q["question"] for q in profile.questions()] == ["How many people used the imaging script?"]
    build_call = next(c for c in fake_ai.calls if c["purpose"] == "profile-build")
    assert "Budget Buddy" in build_call["prompt"] and "Gender" not in build_call["prompt"]


def test_answers_update_only_what_changes(fake_ai, sample_resume):
    _setup(fake_ai, sample_resume)
    asyncio.run(profile.build("test"))
    profile.answer_question("How many people used the imaging script?", "About 300 students a semester.")
    assert len(profile.unsynced()) == 1
    fake_ai.responses["profile-update"] = {"project_bank": PROFILE_OUT["project_bank"] + "\n- about 300 students a semester",
                                               "changes": ["Added the imaging script's reach"], "open_questions": []}
    out = asyncio.run(profile.update_from_answers("test"))
    assert out["sections"] == ["project_bank"]
    assert "300 students" in profile.get("project_bank")
    assert profile.unsynced() == []
    q = profile.questions()[0]
    assert q["status"] == "answered" and q["synced"]
    assert "300 students" in profile.full_context()


def test_full_context_never_includes_self_identification(fake_ai, sample_resume):
    _setup(fake_ai, sample_resume)
    ctx = profile.full_context()
    assert "Disability" not in ctx and "Veteran" not in ctx
    assert "volunteer teaching Scratch" in ctx


def test_search_refuses_until_setup_is_done():
    import pytest
    with pytest.raises(RuntimeError, match="resume"):
        asyncio.run(pipeline.start("full"))


def test_ask_deduplicates():
    assert profile.ask("Have you used Docker?", "The posting asks for it.", source="Acme application", lead_id=7)
    assert not profile.ask("have you used docker", "dup")
    assert profile.open_counts_by_lead() == {7: 1}


def test_only_the_resume_and_answers_feed_the_profile(fake_ai, sample_resume):
    """Saved resumes are storage. Whatever is in them must never reach the profile build."""
    from jobportal.candidate import library
    library.create("Old resume", "# Someone Else\n## Experience\n- MARKER-NOT-FROM-THE-USER", None, "saved")
    _setup(fake_ai, sample_resume)
    asyncio.run(profile.build("test"))
    build_prompt = next(c for c in fake_ai.calls if c["purpose"] == "profile-build")["prompt"]
    assert "Budget Buddy" in build_prompt and "MARKER-NOT-FROM-THE-USER" not in build_prompt
