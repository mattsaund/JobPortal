"""Reaching more places: the new remote boards (Himalayas, Jobicy, Working Nomads), the Recruitee and Personio company
boards, X's official search, fetch_url opening any public page, and jobs from pasted community posts. Every collector reads
canned replies; nothing here reaches the network."""
import asyncio
import json

from conftest import STANDARD_ANSWERS
from fastapi.testclient import TestClient
from test_search import make_cfg, triage_answer

from jobportal.ai import client as ai
from jobportal.core import db, settings
from jobportal.search import packages, pipeline, posts
from jobportal.search.collectors import COLLECTORS, ats, feeds
from jobportal.search.collectors.base import Ctx


def ctx_with(replies: dict, cfg: dict | None = None) -> tuple[Ctx, list]:
    """A Ctx whose get_json and get_text answer from `replies` (the start of a URL to its reply) and record each URL and
    its headers. A URL with no reply fails, like an unreachable site."""
    asked = []
    ctx = Ctx(cfg or make_cfg(allowed=["Ohio", "Remote"]), lambda *a, **k: None)

    async def answer(url, **kw):
        asked.append((url, kw.get("headers") or {}))
        for start, reply in replies.items():
            if url.startswith(start):
                return reply
        raise RuntimeError(f"no reply for {url}")

    ctx.get_json = answer
    ctx.get_text = answer
    return ctx, asked


def test_three_more_remote_boards():
    db.kv_set("profile.answers", {"target_roles": ["Medical Biller"]})
    replies = {
        "https://himalayas.app/jobs/api/search": {"jobs": [{"title": "Medical Biller", "companyName": "Example Health",
                                                             "applicationLink": "https://example.com/apply/9", "guid": "https://himalayas.app/companies/x/jobs/9",
                                                             "locationRestrictions": ["United States"], "pubDate": 1794700800,
                                                             "description": "<p>Code claims.</p>"}]},
        "https://jobicy.com/api/jobs": {"jobs": [{"jobTitle": "Billing &amp; Coding Specialist", "companyName": "Contoso Care",
                                                   "url": "https://jobicy.com/jobs/1-billing", "jobGeo": "USA", "pubDate": "2026-11-10T09:00:00+00:00",
                                                   "jobDescription": "<p>Remote billing.</p>"}]},
        "https://www.workingnomads.com/api/exposed_jobs/": [{"title": "Claims Specialist", "company_name": "Fabrikam", "url": "https://www.workingnomads.com/job/go/1/",
                                                            "location": "Americas", "pub_date": "2026-11-12T00:00:00", "description": "<p>Claims.</p>"}],
    }
    ctx, asked = ctx_with(replies)
    jobs = {j.source_detail: j for j in asyncio.run(feeds.remote_boards(ctx))}
    himalayas = jobs["Himalayas"]
    assert himalayas.url == "https://example.com/apply/9" and himalayas.found_url.startswith("https://himalayas.app/")  # the link stays as given
    assert himalayas.location == "Remote (United States)" and himalayas.posted_at == "2026-11-15" and himalayas.description == "Code claims."
    assert jobs["Jobicy"].title == "Billing & Coding Specialist" and jobs["Jobicy"].url.startswith("https://jobicy.com/")
    assert jobs["Working Nomads"].location == "Remote (Americas)" and jobs["Working Nomads"].posted_at == "2026-11-12"
    assert any(url.startswith("https://himalayas.app/jobs/api/search?q=") for url, _ in asked)
    asyncio.run(ctx.close())


def test_recruitee_and_personio_boards():
    assert ats.detect("https://examplehealth.recruitee.com/o/nurse") == {"ats": "recruitee", "slug": "examplehealth"}
    assert ats.detect("https://example-labs.jobs.personio.de/job/123") == {"ats": "personio", "url": "https://example-labs.jobs.personio.de"}
    assert ats.detect("https://recruitee.com/pricing") is None and ats.detect("https://www.personio.com/") is None
    recruitee = {"offers": [{"title": "Lab Technician", "careers_url": "https://examplehealth.recruitee.com/o/lab-technician",
                             "locations": [{"city": "Columbus", "country": "United States"}], "remote": True,
                             "description": "<p>Run samples.</p>", "published_at": "2026-11-01 10:00:00 UTC"}]}
    personio = ("<workzag-jobs><position><id>77</id><office>Columbus</office><name>Phlebotomist</name><createdAt>2026-11-02T08:00:00+00:00</createdAt>"
                "<jobDescriptions><jobDescription><name>Your tasks</name><value>&lt;p&gt;Draw blood.&lt;/p&gt;</value></jobDescription></jobDescriptions>"
                "</position></workzag-jobs>")
    ctx, _ = ctx_with({"https://examplehealth.recruitee.com/api/offers/": recruitee, "https://example-labs.jobs.personio.de/xml": personio})
    (lab,) = asyncio.run(ats.recruitee(ctx, {"name": "Example Health", "slug": "examplehealth"}))
    assert lab.title == "Lab Technician" and lab.location == "Columbus, United States | Remote" and lab.description == "Run samples."
    (blood,) = asyncio.run(ats.personio(ctx, {"name": "Example Labs", "url": "https://example-labs.jobs.personio.de"}))
    assert blood.url == "https://example-labs.jobs.personio.de/job/77" and blood.location == "Columbus"
    assert blood.description == "Your tasks\nDraw blood." and blood.posted_at == "2026-11-02"
    asyncio.run(ctx.close())


def test_x_search_with_the_users_own_key():
    db.kv_set("profile.answers", {"target_roles": ["Line Cook"]})
    assert "x" in COLLECTORS and settings.get()["sources"]["x"]["enabled"] is False  # it costs money, so it's off until turned on
    ctx, asked = ctx_with({})
    assert asyncio.run(feeds.x_search(ctx)) == [] and asked == []  # no key, no requests
    cfg = make_cfg(levels=["entry"], allowed=["Ohio"])
    cfg["sources"]["x"].update(bearer_token="x-test-token", searches=1, posts_per_search=10)
    reply = {"data": [{"id": "111", "text": "We're hiring a line cook in Columbus, entry level, apply at example.com", "author_id": "9",
                       "created_at": "2026-11-17T12:00:00.000Z"},
                      {"id": "222", "text": "Great game last night", "author_id": "9"}],
             "includes": {"users": [{"id": "9", "username": "examplebistro", "name": "Example Bistro"}]}}
    ctx, asked = ctx_with({feeds.X_SEARCH: reply}, cfg)
    (post,) = asyncio.run(feeds.x_search(ctx))
    assert post.source == "x" and post.url == "https://x.com/examplebistro/status/111" and post.company == "Example Bistro"
    assert post.posted_at == "2026-11-17" and asked[0][1] == {"Authorization": "Bearer x-test-token"}
    assert "is%3Aretweet" in asked[0][0] and "max_results=10" in asked[0][0]
    asyncio.run(ctx.close())


def test_fetch_url_opens_any_public_page(monkeypatch):
    async def public(host):
        return "93.184.215.14"
    monkeypatch.setattr(ai, "_public_address", public)
    for url in ("https://www.linkedin.com/posts/someone-hiring", "https://x.com/example/status/1", "https://m.facebook.com/groups/1",
                "https://www.ziprecruiter.com/c/Example/Job/Nurse", "https://www.indeed.com/viewjob?jk=1"):
        refusal, target = asyncio.run(ai._check_url(url))
        assert refusal == "" and target["host"] == url.split("/")[2], url


POSTS = """[Nursing jobs Discord] Sam (Example Health): We're hiring two night-shift RNs in Columbus, OH. Apply at https://examplehealth.example.com/jobs/rn-nights or DM me.
[Nursing jobs Discord] Alex: anyone know a good scrubs brand?
[Nursing jobs Discord] Pat: Northwind Clinic needs a medical assistant, part time, Dayton. Email pat@example.com"""


def test_jobs_from_pasted_posts(fake_ai, monkeypatch):
    scored = []

    async def fake_retriage(reason="", stages=(), lead_ids=None):
        scored.append((reason, stages, lead_ids))
    monkeypatch.setattr(pipeline, "retriage_leads", fake_retriage)
    fake_ai.responses["pasted-posts"] = {"jobs": [
        {"title": "Registered Nurse (nights)", "company": "Example Health", "location": "Columbus, OH",
         "url": "https://examplehealth.example.com/jobs/rn-nights", "contact": "DM Sam on the Discord", "posted": "", "details": "Two night-shift RNs."},
        {"title": "Medical Assistant", "company": "Northwind Clinic", "location": "Dayton, OH", "url": "https://invented.example.com/ma",
         "contact": "pat@example.com", "posted": "2026-11-15", "details": "Part time."},
        {"title": "", "company": "Nobody", "location": "", "url": "", "contact": "", "posted": "", "details": "not a job"}]}
    out = asyncio.run(posts.add_posts(POSTS, "Nursing jobs Discord"))
    assert out["found"] == 3 and out["added"] == 2 and out["existing"] == 0
    call = fake_ai.calls[0]
    assert call["stage"] == "triage" and "Never invent" in call["system"] and "WHERE THE POSTS ARE FROM: Nursing jobs Discord" in call["prompt"]
    nurse, assistant = (db.lead_row(db.one("SELECT * FROM leads WHERE id=?", (i,))) for i in out["lead_ids"])
    assert nurse["stage"] == "filtered" and nurse["source"] == "paste" and nurse["source_detail"] == "Pasted posts from Nursing jobs Discord"
    assert nurse["url"] == "https://examplehealth.example.com/jobs/rn-nights" and "How to apply: DM Sam" in nurse["description"]
    assert assistant["url"] == "" and assistant["posted_at"] == "2026-11-15"  # an invented link is dropped: it isn't in the paste
    assert scored == [("pasted posts", ("filtered",), out["lead_ids"])]
    again = asyncio.run(posts.add_posts(POSTS, "Nursing jobs Discord"))
    assert again["added"] == 0 and again["existing"] == 2  # the same jobs aren't added twice


def test_the_paste_route(fake_ai, monkeypatch):
    from jobportal.web.server import app
    fake_ai.responses["pasted-posts"] = {"jobs": []}
    with TestClient(app) as client:
        assert client.post("/api/leads/paste", json={"text": "hi"}).status_code == 400
        assert client.post("/api/leads/paste", json={"text": POSTS}).json() == {"found": 0, "added": 0, "existing": 0, "lead_ids": []}


def test_rescoring_can_be_limited_to_some_leads(fake_ai):
    db.kv_set("profile.answers", STANDARD_ANSWERS)
    settings.save(make_cfg(allowed=["Ohio"]))
    first = packages.insert_lead({"fingerprint": "f1", "title": "Data Intern", "company": "Contoso", "location": "Columbus, OH",
                                  "kind": "posting", "source": "paste", "stage": "filtered", "score": 0})
    packages.insert_lead({"fingerprint": "f2", "title": "IT Intern", "company": "Fabrikam", "location": "Columbus, OH",
                          "kind": "posting", "source": "ats", "stage": "filtered", "score": 30})
    fake_ai.responses["retriage"] = triage_answer(lambda item: 80)
    out = asyncio.run(pipeline.retriage_leads(reason="pasted posts", stages=("filtered",), lead_ids=[first]))
    assert out == {"ok": True, "checked": 1, "promoted": 1, "demoted": 0}
    prompt = json.loads(fake_ai.calls[0]["prompt"])
    assert len(prompt) == 1 and prompt[0]["title"] == "Data Intern"
