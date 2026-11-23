"""The source catalog: every job site and public job service JobPortal can read, as one table, and the collector that reads
the ones that are useful for this person.

Each Source in SOURCES says where it is, what it serves and how to read it. One parser (readers.py) serves many sources:
to add a site with a format that's already here, add one entry and nothing else. Its id is the lead's `source`.

Which sources run (active):
- A source for some fields runs when the user's fields (plan.groups) include one of them. Sources for every field run for
  everyone, so a person whose fields aren't known yet still gets those.
- A source for some countries runs when the search area or the person's home country is in it (countries.Area).
- Settings, sources.catalog: one master switch per group, and an `off` list of ids the user turned off. Nothing lists the
  sources that are on, so a source added to this table later reaches existing users by itself, and one they turned off
  stays off. A source that needs a free key stays off until the key is entered (`keys`).

Being a good citizen: every request goes through the shared Ctx (its limit per site, its stop flag, the app's own User-Agent)
with no retries. A source makes at most `terms` searches per run. A 401, 403 or 429, or a page that asks for a person,
ends that source for the run, and nothing tries to get past it. A dead, slow or changed source costs one log line, and the
whole batch has a time limit, so it never holds up the rest of the run."""
import asyncio
import base64
import html as html_module
import io
import json
import random
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import quote, quote_plus, unquote, urljoin

import httpx

from jobportal.core import db
from jobportal.core.levels import posting_regex
from jobportal.core.textutil import (
    NATIONWIDE_RE,
    REMOTE_RE,
    LocationMatcher,
    TargetMatcher,
    age_days,
    clean,
    html_to_text,
    parse_date,
    state_of,
)
from jobportal.search import countries as places, plan
from jobportal.search.collectors import ats, readers
from jobportal.search.collectors.base import Blocked, Ctx, RawJob
from jobportal.search.collectors.readers import pick, text_of

GROUPS = {"field": "Field boards", "general": "General boards", "national": "Public job services",
          "community": "Communities", "discovery": "Discovery"}
ALL = ("all",)  # serves every field
WORLD = ("*",)  # serves every country
SOURCES_AT_ONCE = 12  # sources read in parallel; Ctx still limits the requests to one site
REQUEST_SECONDS = 20  # the most one request may take
SOURCE_SECONDS = 45  # the most one source may take, all its requests together
BATCH_SECONDS = 180  # the most the whole catalog may take in one run
MAX_DESCRIPTION = 12000
MINED_BOARDS_PER_RUN = 24  # employer boards found in the user's own leads, read per run (the rest wait their turn)
SITEMAP_MATCHES = 120  # sitemap pages kept per run
SEASONAL_MATCHES = 150  # seasonal job orders kept per run
SEASONAL_SECONDS = 60  # the most its one large download may take
# What a page that asks for a person looks like. It's only read when a page held no jobs, since a normal page can carry a
# captcha script for its forms.
CHALLENGE_RE = re.compile(r"<title>\s*(?:just a moment|attention required|access denied|are you a robot|pardon our interruption"
                          r"|security check|verify you are human)|cf-browser-verification|challenges\.cloudflare\.com/turnstile"
                          r"|botchallenge|enable javascript and cookies to continue", re.I)
# A community post must use one of these words to count as a hiring post, besides matching the user's level or roles.
HIRING_RE = re.compile(r"hiring|opening|apply|position|role|looking for|\bjobs?\b|wanted|vacanc|needed", re.I)


@dataclass(frozen=True, eq=False)
class Source:
    """One entry of the catalog."""
    id: str  # the settings id and the lead's source
    name: str  # what the Sources dialog shows: the site's name and nothing more
    group: str  # a GROUPS key
    reader: str  # how to read it: a kind of page (see _parse), or a key of SPECIAL for the few that take more than one step
    url: str = ""  # {term} search word, {slug} the same as a path, {place} a place, {target} one of `targets`
    fields: tuple = ALL  # field groups it serves (core/genres.GROUPS), or ALL
    countries: tuple = WORLD  # ISO country codes it serves, or WORLD
    items: str = ""  # where the records are in the answer: a path for JSON, a tag for XML
    map: dict = field(default_factory=dict)  # where each RawJob field is in a record (readers.pick)
    cards: dict = field(default_factory=dict)  # what one job looks like on an HTML page (readers.card_records)
    method: str = "GET"
    body: object = None  # a JSON body with the same {placeholders}, or a function(term, place, countries)
    headers: dict = field(default_factory=dict)
    terms: int = 2  # searches per run, for a source with {term}
    targets: tuple = ()  # the channels, repositories or forums to read, one request each
    within: tuple = ()  # for a source that covers part of a country: its US state codes, or words a place in it contains
    needs: object = None  # a function(cfg) -> bool for sources with one more condition
    keys: tuple = ()  # names of the free API keys it needs, stored under sources.catalog.keys.<id>
    kind: str = "posting"  # or "event"
    posts: bool = False  # community posts: free-form titles, and they must read like a hiring post
    ads: bool = False  # classified ads in a jobs section: free-form titles, but every item already offers work
    gig: bool = False  # freelance projects: free-form titles that still have to match the user's work (the target-role filter)
    keep: str = ""  # a regex an item's text must match, for a source that also returns other things
    limit: int = 0  # the most items kept from one run, for a source whose items are worth a look but aren't postings
    auth: object = None  # a function(keys) -> headers, for sources with `keys`
    link: str = ""  # where a person gets the free key

    @property
    def country(self) -> str:
        """The one country this source lists, when it's only one and not the US (which the location filter reads well)."""
        return self.countries[0] if len(self.countries) == 1 and self.countries[0] not in ("*", "US") else ""


# ---------------------------------------------------------------- small readers for the table


def _before(text: str, sep: str = ": ") -> str:
    """The part of a headline before `sep` ("Company: Job title")."""
    head, found, _ = str(text).partition(sep)
    return head.strip() if found else ""


def _after(text: str, sep: str = ": ") -> str:
    """The part of a headline after `sep`, or all of it."""
    _, found, tail = str(text).partition(sep)
    return tail.strip() if found else str(text).strip()


def _labeled(text, label: str) -> str:
    """The value after "Label:" in a block of text ("Location: Dartmouth (NS) Employer: Hilltop Villa")."""
    found = re.search(rf"{label}:\s*(.*?)(?:\s+[A-Z][a-z]+(?: [a-z]+)?:|$)", html_to_text(str(text)).replace("\n", " "))
    return found.group(1).strip() if found else ""


def _madgex_place(record: dict) -> str:
    """A Madgex board's description ends with the place after "...": "...live the healthiest l... Las Vegas, Nevada"."""
    text = clean(record.get("description"))
    place = clean(text.rsplit("...", 1)[-1]) if "..." in text else ""
    return place if place[:1].isupper() and len(place) <= 60 and not place.endswith(".") else ""  # else it's more of the sentence


def _paren_place(title: str) -> str:
    """A place written in parentheses at the end of a title: "Head Field Technician (Kluane, Yukon, Canada)"."""
    found = re.search(r"\(([^()]*,[^()]*)\)\s*$", str(title))
    return found.group(1).strip() if found else ""


def _no_tracking(url: str) -> str:
    """A link without its query, for feeds that add tracking parameters to every link."""
    return str(url).split("?", 1)[0]


def _slug_words(slug: str) -> str:
    """Words from a slug in an address: "The-Langham-Chicago" gives "The Langham Chicago". Some sites escape a slug twice."""
    return clean(re.sub(r"[-_+]+", " ", html_module.unescape(unquote(unquote(slug)))))


def _after_last(text: str, sep: str) -> str:
    """The part of a headline after the last `sep`, such as a news item's outlet ("Job fair this week - Daily News")."""
    return str(text).rsplit(sep, 1)[-1].strip() if sep in str(text) else ""


def _js_text(text: str) -> str:
    """Text from a JavaScript string: "National\\x20Museum" gives "National Museum"."""
    return clean(re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), str(text)))


def _dmy(value) -> str:
    """"23.11.2026" as "2026-11-23", for sites that write the day first."""
    found = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", clean(value))
    return f"{found.group(3)}-{int(found.group(2)):02d}-{int(found.group(1)):02d}" if found else str(value or "")


def _dig_text(record, path: str) -> str:
    """A value by its path, as text."""
    return str(readers.dig(record, path) or "")


def _with_scheme(url: str) -> str:
    """An address with https:// in front when a site left it off."""
    url = url.strip()
    return url if not url or url.startswith("http") else f"https://{url}"


def _short_us_date(value: str) -> str:
    """"11/23/26" as "2026-11-23", for sites that write two-digit years."""
    found = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2})", clean(value))
    return f"20{found.group(3)}-{int(found.group(1)):02d}-{int(found.group(2)):02d}" if found else value


def _eures_body(term: str, _place: str, codes: list[str]) -> dict:
    """The search EURES' own page sends: newest first, in the user's European countries."""
    return {"resultsPerPage": 50, "page": 1, "sortSearch": "MOST_RECENT",
            "keywords": [{"keyword": term, "specificSearchCode": "EVERYWHERE"}] if term else [], "publicationPeriod": None,
            "occupationUris": [], "skillUris": [], "requiredExperienceCodes": [], "positionScheduleCodes": [], "sectorCodes": [],
            "educationAndQualificationLevelCodes": [], "positionOfferingCodes": [],
            "locationCodes": [c.lower() for c in codes if c in places.EUROPE and c != "GB"], "euresFlagCodes": [],
            "otherBenefitsCodes": [], "requiredLanguages": [], "minNumberPost": None, "sessionId": "jobportal"}


def _eures_place(record: dict) -> str:
    """A EURES posting's countries, by name."""
    return ", ".join(places.NAMES.get(code, code) for code in (record.get("locationMap") or {}))


def _eures_country(record: dict) -> str:
    """The first country a EURES posting is in."""
    return next(iter(record.get("locationMap") or {}), "")


def _fi_text(value) -> str:
    """A Finnish service's text, which comes in several languages: English when there is one."""
    if isinstance(value, dict):
        return value.get("en") or value.get("fi") or value.get("sv") or next(iter(value.values()), "")
    return value or ""


def _fi_place(record: dict) -> str:
    """A Finnish posting's towns."""
    where = record.get("location") or {}
    towns = [_fi_text(m.get("label")) for m in where.get("municipalities") or [] if isinstance(m, dict)]
    return ", ".join(t for t in towns if t) or (where.get("address") or {}).get("postOffice") or ""


def _day_month_name(value) -> str:
    """"03-Jul-2027" as "2027-07-03"."""
    try:
        return datetime.strptime(clean(value), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return ""


def _seasonal_text(record: dict) -> str:
    """A seasonal job order's description: the duties, the pay and the dates. Its contact people stay out."""
    pay = f"Pay: ${record['jobWageOffer']} per {str(record.get('jobWagePer') or 'hour').lower()}" if record.get("jobWageOffer") else ""
    dates = f"Season: {record.get('jobBeginDate')} to {record.get('jobEndDate')}" if record.get("jobBeginDate") else ""
    return "\n".join(x for x in (record.get("jobDuties"), pay, dates) if x)


def _budget(record: dict) -> str:
    """A freelance project's budget as a line for its description."""
    budget, currency = record.get("budget") or {}, (record.get("currency") or {}).get("code", "")
    return f"\n\nBudget: {budget.get('minimum')} to {budget.get('maximum')} {currency}" if budget.get("minimum") else ""


def _madgex(id_: str, name: str, base: str, fields: tuple, countries: tuple = WORLD) -> Source:
    """A board on the Madgex platform: an RSS feed at /jobsrss/ whose titles read "Employer: Job title"."""
    return Source(id_, name, "field", "feed", f"{base}/jobsrss/?keywords={{term}}", fields=fields, countries=countries, map={
        "title": lambda r: _after(r.get("title", "")), "company": lambda r: _before(r.get("title", "")),
        "location": _madgex_place, "url": lambda r: _no_tracking(r.get("link", "")), "date": "pubDate",
        "description": "description"})


def _classifieds_title(text: str) -> str:
    """A title without a seller's shouting."""
    text = clean(text)
    return text.title() if text.isupper() else text


# ---------------------------------------------------------------- the catalog


SOURCES: list[Source] = [
    # ---------------- boards for one field
    _madgex("madgex_chronicle", "Chronicle of Higher Education", "https://jobs.chronicle.com", ("education", "science"), ("US",)),
    _madgex("madgex_insidehighered", "Inside Higher Ed", "https://careers.insidehighered.com", ("education", "science"), ("US",)),
    _madgex("madgex_the", "Times Higher Education", "https://www.timeshighereducation.com/unijobs", ("education", "science")),
    _madgex("madgex_nature", "Nature Careers", "https://www.nature.com/naturecareers", ("science", "education", "healthcare")),
    _madgex("madgex_science", "Science Careers", "https://jobs.sciencecareers.org", ("science", "education")),
    _madgex("madgex_nejm", "NEJM CareerCenter", "https://www.nejmcareercenter.org", ("healthcare",), ("US",)),
    _madgex("madgex_philanthropy", "Chronicle of Philanthropy", "https://jobs.philanthropy.com", ("public", "business")),
    _madgex("madgex_vettimes", "Vet Times", "https://jobs.vettimes.com", ("healthcare", "science"), ("GB",)),
    _madgex("madgex_fwi", "Farmers Weekly", "https://jobs.fwi.co.uk", ("science", "trades"), ("GB",)),
    _madgex("madgex_pharmjournal", "Pharmaceutical Journal", "https://jobs.pharmaceutical-journal.com", ("healthcare",), ("GB", "NZ")),
    _madgex("madgex_chemworld", "Chemistry World", "https://jobs.chemistryworld.com", ("science",)),
    _madgex("madgex_physicsworld", "Physics World", "https://www.physicsworldjobs.com", ("science",)),
    _madgex("madgex_economist", "The Economist", "https://jobs.economist.com", ("business", "public")),
    _madgex("madgex_ft", "FT Executive Appointments", "https://www.exec-appointments.com", ("business", "public")),
    Source("schoolspring", "SchoolSpring", "field", "json",
           "https://api.schoolspring.com/api/Jobs/GetPagedJobsWithSearch?domainName=www.schoolspring.com&keyword={term}&location={place}"
           "&category=&gradelevel=&jobtype=&organization=&swLat=&swLon=&neLat=&neLon=&page=1&size=100&sortDateAscending=false",
           fields=("education",), countries=("US",), items="value.jobsList",
           map={"title": "title", "company": "employer", "location": "location",
                "url": "https://www.schoolspring.com/jobdetail?jobId={jobId}", "date": "displayDate"}),
    Source("culinary_agents", "Culinary Agents", "field", "cards", "https://culinaryagents.com/search/jobs", fields=("service",),
           countries=("US",), cards={"card": r'class="job-title text-ellipsis', "link": r'/entities/[^"]+?(/jobs/\d+-[^"?]+)',
                                     "title": r'<strong>(.*?)</strong>', "company": r'text-body text-ellipsis">(.*?)</div>',
                                     "location": r'text-muted text-ellipsis">(.*?)(?:&bull;|</div>)'}),
    Source("hospitality_online", "Hospitality Online", "field", "cards", "https://www.hospitalityonline.com/jobs", fields=("service",),
           countries=("US",), cards={"card": r'class="card-title', "link": r'href="(/jobs/\d+[^"]*)">(.*?)</a>',
                                     "company": r'<div class="text-truncate">(.*?)</div>', "location": r'card-text[^"]*">(.*?)</div>'}),
    Source("coolworks", "CoolWorks", "field", "rows", "https://www.coolworks.com/search?search[keywords]={term}",
           fields=("service", "science"), countries=("US",), terms=1,
           cards={"row": r'href="(?P<path>/(?P<company>[a-z0-9-]+)/(?:highlighted-job|help-wanted)/\d+-(?P<title>[a-z0-9-]+))"'},
           map={"title": lambda r: _slug_words(re.sub(r"-\d+$", "", r["title"])).title(), "company": lambda r: _slug_words(r["company"]).title(),
                "url": "https://www.coolworks.com{path}"}),
    Source("alltruckjobs", "AllTruckJobs", "field", "cards", "https://www.alltruckjobs.com/jobs", fields=("trades",), countries=("US",),
           cards={"card": r'class="row job_result"|<div id="" class="card mb-4"', "link": r'<h3[^>]*><a[^>]*href="(https://www\.alltruckjobs\.com/job/\d+/[^"?]+)[^"]*"[^>]*>(.*?)</a>',
                  "company": r'<h4[^>]*>(.*?)</h4>', "location": r'<p class="d-block d-md-none[^"]*">(.*?)</p>', "date": r'sp-tablet-stack-s">(posted [^<]+)'}),
    Source("cdljobnow", "CDL Job Now", "field", "cards", "https://www.cdljobnow.com/", fields=("trades",), countries=("US",),
           cards={"card": r'class="listing-card', "link": r'href="(https://www\.cdljobnow\.com/jobs/\d+/[^"]+)"',
                  "title": r'<(?:h\d|p)[^>]*>\s*(CDL[^<]*|[^<]{8,})</', "company": r'alt="([^"]+?)\s*Logo"'}),
    Source("academic_jobs_online", "Academic Jobs Online", "field", "feed", "https://academicjobsonline.org/ajo?joblist-0-0-0-----rss--",
           fields=("education", "science"), map={
               "title": "title", "company": ("Univ", "univ"), "location": ["City", "State", "Country"],
               "url": lambda r: _no_tracking(r.get("link", "")), "date": ("PostDate", "date"), "deadline": "Deadline",
               "description": "description"}),
    Source("euraxess", "EURAXESS", "field", "cards", "https://euraxess.ec.europa.eu/jobs/search", fields=("science", "education"),
           cards={"card": r'<article', "link": r'<a\s+href="(/jobs/\d+)"[^>]*>\s*(?:<span>)?(.*?)(?:</span>)?\s*</a>',
                  "company": r'hreflang="en">(.*?)</a>', "date": r'Posted on:\s*([^<]+)', "description": r'__description"><p>(.*?)</p>'}),
    Source("healthecareers", "Health eCareers", "field", "cards", "https://www.healthecareers.com/search-jobs", fields=("healthcare",),
           countries=("US",), cards={"card": r'class="job-title', "link": r'href="(https://www\.healthecareers\.com/job/[^"]+)"[^>]*>\s*<span[^>]*>(.*?)</span>',
                                     "location": r'job-results-location">(.*?)</span>', "company": r'job-results-employer"[^>]*>(.*?)</span>',
                                     "description": r'job-results-desc"[^>]*>(.*?)</div>'}),
    Source("physemp", "PhysEmp", "field", "cards", "https://www.physemp.com/physician/jobs/{slug}/full-time/all", fields=("healthcare",),
           countries=("US",), terms=1, cards={"link": r'href="(/[a-z-]+/jobs/\d+)">(.*?)</a>',
                                              "company": r'font-medium">(.*?)</span>', "description": r'<p class="text-sm[^"]*">(.*?)</p>'},
           map={"location": lambda r: _after(r.get("title", ""), " Job ")}),
    Source("agcareers", "AgCareers", "field", "cards", "https://www.agcareers.com/job-all.cfm", fields=("science", "trades"),
           countries=("US", "CA"), cards={"card": r'class="ResultDetails"', "link": r'href="(/[^"]+-job-\d+\.cfm)">(.*?)</a>',
                                          "location": r'lbl_text">.*?<br\s*/?>\s*(.*?)\s*\(\d+ km\)', "date": r'lbl_text">\s*([^|<]+?)\s*\|'},
           map={"company": lambda r: _slug_words(r["url"].split("/")[3]).title()}),
    Source("unionjobs", "UnionJobs", "field", "feed", "https://unionjobs.com/rss.php", fields=("public",), countries=("US",), map={
        "title": lambda r: _before(r.get("title", ""), " : ") or r.get("title", ""),
        "company": lambda r: text_of((re.search(r"<strong>(.*?)</strong>", r.get("description", ""), re.S) or [""," "])[1]),
        "location": lambda r: _after(r.get("title", ""), " : "), "url": "link", "date": "pubDate", "description": "description"}),
    Source("rigzone", "Rigzone", "field", "cards", "https://www.rigzone.com/oil/jobs/search/?sk={term}", fields=("trades", "science"),
           cards={"card": r'<article class="update-block', "link": r'href="(/oil/jobs/postings/\d+[^"?]*)[^"]*">\s*(.*?)\s*</a>',
                  "company": r'<address>\s*([^<]+)', "location": r'<address>.*?<br\s*/?>\s*(.*?)\s*</address>'}),
    Source("charityjob", "CharityJob", "field", "cards", "https://www.charityjob.co.uk/jobs?keywords={term}", fields=("public", "healthcare"),
           countries=("GB",), cards={"card": r'class="job-title', "link": r'href="(https://www\.charityjob\.co\.uk/jobs/[^/"]+/[^/"]+/\d+)"[^>]*>\s*(.*?)\s*</a>',
                                     "company": r'class="organi[s]ation">([^,<]+)', "location": r'class="organi[s]ation">[^,<]+,\s*([^<]+)',
                                     "date": r'posted-item">\s*(.*?)\s*</div>'}),
    Source("impactpool", "Impactpool", "field", "cards", "https://www.impactpool.org/search?page=1&per_page=40", fields=("public",),
           cards={"card": r"<div class='job'>", "link": r'href="(/jobs/\d+)"', "title": r"type='cardTitle'>(.*?)</h3>",
                  "company": r"type='bodyEmphasis'>\s*(.*?)\s*</div>", "location": r"type='bodyEmphasis'>.*?type='bodyEmphasis'>\s*(.*?)\s*</div>"}),
    Source("unjobs", "UNjobs", "field", "cards", "https://unjobs.org/New/1", fields=("public",),
           cards={"card": r'class="job"', "link": r'class="jtitle" href="(https://unjobs\.org/vacancies/\d+)">(.*?)</a>',
                  "company": r'</a><br>\s*([^<]+)', "date": r'datetime="([^"]+)"'},
           map={"location": lambda r: _after(r.get("title", ""), ", ")}),
    Source("tamu_nrjb", "Natural Resources Job Board", "field", "cards", "https://jobs.rwfm.tamu.edu/search/", fields=("science",),
           countries=("US", "CA"), cards={"card": r"id=job-\d+-result", "link": r'href=#job-(\d+)', "title": r"<h6>(.*?)</h6>",
                                          "company": r"<p>(.*?)</p>"},
           map={"url": lambda r: "https://jobs.rwfm.tamu.edu/view-job/?id=" + r["url"].rsplit("/", 1)[-1],
                "location": lambda r: _paren_place(r.get("title", ""))}),
    Source("aam_jobhq", "AAM JobHQ", "field", "cards", "https://aam-us-jobs.careerwebsite.com/jobs/", fields=("education", "creative"),
           countries=("US",), cards={"card": r'class="job-card', "link": r'data-job-id="(\d+)"', "title": r'job-title"[^>]*title="([^"]+)"',
                                     "company": r"selectJob\('\d+',\s*this,\s*\w+,\s*'[^']*',\s*'([^']*)'",
                                     "location": r'meta-location">\s*(?:<i[^>]*></i>)?\s*(.*?)\s*</span>'},
           map={"url": lambda r: "https://aam-us-jobs.careerwebsite.com/job/" + r["url"].rsplit("/", 1)[-1] + "/",
                "company": lambda r: _js_text(r.get("company", ""))}),
    Source("archivesgig", "ArchivesGig", "field", "feed", "https://archivesgig.com/feed/", fields=("education",), countries=("US", "CA"),
           map={"title": lambda r: _after(r.get("title", "")).rsplit(", ", 1)[0],
                "company": lambda r: _after(r.get("title", "")).rsplit(", ", 1)[-1],
                "location": lambda r: _before(r.get("title", "")), "url": "link", "date": "pubDate", "description": "description"}),
    Source("playbill", "Playbill", "field", "cards", "https://playbill.com/jobs", fields=("creative",), countries=("US",),
           cards={"card": r'class="pb-tile-wrapper"', "link": r'href="(https://playbill\.com/job/[^"]+)"',
                  "title": r'pb-tile-title">(.*?)</div>', "company": r'pb-tile-location">\s*(.*?)<br',
                  "location": r'pb-tile-location">.*?<br>(.*?)</div>', "date": r'pb-tile-post-date">\s*(.*?)\s*</div>'}),
    Source("artsjobs_uk", "Arts Jobs", "field", "cards", "https://www.artsjobs.org.uk/", fields=("creative",), countries=("GB",),
           cards={"card": r'<header class="listing-header"', "link": r'href="(/jobs/\d+)"[^>]*>(.*?)</a>',
                  "company": r'job__organisation-name">(.*?)</div>', "location": r'ri-map-pin-2-fill"></i>\s*<div[^>]*>(.*?)</div>'}),
    Source("journalismjobs", "JournalismJobs", "field", "cards", "https://www.journalismjobs.com/job-listings", fields=("creative",),
           countries=("US",), cards={"link": r'<a href="(/\d+-[^"]+)"[^>]*class="[^"]*job-item', "title": r'job-item-title">(.*?)</h3>',
                                     "company": r'job-item-company">(.*?)</div>', "description": r'job-item-description">(.*?)</div>',
                                     "location": r'fa-map-marker-alt"></i>\s*(.*?)\s*</li>'}),
    Source("mediabistro", "Mediabistro", "field", "cards", "https://www.mediabistro.com/jobs", fields=("creative", "business"),
           countries=("US",), cards={"card": r'<li class="min-w-0"', "link": r'href="(/jobs/\d+[^"]*)"',
                                     "title": r'<h3[^>]*>(.*?)</h3>', "company": r'<p class="text-base[^"]*">(.*?)</p>',
                                     "date": r'<p class="text-sm[^"]*">(.*?)</p>'}),
    Source("churchjobfinder", "Church Job Finder", "field", "livewire", "https://churchjobfinder.com/", fields=("public",), countries=("US",),
           map={"title": "title", "company": ("church.name", "team.name", "organization_name"),
                "location": ["location.0.city", "location.0.subnational_division"],
                "url": "https://churchjobfinder.com/church-jobs/{slug}", "date": "published_at", "deadline": "closing_date",
                "description": "description"}),
    Source("teamwork_online", "TeamWork Online", "field", "cards", "https://www.teamworkonline.com/jobs-in-sports",
           fields=("business", "service", "creative"), countries=("US", "CA"),
           cards={"link": r'browse-jobs-card__content--title" href="([^"]+)">\s*<div[^>]*>(.*?)</div>',
                  "company": r'--organization">(.*?)</div>', "location": r'--small">(.*?)</div>'}),
    Source("crewseekers", "Crewseekers", "field", "cards", "https://www.crewseekers.net/", fields=("trades", "service"),
           cards={"card": r'<article class="crd-List_Item"', "link": r'href="(/opportunities/\d+[^"]*)"', "title": r'crd-Card_Title">(.*?)</h3>'}),
    Source("allcruisejobs", "AllCruiseJobs", "field", "cards", "https://www.allcruisejobs.com/", fields=("service", "trades"),
           cards={"link": r'<li><a href="(https://www\.allcruisejobs\.com/i\d+/[^"]+)">(.*?)</a>', "date": r'<br>\s*([A-Z][a-z]+ \d{1,2}, \d{4})'}),
    Source("mathjobs", "MathJobs", "field", "mathjobs", "https://www.mathjobs.org/jobs?joblist-0-0-0-----rss--", fields=("education", "science")),
    Source("freelancer", "Freelancer", "community", "json", "https://www.freelancer.com/api/projects/0.1/projects/active?query={term}&limit=50",
           fields=("creative", "tech", "business", "science"), items="result.projects", gig=True, map={
               "title": "title", "url": "https://www.freelancer.com/projects/{seo_url}", "date": "submitdate", "location": lambda _r: "Remote",
               "description": lambda r: (r.get("preview_description") or "") + _budget(r)}),
    # ---------------- general boards
    Source("workable_search", "Workable", "discovery", "json", "https://jobs.workable.com/api/v1/jobs?query={term}&location={place}",
           items="jobs", terms=3, map={
               "title": "title", "company": "company.title", "url": "url", "date": "created",
               "location": ("locations", ["location.city", "location.subregion", "location.countryName"]),
               "description": ("description", "socialSharingDescription")}),
    Source("amazon_jobs", "Amazon", "general", "json", "https://www.amazon.jobs/en/search.json?base_query={term}&result_limit=100",
           items="jobs", map={"title": "title", "company": lambda r: "Amazon", "location": "normalized_location",
                              "url": "https://www.amazon.jobs{job_path}", "date": "posted_date",
                              "description": ["description", "basic_qualifications"]}),
    Source("talent_com", "Talent.com", "general", "cards", "https://www.talent.com/jobs?k={term}&l={place}", countries=("US",),
           cards={"card": r'<article class="JobCard', "link": r'href="(/view\?id=[^"]+)"',
                  "title": r'<h2[^>]*>(.*?)</h2>', "company": r'JobCard_company[^"]*"[^>]*>(.*?)</',
                  "location": r'JobCard_location[^"]*"[^>]*>(.*?)</', "date": r'dateTime="([^"]+)"'}),
    Source("dice", "Dice", "general", "cards", "https://www.dice.com/jobs?q={term}&location={place}", fields=("tech", "science"),
           countries=("US",), cards={"card": r'data-testid="job-card"', "link": r'data-rac="" aria-label="[^"]*" href="(/job-detail/[0-9a-f-]+)"[^>]*>(.*?)</a>',
                                     "company": r'<p[^>]*title="([^"]+)"', "location": r'</a><p[^>]*>([^<]+)<!-- -->',
                                     "date": r'<!-- --> • <!-- -->([^<]+)</p>'}),
    Source("hellowork", "HelloWork", "general", "cards", "https://www.hellowork.com/fr-fr/emploi/recherche.html?k={term}", countries=("FR",),
           cards={"link": r'href="(/fr-fr/emplois/\d+\.html)"\s+title="([^"]+)"'}, map={
               "company": lambda r: _after_last(r.get("title", ""), " - "), "title": lambda r: r.get("title", "").rsplit(" - ", 1)[0]}),
    Source("arbeitnow", "Arbeitnow", "general", "json", "https://www.arbeitnow.com/api/job-board-api?page=1",
           countries=("DE", "AT", "CH"), items="data", map={"title": "title", "company": "company_name", "location": "location", "url": "url",
                                                             "date": "created_at", "description": "description", "country": lambda _r: "DE"}),
    Source("jobberman", "Jobberman", "general", "cards", "https://www.jobberman.com/jobs?q={term}", countries=("NG",),
           cards={"link": r'href="(https://www\.jobberman\.com/listings/[^"]+)"[^>]*data-cy="listing-title-link"[^>]*>(.*?)</a>',
                  "company": r'truncate text-text-secondary">(.*?)</span>', "date": r'(\d+\s+(?:hour|day|week|month)s? ago|Today|Yesterday)'}),
    # ---------------- public job services
    Source("neogov", "GovernmentJobs", "national", "cards", "https://www.governmentjobs.com/jobs?keyword={term}&location={place}",
           countries=("US", "CA"), cards={"card": r'class="job-item-container"', "link": r'class="job-details-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                                          "company": r'job-organization">(.*?)</div>', "location": r'job-location">(.*?)</span>'}),
    Source("statejobs_ny", "StateJobsNY", "national", "cards", "https://statejobs.ny.gov/public/vacancyTable.cfm", countries=("US",),
           within=("NY",), cards={"card": r'<tr class="(?:even|odd)">', "link": r'href="(vacancyDetailsView\.cfm\?id=\d+)">(.*?)</a>',
                                          "date": r'</a></td>\s*<td>[^<]*</td>\s*<td>([^<]*)</td>',
                                          "company": r'</a></td>(?:\s*<td>[^<]*</td>){3}\s*<td>([^<]*)</td>',
                                          "location": r'</a></td>(?:\s*<td>[^<]*</td>){4}\s*<td>([^<]*)</td>',
                                          "description": r'</a></td>(?:\s*<td>[^<]*</td>){2}\s*<td>([^<]*)</td>'},
           map={"location": "{location}, NY", "date": lambda r: _short_us_date(r.get("date", "")),
                "deadline": lambda r: _short_us_date(r.get("description", "")), "description": lambda _r: ""}),
    Source("nyc_jobs", "NYC Jobs", "national", "json", "https://data.cityofnewyork.us/resource/kpav-sd4t.json?$limit=500&$order=posting_date%20DESC",
           countries=("US",), within=("NY",), map={
               "title": "business_title", "company": "agency", "location": "{work_location}, New York, NY",
               "url": "https://cityjobs.nyc.gov/job/{job_id}", "date": "posting_date", "description": ("job_description", "minimum_qual_requirements"),
               "deadline": "post_until"}),
    Source("seasonal_us", "SeasonalJobs", "national", "seasonal", "https://api.seasonaljobs.dol.gov/datahub-search/sjCaseData/zip/jo/{day}",
           fields=("science", "trades"), countries=("US",), map={
               "title": "jobTitle", "company": "empBusinessName", "location": ["jobCity", "jobState"],
               "url": "https://seasonaljobs.dol.gov/jobs/{caseNumber}", "date": "dateSubmitted",
               "deadline": lambda r: _day_month_name(r.get("expirationDate")), "description": _seasonal_text}),
    Source("workforce_au", "Workforce Australia", "national", "json",
           "https://www.workforceaustralia.gov.au/api/v1/global/vacancies/?pageNumber=1&pageSize=100&sort=DateAddedDescending&keyword={term}",
           countries=("AU",), items="results", map={
               "title": "result.title", "company": "result.employerName", "location": ["result.suburb", "result.state", "result.location.label"],
               "url": "https://www.workforceaustralia.gov.au/individuals/jobs/details/{result.vacancyId}", "date": "result.creationDate",
               "deadline": "result.expiryDate", "description": "result.description"}),
    Source("eures", "EURES", "national", "json", "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search", method="POST",
           body=_eures_body, countries=(*places.EU, "IS", "LI", "NO", "CH"), items="jvs", map={
               "title": "title", "company": "employer.name", "location": _eures_place, "country": _eures_country,
               "url": "https://europa.eu/eures/portal/jv-se/jv-details/{id}?lang=en", "date": "creationDate", "description": "description"}),
    Source("cbop_pl", "Praca.gov.pl", "national", "json", "https://oferty.praca.gov.pl/portal-api/v3/oferta/wyszukiwanie?page=0&size=50",
           method="POST", body={}, countries=("PL",), items="payload.ofertyPracyPage.content", map={
               "title": "stanowisko", "company": "pracodawca", "location": "miejscePracy",
               "url": "https://oferty.praca.gov.pl/portal/index.cbop?id={id}", "date": lambda r: _dmy(r.get("dataDodaniaCbop")),
               "deadline": lambda r: _dmy(r.get("dataWaznDo")), "description": ("wymagania", "rodzajUmowy")}),
    Source("jobbank_ca", "Job Bank", "national", "feed", "https://www.jobbank.gc.ca/jobsearch/feed/jobSearchRSSfeed?searchstring={term}&locationstring={place}&sort=D",
           countries=("CA",), map={"title": "title", "company": lambda r: _labeled(r.get("summary", ""), "Employer"),
                                   "location": lambda r: _labeled(r.get("summary", ""), "Location"), "url": "link", "date": "updated",
                                   "description": lambda r: html_to_text(r.get("summary", ""))}),
    Source("jobtech_se", "Platsbanken", "national", "json", "https://jobsearch.api.jobtechdev.se/search?q={term}&limit=100&offset=0",
           countries=("SE",), items="hits", map={
               "title": "headline", "company": "employer.name",
               "location": ["workplace_address.municipality", "workplace_address.region", "workplace_address.country"], "url": "webpage_url",
               "date": "publication_date", "deadline": "application_deadline", "description": "description.text"}),
    Source("nav_no", "Arbeidsplassen", "national", "json", "https://arbeidsplassen.nav.no/stillinger/api/search?q={term}&size=100",
           countries=("NO",), items="hits.hits", map={
               "title": "_source.title", "company": ("_source.employer.name", "_source.businessName"),
               "location": "_source.locationList[].city", "url": "https://arbeidsplassen.nav.no/stillinger/stilling/{_source.uuid}",
               "date": "_source.published", "deadline": "_source.expires", "description": "_source.generatedSearchMetadata.shortSummary"}),
    Source("jobroom_ch", "Job-Room", "national", "json",
           "https://www.job-room.ch/jobadservice/api/jobAdvertisements/_search?page=0&size=100&sort=date_desc", method="POST",
           body={"workloadPercentageMin": 10, "workloadPercentageMax": 100, "permanent": None, "companyName": None, "onlineSince": 30,
                 "displayRestricted": False, "professionCodes": [], "keywords": ["{term}"], "communalCodes": [], "cantonCodes": []},
           countries=("CH",), map={
               "title": "jobAdvertisement.jobContent.jobDescriptions.0.title",
               "company": "jobAdvertisement.jobContent.company.name",
               "location": ["jobAdvertisement.jobContent.location.city", "jobAdvertisement.jobContent.location.cantonCode"],
               "url": lambda r: _with_scheme(_dig_text(r, "jobAdvertisement.jobContent.externalUrl"))
               or f"https://www.job-room.ch/job-search/{_dig_text(r, 'jobAdvertisement.id')}",
               "date": "jobAdvertisement.publication.startDate", "deadline": "jobAdvertisement.publication.endDate",
               "description": "jobAdvertisement.jobContent.jobDescriptions.0.description"}),
    Source("mcf_sg", "MyCareersFuture", "national", "json", "https://api.mycareersfuture.gov.sg/v2/jobs?search={term}&limit=100&page=0",
           countries=("SG",), items="results", map={
               "title": "title", "company": ("hiringCompany.name", "postedCompany.name"),
               "location": lambda r: ", ".join(x for x in [(r.get("address") or {}).get("building"), "Singapore"] if x),
               "url": "metadata.jobDetailsUrl", "date": "metadata.newPostingDate", "deadline": "metadata.expiryDate",
               "description": "description"}),
    Source("nhs_jobs", "NHS Jobs", "national", "xml", "https://www.jobs.nhs.uk/api/v1/search_xml?keyword={term}&location={place}",
           fields=("healthcare", "business", "service", "trades", "tech"), countries=("GB",), items="vacancyDetails", map={
               "title": "title", "company": "employer", "location": ("locations.location",), "url": "url", "date": "postDate",
               "deadline": "closeDate", "description": lambda r: "\n".join(x for x in (r.get("description"), r.get("salary")) if x)}),
    Source("teaching_vacancies_uk", "Teaching Vacancies", "national", "json", "https://teaching-vacancies.service.gov.uk/api/v1/jobs.json?page=1",
           fields=("education", "business", "service"), countries=("GB",), items="data", map={
               "title": "title", "company": "hiringOrganization.name", "location": readers.ld_location, "url": "url", "date": "datePosted",
               "deadline": "validThrough", "description": "description"}),
    Source("apprenticeships_uk", "Find an Apprenticeship", "national", "cards",
           "https://www.findapprenticeship.service.gov.uk/apprenticeships?searchTerm={term}", countries=("GB",),
           cards={"card": r'class="das-search-results__list-item|<li class="das-search-results', "link": r'href="(/apprenticeship/VAC\d+)"[^>]*>\s*<span[^>]*>(.*?)</span>',
                  "company": r'</h2>.*?<p class="govuk-body[^"]*">(.*?)</p>', "location": r'das-!-color-dark-gr[e]y">(.*?)</p>',
                  "deadline": r'Closes in[^(]*\(\w+ (\d+ \w+ \d{4})\)'}),
    Source("myjobscotland", "myjobscotland", "national", "cards", "https://www.myjobscotland.gov.uk/search-jobs", countries=("GB",),
           within=("Scotland", "Glasgow", "Edinburgh", "Aberdeen", "Dundee", "Inverness", "Stirling"), cards={"card": r'class="mjs-card__body"', "link": r'href="(https://myjobscotland\.gov\.uk/[^"]+/jobs/[^"]+)">(.*?)</a>',
                                                            "company": r'Published by\s*(.*?)</span>', "location": r'mjs-card__description">\s*<p>(.*?)</p>'}),
    Source("tyomarkkinatori_fi", "Job Market Finland", "national", "json", "https://tyomarkkinatori.fi/api/jobpostingfulltext/search/v1/search",
           method="POST", body={"query": "{term}", "paging": {"pageNumber": 0, "pageSize": 50}}, countries=("FI",), items="content", map={
               "title": lambda r: _fi_text(r.get("title")),
               "company": lambda r: _fi_text((r.get("employer") or {}).get("ownerName")) or (r.get("employer") or {}).get("name"),
               "location": _fi_place, "url": "https://tyomarkkinatori.fi/en/personal-customers/vacancies/{id}", "date": "publishDate",
               "deadline": "applicationPeriodEndDate"}),
    Source("inpa_it", "InPA", "national", "json", "https://portale.inpa.gov.it/concorsi-smart/api/concorso-public-area/search-better?page=0&size=100",
           method="POST", body={"text": "{term}"}, countries=("IT",), items="content", map={
               "title": ("figuraRicercata", "titolo"), "company": "entiRiferimento.0", "location": lambda r: ", ".join(r.get("sedi") or []),
               "url": "https://www.inpa.gov.it/bandi-e-avvisi/dettaglio-bando-avviso/?concorso_id={id}", "date": "dataPubblicazione",
               "deadline": "dataScadenza", "description": ("descrizioneBreve", "descrizione")}),
    Source("csp_fr", "Choisir le service public", "national", "cards", "https://choisirleservicepublic.gouv.fr/nos-offres/filtres/mot-cles/{slug}/",
           countries=("FR",), cards={"card": r'<div class="fr-card fr-card--horizontal', "link": r'href="(https://choisirleservicepublic\.gouv\.fr/offre-emploi/[^"]+)"[^>]*>\s*(.*?)\s*</a>',
                                     "location": r'Locali[s]ation\s*:\s*</span>\s*(.*?)\s*</li>', "company": r'Employeur\s*:\s*</span>\s*(.*?)\s*</li>'}),
    Source("un_careers", "UN Careers", "national", "json", "https://careers.un.org/api/public/opening/jo/list/filteredV2/en",
           method="POST", body={"filterConfig": {"keyword": "{term}"}, "pagination": {"page": 0, "itemPerPage": 50, "sortBy": "startDate", "sortDirection": -1}},
           fields=ALL, items="data.list", map={
               "title": "postingTitle", "company": ("dept.name",), "location": "dutyStation[].description",
               "url": "https://careers.un.org/jobSearchDescription/{jobId}?language=en", "date": "startDate", "deadline": "endDate",
               "description": "jobDescription"}),
    # ---------------- community places
    Source("kijiji", "Kijiji", "community", "cards", "https://www.kijiji.ca/b-jobs/canada/{slug}/k0c45l0", countries=("CA",), posts=True, ads=True,
           cards={"card": r'<li data-testid="rich-card-list-item', "link": r'data-testid="rich-card-link" href="([^"]+)"[^>]*>(.*?)</a>',
                  "location": r'data-testid="listing-location"[^>]*>(.*?)</', "description": r'data-testid="listing-description"[^>]*>(.*?)</',
                  "date": r'data-testid="listing-date"[^>]*>(.*?)</'}, map={"title": lambda r: _classifieds_title(r.get("title", ""))}),
    Source("gumtree", "Gumtree", "community", "cards", "https://www.gumtree.com/search?search_category=jobs&q={term}", countries=("GB",), posts=True, ads=True,
           cards={"card": r'class="css-1uzjcc7-results-list"|data-q="search-result"', "link": r'href="(/p/[^"]+/\d+)"',
                  "title": r'data-q="tile-title">(.*?)</span>', "company": r'jrp-company-line">.*?jrp-separator[^>]*>.*?</span>\s*(.*?)</',
                  "location": r'jrp-location-line">.*?</svg>\s*(.*?)</'}),
    Source("github_issue_boards", "GitHub job boards", "community", "json", "https://api.github.com/repos/{target}/issues?state=open&per_page=50",
           fields=("tech",), countries=("BR",), posts=True, ads=True, targets=("backend-br/vagas", "frontendbr/vagas"), map={
               "title": "title", "url": "html_url", "date": "created_at", "description": "body"}),
    Source("lemmy", "Lemmy", "community", "json", "https://{target}/api/v3/search?q=hiring&type_=Posts&sort=New&limit=50", items="posts", posts=True,
           targets=("lemmy.world", "programming.dev"), map={
               "title": "post.name", "url": ("post.ap_id", "post.url"), "date": "post.published", "description": "post.body"}),
    Source("discourse", "Discourse forums", "community", "discourse", "https://{target}/search.json?q=hiring%20order%3Alatest", fields=("tech", "science"),
           posts=True, targets=("discourse.julialang.org",)),
    Source("telegram_public", "Telegram channels", "community", "telegram", "https://t.me/s/{target}", posts=True, targets=("remotejobs",)),
    Source("hn_jobstories", "Hacker News jobs", "community", "hn_jobs", "https://hacker-news.firebaseio.com/v0/jobstories.json", fields=("tech",), posts=True, ads=True),
    Source("lobsters_jobs", "Lobsters", "community", "feed", "https://lobste.rs/t/job.rss", fields=("tech",), posts=True, ads=True, map={
        "title": "title", "url": "link", "date": "pubDate", "description": "description"}),
    # ---------------- discovery
    Source("ats_link_mining", "Employer boards", "discovery", "mined"),
    Source("sitemap_governmentjobs", "GovernmentJobs sitemap", "discovery", "sitemap", "https://www.governmentjobs.com/sitemap.xml", countries=("US",),
           needs=lambda cfg: LocationMatcher(cfg["locations"]["allowed"]).anywhere_us),
    Source("google_news", "Google News job fairs", "discovery", "feed", "https://news.google.com/rss/search?q=%22job+fair%22+{place}+when:14d&hl=en-{gl}&gl={gl}&ceid={gl}:en",
           kind="event", keep=r"job fair|career fair|hiring (?:event|fair)|job expo", limit=10, needs=lambda cfg: bool(_first_place(cfg)), map={
               "title": "title", "company": lambda r: _after_last(r.get("title", ""), " - "), "url": "link", "date": "pubDate",
               "description": "description"}),
    Source("nlx_events", "NLx career events", "discovery", "json", "https://careerevents.usnlx.com/api/events/", countries=("US",),
           kind="event", items="data.events", map={
               "title": "name", "url": "url", "location": "address", "date": ("dates.0.start", "created_on"), "description": "description"}),
    # ---------------- free keys
    Source("reed", "Reed", "general", "json", "https://www.reed.co.uk/api/1.0/search?keywords={term}&locationName={place}", countries=("GB",),
           items="results", keys=("api_key",), link="https://www.reed.co.uk/developers/jobseeker",
           auth=lambda k: {"Authorization": "Basic " + base64.b64encode(f"{k['api_key']}:".encode()).decode()}, map={
               "title": "jobTitle", "company": "employerName", "location": "locationName", "url": "jobUrl",
               "date": lambda r: _dmy(r.get("date")), "deadline": lambda r: _dmy(r.get("expirationDate")), "description": "jobDescription"}),
    Source("careeronestop", "CareerOneStop", "general", "json",
           "https://api.careeronestop.org/v1/jobsearch/{user_id}/{term}/{place}/25/0/0/0/50/30", countries=("US",), items="Jobs",
           keys=("user_id", "token"), link="https://www.careeronestop.org/Developers/WebAPI/registration.aspx",
           auth=lambda k: {"Authorization": f"Bearer {k['token']}"}, map={
               "title": "JobTitle", "company": "Company", "location": "Location", "url": "URL", "date": "DatePosted"}),
    Source("findwork", "Findwork", "general", "json", "https://findwork.dev/api/jobs/?search={term}", fields=("tech",), items="results",
           keys=("token",), link="https://findwork.dev/developers/", auth=lambda k: {"Authorization": f"Token {k['token']}"}, map={
               "title": "role", "company": "company_name", "location": ("location", lambda r: "Remote" if r.get("remote") else ""),
               "url": "url", "date": "date_posted", "description": "text"}),
]
BY_ID = {source.id: source for source in SOURCES}


# ---------------------------------------------------------------- which sources run


def _first_place(cfg: dict, src: Source | None = None) -> str:
    """The search area's first real place, for a site's place search: not remote and not a whole country. With `src`, the
    first one inside that source's countries, so a Canadian site isn't asked about Ohio."""
    for entry in cfg["locations"].get("allowed") or []:
        text = clean(entry)
        if not text or NATIONWIDE_RE.fullmatch(text.lower()) or REMOTE_RE.search(text):
            continue
        where, whole = places.read_place(text)
        if whole or (src and src.countries != WORLD and where and not where & set(src.countries)):
            continue
        return text
    return ""


def _section(cfg: dict) -> dict:
    """The catalog's settings (config.py, sources.catalog)."""
    return (cfg.get("sources") or {}).get("catalog") or {}


def _keys_of(cfg: dict, src: Source) -> dict:
    """The keys the user entered for a source."""
    return (_section(cfg).get("keys") or {}).get(src.id) or {}


def has_keys(cfg: dict, src: Source) -> bool:
    """True when a source needs no key, or every key it needs has been entered."""
    keys = _keys_of(cfg, src)
    return all(str(keys.get(name) or "").strip() for name in src.keys)


def is_on(cfg: dict, src: Source) -> bool:
    """The user's switches: the group is on (a group nobody has switched counts as on), the source isn't in the off list, and
    any key it needs is there."""
    section = _section(cfg)
    return (section.get("groups") or {}).get(src.group, True) is not False and src.id not in (section.get("off") or []) and has_keys(cfg, src)


def fits(cfg: dict, src: Source, user_fields: set | None = None, area: places.Area | None = None) -> bool:
    """True when this source is any use to this person: it serves one of their fields and one of their countries."""
    user_fields = set(plan.groups(cfg)) if user_fields is None else user_fields
    area = area or plan.area(cfg)
    if src.fields != ALL and not user_fields & set(src.fields):
        return False
    if src.countries != WORLD and not set(area.countries()) & set(src.countries):
        return False
    if src.within and not (set(src.countries) & area.whole or any(_in_part(entry, src.within) for entry in cfg["locations"].get("allowed") or [])):
        return False
    return not src.needs or bool(src.needs(cfg))


def _in_part(entry: str, part: tuple) -> bool:
    """True when a search area entry is in a part of a country: one of its US states, or a place that names one of its words."""
    low = entry.lower()
    return state_of(entry) in part or any(word.lower() in low for word in part if len(word) > 2)


def active(cfg: dict) -> list[Source]:
    """The sources that run for this person now, in table order."""
    user_fields, area = set(plan.groups(cfg)), plan.area(cfg)
    return [s for s in SOURCES if is_on(cfg, s) and fits(cfg, s, user_fields, area)]


def home_source(cfg: dict, source: str) -> bool:
    """True for a lead from another country's national service when the search area covers that whole country. The location
    filter (countries.Area.judge) already lets those through, and this tells the AI they're fine too."""
    src = BY_ID.get(source)
    if not src or src.countries == WORLD or "US" in src.countries:
        return False
    return bool(set(src.countries) & plan.area(cfg).whole)


def overview(cfg: dict) -> dict:
    """The whole catalog for the Sources dialog (GET /api/sources/catalog): each group with its switch and counts, and each
    source with its switch, whether it runs for this person, and the names of the keys it needs."""
    user_fields, area = set(plan.groups(cfg)), plan.area(cfg)
    rows = []
    for s in SOURCES:
        on, for_you = is_on(cfg, s), fits(cfg, s, user_fields, area)
        rows.append({"id": s.id, "name": s.name, "group": s.group, "on": on, "for_you": for_you, "runs": on and for_you,
                     "off": s.id in (_section(cfg).get("off") or []), "needs_key": bool(s.keys), "keys": list(s.keys),
                     "has_keys": has_keys(cfg, s), "key_url": s.link, "fields": list(s.fields), "countries": list(s.countries)})
    switches = _section(cfg).get("groups") or {}
    groups = [{"id": g, "name": name, "on": switches.get(g, True) is not False, "total": sum(r["group"] == g for r in rows),
               "runs": sum(r["group"] == g and r["runs"] for r in rows)} for g, name in GROUPS.items()]
    return {"enabled": _section(cfg).get("enabled", True) is not False, "groups": groups, "sources": rows,
            "fields": sorted(user_fields), "countries": area.countries(), "systems": sorted(ats.SYSTEM_NAMES.values())}


# ---------------------------------------------------------------- reading one source


# What each kind of page gives when a source's own map doesn't say otherwise.
DEFAULT_MAPS = {
    "feed": {"title": "title", "url": "link", "date": ("pubDate", "published", "updated", "date"), "description": ("description", "content", "summary")},
    "cards": {name: name for name in ("title", "url", "company", "location", "date", "deadline", "description")},
    "discourse": {name: name for name in ("title", "url", "date", "description")},
    "telegram": {name: name for name in ("title", "url", "date", "description")},
    "hn_jobs": {name: name for name in ("title", "url", "date", "description")},
    "mathjobs": {name: name for name in ("title", "url", "company", "deadline")},
}
PAGE_READERS = ("cards", "rows", "embedded")  # sources whose list is a page a person can open


def _country_in(place: str) -> str:
    """The country a job's place names, when it's one and outside the US (the location filter reads US places well)."""
    codes, _ = places.read_place(place) if place else (set(), False)
    return next(iter(codes)) if len(codes) == 1 and "US" not in codes else ""


def _to_job(src: Source, record: dict, page_url: str, post_re: re.Pattern | None) -> RawJob | None:
    """One record as a RawJob, or None without a title and address, or for a community post that doesn't read like a hiring
    post at this person's level."""
    fields = {**DEFAULT_MAPS.get(src.reader, {}), **src.map}
    title = text_of(pick(record, fields.get("title")))[:200]
    url = clean(pick(record, fields.get("url")))
    if not title or not url:
        return None
    description = html_to_text(str(pick(record, fields.get("description")) or ""))[:MAX_DESCRIPTION]
    if src.keep and not re.search(src.keep, f"{title} {description}", re.I):
        return None
    if post_re is not None and not src.ads:
        text = f"{title} {description}"
        if not (post_re.search(text) and HIRING_RE.search(text)):
            return None
    deadline = parse_date(pick(record, fields.get("deadline")))
    if (age_days(deadline) or 0) > 0:  # some boards keep listing openings whose deadline has passed
        return None
    where = pick(record, fields.get("location"))
    several = [text_of(x) for x in where if x] if isinstance(where, list) else []
    country = pick(record, fields.get("country")) or src.country or _country_in(several[0] if several else text_of(where))
    return RawJob(source=src.id, title=title, company=text_of(pick(record, fields.get("company")))[:120], url=urljoin(page_url, url),
                  location="" if several else text_of(where), locations=several, description=description,
                  posted_at=parse_date(pick(record, fields.get("date"))), deadline=deadline,
                  kind=src.kind, strict_titles=not (src.posts or src.gig) and src.kind == "posting", source_detail=src.name,
                  found_url=page_url if src.reader in PAGE_READERS else "", meta={"country": country} if country else {})


def _terms(cfg: dict, src: Source) -> list[str]:
    """The search words for this run: the first `terms` of the user's queries. A source that can list its newest jobs without
    a word gets one empty search, and a site that needs the word in its address is skipped until there is one."""
    template = src.url + (src.body if isinstance(src.body, str) else json.dumps(src.body) if isinstance(src.body, dict) else "")
    if "{term}" not in template and "{slug}" not in template and not callable(src.body):
        return [""]
    queries = plan.all_queries(cfg)[:src.terms]
    return queries or ([] if "{slug}" in template else [""])


def _fill(template: str, term: str, place: str, target: str, keys: dict, gl: str) -> str:
    """A URL template with this request's values, each escaped for its spot in the address."""
    values = {"term": quote_plus(term), "slug": re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-"), "place": quote_plus(place),
              "target": target, "gl": gl, **{k: quote(str(v), safe="") for k, v in keys.items()}}
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template)


def _fill_body(body, term: str, place: str, codes: list[str]):
    """A JSON body with this request's search word and place, or what a body function makes of them."""
    if callable(body):
        return body(term, place, codes)
    if isinstance(body, dict):
        return {k: _fill_body(v, term, place, codes) for k, v in body.items()}
    if isinstance(body, list):
        return [_fill_body(v, term, place, codes) for v in body]
    return body.replace("{term}", term).replace("{place}", place) if isinstance(body, str) else body


async def _fetch(ctx: Ctx, src: Source, url: str, body=None, headers: dict | None = None):
    """One request, with no retries. Raises Blocked when the site refuses or sends a challenge."""
    send = {**src.headers, **(headers or {})}
    extra = {}
    if src.method == "POST":
        send = {"Content-Type": "application/json", "Accept": "application/json", **send}
        extra["content"] = json.dumps(body if body is not None else {})
    return await ctx.polite(src.method, url, timeout=REQUEST_SECONDS, headers=send, **extra)


def _discourse_records(text: str, page_url: str) -> list[dict]:
    """A Discourse forum's search answer: its topics, with the matching post's text."""
    data = json.loads(text)
    blurbs = {p.get("topic_id"): p.get("blurb", "") for p in data.get("posts") or []}
    base = "/".join(page_url.split("/")[:3])
    return [{"title": t.get("title", ""), "url": f"{base}/t/{t.get('slug')}/{t.get('id')}", "date": t.get("created_at"),
             "description": blurbs.get(t.get("id"), "")} for t in data.get("topics") or []]


def _telegram_records(text: str) -> list[dict]:
    """A public Telegram channel's web preview: each message's first line, text, address and time."""
    out = []
    for block in re.split(r'(?=<div class="tgme_widget_message_wrap)', text)[1:]:
        post = re.search(r'data-post="([^"]+)"', block)
        body = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
        when = re.search(r'<time[^>]*datetime="([^"]+)"', block)
        if post and body:
            words = html_to_text(body.group(1))
            out.append({"title": words.split("\n", 1)[0][:160], "url": f"https://t.me/{post.group(1)}", "date": when.group(1) if when else "",
                        "description": words})
    return out


def _livewire_records(text: str) -> list[dict]:
    """Job postings kept in the data of a Livewire page: each card's wire:snapshot attribute holds its record as JSON."""
    out = []
    for raw in re.findall(r'wire:snapshot="([^"]+)"', text):
        try:
            data = json.loads(html_module.unescape(raw)).get("data") or {}
        except json.JSONDecodeError:
            continue
        posting = data.get("jobPosting")
        record = posting[0] if isinstance(posting, list) and posting else posting
        if isinstance(record, dict) and record.get("title"):
            out.append(_unwrap_livewire(record))
    return out


def _unwrap_livewire(value):
    """A Livewire value without its bookkeeping: lists arrive as [items, {"s": "arr"}] and nested the same way."""
    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[1], dict) and "s" in value[1]:
            return _unwrap_livewire(value[0])
        return [_unwrap_livewire(v) for v in value]
    if isinstance(value, dict):
        return {k: _unwrap_livewire(v) for k, v in value.items()}
    return value


def _mathjobs_records(text: str) -> list[dict]:
    """MathJobs lists its openings under each institution's heading, in one long page."""
    out = []
    for heading, block in re.findall(r"<h3[^>]*>(.*?)</h3>\s*<ol[^>]*>(.*?)</ol>", text, re.S):
        for row in re.findall(r"<li>(.*?)</li>", block, re.S):
            link = re.search(r'href="(/jobs/list/\d+)"', row)
            title = re.search(r'<span id="j\d+"[^>]*>(.*?)</span>', row, re.S)
            deadline = re.search(r"\(deadline (\d{4})/(\d{2})/(\d{2})", row)
            if link and title:
                out.append({"url": link.group(1), "title": title.group(1), "company": heading,
                            "deadline": "-".join(deadline.groups()) if deadline else ""})
    return out


def _parse(src: Source, text: str, page_url: str) -> list:
    """The records in one response, by the source's kind of page."""
    if src.reader == "feed":
        return readers.feed_records(text)
    if src.reader == "xml":
        return readers.xml_records(text, src.items)
    if src.reader == "json":
        data = json.loads(text)
        found = readers.dig(data, src.items) if src.items else data
        return found if isinstance(found, list) else []
    if src.reader == "cards":
        return readers.card_records(text, src.cards, page_url)
    if src.reader == "rows":
        return readers.row_records(text, src.cards["row"])
    if src.reader == "embedded":
        found = readers.embedded_json(html_module.unescape(text), src.cards["marker"])
        return found if isinstance(found, list) else []
    if src.reader == "livewire":
        return _livewire_records(text)
    if src.reader == "mathjobs":
        return _mathjobs_records(text)
    if src.reader == "discourse":
        return _discourse_records(text, page_url)
    if src.reader == "telegram":
        return _telegram_records(text)
    raise ValueError(f"unknown reader {src.reader}")


def _post_filter(cfg: dict, src: Source) -> re.Pattern | None:
    """What a community post must match to be kept (core/levels.posting_regex), or None for other sources."""
    return posting_regex(plan.levels(cfg), plan.role_words(cfg)) if src.posts else None


async def _read_plain(ctx: Ctx, src: Source) -> list[RawJob]:
    """A source with one request per search term and target."""
    cfg = ctx.cfg
    place, codes, keys = _first_place(cfg, src), plan.area(cfg).countries(), _keys_of(cfg, src)
    gl = next((c for c in codes if c in ("US", "GB", "CA", "AU", "IE", "NZ", "IN", "SG", "ZA")), "US")
    terms, post_re = _terms(cfg, src), _post_filter(cfg, src)
    headers = src.auth(keys) if src.auth else None
    out, seen, sent = [], set(), 0
    for target in src.targets or ("",):
        for term in terms:
            if sent:  # a short pause between requests to the same site
                await asyncio.sleep(0.4 + random.random() * 0.6)
            sent += 1
            url = _fill(src.url, term, place, target, keys, gl)
            try:
                response = await _fetch(ctx, src, url, _fill_body(src.body, term, place, codes) if src.method == "POST" else None, headers)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404 and "{slug}" in src.url:
                    continue  # the site has no page for this word, which only means no results
                raise
            text = response.text
            records = _parse(src, text, str(response.url))
            if not records and CHALLENGE_RE.search(text[:20000]):
                raise Blocked("a challenge page")
            for record in records:
                job = _to_job(src, record, str(response.url), post_re)
                if job and job.url not in seen:
                    seen.add(job.url)
                    out.append(job)
    return out[:src.limit] if src.limit else out


async def _read_hn_jobs(ctx: Ctx, src: Source) -> list[RawJob]:
    """Hacker News job stories: the list of ids, then each of the newest stories."""
    response = await _fetch(ctx, src, src.url)
    ids = json.loads(response.text)[:HN_STORIES]
    post_re, out = _post_filter(ctx.cfg, src), []
    for story in ids:
        item = json.loads((await _fetch(ctx, src, f"https://hacker-news.firebaseio.com/v0/item/{story}.json")).text) or {}
        link = item.get("url") or f"https://news.ycombinator.com/item?id={story}"
        record = {"title": item.get("title", ""), "url": link, "date": item.get("time"), "description": item.get("text") or ""}
        job = _to_job(src, record, "", post_re)
        if job:
            out.append(job)
    return out


async def _read_sitemap(ctx: Ctx, src: Source) -> list[RawJob]:
    """GovernmentJobs' sitemap: every open job's address. It has no places, so it runs only for a nationwide search
    (Source.needs), and a job counts when its title words match the user's targets. Newest ids come first."""
    targets = TargetMatcher(plan.target_phrases(ctx.cfg), places=ctx.cfg["locations"].get("allowed"))
    if not targets:
        return []
    response = await _fetch(ctx, src, src.url)
    links = [url for url in readers.sitemap_urls(response.text) if re.search(r"/jobs/\d+", url)]
    links.sort(key=lambda url: -int(re.search(r"/jobs/(\d+)", url).group(1)))
    out = []
    for url in links:
        title = readers.slug_title(url)
        if targets.matches(title):
            out.append(RawJob(source=src.id, title=title, company="", url=url, source_detail=src.name, strict_titles=False))
            if len(out) >= SITEMAP_MATCHES:
                break
    return out


def _seasonal_records(content: bytes, cfg: dict) -> list[dict]:
    """The job orders in the Department of Labor's daily file that are in the search area and near the user's work. The file
    unpacks to tens of megabytes, so its records are read one at a time and only the matches are kept."""
    archive = zipfile.ZipFile(io.BytesIO(content))
    text = archive.read(archive.namelist()[0]).decode("utf-8", "replace")
    matcher = LocationMatcher(cfg["locations"].get("allowed") or [])
    targets = TargetMatcher(plan.target_phrases(cfg), places=cfg["locations"].get("allowed"))
    decoder, at, out = json.JSONDecoder(), text.find("[") + 1, []
    while 0 < at < len(text) and len(out) < SEASONAL_MATCHES:
        while at < len(text) and text[at] in " ,\r\n\t":
            at += 1
        if at >= len(text) or text[at] == "]":
            break
        record, at = decoder.raw_decode(text, at)
        place = f"{record.get('jobCity')}, {record.get('jobState')}"
        if matcher.match_one(place) is True and targets.matches(str(record.get("jobTitle") or ""), str(record.get("jobDuties") or "")):
            out.append(record)
    return out


async def _read_seasonal(ctx: Ctx, src: Source) -> list[RawJob]:
    """The US Department of Labor's daily file of seasonal and farm job orders. It's a large download that changes once a day,
    so a search run reads it at most once a day (kv catalog.seasonal_day). The Sources dialog's check always reads it."""
    day = (date.today() - timedelta(days=1)).isoformat()
    if ctx.deliver and db.kv_get("catalog.seasonal_day") == day:
        return []
    response = await ctx.polite("GET", src.url.replace("{day}", day), timeout=SEASONAL_SECONDS)
    records = await asyncio.to_thread(_seasonal_records, response.content, ctx.cfg)
    if ctx.deliver:
        db.kv_set("catalog.seasonal_day", day)
    return [job for job in (_to_job(src, record, "", None) for record in records) if job]


def mined_boards(cfg: dict) -> list[dict]:
    """The employer job boards that the links of this person's own leads point at, best leads first, without the boards they
    already follow. No new site is contacted to find them."""
    have = {ats.board_key(b) for b in cfg["sources"]["ats_boards"].get("boards") or []}
    found: dict[str, dict] = {}
    for row in db.q("SELECT company, url, apply_url FROM leads WHERE app_status != 'trashed' ORDER BY score DESC, id DESC LIMIT 3000"):
        for link in (row["url"], row["apply_url"]):
            board = ats.detect(link) if link else None
            key = ats.board_key(board) if board else None
            if key and key not in have and key not in found:
                found[key] = {**board, "name": row["company"] or key}
    return list(found.values())


async def _read_mined(ctx: Ctx, src: Source) -> list[RawJob]:
    """Read this run's share of the boards found in the user's leads. The rest come up on later runs (kv catalog.mined_at)."""
    boards = mined_boards(ctx.cfg)
    if not boards:
        return []
    start = int(db.kv_get("catalog.mined_at") or 0) % len(boards)
    turn = [boards[(start + i) % len(boards)] for i in range(min(MINED_BOARDS_PER_RUN, len(boards)))]
    db.kv_set("catalog.mined_at", (start + len(turn)) % len(boards))
    results = await asyncio.gather(*(ats.read_board(ctx, b) for b in turn))
    return [job for jobs in results for job in jobs]


HN_STORIES = 12  # newest Hacker News job stories read per run, one request each
SPECIAL = {"hn_jobs": _read_hn_jobs, "sitemap": _read_sitemap, "mined": _read_mined, "seasonal": _read_seasonal}
SLOW_READERS = {"mined": 120, "seasonal": 90}  # seconds for a source with a lot to read, instead of SOURCE_SECONDS


async def read_source(ctx: Ctx, src: Source) -> list[RawJob]:
    """One source's jobs. Raises on any failure (Blocked, a timeout, a changed page); read_one turns that into a log line."""
    reader = SPECIAL.get(src.reader, _read_plain)
    return await asyncio.wait_for(reader(ctx, src), timeout=SLOW_READERS.get(src.reader, SOURCE_SECONDS))


async def read_one(ctx: Ctx, src: Source) -> list[RawJob]:
    """A source's jobs, or [] with one log line when it can't be read. Stop still works: CancelledError passes through."""
    try:
        return await read_source(ctx, src)
    except Blocked as e:
        ctx.log("catalog", f"{src.name}: refused ({e}), left alone this run", "warn")
    except TimeoutError:
        ctx.log("catalog", f"{src.name}: no answer in time, skipped this run", "warn")
    except httpx.HTTPStatusError as e:  # the status alone: the address can hold a user's key
        ctx.log("catalog", f"{src.name}: HTTP {e.response.status_code}, skipped this run", "warn")
    except Exception as e:  # noqa: BLE001 (a dead or changed source must not touch the others)
        ctx.log("catalog", f"{src.name}: {type(e).__name__}: {str(e)[:120]}", "warn")
    return []


async def collect(ctx: Ctx) -> list[RawJob]:
    """Read every source that's on and useful for this person, SOURCES_AT_ONCE at a time, for BATCH_SECONDS at most.

    During a search run each source's jobs are handed over as soon as it finishes (ctx.deliver), so a slow site never
    holds back the others. Without a run (the Sources dialog's check), everything is returned at the end."""
    chosen = active(ctx.cfg)
    slots = asyncio.Semaphore(SOURCES_AT_ONCE)
    gathered: list[RawJob] = []
    finished = 0

    async def run_one(src: Source) -> None:
        nonlocal finished
        async with slots:
            jobs = await read_one(ctx, src)
        finished += 1
        if not (jobs and ctx.deliver):
            gathered.extend(jobs)
            return
        try:
            await ctx.deliver(src.name, jobs)
        except Exception as e:  # noqa: BLE001 (the run's bookkeeping for one source must not end the others)
            ctx.log("catalog", f"{src.name}: couldn't take its jobs: {type(e).__name__}: {str(e)[:120]}", "warn")

    tasks = [asyncio.create_task(run_one(s)) for s in chosen]
    try:
        if tasks:
            _, late = await asyncio.wait(tasks, timeout=BATCH_SECONDS)
            if late:
                ctx.log("catalog", f"{len(late)} sources ran out of time and were skipped this run", "warn")
    finally:  # also on Stop, so nothing keeps running after the run ends
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    ctx.log("catalog", f"read {finished} of {len(chosen)} sources for this search")
    return gathered


collect.hands_over = True  # the run takes its jobs through ctx.deliver (see Pipeline._run_collector)
