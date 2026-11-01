"""Shared building blocks for collectors: RawJob, the record every job source produces, and Ctx, the polite HTTP client they
all share.

A collector is an async function `collect(ctx) -> list[RawJob]` (see collectors/__init__.py). The search run (pipeline.py)
makes one Ctx per run and hands it to every collector, so they share one connection pool, one request limit per site and one
stop flag. The Sources dialog's checks (sources.py) and a package built outside a run (packages.py) make their own
short-lived Ctx.

Nothing here touches the database or the AI."""
import asyncio
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from jobportal.core.textutil import NATIONWIDE_RE

# A desktop Chrome user agent. Several job sites refuse or strip requests from clients they don't recognize.
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
PER_HOST_LIMIT = 4  # requests in flight to one site at a time, unless a collector lowers it with host_limit()
RETRY_STATUSES = (429, 502, 503, 504)  # rate limited, or a passing server problem: worth another try after a pause

# Sources whose "jobs" are posts or comments, not job postings. The title is the post's first line and the URL is the post
# itself, so there is no posting page to fetch more details from.
SOCIAL_SOURCES = frozenset({"hackernews", "mastodon", "reddit", "bluesky"})
# An allowed location that means the whole country ("Nationwide", "Anywhere in the US", "USA"). Match it against the
# lowercased, stripped text with fullmatch(). It's the location filter's own pattern, so a source and the filter always
# agree on which entries are nationwide.
NATIONWIDE = NATIONWIDE_RE


@dataclass
class RawJob:
    """One job (or other lead) exactly as a collector found it, before any filtering or AI.

    The search run turns the ones that pass the rule filters and triage into rows of the leads table. Most fields keep the
    same name there."""
    # Which collector found it: ats, linkedin, github, usajobs, themuse, hackernews, reddit, mastodon, bluesky, remote, rss,
    # adzuna, google or ai_hunt. Leads the user adds by hand use "manual" (packages.add_manual_lead).
    source: str
    title: str
    company: str
    url: str  # the posting, or the post itself for social sources
    location: str = ""  # one display string, such as "Columbus, OH | Remote"
    locations: list[str] = field(default_factory=list)  # each place on its own, when the source lists several
    description: str = ""
    posted_at: str | None = None  # ISO date (YYYY-MM-DD)
    deadline: str | None = None  # ISO date when the source gives one
    apply_url: str | None = None  # a direct application link, when it differs from url
    # "posting" (one specific opening), "program" (an internship, apprenticeship, fellowship or training program), "event"
    # (a career fair, hiring event or info session) or "intel" (a strong hiring signal with no posting yet). Only the AI
    # hunt reports the last three.
    # The too-senior title filter only applies to postings.
    kind: str = "posting"
    category_hint: str = ""  # the source's own category ("internship", "Full-time"), used when triage doesn't pick one
    source_detail: str = ""  # readable origin for the Leads page, such as "Greenhouse: Example Robotics"
    # From a company board starred in the Sources dialog; the rule filters also set it for the Dream list.
    dream: bool = False
    # True means the title must contain a word for the user's levels (Settings filters.title_include) to pass the rule
    # filters. Sources that already narrow results to those levels (LinkedIn, The Muse, the internship lists) set it to
    # False, and so do sources whose titles rarely name a level (USAJobs) or aren't job titles at all (social posts, feeds,
    # the AI hunt).
    strict_titles: bool = True
    # The exact page where the lead was discovered: a comment thread, a list, a company board. The Leads page links to it as
    # "where this was found". Empty means the posting URL itself.
    found_url: str = ""
    # Source-specific extras that help fetch the full posting later (collectors/details.py), such as a board's API address
    # or job id. The search run also keeps meta["found"] here: every place the same job was seen during the run.
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        # Job sites (and AI answers) sometimes send null, or a number, where text belongs. Text fields are always strings
        # from here on, and the location list holds only real places, so the filters, the triage batch ("A | B" joins) and
        # the lead page (company[:30]) never meet None.
        for name in ("title", "company", "url", "location", "description", "category_hint", "source_detail", "found_url"):
            value = getattr(self, name)
            if not isinstance(value, str):
                setattr(self, name, "" if value is None else str(value))
        places = [self.locations] if isinstance(self.locations, str) else self.locations or []  # one place sent as text
        self.locations = [str(place) for place in places if place]
        if not self.location and self.locations:
            self.location = " | ".join(self.locations)  # collectors that have a list leave the display string to this

    def where_found(self) -> dict:
        """This job's entry for the lead's "found" list: {source, label, url}."""
        return {"source": self.source, "label": self.source_detail or self.source, "url": self.found_url or self.url}

    def loc_list(self) -> list[str]:
        """Every location as a list: the separate places when the source gave them, else the one location string."""
        return self.locations or ([self.location] if self.location else [])


class Ctx:
    """The HTTP client that collectors share during one search run or one check in the Sources dialog.

    It is polite by design. At most PER_HOST_LIMIT requests run at once per site (host_limit() lowers that for strict sites),
    rate-limit and server-busy answers are retried after a growing pause, and every request checks the run's stop flag first,
    so Stop or a usage-cap pause ends collection quickly."""

    def __init__(self, cfg: dict, log, run_id: int | None = None, cancel: asyncio.Event | None = None):
        self.cfg = cfg  # the settings in effect; each collector reads its own section, such as cfg["sources"]["linkedin"]
        self.log = log  # log(source, msg, level="info"): the run log during a search, something quieter for page checks
        self.run_id = run_id  # ties AI calls made by collectors (the AI hunt) to their run
        self.cancel = cancel or asyncio.Event()  # set by Stop or by a usage-cap pause
        self.cache: dict = {}  # scratch space collectors can reuse within one run, such as whole Ashby boards in details.py
        self.client = httpx.AsyncClient(headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                                        timeout=httpx.Timeout(30.0, connect=15.0), follow_redirects=True,
                                        limits=httpx.Limits(max_connections=40, max_keepalive_connections=20))
        self._host_slots: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(PER_HOST_LIMIT))

    async def close(self) -> None:
        """Close the connection pool. Call it once the run or check is over."""
        await self.client.aclose()

    def host_limit(self, host: str, n: int) -> None:
        """Allow only n requests at a time to this host (for example "www.linkedin.com"). LinkedIn and Reddit use 1."""
        self._host_slots[host] = asyncio.Semaphore(n)

    async def request(self, method: str, url: str, *, retries: int = 2, **kw) -> httpx.Response:
        """Send one request. Rate limits (429), passing server errors (502 to 504) and network errors are retried up to
        `retries` more times. Returns the response even when its status is an error, so the caller decides what a 404 means.

        Raises the last network error when every try failed, and asyncio.CancelledError when the run was stopped or paused.
        Extra keyword arguments go to httpx (headers, content, timeout)."""
        host = urlparse(url).netloc
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            if self.cancel.is_set():
                raise asyncio.CancelledError()  # unwinds the collector right away, the same way Stop cancels a task
            # Any pause below happens while holding this site's slot, so other requests to the same site wait too. That is
            # the point: a 429 means "slow down".
            async with self._host_slots[host]:
                try:
                    response = await self.client.request(method, url, **kw)
                except httpx.TransportError as e:  # connection problems and timeouts
                    last_error = e
                    if attempt < retries:
                        await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                if response.status_code in RETRY_STATUSES and attempt < retries:
                    await asyncio.sleep(2 * (attempt + 1) + random.random())  # wait longer each time, plus jitter
                    continue
                return response
        raise last_error or RuntimeError(f"request failed: {url}")

    async def get_json(self, url: str, **kw):
        """GET a URL and parse its JSON. Raises httpx.HTTPStatusError on an error status."""
        response = await self.request("GET", url, **kw)
        response.raise_for_status()
        return response.json()

    async def post_json(self, url: str, payload, **kw):
        """POST a JSON body and parse the JSON answer. Raises httpx.HTTPStatusError on an error status."""
        headers = {"Content-Type": "application/json", "Accept": "application/json", **kw.pop("headers", {})}
        response = await self.request("POST", url, content=json.dumps(payload), headers=headers, **kw)
        response.raise_for_status()
        return response.json()

    async def get_text(self, url: str, **kw) -> str:
        """GET a URL and return its body as text (HTML, RSS). Raises httpx.HTTPStatusError on an error status."""
        response = await self.request("GET", url, **kw)
        response.raise_for_status()
        return response.text
