"""The Next moves card on Home: a few things worth doing next, found by plain rules over the saved leads. They are the best
rules of the old Equity mining page, which v0.3.0 removed.

There's no AI here. moves() looks at every lead that isn't deleted and finds:
  No reply          an application sent STALE_DAYS or more days ago that hasn't moved since (a reply would have moved it to
                    In interview or Rejected): follow up, or move it to Rejected so the Tracker stays current
  Second chance     a new opening at a company that turned the user down before, found after that
  Several openings  two or more open roles at one company, where one contact could help with all of them
Each move has a key, so its Hide button keeps it off the card for HIDE_DAYS. The hidden keys live in "moves.hidden".

Called by web/routes/insights.py for the card in web/static/js/pages/home.js."""
from collections import defaultdict
from datetime import date, timedelta

from jobportal.core import db
from jobportal.core.textutil import norm_company

STALE_DAYS = 21  # an application with no reply this long is worth a follow-up
HIDE_DAYS = 30  # how long Hide keeps a move off the card
MAX_MOVES = 5  # the card stays small
OPEN_STAGES = ("ready", "qualified", "packaging")  # passed scoring: its package is done or on its way
NOT_APPLIED = ("new", "ready")


def _days_since(iso) -> int | None:
    """Whole days since an ISO date or timestamp, or None when it isn't one."""
    try:
        return (date.today() - date.fromisoformat(str(iso or "")[:10])).days
    except ValueError:
        return None


def _rejected_at() -> dict[int, str]:
    """When each lead was last moved to Rejected, from its status history (db.add_event writes "applied → rejected")."""
    rows = db.q("SELECT lead_id, MAX(ts) AS ts FROM events WHERE type='status' AND text LIKE '%rejected' GROUP BY lead_id")
    return {row["lead_id"]: row["ts"] for row in rows}


def _hidden() -> dict[str, str]:
    """The moves hidden for now: key to the last day it stays hidden. Keys whose time is up are left out."""
    today = date.today().isoformat()
    return {key: until for key, until in (db.kv_get("moves.hidden") or {}).items() if until >= today}


def _titles(leads: list[dict]) -> str:
    """Up to two job titles, and how many more: "Nurse Aide, Medical Assistant and 2 more"."""
    names = [lead["title"] for lead in leads[:2]]
    more = len(leads) - len(names)
    return ", ".join(names) + (f" and {more} more" if more else "")


def _move(key: str, kind: str, priority: float, lead: dict, text: str, why: str, cta: dict) -> dict:
    """One move for the card. cta is its button: a label plus "href" (a link) or "search" (Leads, searched for that)."""
    return {"key": key, "kind": kind, "priority": priority, "lead_id": lead["id"], "company": lead["company"], "text": text,
            "why": why, "cta": cta}


def moves() -> list[dict]:
    """The moves for the card, most worth doing first, MAX_MOVES at most, without the hidden ones."""
    leads = [dict(row) for row in db.q("SELECT id, title, company, stage, app_status, applied_at, created_at, updated_at, score "
                                       "FROM leads WHERE app_status != 'trashed'")]
    found = []
    for lead in leads:
        days = _days_since(lead["applied_at"])
        if lead["app_status"] == "applied" and days is not None and days >= STALE_DAYS:
            found.append(_move(f"noreply:{lead['id']}", "No reply", 300 + min(days, 90), lead,
                               f"No reply from {lead['company']} in {days} days",
                               f"{lead['title']}. Follow up, or move it to Rejected so your Tracker stays current.",
                               {"label": "Follow up", "href": f"#/leads/{lead['id']}/emails"}))
    companies: dict[str, list[dict]] = defaultdict(list)
    for lead in leads:
        key = norm_company(lead["company"]) or (lead["company"] or "").strip().lower()
        if key:
            companies[key].append(lead)
    rejected_at = _rejected_at()
    for key, group in companies.items():
        open_roles = sorted((lead for lead in group if lead["stage"] in OPEN_STAGES and lead["app_status"] in NOT_APPLIED),
                            key=lambda lead: -(lead["score"] or 0))
        if not open_roles:
            continue
        company = open_roles[0]["company"]
        turned_down = [lead for lead in group if lead["app_status"] == "rejected"]
        if turned_down:
            since = max(rejected_at.get(lead["id"]) or lead["updated_at"] or "" for lead in turned_down)
            newer = [lead for lead in open_roles if (lead["created_at"] or "") > since]
            if newer:
                best = newer[0]
                found.append(_move(f"again:{key}:{best['id']}", "Second chance", 200 + (best["score"] or 0) / 10, best,
                                   f"New opening at {company}, which turned you down before",
                                   f"You applied for {turned_down[0]['title']} before. This one is {best['title']}.",
                                   {"label": "Open", "href": f"#/leads/{best['id']}"}))
        if len(open_roles) >= 2:
            found.append(_move(f"several:{key}", "Several openings", 100 + len(open_roles), open_roles[0],
                               f"{len(open_roles)} openings at {company} fit you",
                               f"{_titles(open_roles)}. One contact there could help with all of them.",
                               {"label": "See them", "search": company}))
    hidden = _hidden()
    found = [move for move in found if move["key"] not in hidden]
    found.sort(key=lambda move: -move["priority"])
    return found[:MAX_MOVES]


def hide(key: str, days: int = HIDE_DAYS) -> None:
    """Keep one move off the card for `days` days. Hidden keys whose time is up are dropped while saving."""
    hidden = _hidden()
    hidden[key] = (date.today() + timedelta(days=days)).isoformat()
    db.kv_set("moves.hidden", hidden)
