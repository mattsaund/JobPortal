"""Tests for jobportal/core/levels.py: the title filters, board search words and post regexes each experience level
implies."""
import re

from jobportal.core import levels


def passes(title: str, lv, roles=None) -> bool:
    """Whether a title gets through the title filters for these levels and roles. An empty include list lets any title
    through, as the Settings page promises ("blank = any title")."""
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
    assert not passes("Staff Accountant", ["entry"])
    assert passes("Associate Product Manager", ["entry"], roles=["Associate Product Manager"])


def test_filters_have_no_repeats():
    inc, exc = levels.title_filters(["senior", "lead"], ["SWE", "swe"])
    assert inc.count("principal") == 1 and inc.count("swe") == 1  # senior and lead both mark "principal"
    assert len(exc) == len(set(exc))


def test_board_filters_and_terms():
    assert levels.linkedin_experience(["internship", "entry"]) == "1,2"
    assert levels.linkedin_experience(["mid"]) == "3,4"
    assert levels.muse_levels(["senior"]) == ["Senior Level"]
    assert "intern" in levels.ats_search_terms(["internship"])
    assert levels.ats_search_terms(["mid"], ["data engineer", "analytics engineer"])[:2] == ["data engineer", "analytics engineer"]
    assert levels.clean(["bogus"]) == levels.DEFAULT_LEVELS


def test_ats_terms_are_capped():
    queries = [f"query {i}" for i in range(12)]
    terms = levels.ats_search_terms(["internship", "entry", "mid"], ["Intern"] + queries)
    assert len(terms) == 8 and terms[:3] == ["intern", "co-op", "student"]  # level words first, "Intern" is a repeat
    assert levels.ats_search_terms(["senior"], queries) == queries[:8]


def test_posting_regex():
    assert levels.posting_regex(["internship"]).search("We're hiring summer interns!")
    rx = levels.posting_regex(["senior"], ["Site Reliability Engineer"])
    assert rx.search("Hiring a reliability engineer for our platform team")
    assert not rx.search("Looking for a pastry chef")
