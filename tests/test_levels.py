"""Tests for jobportal/core/levels.py: the title filters, board search words and post regexes each experience level
implies."""
import re

from jobportal.core import levels


def passes(title: str, lv, roles=None) -> bool:
    """Whether a title gets through the title filters for these levels and roles. An empty include list lets any title
    through, as Settings, Search promises ("leave empty for any title")."""
    inc, exc = levels.title_filters(lv, roles)
    t = title.lower()
    ok_inc = not inc or re.search("|".join(f"(?:{p})" for p in inc), t, re.I)
    bad = exc and re.search("|".join(f"(?:{p})" for p in exc), t, re.I)
    return bool(ok_inc and not bad)


def test_early_career_filters():
    lv = ["internship", "entry"]
    assert passes("Software Engineering Intern", lv)
    assert passes("Junior Data Analyst", lv)
    assert not passes("Senior Software Engineer", lv)
    assert not passes("Engineering Manager", lv)
    assert not passes("Software Engineer II", lv)
    assert levels.early_career(lv)


def test_mid_and_senior_levels_drop_the_title_requirement():
    lv = ["mid", "senior"]
    inc, _ = levels.title_filters(lv)
    assert inc == []
    assert passes("Backend Engineer", lv)
    assert passes("Senior Backend Engineer", lv)
    assert not passes("Software Engineering Intern", lv)
    assert not passes("Director of Engineering", lv)
    assert not levels.early_career(lv)


def test_target_roles_keep_their_own_words():
    assert passes("Staff Accountant", ["entry"], roles=["Staff Accountant"])
    assert not passes("Staff Accountant", ["entry"])  # no level word, and not one of the user's roles
    assert passes("Associate Product Manager", ["entry"], roles=["Associate Product Manager"])
    assert passes("Lead Teacher", ["entry"], roles=["Lead Teacher"]) and not passes("Lead Teacher", ["entry"])


def test_levels_for_every_career():
    early = ["internship", "apprenticeship", "entry"]
    for title in ("Electrician Apprentice", "Pharmacy Technician Trainee", "Accountant I", "Medical Assistant", "Teacher Aide",
                  "Staff Nurse, New Grad", "Line Cook - Team Member"):
        assert passes(title, early), title
    for title in ("Journeyman Electrician", "Accountant II", "Shift Supervisor", "Construction Foreman", "Staff Software Engineer",
                  "Director of Nursing", "Master Electrician"):
        assert not passes(title, early), title
    assert passes("RN Case Manager", early, roles=["RN"]) and passes("Assistant Manager", early, roles=["Assistant Manager"])
    assert passes("Teacher - Grade 3", ["mid"]) and not passes("Apprentice Plumber", ["mid", "senior"])
    assert passes("Store Manager", ["mid"]) and not passes("Vice President of Sales", ["mid"])


def test_nothing_is_assumed_before_the_user_picks_levels():
    assert levels.clean(["bogus"]) == levels.DEFAULT_LEVELS == levels.LEVEL_IDS
    assert levels.title_filters(levels.DEFAULT_LEVELS) == ([], [])  # every title passes: no student or tech assumption
    assert not levels.early_career(levels.DEFAULT_LEVELS)


def test_filters_have_no_repeats():
    inc, exc = levels.title_filters(["senior", "lead"], ["SWE", "swe"])
    assert inc.count("principal") == 1 and inc.count("swe") == 1  # senior and lead both mark "principal"
    assert len(exc) == len(set(exc))


def test_board_filters_and_terms():
    assert levels.linkedin_experience(["internship", "entry"]) == "1,2"
    assert levels.linkedin_experience(["mid"]) == "3,4"
    assert levels.linkedin_experience(["apprenticeship"]) == "1,2"  # LinkedIn has no apprenticeship level
    assert levels.muse_levels(["senior"]) == ["Senior Level"]
    assert levels.muse_levels(["apprenticeship", "entry"]) == ["Internship", "Entry Level"]
    assert "intern" in levels.ats_search_terms(["internship"])
    assert levels.ats_search_terms(["apprenticeship"], ["electrician apprentice"]) == ["apprentice", "trainee", "electrician apprentice"]
    assert levels.ats_search_terms(["mid"], ["data engineer", "analytics engineer"])[:2] == ["data engineer", "analytics engineer"]


def test_ats_terms_are_capped():
    queries = [f"query {i}" for i in range(12)]
    terms = levels.ats_search_terms(["internship", "entry", "mid"], ["Intern"] + queries)
    assert len(terms) == 8 and terms[:3] == ["intern", "co-op", "student"]  # level words first, "Intern" is a repeat
    assert levels.ats_search_terms(["senior"], queries) == queries[:8]


def test_iv_in_a_nursing_title_is_not_level_four():
    _, exclude = levels.title_filters(["entry"], ["Registered Nurse"])
    blocked = lambda title: any(re.search(p, title.lower()) for p in exclude)  # noqa: E731
    assert not blocked("IV Therapy Registered Nurse") and not blocked("IV Team RN")  # intravenous
    assert blocked("Registered Nurse IV") and blocked("Registered Nurse II - ICU")  # levels above entry


def test_posting_regex():
    assert levels.posting_regex(["internship"]).search("We're hiring summer interns!")
    rx = levels.posting_regex(["senior"], ["Site Reliability Engineer"])
    assert rx.search("Hiring a reliability engineer for our platform team")
    assert not rx.search("Looking for a pastry chef")
    assert levels.posting_regex(["mid"], ["Pastry Chef"]).search("Looking for a pastry chef")
    assert levels.posting_regex(["mid"]).search("Now hiring a pastry chef")  # no roles yet: job words from every field
    assert levels.posting_regex(["apprenticeship"]).search("Our union is taking apprentices this spring")
