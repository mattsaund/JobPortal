import asyncio
import re

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


def test_questions_fit_any_field_and_schooling():
    education = {k for k, _ in onboarding.FIELDS["education_level"]["options"]}
    assert {"high_school", "some_college", "trade", "apprenticeship", "associate", "bachelor", "master", "doctorate",
            "professional"} <= education
    assert {"seasonal", "per_diem", "apprenticeship", "part_time"} <= {k for k, _ in onboarding.FIELDS["job_types"]["options"]}
    assert "apprenticeship" in {k for k, _ in onboarding.FIELDS["levels"]["options"]}
    assert "work samples" in onboarding.FIELDS["github"]["label"]  # the id stays "github" for saved answers
    assert onboarding.FIELDS["licenses"]["type"] == "list" and "licenses" not in onboarding.REQUIRED


def test_licenses_reach_the_kit_and_old_industry_names_are_kept():
    answers = onboarding.save_answers({**STANDARD_ANSWERS, "licenses": ["CPR and First Aid, 2025", "Food Handler card"],
                                       "industries": ["Software & SaaS", "Education", "Bogus"]})
    assert answers["industries"] == ["Technology & Software", "Education"]  # renamed in v0.3.0, not dropped
    kit = {row["q"]: row["a"] for row in profile.get("qa")}
    assert kit["Professional licenses and certifications"] == "CPR and First Aid, 2025, Food Handler card"
    assert "Food Handler card" in profile.digest()  # triage sees them


def test_portfolio_links_prefill_the_work_samples_question():
    resume = "Riley Chen\nriley.chen@example.com | behance.net/rileychen-example | Columbus, OH\n\n## Experience\n- Designed menus"
    assert onboarding.regex_prefill(resume)["github"] == "https://behance.net/rileychen-example"


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
    prompt_text = onboarding.answers_for_prompt(profile.standard_answers())
    assert "Gender" not in prompt_text and "Software Engineer" in prompt_text


def test_anywhere_and_remote_only_locations():
    assert onboarding.allowed_locations({"anywhere_us": "yes", "work_modes": ["remote"]}) == ["Anywhere in the US", "Remote"]
    assert onboarding.allowed_locations({"state": "Ohio", "work_modes": ["onsite"]}) == ["Ohio"]
    assert onboarding.allowed_locations({"state": "Ohio", "work_modes": ["remote"]}) == ["Remote"]  # nothing but Remote


def test_skipping_the_places_question_still_searches_near_home():
    # The default work arrangement is all three. Remote alone would drop every on-site job near home.
    every_mode = onboarding.defaults()["work_modes"]
    assert onboarding.allowed_locations({"state": "Ohio", "work_modes": every_mode}) == ["Ohio", "Remote"]
    assert onboarding.allowed_locations({"work_modes": ["hybrid", "remote"]}) == ["Anywhere in the US", "Remote"]  # no home state
    assert onboarding.allowed_locations({"state": "Ohio", "locations": ["Denver, CO"], "work_modes": every_mode}) == ["Denver, CO", "Remote"]


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


def test_saving_answers_again_keeps_edits_made_on_other_pages():
    from jobportal.core import settings
    onboarding.save_answers(STANDARD_ANSWERS)
    cfg = settings.get()
    cfg["dream_companies"].append("Example Labs")  # added on the Dream list page
    cfg["locations"]["allowed"] = ["Ohio", "Remote"]  # changed in the search area editor
    settings.save(cfg)
    onboarding.save_answers({**STANDARD_ANSWERS, "phone": "(555) 010-0123"})  # an unrelated fix
    cfg = settings.get()
    assert cfg["dream_companies"] == ["Example Robotics", "Example Labs"] and cfg["locations"]["allowed"] == ["Ohio", "Remote"]
    onboarding.save_answers({**STANDARD_ANSWERS, "dream_companies": ["Example Aerospace"], "locations": ["Texas"]})
    cfg = settings.get()
    assert cfg["dream_companies"] == ["Example Labs", "Example Aerospace"]  # the answers' swap applied, the page's addition kept
    assert cfg["locations"]["allowed"] == ["Texas", "Remote"]  # the location answers changed, so the area follows them


def test_resume_fills_empty_answers_until_they_are_saved(fake_ai, sample_resume):
    fake_ai.responses["onboarding-prefill"] = {"name": "Jordan Rivera", "city": "Columbus", "target_roles": ["Software Engineer"]}
    out = asyncio.run(onboarding.import_resume("Jordan Rivera.md", data=sample_resume.encode()))
    assert {"name", "city", "email", "target_roles"} <= set(out["filled"])
    answers = profile.standard_answers()
    assert answers["city"] == "Columbus" and "_saved_at" not in answers  # filled in, but setup isn't done
    assert "city" in onboarding.state()["from_resume"]
    # Once the answers are saved, a new resume never changes them.
    onboarding.save_answers({**STANDARD_ANSWERS, "city": "Dayton"})
    fake_ai.responses["onboarding-prefill"] = {"city": "Cleveland"}
    assert asyncio.run(onboarding.import_resume("Newer.md", data=sample_resume.encode()))["filled"] == []
    assert profile.standard_answers()["city"] == "Dayton"


def test_answers_saved_one_at_a_time():
    out = onboarding.merge_answers({"name": "Jordan Rivera", "not_a_question": "ignored"})
    assert not out["complete"] and not out["first_complete"] and "email" in out["missing"]
    assert "not_a_question" not in profile.standard_answers()
    required = {key: STANDARD_ANSWERS[key] for key in onboarding.REQUIRED}
    out = onboarding.merge_answers(required)
    assert out["complete"] and out["first_complete"] and out["missing"] == []
    assert profile.standard_answers()["name"] == "Jordan Rivera"  # the earlier answer stayed
    assert profile.get("facts")["city"] == STANDARD_ANSWERS["city"]  # a complete save writes the facts
    # Later changes keep setup done and stamp the change, so the watcher rebuilds the profile once.
    out = onboarding.merge_answers({"city": ""})
    assert out["complete"] and not out["first_complete"] and out["missing"] == ["city"]
    from jobportal.core import db
    assert db.kv_get("profile.answers_changed_at")


def test_finishing_setup_one_answer_at_a_time_points_the_search_at_every_answer():
    # Home saves each answer as it comes. The answers given before the last required one never reached the settings, so
    # finishing setup must apply them all, not only the last one.
    onboarding.merge_answers({"name": "Jordan Rivera", "email": "jordan.rivera@example.com", "target_roles": ["Registered Nurse"],
                              "levels": ["entry"], "locations": ["Columbus, OH"], "dream_companies": ["Example Health"]})
    onboarding.merge_answers({"city": "Columbus"})
    onboarding.merge_answers({"work_authorized": "yes"})
    assert onboarding.merge_answers({"sponsorship": "no"})["first_complete"]
    cfg = settings.get()
    assert cfg["search"]["levels"] == ["entry"]
    assert re.escape("registered nurse") in cfg["filters"]["title_include"]  # the target role always passes the title filter
    assert cfg["locations"]["allowed"] == ["Columbus, OH", "Remote"]
    assert cfg["dream_companies"] == ["Example Health"]


def test_the_first_full_save_applies_answers_the_resume_filled_in(fake_ai, sample_resume):
    fake_ai.responses["onboarding-prefill"] = {"state": "Ohio", "target_roles": ["Software Engineer"], "levels": ["internship", "entry"]}
    asyncio.run(onboarding.import_resume("Jordan Rivera.md", data=sample_resume.encode()))
    # The form comes back with the pre-filled answers unchanged.
    onboarding.save_answers({**STANDARD_ANSWERS, "state": "Ohio", "locations": [], "work_modes": ["onsite"],
                             "target_roles": ["Software Engineer"], "levels": ["internship", "entry"]})
    cfg = settings.get()
    assert cfg["locations"]["allowed"] == ["Ohio"]
    assert cfg["search"]["levels"] == ["internship", "entry"] and cfg["filters"]["title_include"]
