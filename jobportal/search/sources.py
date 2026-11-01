"""The two checks in the Sources dialog on Leads (web/routes/search.py calls them). Neither one saves anything.

detect_board finds the company job board behind a careers page address, so the user can add a company by pasting a link. It
uses collectors/ats.py to recognize the board and read it once. test_collector runs one source by itself, with the current
settings, and reports how many of its jobs would pass the same rule filters a search run uses (pipeline.RuleFilters)."""
import asyncio
import re

from jobportal.core import settings
from jobportal.search.collectors import COLLECTORS, ats
from jobportal.search.collectors.base import Ctx
from jobportal.search.pipeline import RuleFilters

SUPPORTED_BOARDS = "Greenhouse, Lever, Ashby, Workday, UKG, iCIMS, SmartRecruiters"  # named in the "not found" message
# Careers pages often embed or link the real job board. This finds such a link in the page's HTML.
BOARD_LINK = re.compile(r"(https?://[a-z0-9.-]*(?:myworkdayjobs\.com|greenhouse\.io|lever\.co|ashbyhq\.com|icims\.com"
                        r"|ultipro\.com|smartrecruiters\.com)[^\"'\s<>]*)", re.I)


def _quiet(*_args, **_kwargs) -> None:
    """A collector log that throws messages away. These checks report results, not progress."""


async def _board_linked_from(url: str) -> dict | None:
    """Fetch a careers page and return the first supported job board linked from it, or None. Every link to a supported
    system is tried in page order: the first is often no board at all (a preconnect hint, the vendor's own website in a
    footer), with the real embed further down."""
    ctx = Ctx(settings.get(), _quiet)
    try:
        page = await ctx.get_text(url)
    except Exception:  # noqa: BLE001 (an unreachable page just means no board was found)
        return None
    finally:
        await ctx.close()
    return next((board for link in BOARD_LINK.finditer(page) if (board := ats.detect(link.group(1)))), None)


def _reason(e: Exception) -> str:
    """An exception as a short reason for the Sources dialog. Some, like a timeout, have no message of their own."""
    if isinstance(e, TimeoutError):
        return "no answer in time"
    return str(e) or type(e).__name__


async def detect_board(url: str, name: str = "") -> dict:
    """Find the job board for a careers page and fetch it once to prove it works. Returns the board settings to save,
    how many jobs it has and a few sample titles, or a message saying what went wrong."""
    found = ats.detect(url) or await _board_linked_from(url)
    if not found:
        return {"ok": False, "message": f"Couldn't find a supported job board ({SUPPORTED_BOARDS}) on that page. The AI 'Dream "
                                        "companies' mission can still check it: add the company to your dream companies."}
    board = {"name": name, **found}
    ctx = Ctx(settings.get(), _quiet)
    try:
        jobs = await asyncio.wait_for(ats.HANDLERS[board["ats"]](ctx, {**board, "name": board["name"] or "test"}),
                                      timeout=ats.BOARD_TIMEOUT)
        return {"ok": True, "board": board, "count": len(jobs), "sample": [j.title for j in jobs[:8]]}
    except Exception as e:  # noqa: BLE001 (the board was recognized but the site refused or changed)
        return {"ok": False, "board": board, "message": f"Detected {board['ats']} but fetching failed: {_reason(e)}"}
    finally:
        await ctx.close()


async def test_collector(key: str) -> dict:
    """Run one source with the current settings, then apply the same rule filters a search run uses. Returns the counts,
    the source's log and up to 12 jobs that passed."""
    cfg = settings.get()
    if key == "linkedin":
        cfg["sources"]["linkedin"]["max_requests"] = 4  # a quick look, not a full crawl that could get rate-limited
    logs: list[str] = []
    ctx = Ctx(cfg, lambda _source, msg, level="info": logs.append(f"[{level}] {msg}"))
    try:
        jobs = await asyncio.wait_for(COLLECTORS[key][1](ctx), timeout=300)
    except Exception as e:  # noqa: BLE001 (report any failure, including a timeout, in the Sources dialog)
        return {"ok": False, "error": _reason(e), "logs": logs}
    finally:
        await ctx.close()
    filters = RuleFilters(cfg)
    passed = [j for j in jobs if filters.check(j)[0]]
    return {"ok": True, "found": len(jobs), "pass_filters": len(passed), "logs": logs,
            "sample": [{"title": j.title, "company": j.company, "location": j.location, "url": j.url} for j in passed[:12]]}
