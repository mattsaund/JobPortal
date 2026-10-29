"""Shared types for collectors: the RawJob record and a polite HTTP context."""
import asyncio
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


@dataclass
class RawJob:
    source: str
    title: str
    company: str
    url: str
    location: str = ""
    locations: list[str] = field(default_factory=list)
    description: str = ""
    posted_at: str | None = None
    deadline: str | None = None
    apply_url: str | None = None
    kind: str = "posting"
    category_hint: str = ""
    source_detail: str = ""
    dream: bool = False
    strict_titles: bool = True  # apply title include/exclude filters
    found_url: str = ""  # the exact page where this lead was discovered (thread, comment, board, list…)
    meta: dict = field(default_factory=dict)

    def where_found(self) -> dict:
        return {"source": self.source, "label": self.source_detail or self.source, "url": self.found_url or self.url}

    def loc_list(self) -> list[str]:
        return self.locations or ([self.location] if self.location else [])


class Ctx:
    def __init__(self, cfg: dict, log, run_id: int | None = None, cancel: asyncio.Event | None = None):
        self.cfg = cfg
        self.log = log  # log(source, msg, level="info")
        self.run_id = run_id
        self.cancel = cancel or asyncio.Event()
        self.client = httpx.AsyncClient(headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                                        timeout=httpx.Timeout(30.0, connect=15.0), follow_redirects=True,
                                        limits=httpx.Limits(max_connections=40, max_keepalive_connections=20))
        self._host_sems: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(4))

    async def close(self):
        await self.client.aclose()

    def host_limit(self, host: str, n: int):
        self._host_sems[host] = asyncio.Semaphore(n)

    async def request(self, method: str, url: str, *, retries: int = 2, **kw) -> httpx.Response:
        host = urlparse(url).netloc
        last: Exception | None = None
        for attempt in range(retries + 1):
            if self.cancel.is_set():
                raise asyncio.CancelledError()
            async with self._host_sems[host]:
                try:
                    r = await self.client.request(method, url, **kw)
                    if r.status_code in (429, 502, 503, 504) and attempt < retries:
                        await asyncio.sleep(2 * (attempt + 1) + random.random())
                        continue
                    return r
                except (httpx.TransportError, httpx.TimeoutException) as e:
                    last = e
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise last or RuntimeError(f"request failed: {url}")

    async def get_json(self, url: str, **kw):
        r = await self.request("GET", url, **kw)
        r.raise_for_status()
        return r.json()

    async def post_json(self, url: str, payload, **kw):
        headers = {"Content-Type": "application/json", "Accept": "application/json", **kw.pop("headers", {})}
        r = await self.request("POST", url, content=json.dumps(payload), headers=headers, **kw)
        r.raise_for_status()
        return r.json()

    async def get_text(self, url: str, **kw) -> str:
        r = await self.request("GET", url, **kw)
        r.raise_for_status()
        return r.text
