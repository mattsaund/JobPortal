"""The search package: rule filters, triage, the search run, per-lead package work and the collectors' parsing.
No network: HTTP requests, the AI, PDF rendering and posting fetches are replaced with fakes."""
import asyncio
import copy
import json
from datetime import date, timedelta
from urllib.parse import quote

import pytest

from jobportal.ai import client as ai
from jobportal.candidate import profile
from jobportal.core import db, settings, textutil
from jobportal.core.levels import title_filters
from jobportal.core.textutil import fingerprint
from jobportal.search import collectors, packages, pipeline
from jobportal.search.collectors import ats, feeds, hunt, linkedin
from jobportal.search.collectors.base import Ctx, RawJob
from jobportal.search.pipeline import RuleFilters


def make_cfg(levels=("internship", "entry"), **locations) -> dict:
    """Default settings with a search area of Ohio and Pittsburgh, the given experience levels (a student's, unless a test
    says otherwise) with the title filters they imply, and any location settings given."""
    cfg = settings.get()
    cfg["locations"].update({"allowed": ["Ohio", "Pittsburgh, PA"], **locations})
    cfg["search"]["levels"] = list(levels)
    cfg["filters"]["title_include"], cfg["filters"]["title_exclude"] = title_filters(levels)
    return cfg


def job(title="Software Engineering Intern", company="Contoso", location="Columbus, OH", **fields) -> RawJob:
    """A job from a company board unless fields say otherwise."""
    return RawJob(fields.pop("source", "ats"), title, company, fields.pop("url", "https://jobs.example.com/1"), location=location, **fields)


def verdict(cfg: dict, j: RawJob) -> str:
    """ "pass", or the reason the rule filters dropped the job."""
    passed, reason, _ = RuleFilters(cfg).check(j)
    return "pass" if passed else reason


def skills(*entries: tuple[str, str]) -> None:
    """Save a skills inventory of (skill, level) pairs to the profile."""
    profile.save("skills_inventory", [{"skill": s, "category": "Languages", "level": level, "evidence": []} for s, level in entries])


# ---------------------------------------------------------------- rule filters


@pytest.mark.parametrize("locations, allowed, expected", [
    (["Columbus, OH"], ["Ohio", "Pittsburgh, PA"], "pass"),
    (["Pittsburgh, PA"], ["Ohio", "Pittsburgh, PA"], "pass"),
    (["Austin, TX"], ["Ohio", "Pittsburgh, PA"], "outside your locations"),
    (["Remote"], ["Ohio", "Pittsburgh, PA"], "outside your locations"),
    (["Remote"], ["Ohio", "Remote"], "pass"),
    (["Austin, TX"], ["Nationwide"], "pass"),
    (["London, UK"], ["Nationwide"], "outside your locations"),
    (["Austin, TX", "Columbus, OH"], ["Ohio"], "pass"),  # one allowed place is enough
])
def test_location_filter(locations, allowed, expected):
    assert verdict(make_cfg(allowed=allowed), job(location="", locations=locations)) == expected


def test_unknown_locations_follow_the_setting():
    assert verdict(make_cfg(unknown_policy="ai"), job(location="Various")) == "pass"
    assert verdict(make_cfg(unknown_policy="drop"), job(location="Various")) == "unknown location"
    hunted = job(location="Various", source="ai_hunt", strict_titles=False)  # hunt agents were given the search area
    assert verdict(make_cfg(unknown_policy="drop"), hunted) == "pass"


def test_too_senior_titles_are_dropped_but_events_are_not():
    cfg = make_cfg()

    def from_linkedin(title: str, **fields) -> RawJob:
        return job(title=title, source="linkedin", strict_titles=False, **fields)

    assert verdict(cfg, from_linkedin("Senior Software Engineer")) == "too senior / excluded title"
    assert verdict(cfg, from_linkedin("Software Engineer II")) == "too senior / excluded title"
    assert verdict(cfg, from_linkedin("Engineering Manager")) == "too senior / excluded title"
    assert verdict(cfg, from_linkedin("Junior Software Engineer")) == "pass"
    # The too-senior words only apply to postings: an event's name isn't a job title.
    assert verdict(cfg, job(title="Engineering Manager Info Session", kind="event", source="ai_hunt", strict_titles=False)) == "pass"


def test_strict_titles_need_a_word_for_the_users_levels():
    cfg = make_cfg()
    assert verdict(cfg, job(title="Software Engineer")) == "title doesn't match your levels"
    assert verdict(cfg, job(title="Software Engineer", source="linkedin", strict_titles=False)) == "pass"


def test_target_roles_gate_job_board_titles_but_not_social_posts():
    cfg = make_cfg(levels=["entry", "mid"])
    assert verdict(cfg, job(title="Software Engineer")) == "pass"  # no targets yet: nothing is assumed, everything passes
    db.kv_set("profile.answers", {"target_roles": ["Barista", "Line Cook"]})
    profile.save("search_plan", {"role_families": ["Food service"], "queries": ["coffee shop jobs"], "dream_companies": [], "notes": ""})
    for title in ("Barista", "Prep Cook", "Food Service Worker", "Coffee Bar Attendant"):
        assert verdict(cfg, job(title=title)) == "pass", title
    assert verdict(cfg, job(title="Software Engineer")) == "outside your target roles"
    assert verdict(cfg, job(title="Software Engineer", source="reddit", strict_titles=False)) == "pass"  # a post's headline
    assert verdict(cfg, job(title="Shift Lead", description="Make espresso drinks, prep food and cook breakfast.")) == "pass"
    cfg["filters"]["require_target_match"] = False
    assert verdict(cfg, job(title="Software Engineer")) == "pass"


def test_filters_work_for_any_career():
    def from_linkedin(title: str) -> RawJob:  # titles LinkedIn already narrowed to the levels, so only the exclusions apply
        return job(title=title, source="linkedin", strict_titles=False)

    db.kv_set("profile.answers", {"target_roles": ["Registered Nurse"]})
    nurse = make_cfg(levels=["entry"])
    assert verdict(nurse, job(title="Staff Nurse, New Grad Residency")) == "pass"  # "staff" isn't a senior word here
    assert verdict(nurse, from_linkedin("Nurse Manager")) == "too senior / excluded title"
    assert verdict(nurse, from_linkedin("RN Case Manager")) == "pass"  # front-line work, despite "manager"
    db.kv_set("profile.answers", {"target_roles": ["Electrician"]})
    apprentice = make_cfg(levels=["apprenticeship"])
    assert verdict(apprentice, job(title="Electrician Apprentice")) == "pass"
    assert verdict(apprentice, from_linkedin("Journeyman Electrician")) == "too senior / excluded title"
    db.kv_set("profile.answers", {"target_roles": ["Kindergarten Teacher"]})
    assert verdict(make_cfg(levels=["entry"]), from_linkedin("Teacher - Grade 3")) == "pass"  # a grade, not a level


def test_excluded_companies_keywords_old_and_incomplete_postings():
    cfg = make_cfg()
    cfg["filters"].update(exclude_companies=["Blocked"], exclude_keywords=["active clearance"])
    assert verdict(cfg, job(company="Blocked Corp")) == "excluded company"
    assert verdict(cfg, job(description="Requires an ACTIVE CLEARANCE.")) == "excluded keyword"
    assert verdict(cfg, job(posted_at=(date.today() - timedelta(days=120)).isoformat())) == "too old"
    assert verdict(cfg, job(url="")) == "incomplete"


def test_null_fields_from_a_source_become_empty_text(fake_ai):
    j = RawJob("themuse", "Data Intern", None, "https://jobs.example.com/m", locations=[None, "Columbus, OH"], description=None)
    assert (j.company, j.locations, j.description) == ("", ["Columbus, OH"], "")
    settings.save(make_cfg())
    assert verdict(settings.get(), j) == "pass"
    fake_ai.responses["triage"] = triage_answer(lambda item: 80)

    async def scenario():
        run = pipeline.Pipeline("full")
        try:
            await run.add_jobs("test", [j])
            await run.triage_batch(run.take_batch(10))  # used to fail joining the locations
        finally:
            await run.ctx.close()

    asyncio.run(scenario())
    assert db.one("SELECT company, location FROM leads") == {"company": "", "location": "Columbus, OH"}


def test_dream_companies_may_skip_the_search_area():
    cfg = make_cfg(dream_bypass=True)
    cfg["dream_companies"] = ["Example Robotics"]
    far_dream = job(company="Example Robotics", location="Austin, TX")
    assert verdict(cfg, far_dream) == "pass" and far_dream.dream
    cfg["locations"]["dream_bypass"] = False
    assert verdict(cfg, job(company="Example Robotics", location="Austin, TX")) == "outside your locations"
    # A company board the user starred in the Sources dialog counts as a dream company too.
    assert verdict(make_cfg(dream_bypass=True), job(location="Austin, TX", dream=True)) == "pass"


def test_dream_job_titles_need_their_own_switch():
    cfg = make_cfg(dream_bypass=True, dream_jobs_bypass=False)
    cfg["dream_jobs"] = ["Robotics Intern"]
    assert verdict(cfg, job(title="Robotics Intern", location="Austin, TX")) == "outside your locations"
    cfg["locations"]["dream_jobs_bypass"] = True
    assert verdict(cfg, job(title="Robotics Intern", location="Austin, TX")) == "pass"


def test_profile_dream_companies_count_unless_removed():
    profile.save("search_plan", {"role_families": [], "queries": [], "dream_companies": ["Northwind Labs"], "notes": ""})
    cfg = make_cfg(dream_bypass=True)
    assert verdict(cfg, job(company="Northwind Labs", location="Austin, TX")) == "pass"
    cfg["dream_exclude"] = ["northwind labs"]
    assert verdict(cfg, job(company="Northwind Labs", location="Austin, TX")) == "outside your locations"


def test_pre_score_rewards_the_area_entry_titles_and_skills():
    skills(("Python", "strong"))
    filters = RuleFilters(make_cfg())
    in_area = filters.check(job(description="Python every day."))[2]
    vague = filters.check(job(title="Software Developer", location="Various", strict_titles=False))[2]
    assert in_area == 40 + 10 + 8 + 2  # in the search area, an intern title, one of the candidate's skills in the text
    assert vague == 40


def test_skill_regex_uses_only_the_candidates_skills():
    assert pipeline.skill_regex() is None  # no profile yet, so nothing to reward
    skills(("Python", "strong"), ("Go", "strong"), ("Rust", "listed"))
    # C++ isn't one of their skills, Rust is only listed, and Go is too ambiguous to search for.
    assert pipeline.skill_regex().findall("Python and C++ and Rust, good to go") == ["Python"]
    skills(("C/C++", "working"))
    assert sorted(m.lower() for m in pipeline.skill_regex().findall("C, C++ and C#")) == ["c", "c++"]


def test_triage_location_flag_follows_the_dream_switches():
    cfg = make_cfg(dream_bypass=True, dream_jobs_bypass=False)
    cfg["dream_jobs"] = ["Robotics Intern"]
    assert pipeline.location_ok_by_settings(cfg, True, "Data Intern")
    assert not pipeline.location_ok_by_settings(cfg, False, "Robotics Intern")
    cfg["locations"].update(dream_bypass=False, dream_jobs_bypass=True)
    assert pipeline.location_ok_by_settings(cfg, False, "Robotics Intern")
    assert not pipeline.location_ok_by_settings(cfg, True, "Data Intern")


def test_priority_moves_close_deadlines_up_and_survives_bad_dates():
    soon, later = (date.today() + timedelta(days=3)).isoformat(), (date.today() + timedelta(days=10)).isoformat()
    assert (pipeline.priority(70, soon), pipeline.priority(70, later), pipeline.priority(70, None)) == (90, 78, 70)
    assert pipeline.priority(70, "2026-02-30") == 70  # an impossible date used to crash the whole run
    assert pipeline.priority(None, "rolling") == 0


# ---------------------------------------------------------------- the search run


def test_add_jobs_merges_duplicates_and_known_leads():
    settings.save(make_cfg(allowed=["Ohio"]))
    known = packages.insert_lead({"fingerprint": fingerprint("Contoso", "Data Intern", "Columbus, OH"), "title": "Data Intern",
                                  "company": "Contoso", "url": "https://jobs.example.com/d", "source": "ats", "sources": '["ats"]',
                                  "found": json.dumps([{"source": "ats", "label": "ats", "url": "https://jobs.example.com/d"}])})
    again = RawJob("linkedin", "Data Intern", "Contoso", "https://www.linkedin.com/jobs/view/4012345678/", location="Columbus, OH",
                   strict_titles=False)
    first = RawJob("ats", "Software Engineering Intern", "Fabrikam", "https://jobs.example.com/s1", location="Columbus, OH")
    copy_of_first = RawJob("reddit", "Software Engineering Intern", "Fabrikam", "https://www.reddit.com/r/hiring/1", location="Columbus, OH",
                           strict_titles=False)
    senior = RawJob("linkedin", "Senior Software Engineer", "Fabrikam", "https://jobs.example.com/s2", location="Columbus, OH", strict_titles=False)

    async def scenario():
        run = pipeline.Pipeline("full")
        try:
            await run.add_jobs("test", [again, first, copy_of_first, senior])
            return run
        finally:
            await run.ctx.close()

    run = asyncio.run(scenario())
    assert (run.stats["found"], run.stats["already known"], run.stats["duplicate"], run.stats["candidates"]) == (4, 1, 1, 1)
    assert run.stats["filtered: too senior / excluded title"] == 1
    lead = db.lead_row(db.one("SELECT sources, found FROM leads WHERE id=?", (known,)))
    assert lead["sources"] == ["ats", "linkedin"] and len(lead["found"]) == 2
    (_, pooled), = run.pool.values()
    assert [place["url"] for place in pooled.meta["found"]] == ["https://jobs.example.com/s1", "https://www.reddit.com/r/hiring/1"]


def test_take_batch_takes_turns_across_kinds_of_work():
    async def scenario():
        run = pipeline.Pipeline("full")
        try:
            for i in range(3):
                run.pool[f"swe{i}"] = (90 - i, RawJob("ats", f"Software Developer {i}", "Contoso", f"https://jobs.example.com/{i}"))
            run.pool["cyber"] = (50, RawJob("ats", "Cybersecurity Analyst", "Contoso", "https://jobs.example.com/c"))
            return [fp for fp, _ in run.take_batch(2)], set(run.pool)
        finally:
            await run.ctx.close()

    picked, left = asyncio.run(scenario())
    assert picked == ["swe0", "cyber"]  # the lower-scored security job still gets a turn
    assert left == {"swe1", "swe2"}


def test_backlog_keeps_each_candidates_own_rule_score():
    async def scenario():
        first = pipeline.Pipeline("full")
        first.pool["fp1"] = (50.0, RawJob("ats", "Data Intern", "Contoso", "https://jobs.example.com/d"))
        assert first.save_backlog() == 1
        await first.ctx.close()
        db.ex("UPDATE candidates SET first_seen=?", ((date.today() - timedelta(days=3)).isoformat(),))  # first seen 3 days ago
        second = pipeline.Pipeline("full")
        assert second.load_backlog() == 1
        assert second.pool["fp1"][0] == 59  # 3 points for each day it waited
        second.save_backlog()  # the triage cap missed it again
        await second.ctx.close()

    asyncio.run(scenario())
    assert db.one("SELECT rule_score FROM candidates WHERE fingerprint='fp1'")["rule_score"] == 50  # the bonus doesn't pile up


def triage_answer(score_for) -> callable:
    """A fake triage AI that scores each item with score_for(item)."""
    def answer(prompt: str) -> dict:
        results = []
        for item in json.loads(prompt):
            score = score_for(item)
            results.append({"id": item["id"], "score": score, "verdict": "strong" if score >= 60 else "no", "eligibility": "eligible",
                            "category": "internship", "summary": "", "reasons": [], "red_flags": [], "genres": ["robotics"],
                            "industry": "Manufacturing"})
        return {"results": results}
    return answer


def test_triage_saves_leads_and_tells_the_ai_about_the_dream_job_switch(fake_ai):
    cfg = make_cfg(allowed=["Ohio"], dream_bypass=False, dream_jobs_bypass=True)
    cfg["dream_jobs"] = ["Robotics Intern"]
    settings.save(cfg)
    fake_ai.responses["triage"] = triage_answer(lambda item: 80 if item["title"] == "Robotics Intern" else 30)

    async def scenario():
        run = pipeline.Pipeline("full")
        try:
            await run.add_jobs("test", [RawJob("ats", "Robotics Intern", "Contoso", "https://jobs.example.com/r", location="Austin, TX"),
                                        RawJob("ats", "Software Engineering Intern", "Fabrikam", "https://jobs.example.com/s", location="Columbus, OH")])
            await run.triage_batch(run.take_batch(10))
            return run
        finally:
            await run.ctx.close()

    run = asyncio.run(scenario())
    items = json.loads(next(c for c in fake_ai.calls if c["purpose"] == "triage")["prompt"])
    assert {i["title"]: i["location_ok_by_their_settings"] for i in items} == {"Robotics Intern": True, "Software Engineering Intern": False}
    leads = {r["title"]: r for r in db.q("SELECT title, stage, dream, industry FROM leads")}
    assert leads["Robotics Intern"]["stage"] == "qualified" and leads["Robotics Intern"]["dream"] == 1
    assert leads["Software Engineering Intern"]["stage"] == "filtered"
    assert run.package_q.qsize() == 1 and run.stats["qualified"] == 1 and run.stats["below threshold"] == 1


def test_a_triage_result_without_a_score_costs_only_that_job(fake_ai):
    settings.save(make_cfg(allowed=["Ohio"]))

    def answer(prompt: str) -> dict:  # the AI leaves the score out for one job and writes the other one's as text
        return {"results": [{"id": item["id"], "verdict": "strong", "eligibility": "eligible", "summary": "", "genres": [],
                             **({"score": "88"} if item["title"] == "Data Intern" else {})} for item in json.loads(prompt)]}

    fake_ai.responses["triage"] = answer

    async def scenario():
        run = pipeline.Pipeline("full")
        try:
            await run.add_jobs("test", [job("Data Intern", url="https://jobs.example.com/d"), job(url="https://jobs.example.com/s")])
            await run.triage_batch(run.take_batch(10))
            return run
        finally:
            await run.ctx.close()

    run = asyncio.run(scenario())
    assert {r["title"]: (r["stage"], r["score"]) for r in db.q("SELECT title, stage, score FROM leads")} == {"Data Intern": ("qualified", 88)}
    assert run.stats["triage missing"] == 1 and run.stats["qualified"] == 1


def test_retriage_tells_the_ai_when_a_dream_lead_may_be_anywhere(fake_ai):
    settings.save(make_cfg(allowed=["Ohio"], dream_bypass=True))
    dream = packages.insert_lead({"fingerprint": "a", "title": "Robotics Intern", "company": "Example Robotics", "location": "Austin, TX",
                                  "kind": "posting", "source": "ats", "stage": "filtered", "score": 40, "dream": 1})
    plain = packages.insert_lead({"fingerprint": "b", "title": "Data Intern", "company": "Contoso", "location": "Austin, TX",
                                  "kind": "posting", "source": "ats", "stage": "qualified", "score": 70, "dream": 0})
    fake_ai.responses["retriage"] = triage_answer(lambda item: 85 if item["location_ok_by_their_settings"] else 20)
    assert asyncio.run(pipeline.retriage_leads(reason="test")) == {"ok": True, "checked": 2, "promoted": 1, "demoted": 1}
    assert db.one("SELECT stage FROM leads WHERE id=?", (dream,))["stage"] == "qualified"
    assert db.one("SELECT stage FROM leads WHERE id=?", (plain,))["stage"] == "filtered"


def test_retriage_leaves_alone_a_lead_packaged_while_the_ai_worked(fake_ai):
    settings.save(make_cfg(allowed=["Ohio"]))
    lead_id = packages.insert_lead({"fingerprint": "p", "title": "Data Intern", "company": "Contoso", "location": "Columbus, OH",
                                    "kind": "posting", "source": "ats", "stage": "qualified", "score": 70})

    def answer(prompt: str) -> dict:
        db.update_lead(lead_id, stage="ready", resume_md="# Jordan Rivera")  # the run's package worker finishes it meanwhile
        return triage_answer(lambda item: 20)(prompt)

    fake_ai.responses["retriage"] = answer
    assert asyncio.run(pipeline.retriage_leads(reason="test"))["checked"] == 0
    assert db.one("SELECT stage, score FROM leads WHERE id=?", (lead_id,)) == {"stage": "ready", "score": 70}


def test_retag_industries_saves_only_valid_answers_for_leads_it_sent(fake_ai):
    first = packages.insert_lead({"fingerprint": "r1", "title": "Data Intern", "company": "Contoso", "industry": "Other"})
    second = packages.insert_lead({"fingerprint": "r2", "title": "Tutor", "company": "Example Academy", "industry": "Other"})
    fake_ai.responses["retag-industries"] = {"results": [{"id": first, "industry": "Education"}, {"id": second, "industry": "Made-up industry"},
                                                         {"id": 999, "industry": "Education"}]}
    assert asyncio.run(pipeline.retag_industries()) == 1
    assert db.one("SELECT industry FROM leads WHERE id=?", (first,))["industry"] == "Education"
    assert db.one("SELECT industry FROM leads WHERE id=?", (second,))["industry"] == "Other"


PACKAGE_OUT = {
    "title": "Software Engineering Intern", "company": "Example Robotics", "location": "Columbus, OH", "industry": "Manufacturing",
    "fit": {"score": 82, "summary": "", "strengths": [], "gaps": [], "eligibility_notes": ""}, "posting_status": "open",
    "apply_url": "https://jobs.example.com/apply", "deadline": "", "job_summary": "", "keywords": ["Python"],
    "resume_strategy": {"archetype": "general", "theme": "modern", "section_order": [], "summary": "", "projects": [], "skills_grouping": "",
                        "max_pages": 1, "rationale": ""},
    "resume_md": "# Jordan Rivera\n\n## Skills\n- Python", "cover_letter_md": "Dear team,", "emails": [], "linkedin_note": "", "contacts": [],
    "application_answers": [], "interview_prep_md": "", "company_brief_md": "", "action_plan": [],
    "questions_for_candidate": [{"question": "Which Python projects did you ship?", "why": "The posting stresses Python.", "field": "project_bank"}],
}


@pytest.fixture
def no_rendering(monkeypatch):
    """Package work without a PDF engine or the network: a fixed resume check, no PDFs, and a canned posting fetch."""
    async def fake_check(md, keywords, style, archetype=""):
        return {"score": 90, "issues": [], "coverage": 1.0, "unverified_skills": [], "pages": 1, "max_pages": style.get("max_pages", 1)}

    async def fake_render(lead_id):
        return {}

    async def fake_fetch(ctx, url, meta=None):
        return {"description": "Build internal tools in Python for the robotics team. " * 20}

    monkeypatch.setattr(packages, "check_resume", fake_check)
    monkeypatch.setattr(packages, "render_files", fake_render)
    monkeypatch.setattr(packages.details, "fetch", fake_fetch)


@pytest.fixture
def ready_to_search():
    """A finished setup (resume, standard answers, built profile) and settings with every real source turned off."""
    db.kv_set("profile.resume", {"text": "# Jordan Rivera", "name": "resume.md"})
    db.kv_set("profile.answers", {"_saved_at": db.now(), "target_roles": ["Software Engineer", "Data Analyst"]})
    db.kv_set("profile.built_at", db.now())
    cfg = make_cfg(allowed=["Ohio"])
    for source in cfg["sources"].values():
        source["enabled"] = False
    cfg["sources"]["fake"] = {"enabled": True}
    cfg["run"]["max_packages"] = 1
    settings.save(cfg)


def fake_source(monkeypatch, *jobs: RawJob) -> None:
    """Register a collector that returns these jobs, and make the run's waits instant."""
    async def collect(ctx):
        return list(jobs)

    real_sleep = asyncio.sleep

    async def quick_sleep(_seconds):
        await real_sleep(0)  # still lets other tasks run, without the real wait

    monkeypatch.setitem(collectors.COLLECTORS, "fake", ("Fake source", collect))
    monkeypatch.setattr(pipeline.asyncio, "sleep", quick_sleep)


async def run_to_the_end(mode: str) -> int:
    """Start a search run in this mode and wait for it to finish. Returns its run id."""
    run_id = await pipeline.start(mode)
    await pipeline._current.task
    return run_id


def test_a_whole_run_finds_triages_and_packages(fake_ai, no_rendering, ready_to_search, monkeypatch):
    fake_source(monkeypatch, RawJob("fake", "Software Engineering Intern", "Example Robotics", "https://jobs.example.com/1", location="Columbus, OH"),
                RawJob("fake", "Data Intern", "Contoso", "https://jobs.example.com/2", location="Columbus, OH"))
    fake_ai.responses["triage"] = triage_answer(lambda item: 85 if item["title"].startswith("Software") else 30)
    fake_ai.responses["package"] = copy.deepcopy(PACKAGE_OUT)
    fake_ai.responses["resume-review"] = {"resume_md": PACKAGE_OUT["resume_md"], "changes": []}
    run_id = asyncio.run(run_to_the_end("boards"))
    run = db.one("SELECT status, stats FROM runs WHERE id=?", (run_id,))
    stats = json.loads(run["stats"])
    assert run["status"] == "done" and pipeline._current is None
    assert [stats[k] for k in ("found", "candidates", "triaged", "qualified", "packaged")] == [2, 2, 2, 1, 1]
    assert {r["title"]: r["stage"] for r in db.q("SELECT title, stage FROM leads")} == {"Software Engineering Intern": "ready",
                                                                                         "Data Intern": "filtered"}


def test_two_quick_starts_make_one_run(fake_ai, ready_to_search, monkeypatch):
    fake_source(monkeypatch)

    async def scenario():
        first = await pipeline.start("boards")
        with pytest.raises(RuntimeError, match="already in progress"):
            await pipeline.start("boards")  # a double click: the first run's task hasn't had its first turn yet
        await pipeline._current.task
        return first

    run_id = asyncio.run(scenario())
    assert [row["id"] for row in db.q("SELECT id FROM runs")] == [run_id] and pipeline._current is None


def test_stop_puts_the_lead_being_packaged_back_in_the_queue(fake_ai, no_rendering, ready_to_search, monkeypatch):
    fake_source(monkeypatch, RawJob("fake", "Software Engineering Intern", "Example Robotics", "https://jobs.example.com/1", location="Columbus, OH"))
    fake_ai.responses["triage"] = triage_answer(lambda item: 85)

    def stopped_while_packaging(prompt):
        run = pipeline._current
        run.cancel.set()  # what Stop does to the run...
        run.task.cancel()
        raise asyncio.CancelledError()  # ...and to the AI request that was running

    fake_ai.responses["package"] = stopped_while_packaging
    run_id = asyncio.run(run_to_the_end("boards"))
    assert db.one("SELECT status FROM runs WHERE id=?", (run_id,))["status"] == "stopped"
    assert db.one("SELECT stage FROM leads")["stage"] == "qualified"  # not stuck in "packaging"


# ---------------------------------------------------------------- per-lead work


def test_build_package_saves_the_package_and_marks_the_lead_ready(fake_ai, no_rendering):
    lead_id = packages.add_manual_lead("https://jobs.example.com/9", "Short text.")
    fake_ai.responses["package"] = copy.deepcopy(PACKAGE_OUT)
    fake_ai.responses["resume-review"] = {"resume_md": "# Jordan Rivera\n\n## Skills\n- Python, SQL", "changes": ["Added SQL"]}
    summary = asyncio.run(packages.build_package(lead_id))
    lead = db.lead_row(db.one("SELECT * FROM leads WHERE id=?", (lead_id,)))
    assert summary["stage"] == "ready" and summary["score"] == 82
    assert lead["title"] == "Software Engineering Intern" and lead["company"] == "Example Robotics"  # the placeholders were replaced
    assert lead["apply_url"] == "https://jobs.example.com/apply" and lead["industry"] == "Manufacturing"
    assert lead["resume_md"].endswith("Python, SQL") and lead["package"]["resume_style"] == {"theme": "modern", "max_pages": 1}
    assert "resume_md" not in lead["package"] and "_tokens" not in lead["package"]
    assert "Build internal tools" in lead["description"]  # the short pasted text was replaced by the full posting
    assert [q["question"] for q in profile.questions()] == ["Which Python projects did you ship?"]


def test_a_failed_package_is_marked_as_an_error(fake_ai, no_rendering):
    lead_id = packages.add_manual_lead("https://jobs.example.com/11", "x" * 700)
    with pytest.raises(ai.AIError):  # the fake AI has no answer for "package"
        asyncio.run(packages.build_package(lead_id))
    row = db.one("SELECT stage, stage_error FROM leads WHERE id=?", (lead_id,))
    assert row["stage"] == "error" and "no fake response" in row["stage_error"]


def test_package_corrections_only_replace_guesses():
    package = {"title": "Data Engineering Intern", "company": "Contoso", "location": "Remote", "industry": "Education",
               "apply_url": "mailto:jobs@example.com", "deadline": "2026-12-01T00:00"}
    board_lead = {"source": "ats", "title": "Data Intern", "company": "Contoso", "location": "", "industry": "Other"}
    assert packages._corrections(board_lead, package, settings.get()) == {"location": "Remote", "deadline": "2026-12-01"}
    reddit_lead = {"source": "reddit", "title": "[Hiring] interns!", "company": "", "location": "Columbus", "industry": ""}
    assert packages._corrections(reddit_lead, package, settings.get()) == {
        "title": "Data Engineering Intern", "company": "Contoso", "location": "Remote", "industry": "Education", "deadline": "2026-12-01"}


def test_two_jobs_pasted_as_text_become_two_leads():
    first = packages.add_manual_lead(text="Help desk technician at a public library.")
    second = packages.add_manual_lead(text="Junior data analyst for a food bank.")
    assert first != second and db.one("SELECT COUNT(*) n FROM leads")["n"] == 2


def test_gap_questions_keep_edits_made_while_the_ai_works(fake_ai):
    lead_id = packages.add_manual_lead("https://jobs.example.com/12", "x" * 700, "Data Intern", "Contoso")
    db.update_lead(lead_id, resume_md="# Jordan Rivera", package={"keywords": ["SQL"]})

    def ask(prompt):
        db.update_lead(lead_id, package={"keywords": ["SQL"], "notes": "edited meanwhile"})  # the user saves an edit mid-call
        return {"questions": [{"question": "Have you used SQL at work?", "why": "The posting asks for it.", "field": "skills"}]}

    fake_ai.responses["gap-questions"] = ask
    assert asyncio.run(packages.gap_questions(lead_id)) == 1
    assert db.lead_row(db.one("SELECT package FROM leads WHERE id=?", (lead_id,)))["package"]["notes"] == "edited meanwhile"


def test_a_resume_recheck_keeps_package_edits_saved_while_it_ran(no_rendering, monkeypatch):
    lead_id = packages.add_manual_lead("https://jobs.example.com/16", "x" * 700, "Data Intern", "Contoso")
    db.update_lead(lead_id, resume_md="# Jordan Rivera", package={"keywords": ["SQL"]})
    real_check = packages.check_resume

    async def check_while_the_user_saves(md, keywords, style, archetype=""):
        db.update_lead(lead_id, package={"keywords": ["SQL"], "plan_done": [0, 1]})  # the lead page saves its checklist
        return await real_check(md, keywords, style, archetype)

    monkeypatch.setattr(packages, "check_resume", check_while_the_user_saves)
    assert asyncio.run(packages.recheck_resume(packages._load_lead(lead_id)))["score"] == 90
    package = packages._load_lead(lead_id)["package"]
    assert package["plan_done"] == [0, 1] and package["resume_check"]["score"] == 90


def test_a_reworked_resume_keeps_package_edits_saved_while_the_ai_worked(fake_ai, no_rendering):
    lead_id = packages.add_manual_lead("https://jobs.example.com/17", "x" * 700, "Data Intern", "Contoso")
    db.update_lead(lead_id, resume_md="# Jordan Rivera", package={"keywords": ["SQL"]})
    item = {"id": 1, "name": "General resume", "md": "# Jordan Rivera\n\n## Skills\n- SQL", "style": {}}

    def tailor(prompt):
        db.update_lead(lead_id, package={"keywords": ["SQL"], "contacts": [{"name": "Riley Chen"}]})  # added on the lead page
        return {"text": item["md"], "change_summary": "Tailored"}

    fake_ai.responses["library-tailor"] = tailor
    fake_ai.responses["resume-review"] = {"resume_md": item["md"], "changes": []}
    asyncio.run(packages.use_saved_resume(lead_id, item, tailor=True))
    package = packages._load_lead(lead_id)["package"]
    assert package["contacts"] == [{"name": "Riley Chen"}] and package["resume_from_library"] == 1


def test_revising_a_lead_resume_follows_the_playbook_and_its_page_limit(fake_ai):
    from jobportal.documents import revise
    lead_id = packages.add_manual_lead("https://jobs.example.com/18", "x" * 700, "Data Intern", "Contoso")
    db.update_lead(lead_id, resume_md="# Jordan Rivera", package={"resume_style": {"theme": "modern", "max_pages": 2}})
    fake_ai.responses["revise:resume"] = {"text": "# Jordan Rivera", "change_summary": "Shorter"}
    asyncio.run(revise.revise_lead_document(packages._load_lead(lead_id), "resume", "Make it shorter", "# Jordan Rivera"))
    call = fake_ai.calls[-1]
    assert "=== RESUME PLAYBOOK ===" in call["system"] and "layout modern, page limit 2" in call["prompt"]


def test_use_saved_resume_as_is(no_rendering):
    lead_id = packages.add_manual_lead("https://jobs.example.com/13", "x" * 700, "Data Intern", "Contoso")
    db.update_lead(lead_id, package={"keywords": ["Python", "SQL"]})
    item = {"id": 5, "name": "General resume", "md": "# Jordan Rivera\n\n## Skills\n- Python", "style": {"theme": "compact"}}
    assert asyncio.run(packages.use_saved_resume(lead_id, item, tailor=False)) == {"ok": True, "change_summary": "", "coverage": 0.5,
                                                                                   "check": 90}
    lead = db.lead_row(db.one("SELECT resume_md, package FROM leads WHERE id=?", (lead_id,)))
    assert lead["resume_md"] == item["md"] and lead["package"]["resume_from_library"] == 5
    assert lead["package"]["resume_style"] == {"theme": "compact", "max_pages": 1}


def test_apply_answers_needs_an_answer_first():
    lead_id = packages.add_manual_lead("https://jobs.example.com/14", "x" * 700, "Data Intern", "Contoso")
    assert asyncio.run(packages.apply_answers(lead_id)) == {"ok": False, "message": "Answer at least one question first."}


def test_apply_answers_reworks_the_resume_and_marks_the_answers_used(fake_ai, no_rendering):
    cfg = settings.get()
    cfg["profile"]["auto_analyze"] = False
    settings.save(cfg)
    lead_id = packages.add_manual_lead("https://jobs.example.com/15", "x" * 700, "Data Intern", "Contoso")
    db.update_lead(lead_id, resume_md="# Jordan Rivera\n\n## Skills\n- Python", package={"keywords": ["Python", "SQL"]})
    db.kv_set("profile.built_at", db.now())
    profile.ask("Have you used SQL?", "The posting asks for it.", lead_id=lead_id)
    profile.answer_question("Have you used SQL?", "Yes, in my database course project.")
    fake_ai.responses["profile-update"] = {"changes": [], "open_questions": []}
    fake_ai.responses["apply-answers"] = {"text": "# Jordan Rivera\n\n## Skills\n- Python, SQL", "change_summary": "Added SQL"}
    fake_ai.responses["resume-review"] = {"resume_md": "# Jordan Rivera\n\n## Skills\n- Python, SQL", "changes": []}
    assert asyncio.run(packages.apply_answers(lead_id)) == {"ok": True, "change_summary": "Added SQL", "coverage": 1.0}
    assert "A: Yes, in my database course project." in next(c for c in fake_ai.calls if c["purpose"] == "apply-answers")["prompt"]
    assert [q["status"] for q in profile.questions()] == ["applied"]
    lead = db.lead_row(db.one("SELECT resume_md, package FROM leads WHERE id=?", (lead_id,)))
    assert lead["resume_md"].endswith("Python, SQL") and lead["package"]["original_resume_md"] == lead["resume_md"]


# ---------------------------------------------------------------- collectors


def test_linkedin_locations():
    assert linkedin.li_locations(["Nationwide", "Remote", "OH", "new york", "DC", "Pittsburgh, PA", " "]) == [
        ("United States", {}), ("United States", {"f_WT": "2"}), ("Ohio, United States", {}), ("New York, United States", {}),
        ("Washington, District of Columbia, United States", {}), ("Pittsburgh, PA", {})]


CARD = """<li><div data-entity-urn="urn:li:jobPosting:4012345678"><h3 class="base-search-card__title"> Software Engineering Intern </h3>
<h4 class="base-search-card__subtitle"><a>Example Robotics</a></h4><span class="job-search-card__location">Columbus, OH</span>
<time datetime="2026-10-27">2 days ago</time></div></li>"""


def test_linkedin_search_runs_to_the_end(monkeypatch):
    cfg = make_cfg(allowed=["Ohio", "Remote"], dream_bypass=False)
    cfg["search"]["queries"] = ["software engineer intern"]
    logs = []

    class Page:
        status_code, text = 200, CARD

    async def fake_request(method, url, **kw):
        assert "keywords=software+engineer+intern" in url and "f_E=1%2C2" in url  # internship and entry level
        return Page()

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(linkedin.asyncio, "sleep", no_wait)

    async def scenario():
        ctx = Ctx(cfg, lambda source, msg, level="info": logs.append(msg))
        ctx.request = fake_request
        try:
            return await linkedin.collect(ctx)
        finally:
            await ctx.close()

    jobs = asyncio.run(scenario())
    assert len(jobs) == 1  # both searches return the same card, kept once
    assert jobs[0].url == jobs[0].found_url == "https://www.linkedin.com/jobs/view/4012345678/"
    assert jobs[0].title == "Software Engineering Intern" and not jobs[0].strict_titles
    assert logs[-1] == "2 searches found 1 unique postings"


def test_linkedin_backs_off_when_blocked_and_counts_what_it_did(monkeypatch):
    cfg = make_cfg(allowed=["Ohio", "Remote", "Pittsburgh, PA"], dream_bypass=False)
    cfg["search"]["queries"] = ["nurse", "medical assistant", "phlebotomist"]  # nine searches in all
    logs, waits = [], []

    class Blocked:
        status_code, text = 999, ""  # LinkedIn's own "go away" answer

    async def fake_request(method, url, **kw):
        return Blocked()

    async def record_wait(seconds):
        waits.append(seconds)

    monkeypatch.setattr(linkedin.asyncio, "sleep", record_wait)

    async def scenario():
        ctx = Ctx(cfg, lambda source, msg, level="info": logs.append(msg))
        ctx.request = fake_request
        try:
            return await linkedin.collect(ctx)
        finally:
            await ctx.close()

    assert asyncio.run(scenario()) == []
    assert logs[-1] == "3 searches found 0 unique postings"  # stopped after three blocks, and says so
    assert waits.count(linkedin.BACKOFF_SECONDS) == 2 and len(waits) == 4  # a pause before each later search, plus back-offs


def test_hunt_rotates_missions_and_respects_levels():
    cfg = make_cfg()
    cfg["sources"]["ai_hunt"].update(missions_per_run=2, missions=[
        {"id": "a", "name": "A", "prompt": ""}, {"id": "b", "name": "B", "prompt": ""}, {"id": "c", "name": "C", "prompt": ""},
        {"id": "off", "name": "Off", "prompt": "", "enabled": False},
        {"id": "senior", "name": "Senior only", "prompt": "", "only_levels": ["senior"]}])

    def ids(missions):
        return [m["id"] for m in missions]

    assert ids(hunt.pick_missions(cfg, all_missions=False)) == ["a", "b"]
    assert ids(hunt.pick_missions(cfg, all_missions=False)) == ["c", "a"]
    assert ids(hunt.pick_missions(cfg, all_missions=True)) == ["a", "b", "c"]


def test_one_bad_term_or_item_costs_only_itself():
    import httpx

    from jobportal.search.collectors import github_lists
    cfg = make_cfg(levels=["internship"])  # several search terms: intern, co-op, student
    ctx = Ctx(cfg, lambda *a, **k: None)
    board = {"name": "Example Health", "url": "https://careers-example.icims.com"}
    calls = []

    async def unreachable(url, payload, **kw):
        calls.append(url)
        raise httpx.ConnectError("no route to host")

    ctx.post_json = unreachable
    with pytest.raises(httpx.ConnectError):  # a dead site ends the board at once: no 50 second retries for every term
        asyncio.run(ats.workday(ctx, {**board, "url": "https://example.wd5.myworkdayjobs.com/External"}))
    assert len(calls) == 1

    card = ('<div class="iCIMS_JobCardItem"><a href="https://careers-example.icims.com/jobs/{n}/nurse">'
            '<h3>Nurse Intern {n}</h3></a></div>')

    async def one_refused_term(url, **kw):
        if "searchKeyword=co-op" in url:
            raise httpx.HTTPStatusError("500", request=httpx.Request("GET", url), response=httpx.Response(500))
        return card.format(n=len(url))

    ctx.get_text = one_refused_term
    assert len(asyncio.run(ats.icims(ctx, board))) >= 2  # the other terms' postings are kept

    async def null_place(url, payload, **kw):
        return {"opportunities": [{"Title": "Medical Assistant", "Id": "1", "Locations": [{"Address": {}, "LocalizedName": None}]}]}

    ctx.post_json = null_place
    assert asyncio.run(ats.ukg(ctx, {**board, "url": "https://recruiting.ultipro.com/EXA1000/JobBoard/0a1b"}))[0].locations == []

    async def lists(url, **kw):
        return ["not a listing", {"title": "Data Intern", "company_name": "Contoso", "url": "https://jobs.example.com/g",
                                  "locations": [None, "Columbus, OH"], "terms": [None, "Summer 2027"]}]

    _targets(["Software Engineer"])  # the lists only run for tech targets
    ctx.get_json = lists
    jobs = asyncio.run(github_lists.collect(ctx))
    assert jobs and all(j.location == "Columbus, OH" for j in jobs)
    asyncio.run(ctx.close())


def test_detect_company_boards_from_links():
    assert ats.detect("https://job-boards.greenhouse.io/examplerobotics/jobs/123") == {"ats": "greenhouse", "slug": "examplerobotics"}
    assert ats.detect("https://boards.greenhouse.io/embed/job_board?for=example-robotics") == {"ats": "greenhouse", "slug": "example-robotics"}
    assert ats.detect("https://boards.greenhouse.io/embed/job_board?for=") is None  # used to raise an error
    assert ats.detect("https://example.wd5.myworkdayjobs.com/en-US/External/job/Columbus") == {
        "ats": "workday", "url": "https://example.wd5.myworkdayjobs.com/External"}
    assert ats.detect("https://jobs.lever.co/example/abc") == {"ats": "lever", "slug": "example"}
    assert ats.detect("https://careers-example.icims.com/jobs/1/intern") == {"ats": "icims", "url": "https://careers-example.icims.com"}
    assert ats.detect("https://example.com/careers") is None
    # The systems' own websites aren't boards, and a board id may be written in capitals.
    for site in ("https://www.greenhouse.io/privacy-policy", "https://www.lever.co/careers", "https://www.ashbyhq.com/careers"):
        assert ats.detect(site) is None, site
    guid = "0A1B2C3D-4E5F-6789-ABCD-EF0123456789"
    assert ats.detect(f"https://recruiting.ultipro.com/EXA1000EXMP/JobBoard/{guid}/?q=nurse") == {
        "ats": "ukg", "url": f"https://recruiting.ultipro.com/EXA1000EXMP/JobBoard/{guid}"}
    assert ats.detect("https://[x") is None  # a broken address, which used to raise


def test_a_lever_posting_keeps_its_closing_section():
    posting = {"descriptionPlain": "Help patients.", "lists": [{"text": "Requirements", "content": "<ul><li>CPR</li></ul>"}],
               "additionalPlain": "Pay: $22 an hour"}
    text = ats.lever_description(posting)  # a single posting's fetch (details.py) used to drop the pay and benefits part
    assert text.startswith("Help patients.") and "Requirements:" in text and text.endswith("Pay: $22 an hour")


def test_posting_details_from_odd_pages():
    from jobportal.search.collectors import details
    # A JobPosting may name its place as plain text, or give an address as plain text.
    assert details._ld_location({"jobLocation": "Remote"}) == "Remote"
    assert details._ld_location({"jobLocation": [{"address": "Columbus, OH"},
                                                 {"address": {"addressLocality": "Austin", "addressRegion": "TX"}}]}) == "Columbus, OH | Austin, TX"
    # LinkedIn's apply redirect carries the real address encoded once, and that address keeps its own escapes.
    real = "https://jobs.example.com/apply?return=https%3A%2F%2Fexample.com%2F%3Fa%3D1%26b%3D2"
    page = f'<code id="applyUrl"><!--"https://www.linkedin.com/jobs/view/externalApply/4012345678?url={quote(real, safe="")}&urlHash=x"--></code>'
    ctx = Ctx(make_cfg(), lambda *a, **k: None)
    downloads = []

    async def get_text(url, **kw):
        return page

    async def get_json(url, **kw):  # one Ashby board, slow to download
        downloads.append(url)
        await asyncio.sleep(0.01)
        return {"jobs": [{"id": "a1", "descriptionPlain": "Care for patients."}, {"id": "a2", "descriptionPlain": "Answer phones."}]}

    ctx.get_text, ctx.get_json = get_text, get_json

    async def scenario():
        linked = await details.linkedin_detail(ctx, "4012345678")
        both = await asyncio.gather(details.fetch(ctx, "https://jobs.ashbyhq.com/example-health/a1"),
                                    details.fetch(ctx, "https://jobs.ashbyhq.com/example-health/a2"))
        await ctx.close()
        return linked, both

    linked, both = asyncio.run(scenario())
    assert linked["apply_url"] == real  # not decoded a second time, which split its own query at "&b=2"
    assert [d["description"] for d in both] == ["Care for patients.", "Answer phones."] and len(downloads) == 1


def test_a_careers_page_is_searched_past_links_that_are_no_board(monkeypatch):
    from jobportal.search import sources
    page = ('<link rel="preconnect" href="https://boards.greenhouse.io"><a href="https://www.greenhouse.io/privacy">Privacy</a>'
            '<script src="https://boards.greenhouse.io/embed/job_board/js?for=example-health"></script>')

    async def careers_page(self, url, **kw):
        return page

    monkeypatch.setattr(Ctx, "get_text", careers_page)
    assert asyncio.run(sources._board_linked_from("https://example.com/careers")) == {"ats": "greenhouse", "slug": "example-health"}


def test_feeds_read_rss_and_atom():
    rss = """<rss><channel><item><title>Hiring: IT intern</title><link>https://example.com/a</link>
<description>&lt;p&gt;Apply by Friday&lt;/p&gt;</description><pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>New grad role</title><link href="https://example.com/b"/>
<summary>Join us</summary><updated>2026-10-20T00:00:00Z</updated></entry></feed>"""
    assert feeds._parse_feed(rss) == [{"title": "Hiring: IT intern", "link": "https://example.com/a", "summary": "Apply by Friday", "date": "2026-10-27"}]
    assert feeds._parse_feed(atom) == [{"title": "New grad role", "link": "https://example.com/b", "summary": "Join us", "date": "2026-10-20"}]
    assert feeds._parse_feed("not xml") == []


def test_empty_title_include_lets_every_title_through():
    """Mid-level searches have no level words, so the include filter must not drop every job-board title."""
    from jobportal.core import settings
    cfg = settings.get()
    cfg["filters"]["title_include"] = []
    cfg["locations"]["allowed"] = ["Anywhere in the US"]
    job = RawJob("ats_boards", "Software Engineer", "Example Robotics", "https://jobs.example.com/1", location="Austin, TX")
    ok, reason, _ = pipeline.RuleFilters(cfg).check(job)
    assert ok, reason


def test_dream_bypass_covers_the_us_only():
    from jobportal.core import settings
    cfg = settings.get()
    cfg["filters"]["title_include"] = []
    cfg["locations"].update(allowed=["Ohio"], dream_bypass=True)
    cfg["dream_companies"] = ["Example Robotics"]
    filters = pipeline.RuleFilters(cfg)
    job = lambda loc: RawJob("ats_boards", "Software Engineer", "Example Robotics", f"https://jobs.example.com/{loc}", location=loc)  # noqa: E731
    assert filters.check(job("Austin, TX"))[0]  # outside the search area, but a dream company in the US
    assert filters.check(job("Toronto, ON"))[1] == "outside the US"


def _targets(roles: list[str], families: list[str] = ()) -> None:
    """Set the user's target roles (standard answers) and the profile plan's role families."""
    db.kv_set("profile.answers", {"target_roles": roles})
    profile.save("search_plan", {"role_families": list(families), "queries": [], "dream_companies": [], "notes": ""})


def test_sources_learn_the_users_fields_from_their_targets():
    from jobportal.search import plan
    cfg = make_cfg(levels=["internship", "entry"], allowed=["Ohio", "Remote"])
    assert not plan.in_tech(cfg) and plan.fields(cfg) == []  # no targets: no field is assumed, tech least of all
    _targets(["Registered Nurse", "Patient Care Technician"], ["Nursing", "Home health"])
    assert plan.fields(cfg)[0] == "nursing" and plan.groups(cfg)[0] == "healthcare" and not plan.in_tech(cfg)
    ctx = Ctx(cfg, lambda *a, **k: None)
    instances, tags = feeds._mastodon_plan(ctx)
    assert "nursingjobs" in tags and "techjobs" not in tags and "hachyderm.io" not in instances
    assert "internship" in tags and "remotejobs" in tags  # an internship search with Remote allowed
    assert "techjobs" not in feeds._reddit_subreddits(ctx) and "RemoteJobs" in feeds._reddit_subreddits(ctx)
    assert feeds._wwr_feeds(ctx) == [feeds.WWR_FEED.format(feeds.WWR_OTHER)]
    _targets(["Software Engineer", "Data Analyst"])
    assert plan.in_tech(cfg)
    instances, tags = feeds._mastodon_plan(ctx)
    assert "techjobs" in tags and "hachyderm.io" in instances and "techjobs" in feeds._reddit_subreddits(ctx)
    _targets(["Graphic Designer"])
    assert {"DesignJobs", "HungryArtists"} <= set(feeds._reddit_subreddits(ctx))
    asyncio.run(ctx.close())


def test_tech_only_sources_skip_themselves_for_other_fields():
    from jobportal.search.collectors import github_lists
    _targets(["Line Cook", "Barista"])
    logs = []
    ctx = Ctx(make_cfg(), lambda source, msg, level="info": logs.append(msg))

    async def no_network(*args, **kwargs):
        raise AssertionError("a skipped source must not make requests")

    ctx.request = no_network
    assert asyncio.run(github_lists.collect(ctx)) == [] and asyncio.run(feeds.hackernews(ctx)) == []
    assert all("aren't in tech" in line for line in logs)
    asyncio.run(ctx.close())


def test_the_muse_searches_the_users_fields(monkeypatch):
    _targets(["Pastry Chef", "Line Cook"])
    asked = []

    async def fake_get_json(url, **kw):
        asked.append(url)
        return {"results": [], "page_count": 1}

    ctx = Ctx(make_cfg(levels=["entry"]), lambda *a, **k: None)
    ctx.get_json = fake_get_json
    asyncio.run(feeds.themuse(ctx))
    assert "category=Food+and+Hospitality+Services" in asked[0] and "level=Entry+Level" in asked[0]
    asyncio.run(ctx.close())


def test_the_muse_searches_a_states_largest_cities():
    assert feeds._muse_locations(["Maryland", "Remote", "DC", "Pittsburgh, PA"]) == [
        "Baltimore, MD", "Columbia, MD", "Rockville, MD", "Frederick, MD", "Annapolis, MD", "Flexible / Remote", "Washington, DC",
        "Pittsburgh, PA"]
    assert set(textutil.MAJOR_CITIES) == set(textutil.STATES)  # every state and DC
    assert all(len(cities) >= 2 for state, cities in textutil.MAJOR_CITIES.items() if state != "DC")


def test_a_nationwide_search_area_is_no_remote_permission_and_no_place_name():
    ctx = Ctx(make_cfg(allowed=["Anywhere in the US"]), lambda *a, **k: None)
    # The location filter drops remote jobs unless Remote itself is allowed, so the remote boards must not run for them.
    assert not feeds._remote_allowed(ctx)
    assert asyncio.run(feeds.remote_boards(ctx)) == []
    assert feeds._places(ctx) == ["United States"]  # what Adzuna's place search can read
    ctx.cfg["locations"]["allowed"] = ["Remote", "Ohio", "Anywhere", "United States"]
    assert feeds._remote_allowed(ctx) and feeds._places(ctx) == ["Ohio", "United States"]
    asyncio.run(ctx.close())


def test_we_work_remotely_items():
    xml = """<rss><channel><item><title>Example Health: Patient Support Specialist</title><region>USA Only</region>
<link>https://weworkremotely.com/remote-jobs/example-health-patient-support</link><description>&lt;p&gt;Help patients.&lt;/p&gt;</description>
<pubDate>Tue, 27 Oct 2026 10:00:00 +0000</pubDate></item></channel></rss>"""
    assert feeds._wwr_items(xml) == [{"title": "Example Health: Patient Support Specialist", "region": "USA Only",
                                      "link": "https://weworkremotely.com/remote-jobs/example-health-patient-support",
                                      "description": "Help patients.", "date": "2026-10-27"}]
    assert feeds._wwr_items("not xml") == []


def test_hunt_missions_for_some_fields_only():
    cfg = make_cfg()
    cfg["sources"]["ai_hunt"].update(missions_per_run=0, missions=[
        {"id": "all", "name": "Everyone", "prompt": ""}, {"id": "labs", "name": "Labs", "prompt": "", "only_groups": ["science"]}])
    assert [m["id"] for m in hunt.pick_missions(cfg, all_missions=True)] == ["all", "labs"]  # fields unknown: nothing skipped
    _targets(["Retail Sales Associate", "Cashier"])
    assert [m["id"] for m in hunt.pick_missions(cfg, all_missions=True)] == ["all"]
    _targets(["Research Assistant"])
    assert [m["id"] for m in hunt.pick_missions(cfg, all_missions=True)] == ["all", "labs"]


def test_role_words_follow_the_profile_plan_switch():
    from jobportal.candidate import profile
    from jobportal.core import settings
    from jobportal.search import plan
    profile.save("search_plan", {"role_families": ["Robotics software"], "queries": [], "dream_companies": []})
    cfg = settings.get()
    assert "Robotics software" in plan.role_words(cfg)
    cfg["search"]["use_profile_plan"] = False
    assert "Robotics software" not in plan.role_words(cfg)
