import asyncio
import copy
import time

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


def test_a_failed_sync_waits_before_trying_again(fake_ai, sample_resume, monkeypatch):
    _setup(fake_ai, sample_resume)
    asyncio.run(profile.build("test"))
    db.kv_set("profile.documents_changed_at", time.time() - 120)  # a document added two minutes ago
    del fake_ai.responses["profile-build"]  # and now every build fails, as when the ChatGPT sign-in has ended
    options = {"sync_delay_sec": 60}
    assert asyncio.run(profile.sync_once(options)) == "failed"
    assert asyncio.run(profile.sync_once(options)) == "waiting"  # not one failing AI call (and error toast) per tick
    assert sum(c["purpose"] == "profile-build" for c in fake_ai.calls) == 2  # the first build, then one failed try
    db.kv_set("profile.documents_changed_at", time.time() - 90)  # another document: worth a new try right away
    assert asyncio.run(profile.sync_once(options)) == "failed"
    fake_ai.responses["profile-build"] = copy.deepcopy(PROFILE_OUT)
    monkeypatch.setattr(profile, "RETRY_AFTER_FAILURE_SEC", 0)  # the wait is over
    assert asyncio.run(profile.sync_once(options)) == "done"
    assert asyncio.run(profile.sync_once(options)) == ""  # the documents are in the profile now


def test_answers_given_during_an_update_wait_for_the_next_one(fake_ai, sample_resume):
    _setup(fake_ai, sample_resume)
    asyncio.run(profile.build("test"))
    profile.answer_question("How many people used the imaging script?", "About 300 students a semester.")

    def update(prompt):  # the user answers another question while the AI is still working
        profile.answer_question("Do you have a driver's license?", "Yes.")
        return {"changes": ["Added the imaging script's reach"], "open_questions": []}

    fake_ai.responses["profile-update"] = update
    asyncio.run(profile.update_from_answers("test"))
    assert [q["question"] for q in profile.unsynced()] == ["Do you have a driver's license?"]


def test_builds_keep_questions_raised_by_applications(fake_ai, sample_resume):
    _setup(fake_ai, sample_resume)
    profile.ask("How many people used the imaging script?", "The posting asks about scale.", source="Example Robotics application",
                lead_id=3)
    asyncio.run(profile.build("test"))  # PROFILE_OUT asks the same question
    assert profile.open_counts_by_lead() == {3: 1}
    fake_ai.responses["profile-build"] = {**copy.deepcopy(PROFILE_OUT), "open_questions": []}
    asyncio.run(profile.build("test"))
    assert [q["source"] for q in profile.questions()] == ["Example Robotics application"]


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


def test_the_profile_reads_documents_but_never_saved_resumes(fake_ai, sample_resume):
    """Extra documents feed the profile build. Saved resumes are storage: whatever is in them must never reach it."""
    from jobportal.candidate import documents, library
    library.create("Old resume", "# Someone Else\n## Experience\n- MARKER-NOT-FROM-THE-USER", None, "saved")
    documents.add("certificate.txt", b"Certified ROS Developer. Jordan Rivera, 2026.")
    _setup(fake_ai, sample_resume)
    asyncio.run(profile.build("test"))
    build_prompt = next(c for c in fake_ai.calls if c["purpose"] == "profile-build")["prompt"]
    assert "Budget Buddy" in build_prompt and "Certified ROS Developer" in build_prompt
    assert "MARKER-NOT-FROM-THE-USER" not in build_prompt
    # The build remembers which documents it read, so the watcher only rebuilds when they change again.
    assert db.kv_get("profile.documents_built") == documents.changed_at()


def test_document_details_reach_the_profile_build(fake_ai, sample_resume):
    from jobportal.candidate import documents
    _setup(fake_ai, sample_resume)
    documents.add("RN license.txt", b"Ohio Board of Nursing\nThis certifies that\nJordan Rivera\nis licensed as a Registered Nurse\n"
                                    b"Issued: 06/15/2024 Expires: 08/31/2026")
    asyncio.run(profile.build("test"))
    call = next(c for c in fake_ai.calls if c["purpose"] == "profile-build")
    assert ("DETAILS (a rough reading by patterns; the text wins): kind: license; title: Registered Nurse License; "
            "issuer: Ohio Board of Nursing; issued: 2024-06; expires: 2026-08") in call["prompt"]
    assert "## Licenses & Certifications" in call["system"] and "## Awards & Honors" in call["system"]  # where they land


def test_documents_from_before_readings_existed_are_read_lazily():
    from jobportal.candidate import documents
    db.kv_set("profile.answers", {"name": "Jordan Rivera"})
    db.kv_set("profile.documents", [{"id": "old1", "name": "Jordan Rivera.txt", "kind": "award", "text": "Jordan Rivera\n"
                                     "Example State University\nDean's List, Spring 2025", "chars": 60, "added_at": db.now(),
                                     "sha1": "x", "stored_as": "old1 Jordan Rivera.txt"}])
    (entry,) = documents.listing()
    assert entry["parsed_by"] == "rules" and entry["parsing"] is False
    assert entry["parsed"]["title"] == "Dean's List" and entry["parsed"]["issuer"] == "Example State University"
    assert "Jordan" not in entry["parsed"]["title"] and entry["parsed"]["issued"] == "2025"  # never the user's own name
    assert db.kv_get("profile.documents")[0]["parsed"] == entry["parsed"]  # saved, so it's read only once
    assert db.kv_get("profile.documents_changed_at") is None  # nothing about the document changed: no rebuild


def test_parse_pending_reads_what_only_the_rules_read(fake_ai, monkeypatch):
    from jobportal.candidate import documents
    documents.add("cpr.txt", b"American Heart Association\nBLS Provider\nIssue Date 2/2025 Renew By 2/2027")
    documents.add("food.txt", b"Certificate of completion: Food Handler Training. Issued March 2025.")
    assert asyncio.run(documents.parse_pending()) == 0  # nobody is signed in
    monkeypatch.setattr(documents, "_signed_in", lambda: True)
    assert asyncio.run(documents.parse_pending()) == 0  # the fake AI has no answer: the first failure ends the round
    assert all(d["parsed_by"] == "rules" for d in documents.listing())
    fake_ai.responses["document-parse"] = {"kind": "certificate", "title": "BLS Provider", "issuer": "American Heart Association",
                                           "issued": "2025-02", "expires": "2027-02", "skills": ["CPR"], "summary": "A BLS card."}
    assert asyncio.run(documents.parse_pending()) == 2 and all(d["parsed_by"] == "ai" for d in documents.listing())
    assert asyncio.run(documents.parse_pending()) == 0  # nothing left to read


def test_document_kinds_cover_british_spelling_and_resumes():
    from jobportal.candidate import documents
    british = "licen" + "ce"  # spelled out in pieces: the repo's own text sticks to American spelling
    assert documents._kind("permit.txt", f"Driving {british} issued 2024 by the state") == "license"
    resume_text = "Jordan Rivera\n## Experience\nCashier\n## Education\nExample High School\nFood handler certification"
    assert documents._kind("Jordan Rivera.md", resume_text) == "resume"  # a resume that mentions a certificate is a resume
    assert documents.recipients("This certifies that\nJordan Rivera\nhas completed CPR") == ["Jordan Rivera"]


def test_answers_used_in_a_resume_are_marked_applied():
    profile.ask("Have you used ROS?", "The posting asks for it.", source="Example Robotics application", lead_id=3)
    profile.answer_question("Have you used ROS?", "Yes, in a class project.")
    profile.mark_answers_applied(3)
    assert profile.questions()[0]["status"] == "applied"
