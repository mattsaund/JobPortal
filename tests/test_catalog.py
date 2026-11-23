"""The source catalog and the newer company boards: every parser, the field and country routing, the switches, and what happens
when a site fails or says no. Every request is answered by a mock, so nothing here reaches the network, and every employer
and person is fictional."""
import asyncio
import io
import json
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient
from test_search import make_cfg

from jobportal.core import db, settings
from jobportal.search import countries, pipeline, plan
from jobportal.search.collectors import COLLECTORS, ats, base, catalog, details, feeds, readers
from jobportal.search.collectors.base import Blocked, Ctx, RawJob
from jobportal.search.pipeline import RuleFilters, location_ok_by_settings


def reply_for(reply, request) -> httpx.Response:
    """A mock answer: a status number, (status, body), text, a function of the request, or anything else as JSON."""
    if callable(reply):
        return reply_for(reply(request), request)
    if isinstance(reply, httpx.Response):
        return reply
    if isinstance(reply, int):
        return httpx.Response(reply)
    if isinstance(reply, tuple):
        return httpx.Response(reply[0], text=reply[1])
    if isinstance(reply, str):
        return httpx.Response(200, text=reply)
    return httpx.Response(200, json=reply)


def served(routes: dict, cfg: dict | None = None) -> tuple[Ctx, list, list]:
    """A Ctx whose requests are answered from `routes` (the start of a URL to its reply); any other URL gets a 404. Returns
    the Ctx, the (method, URL, body) of each request, and its log lines as (level, message)."""
    asked, log = [], []

    def answer(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append((request.method, url, request.content.decode()))
        for start, reply in routes.items():
            if url.startswith(start):
                return reply_for(reply, request)
        return httpx.Response(404, text="not here")

    ctx = Ctx(cfg or make_cfg(levels=["mid"], allowed=["Ohio", "Remote"]), lambda _s, msg, level="info": log.append((level, msg)))
    asyncio.run(ctx.client.aclose())
    ctx.client = httpx.AsyncClient(transport=httpx.MockTransport(answer), follow_redirects=True)
    return ctx, asked, log


def read(source_id: str, routes: dict, cfg: dict | None = None) -> tuple[list[RawJob], list]:
    """One catalog source's jobs, and the requests it made."""
    ctx, asked, _ = served(routes, cfg)

    async def go():
        try:
            return await catalog.read_source(ctx, catalog.BY_ID[source_id])
        finally:
            await ctx.close()
    return asyncio.run(go()), asked


def board(system: str, routes: dict, cfg: dict | None = None, **entry) -> tuple[list[RawJob], list]:
    """One company board's postings, and the requests it made."""
    ctx, asked, _ = served(routes, cfg)

    async def go():
        try:
            return await ats.HANDLERS[system](ctx, {"ats": system, "name": "Example Works", **entry})
        finally:
            await ctx.close()
    return asyncio.run(go()), asked


def targets(*roles: str) -> None:
    """Save the user's target roles."""
    db.kv_set("profile.answers", {"target_roles": list(roles)})


def only(jobs: list[RawJob]) -> RawJob:
    assert len(jobs) == 1, [j.title for j in jobs]
    return jobs[0]


# ---------------------------------------------------------------- the table


def test_every_entry_is_complete():
    from jobportal.core.genres import GROUPS
    ids = [s.id for s in catalog.SOURCES]
    assert len(ids) == len(set(ids))
    readers_known = {"feed", "json", "xml", "cards", "rows", "livewire", "mathjobs", "discourse", "telegram", *catalog.SPECIAL}
    for s in catalog.SOURCES:
        assert s.group in catalog.GROUPS and s.reader in readers_known and s.name and len(s.name) <= 32, s.id
        assert s.fields == catalog.ALL or set(s.fields) <= set(GROUPS), s.id
        assert s.countries == catalog.WORLD or all(len(c) == 2 and c.isupper() for c in s.countries), s.id
        assert s.reader == "mined" or s.url.startswith("https://"), s.id
        assert not s.keys or (s.auth and s.link), s.id
        if s.posts or s.kind == "event":  # headlines: the rule filters treat these as social posts
            assert s.id in base.SOCIAL_SOURCES, s.id
    assert {i for i in base.SOCIAL_SOURCES if i in catalog.BY_ID} == {s.id for s in catalog.SOURCES if s.posts or s.kind == "event"}


def test_it_is_registered_and_on_by_default():
    assert "catalog" in COLLECTORS and COLLECTORS["catalog"][0] == "Job sites" and "themuse" not in COLLECTORS
    section = settings.get()["sources"]["catalog"]
    assert section["enabled"] is True and section["off"] == [] and set(section["groups"]) == set(catalog.GROUPS)


# ---------------------------------------------------------------- one test per kind of parser


def test_rss_board_with_the_employer_in_the_title():
    feed = """<?xml version="1.0"?><rss version="2.0"><channel>
    <item><title>Example Health: Pediatric Nurse</title><description>Example Health: Join our team of caring people... Columbus, Ohio</description>
    <link>https://jobs.example.org/job/11/pediatric-nurse/?TrackID=1&amp;utm_source=rss</link><pubDate>Mon, 23 Nov 2026 05:00:00 -0500</pubDate></item>
    <item><title>No Place Clinic: Nurse</title><description>We are seeking an experienced... nurse to join</description>
    <link>https://jobs.example.org/job/12/nurse/</link></item></channel></rss>"""
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["pediatric nurse"]
    jobs, asked = read("madgex_nejm", {"https://www.nejmcareercenter.org/jobsrss/": feed}, cfg)
    assert "keywords=pediatric+nurse" in asked[0][1]
    first = jobs[0]
    assert (first.title, first.company, first.location) == ("Pediatric Nurse", "Example Health", "Columbus, Ohio")
    assert first.url == "https://jobs.example.org/job/11/pediatric-nurse/" and first.posted_at == "2026-11-23" and first.source == "madgex_nejm"
    assert jobs[1].location == ""  # text after "..." that isn't a place stays out


def test_atom_feed_with_labels_in_its_summary():
    feed = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title type="html"><![CDATA[registered nurse (R.N.)]]></title>
    <link rel="alternate" type="text/html" href="https://www.jobbank.gc.ca/jobsearch/jobposting/501"/><updated>2026-11-23T08:35:00Z</updated>
    <summary type="html"><![CDATA[<strong>Job number:</strong> 3726587<br /><strong>Location:</strong> Dartmouth (NS) <br /><strong>Employer:</strong> Example Villa<br /><strong>Salary:</strong> $27.00 hourly]]></summary>
    </entry></feed>"""
    cfg = make_cfg(levels=["mid"], allowed=["Toronto, ON"])
    cfg["search"]["queries"] = ["nurse"]
    job = only(read("jobbank_ca", {"https://www.jobbank.gc.ca/": feed}, cfg)[0])
    assert (job.title, job.company, job.location) == ("registered nurse (R.N.)", "Example Villa", "Dartmouth (NS)")
    assert job.meta == {"country": "CA"} and job.posted_at == "2026-11-23"


def test_rss_with_its_own_fields_and_a_passed_deadline():
    feed = """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:ajo="https://academicjobsonline.org/ajo">
    <item rdf:about="https://academicjobsonline.org/ajo/Example/1?rss"><title>Postdoc in Physics</title><link>https://academicjobsonline.org/ajo/Example/1?rss</link>
    <description>A postdoc.</description><ajo:Univ>Example University</ajo:Univ><ajo:City>Columbus</ajo:City><ajo:State>Ohio</ajo:State><ajo:Country>United States</ajo:Country>
    <ajo:PostDate>2026-11-20</ajo:PostDate><ajo:Deadline>2099-01-15</ajo:Deadline></item>
    <item rdf:about="https://academicjobsonline.org/ajo/Example/2?rss"><title>Closed Chair</title><link>https://academicjobsonline.org/ajo/Example/2</link>
    <ajo:Deadline>2020-01-15</ajo:Deadline></item></rdf:RDF>"""
    job = only(read("academic_jobs_online", {"https://academicjobsonline.org/": feed})[0])  # the closed one is left out
    assert (job.company, job.location, job.deadline, job.posted_at) == ("Example University", "Columbus, Ohio, United States", "2099-01-15", "2026-11-20")
    assert job.url == "https://academicjobsonline.org/ajo/Example/1"


def test_xml_records():
    xml = """<nhsJobs><vacancyDetails><id>5</id><title>Practice Nurse</title><description>Join us.</description><employer>Example NHS Trust</employer>
    <salary>Negotiable</salary><closeDate>2099-11-25</closeDate><postDate>2026-11-11T16:41:19.316305427</postDate><url>https://beta.jobs.nhs.uk/candidate/jobadvert/C1</url>
    <locations><location>London, EC1A 7BE</location><location>Leeds, LS1 4AP</location></locations></vacancyDetails></nhsJobs>"""
    cfg = make_cfg(levels=["mid"], allowed=["London"])
    cfg["search"]["queries"] = ["nurse"]
    job = only(read("nhs_jobs", {"https://www.jobs.nhs.uk/": xml}, cfg)[0])
    assert (job.title, job.company, job.deadline) == ("Practice Nurse", "Example NHS Trust", "2099-11-25")
    assert job.location == "London, EC1A 7BE, Leeds, LS1 4AP" or job.locations == ["London, EC1A 7BE", "Leeds, LS1 4AP"]


def test_json_with_a_field_map():
    answer = {"jobs": [{"title": "Registered Nurse", "url": "https://jobs.workable.com/view/abc", "created": "2026-11-17T23:35:43.458Z", "description": "<p>Care.</p>",
                        "company": {"title": "Example Recovery"}, "location": {"city": "Groveport", "subregion": "Ohio", "countryName": "United States"}},
                       {"title": "", "url": "https://jobs.workable.com/view/no-title"}]}
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["nurse"]
    jobs, asked = read("workable_search", {"https://jobs.workable.com/api/v1/jobs": answer}, cfg)
    job = only(jobs)
    assert "query=nurse" in asked[0][1] and "location=Ohio" in asked[0][1]
    assert (job.company, job.location, job.description, job.posted_at) == ("Example Recovery", "Groveport, Ohio, United States", "Care.", "2026-11-17")


def test_json_post_body_carries_the_search_and_the_country():
    answer = {"jvs": [{"title": "Krankenpfleger", "id": "abc", "creationDate": 1795440600000, "description": "Pflege.",
                       "locationMap": {"DE": [None]}, "employer": {"name": "Beispiel Klinik"}}]}
    db.kv_set("profile.answers", {"country": "Germany"})
    cfg = make_cfg(levels=["mid"], allowed=["Germany"])
    cfg["search"]["queries"] = ["Pflege"]
    jobs, asked = read("eures", {"https://europa.eu/eures/": answer}, cfg)
    job = only(jobs)
    sent = json.loads(asked[0][2])
    assert asked[0][0] == "POST" and sent["keywords"][0]["keyword"] == "Pflege" and sent["locationCodes"] == ["de"]
    assert job.location == "Germany" and job.meta == {"country": "DE"} and job.url.endswith("jv-details/abc?lang=en")


def test_html_cards():
    page = """<ul><li class="job-item"><div class="job-item-container"><h3><a aria-label="x" class="job-details-link" href="/jobs/55-0/public-health-nurse">Public Health
    Nurse</a></h3><div class="primaryInfo job-organization">Example County</div><div><span class="job-location">Dayton, OH</span></div></div></li>
    <li class="job-item"><div class="job-item-container"><h3><a class="job-details-link" href="/jobs/55-0/public-health-nurse">Public Health Nurse</a></h3></div></li></ul>"""
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["nurse"]
    job = only(read("neogov", {"https://www.governmentjobs.com/jobs": page}, cfg)[0])  # the same job twice counts once
    assert (job.title, job.company, job.location) == ("Public Health Nurse", "Example County", "Dayton, OH")
    assert job.url == "https://www.governmentjobs.com/jobs/55-0/public-health-nurse"
    assert job.found_url.startswith("https://www.governmentjobs.com/jobs?keyword=nurse")  # a page a person can open


def test_rows_from_one_pattern():
    page = '<a href="/camp-example/highlighted-job/83539-wilderness-trip-leader-32">x</a><a href="/camp-example/highlighted-job/83539-wilderness-trip-leader-32">y</a>'
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["guide"]
    job = only(read("coolworks", {"https://www.coolworks.com/search": page}, cfg)[0])
    assert (job.title, job.company) == ("Wilderness Trip Leader", "Camp Example")
    assert job.url == "https://www.coolworks.com/camp-example/highlighted-job/83539-wilderness-trip-leader-32"


def test_livewire_page():
    record = {"title": " Worship Pastor", "slug": "worship-pastor-1", "published_at": "2026-11-21T03:37:30.000000Z", "description": "<p>Lead worship.</p>",
              "church": {"name": "Example Church"}, "location": [[{"city": "Detroit", "subnational_division": "MI"}], {"s": "arr"}]}
    snapshot = json.dumps({"data": {"jobPosting": [record, {"class": "App"}]}}).replace("&", "&amp;").replace('"', "&quot;")
    job = only(read("churchjobfinder", {"https://churchjobfinder.com/": f'<div wire:snapshot="{snapshot}"></div>'})[0])
    assert (job.title, job.company, job.location) == ("Worship Pastor", "Example Church", "Detroit, MI")
    assert job.url == "https://churchjobfinder.com/church-jobs/worship-pastor-1" and job.description == "Lead worship."


def test_a_page_grouped_by_employer():
    page = """<h3>Example Institute</h3><ol class="sp5"><li>[<a href="/jobs/list/1">X</a>] <span id="j1">Research Officer</span>
    <span class="purplesml">(deadline 2099/11/09 11:59PM)</span></li><li>[<a href="/jobs/list/2">Y</a>] <span id="j2">Old Post</span>
    <span>(deadline 2020/01/01 11:59PM)</span></li></ol>"""
    job = only(read("mathjobs", {"https://www.mathjobs.org/": page})[0])
    assert (job.title, job.company, job.deadline, job.url) == ("Research Officer", "Example Institute", "2099-11-09", "https://www.mathjobs.org/jobs/list/1")


def test_community_posts_keep_the_hiring_word_filter():
    targets("Julia Developer")
    answer = {"topics": [{"id": 1, "title": "Hiring a Julia Developer", "slug": "hiring-a-julia-developer", "created_at": "2026-11-01T00:00:00Z"},
                         {"id": 2, "title": "Julia package question", "slug": "package-question", "created_at": "2026-11-01T00:00:00Z"}],
              "posts": [{"topic_id": 1, "blurb": "Apply by email."}, {"topic_id": 2, "blurb": "How does this work?"}]}
    cfg = make_cfg(levels=["mid"], allowed=["Remote"])
    job = only(read("discourse", {"https://discourse.julialang.org/": answer}, cfg)[0])
    assert job.title == "Hiring a Julia Developer" and job.url == "https://discourse.julialang.org/t/hiring-a-julia-developer/1"
    assert job.strict_titles is False and job.source in base.SOCIAL_SOURCES


def test_freelance_projects_must_match_the_users_work():
    targets("Translator")
    answer = {"result": {"projects": [
        {"title": "English to Spanish translator", "seo_url": "translation/en-es", "submitdate": 1795455742, "preview_description": "Translate a manual.",
         "budget": {"minimum": 600, "maximum": 1500}, "currency": {"code": "USD"}},
        {"title": "Build a logo", "seo_url": "design/logo", "submitdate": 1795455742, "preview_description": "A logo for a shop."}]}}
    cfg = make_cfg(levels=["entry"], allowed=["Remote"])
    jobs, _ = read("freelancer", {"https://www.freelancer.com/api/": answer}, cfg)
    assert len(jobs) == 2 and all(j.strict_titles is False and j.location == "Remote" for j in jobs)  # titles rarely name a level
    assert "Budget: 600 to 1500 USD" in jobs[0].description
    filters = RuleFilters(cfg)
    assert filters.check(jobs[0])[0] is True and filters.check(jobs[1])[1] == "outside your target roles"
    targets("Registered Nurse")
    assert "freelancer" not in {s.id for s in catalog.active(make_cfg(levels=["mid"], allowed=["Ohio"]))}  # not a field with gig work


def test_news_items_keep_to_job_fairs_and_a_few_per_run():
    items = "".join(f"<item><title>County job fair number {n} - Daily News</title><link>https://news.example.org/{n}</link></item>" for n in range(15))
    feed = f"<rss><channel><item><title>Mayor opens a bridge - Daily News</title><link>https://news.example.org/x</link></item>{items}</channel></rss>"
    jobs, asked = read("google_news", {"https://news.google.com/rss/search": feed}, make_cfg(levels=["mid"], allowed=["Ohio"]))
    assert len(jobs) == 10 and all("job fair" in j.title for j in jobs)
    assert jobs[0].kind == "event" and jobs[0].company == "Daily News" and "Ohio" in asked[0][1] and "gl=US" in asked[0][1]


def test_telegram_channel_preview():
    targets("Data Analyst")
    page = """<div class="tgme_widget_message_wrap"><div data-post="remotejobs/7"><div class="tgme_widget_message_text js-message_text">We are hiring a Data Analyst<br/>Apply today</div>
    <time datetime="2026-11-20T10:00:00+00:00"></time></div></div>
    <div class="tgme_widget_message_wrap"><div data-post="remotejobs/8"><div class="tgme_widget_message_text">Happy holidays</div></div></div>"""
    job = only(read("telegram_public", {"https://t.me/s/": page}, make_cfg(levels=["mid"], allowed=["Remote"]))[0])
    assert (job.title, job.url, job.posted_at) == ("We are hiring a Data Analyst", "https://t.me/remotejobs/7", "2026-11-20")


def test_hacker_news_job_stories_take_two_steps():
    routes = {"https://hacker-news.firebaseio.com/v0/jobstories.json": [101, 102],
              "https://hacker-news.firebaseio.com/v0/item/101.json": {"title": "Example (YC S13) Is Hiring", "url": "https://example.com/jobs", "time": 1795400000},
              "https://hacker-news.firebaseio.com/v0/item/102.json": {"title": "Fabrikam Is Hiring", "text": "<p>Email us.</p>", "time": 1795400000}}
    jobs, asked = read("hn_jobstories", routes)
    assert [j.url for j in jobs] == ["https://example.com/jobs", "https://news.ycombinator.com/item?id=102"] and len(asked) == 3


def test_sitemap_runs_for_a_nationwide_search_and_matches_titles():
    targets("Business Analyst")
    xml = """<urlset><url><loc>https://www.governmentjobs.com/jobs/100-0/business-analyst</loc></url><url><loc>https://www.governmentjobs.com/jobs/200-0/senior-business-analyst</loc></url>
    <url><loc>https://www.governmentjobs.com/jobs/300-0/lifeguard</loc></url><url><loc>https://www.governmentjobs.com/careers/about</loc></url></urlset>"""
    source = catalog.BY_ID["sitemap_governmentjobs"]
    cfg = make_cfg(levels=["mid"], allowed=["Anywhere in the US"])
    assert catalog.fits(cfg, source)
    assert not catalog.fits(make_cfg(levels=["mid"], allowed=["Ohio"]), source)  # it names no places, so a local search skips it
    jobs, _ = read("sitemap_governmentjobs", {"https://www.governmentjobs.com/sitemap.xml": xml}, cfg)
    assert [j.title for j in jobs] == ["Senior business analyst", "Business analyst"]  # newest id first


def test_seasonal_job_orders_from_a_daily_file():
    targets("Farm Worker")
    records = [{"caseNumber": "JO-1", "jobTitle": "Farm Worker", "jobCity": "Wooster", "jobState": "OH", "jobDuties": "Plant and harvest.", "jobWageOffer": "17.71",
                "jobWagePer": "Hour", "jobBeginDate": "01-Feb-2027", "jobEndDate": "30-Nov-2027", "expirationDate": "03-Jul-2099", "dateSubmitted": "2026-11-18T14:56:46.460Z",
                "empBusinessName": "Example Farms", "emppocEmail": "owner@example.com"},
               {"caseNumber": "JO-2", "jobTitle": "Farm Worker", "jobCity": "Fresno", "jobState": "CA", "jobDuties": "Harvest."},  # outside the search area
               {"caseNumber": "JO-3", "jobTitle": "Line Cook", "jobCity": "Toledo", "jobState": "OH", "jobDuties": "Cook meals."}]  # not this person's work
    pack = io.BytesIO()
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr("day_jo.json", json.dumps(records))
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    jobs, asked = read("seasonal_us", {"https://api.seasonaljobs.dol.gov/datahub-search/sjCaseData/zip/jo/": httpx.Response(200, content=pack.getvalue())}, cfg)
    job = only(jobs)
    assert (job.title, job.company, job.location, job.deadline) == ("Farm Worker", "Example Farms", "Wooster, OH", "2099-07-03")
    assert job.url == "https://seasonaljobs.dol.gov/jobs/JO-1" and "Pay: $17.71 per hour" in job.description and "owner@example.com" not in job.description
    assert len(asked) == 1


def test_a_search_run_reads_the_seasonal_file_once_a_day():
    targets("Farm Worker")
    pack = io.BytesIO()
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr("day_jo.json", "[]")
    ctx, asked, _ = served({"https://api.seasonaljobs.dol.gov/": httpx.Response(200, content=pack.getvalue())}, make_cfg(levels=["mid"], allowed=["Ohio"]))

    async def deliver(name, jobs):
        pass
    ctx.deliver = deliver

    async def go():
        try:
            await catalog.read_source(ctx, catalog.BY_ID["seasonal_us"])
            await catalog.read_source(ctx, catalog.BY_ID["seasonal_us"])
        finally:
            await ctx.close()
    asyncio.run(go())
    assert len(asked) == 1


def test_page_helpers():
    page = """<script type="application/ld+json">{"@type": "ItemList", "itemListElement": [{"item": {"@type": "JobPosting", "title": "Welder",
    "jobLocation": {"address": {"addressLocality": "Akron", "addressRegion": "OH"}}, "jobLocationType": "TELECOMMUTE"}}]}</script>"""
    posting = only_item(readers.jsonld_postings(page))
    assert posting["title"] == "Welder" and readers.ld_location(posting) == "Akron, OH | Remote"
    assert details._ld_location(posting) == "Akron, OH | Remote"
    assert readers.embedded_json('x window.pageData = {"Jobs": [1]}; y', "window.pageData =") == {"Jobs": [1]}
    assert readers.embedded_json("nothing", "window.pageData =") is None
    assert readers.slug_title("https://x.example/jobs/2127857-0/business-analyst") == "Business analyst"
    assert readers.pick({"a": [{"b": 1}, {"b": 2}]}, "a[].b") == [1, 2] and readers.pick({"a": {"b": 3}}, ("x", "a.b")) == 3
    assert readers.pick({"c": "Akron", "s": "OH"}, ["c", "x", "s"]) == "Akron, OH" and readers.pick({"id": 9}, "https://x.example/{id}") == "https://x.example/9"


def only_item(items: list) -> dict:
    assert len(items) == 1
    return items[0]


# ---------------------------------------------------------------- company boards


# system, board entry, where its list is, the answer, expected (title, url, location).
BOARDS = [
    ("workable", {"slug": "example"}, "https://apply.workable.com/api/v1/widget/accounts/example",
     {"name": "Example", "jobs": [{"title": "Controller", "url": "https://apply.workable.com/j/A1", "city": "Akron", "state": "Ohio", "country": "United States",
                                   "published_on": "2026-09-23", "telecommuting": True, "description": "<p>Books.</p>"}]},
     ("Controller", "https://apply.workable.com/j/A1", "Akron, Ohio, United States | Remote")),
    ("adp", {"slug": "cid-1"}, "https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions",
     {"jobRequisitions": [{"itemID": "9200_1", "requisitionTitle": "Install Tech", "postDate": "2026-11-23T23:39:00",
                           "customFieldGroup": {"stringFields": [{"nameCode": {"codeValue": "ExternalJobID"}, "stringValue": "581098"}]},
                           "requisitionLocations": [{"address": {"cityName": "Akron", "countrySubdivisionLevel1": {"codeValue": "OH"}}}]}]},
     ("Install Tech", "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=cid-1&jobId=581098&lang=en_US", "Akron, OH")),
    ("bamboohr", {"slug": "example"}, "https://example.bamboohr.com/careers/list",
     {"result": [{"id": "645", "jobOpeningName": "Sales Executive", "atsLocation": {"city": "Bedford", "state": "Massachusetts", "country": "United States"}}]},
     ("Sales Executive", "https://example.bamboohr.com/careers/645", "Bedford, Massachusetts, United States")),
    ("breezy", {"slug": "example"}, "https://example.breezy.hr/json",
     [{"name": "Data Analyst", "url": "https://example.breezy.hr/p/b3", "published_date": "2026-11-17T14:23:57.005Z", "company": {"name": "Example Co"},
       "location": {"city": "San Diego", "state": {"name": "California"}, "country": {"name": "United States"}}}],
     ("Data Analyst", "https://example.breezy.hr/p/b3", "San Diego, California, United States")),
    ("pinpoint", {"slug": "example"}, "https://example.pinpointhq.com/postings.json",
     {"data": [{"title": "Test Engineer", "url": "https://example.pinpointhq.com/en/postings/3a", "location": {"name": "Redondo Beach"}, "description": "<p>Tests.</p>",
                "key_responsibilities": "<ul><li>Build</li></ul>", "deadline_at": "2099-01-01T00:00:00Z"}]},
     ("Test Engineer", "https://example.pinpointhq.com/en/postings/3a", "Redondo Beach")),
    ("rippling", {"slug": "example"}, "https://ats.rippling.com/api/v2/board/example/jobs",
     {"items": [{"name": "Electrical Intern", "url": "https://ats.rippling.com/example/jobs/38", "locations": [{"name": "Los Angeles, CA"}, {"name": "Remote"}]}]},
     ("Electrical Intern", "https://ats.rippling.com/example/jobs/38", "Los Angeles, CA | Remote")),
    ("gem", {"slug": "example"}, "https://api.gem.com/job_board/v0/example/job_posts/",
     [{"title": "Lab Intern", "absolute_url": "https://jobs.gem.com/example/1", "location": {"name": "Philadelphia"}, "first_published_at": "2026-02-09T22:58:43.834Z", "content_plain": "Lab work."}],
     ("Lab Intern", "https://jobs.gem.com/example/1", "Philadelphia")),
    ("manatal", {"slug": "example"}, "https://www.careers-page.com/api/v1.0/c/example/jobs/",
     {"results": [{"position_name": "Marketing Intern", "hash": "L9Y", "location_display": "Bangkok, Thailand", "description": "<p>Plan.</p>"}]},
     ("Marketing Intern", "https://www.careers-page.com/example/job/L9Y", "Bangkok, Thailand")),
    ("ukg_ready", {"url": "https://secure7.saashr.com/ta/620.careers"}, "https://secure7.saashr.com/ta/rest/ui/recruitment/companies/%7C620/job-requisitions",
     {"job_requisitions": [{"id": 65, "job_title": "Expeditor", "location": {"city": "Dallas", "state": "TX", "country": "USA"}, "job_description": "Move parts."}]},
     ("Expeditor", "https://secure7.saashr.com/ta/620.careers?ShowJob=65", "Dallas, TX, USA")),
    ("traffit", {"slug": "example"}, "https://example.traffit.com/public/job_posts/published",
     [{"url": "https://example.traffit.com/public/an/37", "valid_start": "2026-11-13 10:49:09",
       "advert": {"name": "Marketing Specialist", "values": [{"field_id": "description", "value": "<p>Ads.</p>"},
                                                              {"field_id": "geolocation", "value": '{"country": "Polska", "locality": "Gdynia"}'}]}}],
     ("Marketing Specialist", "https://example.traffit.com/public/an/37", "Gdynia, Polska")),
    ("jibe", {"url": "https://example.jibeapply.com"}, "https://example.jibeapply.com/api/jobs",
     {"jobs": [{"data": {"title": "Production Engineer", "hiring_organization": "Example Inc", "apply_url": "https://example.icims.com/jobs/5/login",
                         "location_name": "US Remote", "posted_date": "2026-08-20T13:59:00+0000", "description": "Run it."}}]},
     ("Production Engineer", "https://example.icims.com/jobs/5/login", "US Remote")),
    ("jobvite", {"slug": "example"}, "https://jobs.jobvite.com/example/jobs",
     '<table><tr><td class="jv-job-list-name"> <a href="/example/job/oU1">Finance Manager</a> </td><td class="jv-job-list-location"> San Jose, California </td></tr></table>',
     ("Finance Manager", "https://jobs.jobvite.com/example/job/oU1", "San Jose, California")),
    ("applicantstack", {"slug": "example"}, "https://example.applicantstack.com/x/openings",
     '<tr class="evenrow"><td class=""><a href="https://example.applicantstack.com/x/detail/a29">Sales Executive </a></td><td class="">Ann Arbor, MI</td><td>Sales</td></tr>',
     ("Sales Executive", "https://example.applicantstack.com/x/detail/a29", "Ann Arbor, MI")),
    ("softgarden", {"slug": "example"}, "https://example.softgarden.io/en/vacancies",
     '<div id="job_id_660"><div class="matchValue date">7/10/26</div><div class="matchValue title"><a href="../job/660/Key-Account?l=en">Key Account Manager (m/w/d)</a></div>'
     '<span class="location-view-item">Berlin</span></div>',
     ("Key Account Manager (m/w/d)", "https://example.softgarden.io/job/660/Key-Account?l=en", "Berlin")),
    ("loxo", {"slug": "example"}, "https://app.loxo.co/example",
     """<div class='job-title' style='color: #005bf7;' href="/job/MjU4" > Sales Representative </div>""".replace("<div class='job-title'", "<a class='job-title'").replace("</div>", "</a>")
     + "<div class='job-location' style='color: #000;'><i class='material-icons'>place</i> Austin, Texas</div>",
     ("Sales Representative", "https://app.loxo.co/job/MjU4", "Austin, Texas")),
    ("avature", {"url": "https://careers.example.com"}, "https://careers.example.com/en_US/careers/SearchJobs",
     '<article class="article article--result"><h3 class="article__header__text__title title"> <a class="link" href="https://careers.example.com/en_GB/careers/JobDetail/Clerk/221">Store Clerk</a></h3>'
     '<span class="list-item-location">Leeds</span></article>',
     ("Store Clerk", "https://careers.example.com/en_GB/careers/JobDetail/Clerk/221", "Leeds")),
    ("growthzone", {"url": "https://business.examplechamber.org"}, "https://business.examplechamber.org/jobs",
     '<div class="card-body gz-card-top gz-jobs-card-body"><small class="text-muted gz-jobs-date">Posted 09/27/2026</small><h5><a href="https://business.examplechamber.org/jobs/info/bookkeeper-1090">Bookkeeper</a></h5>'
     '<p class="card-text gz-description gz-job-description">Keep the books.</p></div>',
     ("Bookkeeper", "https://business.examplechamber.org/jobs/info/bookkeeper-1090", "")),
    ("teamtailor", {"url": "https://example.teamtailor.com"}, "https://example.teamtailor.com/jobs.rss",
     """<rss xmlns:tt="https://teamtailor.com/locations"><channel><item><title>Head of Campaigns</title><description>&lt;p&gt;Plan.&lt;/p&gt;</description>
     <pubDate>Fri, 20 Nov 2026 15:12:26 +0000</pubDate><link>https://example.teamtailor.com/jobs/1-head</link><remoteStatus>hybrid</remoteStatus>
     <tt:locations><tt:location><tt:city>London</tt:city><tt:country>United Kingdom</tt:country></tt:location></tt:locations></item></channel></rss>""",
     ("Head of Campaigns", "https://example.teamtailor.com/jobs/1-head", "London, United Kingdom | Remote")),
    ("jazzhr", {"slug": "example"}, "https://app.jazz.co/feeds/export/jobs/example",
     "<jobs><job><title>Weld Engineer</title><city>Akron</city><state>OH</state><country>US</country><url>https://example.applytojob.com/apply/x/Weld</url><description>&lt;p&gt;Weld.&lt;/p&gt;</description></job></jobs>",
     ("Weld Engineer", "https://example.applytojob.com/apply/x/Weld", "Akron, OH, US")),
    ("paylocity", {"slug": "abc-guid"}, "https://recruiting.paylocity.com/recruiting/jobs/All/abc-guid",
     'x <script>window.pageData = {"Jobs": [{"JobId": 42, "JobTitle": "HR Manager", "LocationName": "Lexington KY", "PublishedDate": "2026-11-05T10:00:00", "Description": "<p>People.</p>"}]};</script>',
     ("HR Manager", "https://recruiting.paylocity.com/Recruiting/Jobs/Details/42", "Lexington KY")),
    ("join", {"slug": "example"}, "https://join.com/companies/example",
     '<script id="__NEXT_DATA__">{"props": {"jobs":{"items":[{"idParam":"1-eng","title":"Engineer","createdAt":"2026-05-04T14:49:10.217Z","city":{"cityName":"Berlin","countryName":"Germany"}}]}}}</script>',
     ("Engineer", "https://join.com/companies/example/1-eng", "Berlin, Germany")),
]


@pytest.mark.parametrize("system, entry, start, answer, expected", BOARDS, ids=[b[0] for b in BOARDS])
def test_company_board(system, entry, start, answer, expected):
    job = only(board(system, {start: answer}, **entry)[0])
    assert (job.title, job.url, job.location) == expected
    assert job.source == "ats" and job.meta["ats"] == system and job.source_detail == f"{ats.SYSTEM_NAMES[system]}: Example Works"


def test_board_systems_that_search_by_word():
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["nurse"]
    oracle = {"items": [{"requisitionList": [{"Id": "21", "Title": "Health Nurse", "PrimaryLocation": "Jersey City, NJ", "PostedDate": "2026-10-22", "ShortDescriptionStr": "Care."}]}]}
    jobs, asked = board("oracle", {"https://example.fa.us2.oraclecloud.com/hcmRestApi/": oracle}, cfg, url="https://example.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1")
    assert only(jobs).url == "https://example.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/21"
    assert 'siteNumber=CX_1' in asked[0][1] and 'keyword="nurse"' in asked[0][1].replace("%22", '"')
    phenom = 'phApp.ddo = {"eagerLoadRefineSearch": {"data": {"jobs": [{"jobId": "R1", "title": "Pharmacy Technician", "city": "Akron", "state": "Ohio", "country": "US", "postedDate": "2026-09-28T00:00:00"}]}}}; next'
    job = only(board("phenom", {"https://careers.example.com/us/en/search-results": phenom}, cfg, url="https://careers.example.com")[0])
    assert (job.url, job.location) == ("https://careers.example.com/us/en/job/R1", "Akron, Ohio, US")
    feed = "<rss><channel><item><title>Nurse Practitioner (Durham, NC, US)</title><link>https://careers.example.com/job/Durham-NP/1377746900/</link><description>Care.</description></item></channel></rss>"
    job = only(board("successfactors", {"https://careers.example.com/services/rss/job/": feed}, cfg, url="https://careers.example.com")[0])
    assert (job.title, job.location) == ("Nurse Practitioner", "Durham, NC, US")
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><link rel="alternate" href="https://jobs.example.edu/postings/9"/><title>Campus Nurse</title>
    <published>2026-11-22T19:26:40-05:00</published><content>&lt;p&gt;Care.&lt;/p&gt;</content></entry></feed>"""
    jobs, asked = board("peopleadmin", {"https://jobs.example.edu/postings/search.atom": atom}, cfg, url="https://jobs.example.edu")
    assert only(jobs).url == "https://jobs.example.edu/postings/9" and "query=nurse" in asked[0][1] and jobs[0].posted_at == "2026-11-22"


def test_board_systems_that_need_a_first_look():
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["engineer"]
    taleo = {"requisitionList": [{"contestNo": "26000", "column": ["UAS Project Engineer", '["US-RI-Providence"]', "Nov 5, 2026"]}]}
    jobs, asked = board("taleo", {"https://example.taleo.net/careersection/ex/jobsearch.ftl": "<script>queryString: 'portal=101430233'</script>",
                                  "https://example.taleo.net/careersection/rest/jobboard/searchjobs": taleo}, cfg,
                        url="https://example.taleo.net/careersection/ex/jobsearch.ftl")
    job = only(jobs)
    assert (job.title, job.location, job.posted_at) == ("UAS Project Engineer", "US-RI-Providence", "2026-11-05")
    assert job.url == "https://example.taleo.net/careersection/ex/jobdetail.ftl?job=26000"
    assert "portal=101430233" in asked[1][1] and json.loads(asked[1][2])["fieldData"]["fields"]["KEYWORD"] == "engineer"
    answer = {"data": {"jobs": [{"id": 7, "title": "Events &amp; Coordinator", "orgTitle": "Example Org", "city": "Bedford Park", "abbreviation": "IL", "startDateRef": "2026-11-12"}]}}
    jobs, asked = board("applicantpro", {"https://example.applicantpro.com/jobs/": 'courierCurrentRouteData = {"domain_id":"7949"}',
                                         "https://example.applicantpro.com/core/jobs/7949": answer}, cfg, url="https://example.applicantpro.com")
    job = only(jobs)
    assert (job.title, job.company, job.location, job.url) == ("Events & Coordinator", "Example Org", "Bedford Park, IL", "https://example.applicantpro.com/jobs/7")


def test_board_terms_lead_with_the_users_own_words():
    cfg = make_cfg(levels=["internship", "entry"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["dental hygienist", "dental assistant", "oral surgery"]
    terms = ats._few_terms(cfg)
    assert terms[:2] == ["dental hygienist", "dental assistant"] and terms[2] == "intern" and len(terms) == ats.TERMS_PER_BOARD
    empty = make_cfg(levels=["mid"], allowed=["Ohio"])
    assert ats._few_terms(empty) == [""]  # nothing to search for yet: one search of the newest openings


def test_workday_on_myworkdaysite():
    assert ats.detect("https://wd5.myworkdaysite.com/en-US/recruiting/example/External/job/Akron/Nurse_R1") == {
        "ats": "workday", "url": "https://wd5.myworkdaysite.com/recruiting/example/External"}
    assert ats.detect("https://wd5.myworkdaysite.com/") is None
    assert ats._wd_parts("https://wd5.myworkdaysite.com/recruiting/example/External") == ("https://wd5.myworkdaysite.com", "example", "External")
    assert ats._wd_parts("https://example.wd5.myworkdayjobs.com/en-US/External") == ("https://example.wd5.myworkdayjobs.com", "example", "External")
    answer = {"total": 1, "jobPostings": [{"title": "RN", "externalPath": "/job/Akron/RN_R1", "locationsText": "Akron, OH", "postedOn": "Posted Today"}]}
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["nurse"]
    jobs, asked = board("workday", {"https://wd5.myworkdaysite.com/wday/cxs/example/External/jobs": answer}, cfg,
                        url="https://wd5.myworkdaysite.com/recruiting/example/External")
    job = only(jobs)
    assert job.url == "https://wd5.myworkdaysite.com/recruiting/example/External/job/Akron/RN_R1"
    assert job.meta["api"] == "https://wd5.myworkdaysite.com/wday/cxs/example/External/job/Akron/RN_R1" and asked[0][0] == "POST"
    ctx, _, _ = served({"https://wd5.myworkdaysite.com/wday/cxs/example/External/job/Akron/RN_R1": {"jobPostingInfo": {"jobDescription": "<p>Care.</p>", "location": "Akron, OH"}}})

    async def fetch():
        try:
            return await details.fetch(ctx, "https://wd5.myworkdaysite.com/en-US/recruiting/example/External/job/Akron/RN_R1")
        finally:
            await ctx.close()
    assert asyncio.run(fetch())["description"] == "Care."


@pytest.mark.parametrize("url, expected", [
    ("https://apply.workable.com/example/j/5CD/", {"ats": "workable", "slug": "example"}),
    ("https://example.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/21", {"ats": "oracle", "url": "https://example.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001"}),
    ("https://example.jobs2web.com/job/Akron-Nurse/1/", {"ats": "successfactors", "url": "https://example.jobs2web.com"}),
    ("https://careers.example.com/job/Claremont-Intern/1377746900/", {"ats": "successfactors", "url": "https://careers.example.com"}),
    ("https://example.taleo.net/careersection/ex/jobdetail.ftl?job=2", {"ats": "taleo", "url": "https://example.taleo.net/careersection/ex/jobsearch.ftl"}),
    ("https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=abc-1&jobId=9", {"ats": "adp", "slug": "abc-1"}),
    ("https://recruiting.paylocity.com/recruiting/jobs/All/57afc459-3130-4f92-b284-cd0828819ff0", {"ats": "paylocity", "slug": "57afc459-3130-4f92-b284-cd0828819ff0"}),
    ("https://example.bamboohr.com/careers/713/", {"ats": "bamboohr", "slug": "example"}),
    ("https://example.applytojob.com/apply/Oh/AI", {"ats": "jazzhr", "slug": "example"}),
    ("https://secure7.saashr.com/ta/620.careers?ShowJob=63", {"ats": "ukg_ready", "url": "https://secure7.saashr.com/ta/620.careers"}),
    ("https://example.applicantpro.com/jobs/40", {"ats": "applicantpro", "url": "https://example.applicantpro.com"}),
    ("https://example.isolvedhire.com/jobs/", {"ats": "applicantpro", "url": "https://example.isolvedhire.com"}),
    ("https://jobs.example.edu/postings/search", {"ats": "peopleadmin", "url": "https://jobs.example.edu"}),
    ("https://example.peopleadmin.com/postings/12", {"ats": "peopleadmin", "url": "https://example.peopleadmin.com"}),
    ("https://example.jibeapply.com/jobs/5?lang=en", {"ats": "jibe", "url": "https://example.jibeapply.com"}),
    ("https://example.avature.net/en_US/careers/JobDetail?jobId=3", {"ats": "avature", "url": "https://example.avature.net"}),
    ("https://jobs.jobvite.com/example/job/o1", {"ats": "jobvite", "slug": "example"}),
    ("https://example.na.teamtailor.com/jobs/1", {"ats": "teamtailor", "url": "https://example.na.teamtailor.com"}),
    ("https://example.breezy.hr/p/3f", {"ats": "breezy", "slug": "example"}),
    ("https://example.pinpointhq.com/en/postings/8", {"ats": "pinpoint", "slug": "example"}),
    ("https://ats.rippling.com/example/jobs/e3", {"ats": "rippling", "slug": "example"}),
    ("https://example.applicantstack.com/x/detail/a2", {"ats": "applicantstack", "slug": "example"}),
    ("https://jobs.gem.com/example/am9", {"ats": "gem", "slug": "example"}),
    ("https://www.careers-page.com/example/job/L9", {"ats": "manatal", "slug": "example"}),
    ("https://join.com/companies/example/1-x", {"ats": "join", "slug": "example"}),
    ("https://example.softgarden.io/job/1/x", {"ats": "softgarden", "slug": "example"}),
    ("https://app.loxo.co/example", {"ats": "loxo", "slug": "example"}),
    ("https://example.traffit.com/public/an/3", {"ats": "traffit", "slug": "example"}),
    ("https://business.examplechamber.org/jobs/info/x-1090", {"ats": "growthzone", "url": "https://business.examplechamber.org"}),
    # the vendors' own pages and ordinary sites are no boards
    ("https://www.bamboohr.com/pricing", None), ("https://www.workable.com/", None), ("https://apply.workable.com/j/5CD", None),
    ("https://www.teamtailor.com/en/", None), ("https://www.example.com/jobs/12", None), ("https://en.wikipedia.org/wiki/Nurse", None),
])
def test_detect(url, expected):
    assert ats.detect(url) == expected


def test_every_system_has_a_reader_and_a_name():
    assert set(ats.HANDLERS) == set(ats.SYSTEM_NAMES)


# ---------------------------------------------------------------- who gets what


def ids(cfg: dict) -> set[str]:
    return {s.id for s in catalog.active(cfg)}


def test_field_sources_run_for_their_fields():
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    targets("Registered Nurse")
    assert "healthcare" in plan.groups(cfg)
    chosen = ids(cfg)
    assert {"madgex_nejm", "healthecareers", "workable_search", "neogov"} <= chosen  # the field's boards, and the general ones
    assert not chosen & {"schoolspring", "alltruckjobs", "playbill", "dice", "hn_jobstories"}
    targets("Truck Driver")
    chosen = ids(cfg)
    assert {"alltruckjobs", "cdljobnow"} <= chosen and "madgex_nejm" not in chosen
    targets("Elementary School Teacher")
    assert "schoolspring" in ids(cfg)
    targets("Software Engineer")
    assert {"dice", "hn_jobstories", "lobsters_jobs"} <= ids(cfg)


def test_a_person_whose_fields_are_unknown_gets_the_general_sources():
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    assert plan.groups(cfg) == []
    chosen = catalog.active(cfg)
    assert chosen and all(s.fields == catalog.ALL for s in chosen)
    assert {"workable_search", "neogov", "amazon_jobs"} <= {s.id for s in chosen}


def test_national_services_run_for_their_countries():
    targets("Registered Nurse")
    us = ids(make_cfg(levels=["mid"], allowed=["Ohio"]))
    assert not us & {"jobbank_ca", "nhs_jobs", "eures", "workforce_au", "jobtech_se", "madgex_vettimes"}
    assert "jobbank_ca" in ids(make_cfg(levels=["mid"], allowed=["Toronto, ON"]))
    assert "nhs_jobs" in ids(make_cfg(levels=["mid"], allowed=["United Kingdom"]))
    assert "workforce_au" in ids(make_cfg(levels=["mid"], allowed=["Sydney NSW"]))
    assert {"eures", "jobtech_se"} <= ids(make_cfg(levels=["mid"], allowed=["Sweden"]))
    assert "eures" in ids(make_cfg(levels=["mid"], allowed=["Europe"]))


def test_the_home_country_counts_when_the_area_names_no_place():
    targets("Registered Nurse")
    db.kv_set("profile.answers", {"target_roles": ["Registered Nurse"], "country": "Canada"})
    assert "jobbank_ca" in ids(make_cfg(levels=["mid"], allowed=["Anywhere in the US", "Remote"]))  # the setup's default area


def test_a_state_service_runs_only_for_people_in_that_state():
    targets("Clerk")
    assert "statejobs_ny" in ids(make_cfg(levels=["mid"], allowed=["New York"]))
    assert "statejobs_ny" in ids(make_cfg(levels=["mid"], allowed=["Anywhere in the US"]))
    assert "statejobs_ny" in ids(make_cfg(levels=["mid"], allowed=["Buffalo, NY"]))  # a city in the state
    assert "statejobs_ny" not in ids(make_cfg(levels=["mid"], allowed=["Ohio"]))
    assert "myjobscotland" in ids(make_cfg(levels=["mid"], allowed=["United Kingdom"]))
    assert "myjobscotland" in ids(make_cfg(levels=["mid"], allowed=["Edinburgh"]))
    assert "myjobscotland" not in ids(make_cfg(levels=["mid"], allowed=["London"]))


@pytest.mark.parametrize("entry, expected", [
    ("Ohio", ({"US"}, False)), ("Pittsburgh, PA", ({"US"}, False)), ("Anywhere in the US", ({"US"}, True)), ("Remote", (set(), False)),
    ("Germany", ({"DE"}, True)), ("Berlin, Germany", ({"DE"}, False)), ("Toronto, ON", ({"CA"}, False)), ("Canada", ({"CA"}, True)),
    ("Ontario", ({"CA"}, False)), ("United Kingdom", ({"GB"}, True)), ("Leeds, England", ({"GB"}, False)), ("Geelong VIC 3220", ({"AU"}, False)),
    ("Remote, Germany", ({"DE"}, False)), ("Anywhere in Canada", ({"CA"}, True)), ("Paris, TX", ({"US"}, False)), ("Dublin, OH", ({"US"}, False)),
    ("Dublin", ({"IE"}, False)), ("Portland", ({"US"}, False)), ("", (set(), False)),
])
def test_reading_a_place(entry, expected):
    assert countries.read_place(entry) == expected


# ---------------------------------------------------------------- the location filter for other countries


def national(location: str, country: str, source: str = "jobbank_ca") -> RawJob:
    return RawJob(source, "Registered Nurse", "Example Clinic", "https://jobs.example.org/1", location=location, meta={"country": country})


def verdict(cfg: dict, job: RawJob) -> str:
    passed, reason, _ = RuleFilters(cfg).check(job)
    return "pass" if passed else reason


def test_a_whole_country_keeps_its_national_services_jobs():
    db.kv_set("profile.answers", {"target_roles": ["Registered Nurse"]})
    cfg = make_cfg(levels=["mid"], allowed=["Canada"])
    assert verdict(cfg, national("Vancouver, BC", "CA")) == "pass"  # the filter alone reads ", BC" as outside the area
    cfg = make_cfg(levels=["mid"], allowed=["Germany"])
    assert verdict(cfg, national("Hamburg, DE", "DE", "jobroom_ch")) == "pass"  # not Delaware
    cfg = make_cfg(levels=["mid"], allowed=["United Kingdom"])
    assert verdict(cfg, national("Leeds, England", "GB", "nhs_jobs")) == "pass"


def test_a_board_for_several_countries_tags_each_job_by_its_place():
    feed = """<rss><channel><item><title>Example Trust: Pharmacist</title><description>Join us... Rotherham, England</description>
    <link>https://jobs.example.org/job/1/a/</link></item><item><title>Example Health NZ: Pharmacist</title><description>Join us... Auckland, New Zealand</description>
    <link>https://jobs.example.org/job/2/b/</link></item><item><title>Example Clinic: Pharmacist</title><description>Join us... Austin, Texas</description>
    <link>https://jobs.example.org/job/3/c/</link></item></channel></rss>"""
    db.kv_set("profile.answers", {"target_roles": ["Pharmacist"]})
    cfg = make_cfg(levels=["mid"], allowed=["United Kingdom"])
    jobs, _ = read("madgex_pharmjournal", {"https://jobs.pharmaceutical-journal.com/": feed}, cfg)
    assert [j.meta.get("country") for j in jobs] == ["GB", "NZ", None]
    assert verdict(cfg, jobs[0]) == "pass" and verdict(cfg, jobs[1]) == "outside your locations"


def test_a_part_of_a_country_leaves_the_call_to_the_ai():
    db.kv_set("profile.answers", {"target_roles": ["Registered Nurse"]})
    cfg = make_cfg(levels=["mid"], allowed=["Ontario"], unknown_policy="ai")
    assert verdict(cfg, national("Toronto, ON", "CA")) == "pass"  # the matcher can't tell ON from Ontario
    cfg["locations"]["unknown_policy"] = "drop"
    assert verdict(cfg, national("Toronto, ON", "CA")) == "unknown location"


def test_the_filter_is_no_looser_for_anyone_else():
    db.kv_set("profile.answers", {"target_roles": ["Registered Nurse"]})
    ohio = make_cfg(levels=["mid"], allowed=["Ohio"])
    assert verdict(ohio, national("Vancouver, BC", "CA")) == "outside your locations"  # a US user, a Canadian job
    assert verdict(ohio, national("Hamburg, DE", "DE")) == "outside your locations"
    assert verdict(ohio, RawJob("neogov", "Registered Nurse", "Example County", "https://jobs.example.org/2", location="Austin, TX")) == "outside your locations"
    canada = make_cfg(levels=["mid"], allowed=["Canada"])
    assert verdict(canada, national("Berlin, Germany", "DE")) == "outside your locations"  # the wrong country
    untagged = RawJob("ats", "Registered Nurse", "Example Clinic", "https://jobs.example.org/3", location="Vancouver, BC")
    assert verdict(canada, untagged) == "outside your locations"  # a job not from a national service is judged as before
    assert countries.Area(["Ohio"], "United States").judge(False, "US") is False


def test_the_ai_is_told_a_home_country_job_is_in_the_area():
    db.kv_set("profile.answers", {"target_roles": ["Registered Nurse"], "country": "Canada"})
    home = make_cfg(levels=["mid"], allowed=["Anywhere in the US", "Remote"])
    assert location_ok_by_settings(home, False, "Registered Nurse", "jobbank_ca") is True
    assert location_ok_by_settings(home, False, "Registered Nurse", "nhs_jobs") is False
    assert location_ok_by_settings(home, False, "Registered Nurse", "ats") is False
    db.kv_set("profile.answers", {"target_roles": ["Registered Nurse"], "country": "United States"})
    assert location_ok_by_settings(make_cfg(levels=["mid"], allowed=["Ohio"]), False, "Registered Nurse", "neogov") is False


# ---------------------------------------------------------------- the switches


def test_a_group_switch_and_the_off_list():
    targets("Registered Nurse")
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    assert "madgex_nejm" in ids(cfg) and "healthecareers" in ids(cfg)
    cfg["sources"]["catalog"]["off"] = ["madgex_nejm"]
    assert "madgex_nejm" not in ids(cfg) and "healthecareers" in ids(cfg)
    cfg["sources"]["catalog"]["off"] = []
    cfg["sources"]["catalog"]["groups"]["field"] = False
    assert not {s.id for s in catalog.active(cfg) if s.group == "field"} and "neogov" in ids(cfg)


def test_a_new_source_reaches_people_who_saved_their_settings(monkeypatch):
    targets("Registered Nurse")
    stored = make_cfg(levels=["mid"], allowed=["Ohio"])
    stored["sources"]["catalog"]["off"] = ["madgex_nejm"]
    settings.save(stored)
    newcomer = catalog.Source("brand_new", "Brand New Board", "field", "feed", "https://new.example.org/feed", fields=("healthcare",))
    monkeypatch.setattr(catalog, "SOURCES", [*catalog.SOURCES, newcomer])
    chosen = ids(settings.get())
    assert "brand_new" in chosen and "madgex_nejm" not in chosen  # the new one is on, and the one turned off stays off


def test_settings_saved_before_the_catalog_existed_still_work():
    targets("Registered Nurse")
    old = make_cfg(levels=["mid"], allowed=["Ohio"])
    del old["sources"]["catalog"]
    db.kv_set("settings", old)
    assert "madgex_nejm" in ids(settings.get())
    assert ids(old)  # and a config without the section at all counts as everything on


def test_a_source_that_needs_a_key_waits_for_it():
    cfg = make_cfg(levels=["mid"], allowed=["United Kingdom"])
    assert "reed" not in ids(cfg)
    cfg["sources"]["catalog"]["keys"] = {"reed": {"api_key": "   "}}
    assert "reed" not in ids(cfg)
    cfg["sources"]["catalog"]["keys"] = {"reed": {"api_key": "reed-test-key"}}
    assert "reed" in ids(cfg)
    answer = {"results": [{"jobTitle": "Nurse", "employerName": "Example Care", "locationName": "Leeds", "jobUrl": "https://www.reed.co.uk/jobs/nurse/1",
                           "date": "20/11/2026", "expirationDate": "31/12/2099", "jobDescription": "Care."}]}
    cfg["search"]["queries"] = ["nurse"]
    seen = {}

    def reply(request):
        seen.update(request.headers)
        return httpx.Response(200, json=answer)
    job = only(read("reed", {"https://www.reed.co.uk/api/1.0/search": reply}, cfg)[0])
    assert (job.title, job.posted_at, job.deadline) == ("Nurse", "2026-11-20", "2099-12-31")
    assert seen["authorization"].startswith("Basic ")  # the key is the user name of a Basic login


def test_keyed_sources_build_their_requests():
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["nurse"]
    cfg["sources"]["catalog"]["keys"] = {"careeronestop": {"user_id": "u1", "token": "t1"}, "findwork": {"token": "f1"}}
    headers = {}

    def reply(request):
        headers.update(request.headers)
        return httpx.Response(200, json={"Jobs": [{"JobTitle": "Nurse", "Company": "Example", "Location": "Akron, OH", "URL": "https://jobs.example.org/9", "DatePosted": "2026-11-20"}]})
    jobs, asked = read("careeronestop", {"https://api.careeronestop.org/v1/jobsearch/u1/nurse/Ohio/": reply}, cfg)
    assert only(jobs).location == "Akron, OH" and headers["authorization"] == "Bearer t1"
    answer = {"results": [{"role": "Developer", "company_name": "Example", "remote": True, "url": "https://findwork.dev/1", "date_posted": "2026-11-20", "text": "Code."}]}
    job = only(read("findwork", {"https://findwork.dev/api/jobs/": answer}, cfg)[0])
    assert (job.title, job.location) == ("Developer", "Remote")


def test_the_catalog_route():
    from jobportal.web.server import app
    targets("Registered Nurse")
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["sources"]["catalog"]["off"] = ["healthecareers"]
    settings.save(cfg)
    with TestClient(app) as client:
        out = client.get("/api/sources/catalog").json()
        assert client.post("/api/sources/test/not-a-source").status_code == 404
    assert out["enabled"] is True and out["fields"] == ["healthcare"] and out["countries"] == ["US"]
    assert [g["id"] for g in out["groups"]] == list(catalog.GROUPS) and sum(g["total"] for g in out["groups"]) == len(catalog.SOURCES)
    rows = {r["id"]: r for r in out["sources"]}
    assert len(rows) == len(catalog.SOURCES) and "Greenhouse" in out["systems"]
    assert rows["madgex_nejm"]["runs"] is True and rows["madgex_nejm"]["needs_key"] is False
    off = rows["healthecareers"]
    assert off["off"] is True and off["on"] is False and off["runs"] is False and off["for_you"] is True
    teacher = rows["schoolspring"]
    assert teacher["on"] is True and teacher["for_you"] is False and teacher["runs"] is False
    reed = rows["reed"]
    assert reed["needs_key"] is True and reed["keys"] == ["api_key"] and reed["has_keys"] is False and reed["on"] is False and reed["key_url"].startswith("https://")


def test_testing_one_catalog_source(monkeypatch):
    from jobportal.search import sources
    targets("Registered Nurse")
    settings.save(make_cfg(levels=["mid"], allowed=["Ohio"]))

    async def fake_read(ctx, src):
        return [RawJob(src.id, "Registered Nurse", "Example Health", "https://jobs.example.org/1", location="Akron, OH")]
    monkeypatch.setattr(catalog, "read_source", fake_read)
    out = asyncio.run(sources.test_collector("madgex_vettimes"))  # a check works even for a source that wouldn't run for this person
    assert out["ok"] is True and out["found"] == 1 and out["pass_filters"] == 1


# ---------------------------------------------------------------- failing sites


FEED = """<rss><channel><item><title>Example Health: Registered Nurse</title><link>https://jobs.example.org/job/1/nurse/</link><description>Care.</description></item></channel></rss>"""


def run_collect(routes: dict, cfg: dict, picked: list[str], monkeypatch) -> tuple[list[RawJob], list, list]:
    """collect() with only the sources in `picked` in the table."""
    monkeypatch.setattr(catalog, "SOURCES", [catalog.BY_ID[i] for i in picked])
    ctx, asked, log = served(routes, cfg)

    async def go():
        try:
            return await catalog.collect(ctx)
        finally:
            await ctx.close()
    return asyncio.run(go()), asked, log


def test_a_failing_source_does_not_stop_the_others(monkeypatch):
    targets("Registered Nurse")
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    routes = {"https://www.nejmcareercenter.org/": FEED,  # works
              "https://www.healthecareers.com/": 500,  # a server error
              "https://jobs.workable.com/": "this is not JSON",  # a changed page
              "https://www.governmentjobs.com/": 403}  # refused

    def boom(request):
        raise httpx.ConnectError("no route to host", request=request)
    routes["https://www.nature.com/"] = boom
    jobs, _, log = run_collect(routes, cfg, ["madgex_nejm", "healthecareers", "workable_search", "neogov", "madgex_nature"], monkeypatch)
    assert [j.title for j in jobs] == ["Registered Nurse"]
    warnings = [m for level, m in log if level == "warn"]
    assert len(warnings) == 4  # one line for each site that failed
    assert any("GovernmentJobs: refused (HTTP 403)" in m for m in warnings) and any("Nature Careers" in m for m in warnings)


def test_a_refusal_ends_that_source_at_once(monkeypatch):
    targets("Registered Nurse")
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["nurse", "rn"]
    for status in (401, 403, 429):
        jobs, asked, log = run_collect({"https://www.nejmcareercenter.org/": status}, cfg, ["madgex_nejm"], monkeypatch)
        assert jobs == [] and len(asked) == 1, status  # no second search, and no retry
        assert sum(level == "warn" for level, _ in log) == 1
        monkeypatch.undo()
        targets("Registered Nurse")


@pytest.mark.parametrize("page", [
    "<html><head><title>Just a moment...</title></head><body>checking your browser</body></html>",
    '<html><body><div class="cf-browser-verification">wait</div></body></html>',
    "<html><title>Access Denied</title></html>",
])
def test_a_challenge_page_counts_as_a_refusal(page):
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["nurse", "rn"]
    ctx, asked, _ = served({"https://www.governmentjobs.com/": page}, cfg)

    async def go():
        try:
            await catalog.read_source(ctx, catalog.BY_ID["neogov"])
        finally:
            await ctx.close()
    with pytest.raises(Blocked):
        asyncio.run(go())
    assert len(asked) == 1


def test_a_normal_page_with_a_captcha_script_is_no_challenge():
    page = """<script src="https://www.google.com/recaptcha/api.js"></script><div class="job-item-container"><a class="job-details-link" href="/jobs/1-0/nurse">Nurse</a></div>"""
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["nurse"]
    assert only(read("neogov", {"https://www.governmentjobs.com/": page}, cfg)[0]).title == "Nurse"


def test_polite_requests_stop_at_a_refusal():
    for reply, message in ((403, "HTTP 403"), (429, "HTTP 429"), (httpx.Response(202), "a challenge page")):
        ctx, asked, _ = served({"https://site.example/": reply})

        async def go():
            try:
                await ctx.polite("GET", "https://site.example/page")
            finally:
                await ctx.close()
        with pytest.raises(Blocked, match=message):
            asyncio.run(go())
        assert len(asked) == 1


def test_a_dropped_connection_gets_one_more_try(monkeypatch):
    real_sleep = asyncio.sleep

    async def quick(_seconds):
        await real_sleep(0)
    monkeypatch.setattr(base.asyncio, "sleep", quick)
    calls = []

    def flaky(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("slow", request=request)
        return httpx.Response(200, text="ok")
    ctx, _, _ = served({"https://site.example/": flaky})

    async def go():
        try:
            return (await ctx.polite("GET", "https://site.example/page")).text
        finally:
            await ctx.close()
    assert asyncio.run(go()) == "ok" and len(calls) == 2


def test_a_failure_never_logs_an_address_with_a_key(monkeypatch):
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["search"]["queries"] = ["nurse"]
    cfg["sources"]["catalog"]["keys"] = {"careeronestop": {"user_id": "my-user-id", "token": "my-token"}}
    monkeypatch.setattr(catalog, "SOURCES", [catalog.BY_ID["careeronestop"]])
    _, _, log = run_collect({"https://api.careeronestop.org/": 500}, cfg, ["careeronestop"], monkeypatch)
    assert any("HTTP 500" in m for _, m in log) and not any("my-user-id" in m or "my-token" in m for _, m in log)


def test_a_refused_board_is_one_log_line():
    ctx, asked, log = served({"https://example.breezy.hr/json": 403})

    async def go():
        try:
            return await ats.read_board(ctx, {"ats": "breezy", "name": "Example Works", "slug": "example"})
        finally:
            await ctx.close()
    assert asyncio.run(go()) == [] and len(asked) == 1
    assert len(log) == 1 and "refused (HTTP 403)" in log[0][1]


def test_a_slow_source_is_cut_off_and_the_rest_arrive(monkeypatch):
    targets("Registered Nurse")
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    monkeypatch.setattr(catalog, "SOURCE_SECONDS", 0.05)

    async def stuck(ctx, method, url, **kw):
        if "nature.com" in url:
            await asyncio.sleep(30)
        return httpx.Response(200, text=FEED, request=httpx.Request(method, url))
    monkeypatch.setattr(Ctx, "polite", stuck)
    jobs, _, log = run_collect({}, cfg, ["madgex_nejm", "madgex_nature"], monkeypatch)
    assert [j.source for j in jobs] == ["madgex_nejm"]
    assert sum("no answer in time" in m for _, m in log) == 1


def test_the_whole_batch_has_a_time_limit(monkeypatch):
    targets("Registered Nurse")
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    monkeypatch.setattr(catalog, "BATCH_SECONDS", 0.05)
    finished = []

    async def stuck(ctx, method, url, **kw):
        if "nature.com" in url:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                finished.append("canceled")
                raise
        return httpx.Response(200, text=FEED, request=httpx.Request(method, url))
    monkeypatch.setattr(Ctx, "polite", stuck)
    jobs, _, log = run_collect({}, cfg, ["madgex_nejm", "madgex_nature"], monkeypatch)
    assert [j.source for j in jobs] == ["madgex_nejm"] and finished == ["canceled"]
    assert any("ran out of time" in m for _, m in log)


def test_stop_cancels_the_sources_in_flight(monkeypatch):
    targets("Registered Nurse")
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    monkeypatch.setattr(catalog, "SOURCES", [catalog.BY_ID["madgex_nejm"]])
    canceled = []

    async def stuck(ctx, method, url, **kw):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            canceled.append(url)
            raise
    monkeypatch.setattr(Ctx, "polite", stuck)
    ctx, _, _ = served({}, cfg)

    async def go():
        task = asyncio.create_task(catalog.collect(ctx))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await ctx.close()
    asyncio.run(go())
    assert len(canceled) == 1


def test_a_search_run_gets_each_sites_jobs_as_it_finishes(monkeypatch):
    targets("Registered Nurse")
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    monkeypatch.setattr(catalog, "SOURCES", [catalog.BY_ID["madgex_nejm"]])
    ctx, _, _ = served({"https://www.nejmcareercenter.org/": FEED}, cfg)
    handed = []

    async def deliver(name, jobs):
        handed.append((name, [j.title for j in jobs]))
    ctx.deliver = deliver

    async def go():
        try:
            return await catalog.collect(ctx)
        finally:
            await ctx.close()
    assert asyncio.run(go()) == []  # already handed over, so the run doesn't add them twice
    assert handed == [("NEJM CareerCenter", ["Registered Nurse"])]


def test_a_search_run_takes_a_national_services_jobs(monkeypatch):
    db.kv_set("profile.answers", {"target_roles": ["Registered Nurse"], "country": "Canada"})
    settings.save(make_cfg(levels=["mid"], allowed=["Canada"]))
    monkeypatch.setattr(catalog, "SOURCES", [catalog.BY_ID["jobbank_ca"]])
    feed = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>registered nurse</title><link href="https://www.jobbank.gc.ca/jobsearch/jobposting/9"/>
    <updated>2026-11-20T08:00:00Z</updated><summary><![CDATA[<strong>Location:</strong> Vancouver, BC <br /><strong>Employer:</strong> Example Clinic]]></summary></entry></feed>"""
    run = pipeline.Pipeline("boards")

    async def go():
        await run.ctx.client.aclose()
        run.ctx.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=feed)))
        await run._run_collector("Job sites", catalog.collect)
        await run.ctx.close()
    asyncio.run(go())
    assert run.stats["found"] == 1 and run.stats["candidates"] == 1  # through the real filters, without being counted twice
    (_, job), = run.pool.values()
    assert job.source == "jobbank_ca" and job.meta["country"] == "CA"


def test_requests_keep_the_apps_own_user_agent():
    seen = {}

    def reply(request):
        seen.update(request.headers)
        return httpx.Response(200, text=FEED)
    ctx, _, _ = served({"https://www.nejmcareercenter.org/": reply})
    ctx.client.headers["User-Agent"] = base.UA

    async def go():
        try:
            return await catalog.read_source(ctx, catalog.BY_ID["madgex_nejm"])
        finally:
            await ctx.close()
    asyncio.run(go())
    assert seen["user-agent"] == base.UA


# ---------------------------------------------------------------- employer boards from the user's own leads


def lead(url: str, company: str, score: int = 70, apply_url: str = "") -> None:
    db.ex("INSERT INTO leads(fingerprint, title, company, url, apply_url, score, stage, app_status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (url, "Nurse", company, url, apply_url, score, "filtered", "new", db.now(), db.now()))


def test_boards_are_found_in_the_users_own_leads(monkeypatch):
    targets("Registered Nurse")
    lead("https://example.bamboohr.com/careers/12", "Example Care", 90)
    lead("https://example.bamboohr.com/careers/13", "Example Care", 80)  # the same board again
    lead("https://www.linkedin.com/jobs/view/123456", "Fabrikam", 85, "https://jobs.lever.co/fabrikam/abc")  # through its apply link
    lead("https://jobs.example.org/not-a-board", "Contoso", 75)
    lead("https://boards.greenhouse.io/already/jobs/1", "Already Followed", 60)
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["sources"]["ats_boards"]["boards"] = [{"ats": "greenhouse", "slug": "already", "name": "Already Followed"}]
    found = catalog.mined_boards(cfg)
    assert [(b["ats"], b.get("slug"), b["name"]) for b in found] == [("bamboohr", "example", "Example Care"), ("lever", "fabrikam", "Fabrikam")]


def test_found_boards_are_read_in_turns(monkeypatch):
    targets("Registered Nurse")
    monkeypatch.setattr(catalog, "MINED_BOARDS_PER_RUN", 2)
    for n in range(5):
        lead(f"https://company{n}.breezy.hr/p/1", f"Company {n}", 90 - n)
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    read_boards = []

    async def fake_board(ctx, b):
        read_boards.append(b["slug"])
        return [RawJob("ats", "Nurse", b["name"], f"https://{b['slug']}.breezy.hr/p/1")]
    monkeypatch.setattr(ats, "read_board", fake_board)

    def one_run():
        ctx, _, _ = served({}, cfg)

        async def go():
            try:
                return await catalog.read_source(ctx, catalog.BY_ID["ats_link_mining"])
            finally:
                await ctx.close()
        return asyncio.run(go())
    assert len(one_run()) == 2 and read_boards == ["company0", "company1"]
    read_boards.clear()
    one_run()
    assert read_boards == ["company2", "company3"]  # the next ones wait their turn, then it wraps around
    read_boards.clear()
    one_run()
    assert read_boards == ["company4", "company0"]


# ---------------------------------------------------------------- Reddit, which now refuses most anonymous feeds


def reddit_cfg() -> dict:
    cfg = make_cfg(levels=["mid"], allowed=["Ohio"])
    cfg["sources"]["reddit"]["subreddits"] = ["forhire", "jobbit"]
    return cfg


def fast_sleep(monkeypatch) -> None:
    real_sleep = asyncio.sleep

    async def quick(_seconds):
        await real_sleep(0)
    monkeypatch.setattr(feeds.asyncio, "sleep", quick)


def test_reddit_stops_at_its_first_refusal(monkeypatch):
    fast_sleep(monkeypatch)
    targets("Line Cook")
    ctx, asked, log = served({"https://www.reddit.com/": (404, "<feed><title>Not Found</title></feed>")}, reddit_cfg())

    async def go():
        try:
            return await feeds.reddit(ctx)
        finally:
            await ctx.close()
    assert asyncio.run(go()) == [] and len(asked) == 1
    assert "add a free Reddit app key" in log[-1][1] and log[-1][0] == "warn"


def test_reddit_with_the_users_own_app_uses_the_official_api(monkeypatch):
    fast_sleep(monkeypatch)
    targets("Line Cook")
    cfg = reddit_cfg()
    cfg["sources"]["reddit"].update(client_id="app-id", client_secret="app-secret")
    listing = {"data": {"children": [
        {"data": {"title": "[Hiring] Line cook", "selftext": "We're hiring a line cook, apply today.", "permalink": "/r/forhire/comments/1/hiring/", "created_utc": 1795400000}},
        {"data": {"title": "Best knives?", "selftext": "Any tips?", "permalink": "/r/forhire/comments/2/knives/", "created_utc": 1795400000}}]}}
    seen = []

    def api(request):
        seen.append((request.headers["authorization"], request.headers["user-agent"]))
        return httpx.Response(200, json=listing)
    ctx, asked, _ = served({"https://www.reddit.com/api/v1/access_token": {"access_token": "tok"}, "https://oauth.reddit.com/": api}, cfg)

    async def go():
        try:
            return await feeds.reddit(ctx)
        finally:
            await ctx.close()
    jobs = asyncio.run(go())
    assert asked[0][0] == "POST" and asked[0][2] == "grant_type=client_credentials"
    assert {j.url for j in jobs} == {"https://www.reddit.com/r/forhire/comments/1/hiring/"} and jobs[0].source == "reddit"
    assert seen[0][0] == "bearer tok" and seen[0][1] == feeds.REDDIT_APP and all("oauth.reddit.com" in a[1] for a in asked[1:])


def test_a_refused_reddit_key_falls_back_to_the_feeds(monkeypatch):
    fast_sleep(monkeypatch)
    targets("Line Cook")
    cfg = reddit_cfg()
    cfg["sources"]["reddit"].update(client_id="app-id", client_secret="wrong")
    ctx, asked, log = served({"https://www.reddit.com/api/v1/access_token": 401, "https://www.reddit.com/r/": 404}, cfg)

    async def go():
        try:
            return await feeds.reddit(ctx)
        finally:
            await ctx.close()
    assert asyncio.run(go()) == [] and len(asked) == 2
    assert any("refused the app key" in m for _, m in log)
