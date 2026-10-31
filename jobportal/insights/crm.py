"""The Equity mining page: treat the lead database like a sales team's book of business and find the most valuable next moves.

There's no AI here. book() applies plain rules to every lead and turns what they find into a ranked worklist of moves:
  Closing soon            a qualified or ready lead whose deadline is in the next 14 days
  Ready to apply          a finished application package the user hasn't applied with yet
  Build package           a strong qualified lead (fit 78 or more) still waiting for its package
  Follow up               an application whose follow-up date has arrived
  Stale application       applied 21 or more days ago with no response
  Reach out               a researched contact nobody has written to yet
  Strengthen              open questions whose answers would improve that lead's resume
  Near miss               a lead scored just under the minimum score, with no eligibility problem
  Multi-opening account   two or more open roles at one company, where one referral could cover them all
  Re-engage               a new opening at a company that rejected or ghosted the user before
Each move gets a priority (higher comes first) from the lead's fit score and how urgent it is. Done and Snooze hide a move
for a while; snooze() keeps the hidden keys in "crm.snoozed".

Leads also roll up by company into accounts. An account's equity is the value of its three best live leads (lead_value())
plus a bonus for known contacts, so the companies where the user has the most to gain come first.

Called by web/routes/insights.py for web/static/js/pages/crm.js."""
from collections import defaultdict
from datetime import date, timedelta

from jobportal.candidate import profile as profile_mod
from jobportal.core import db, settings as settings_mod
from jobportal.core.textutil import norm_company

OPEN_STAGES = ("ready", "qualified", "packaging")  # passed triage; the package is done or on its way
NOT_APPLIED = ("new", "ready")
AWAITING = ("applied", "interviewing")  # applied and waiting to hear back
IN_FLIGHT = AWAITING + ("accepted",)
ACTIVE_STATUSES = NOT_APPLIED + IN_FLIGHT  # everything except rejected, ghosted, withdrawn and trashed
# How much each pipeline stage is worth in lead_value(): how close it is to an application. Other stages count 0.5.
STAGE_WEIGHT = {"ready": 1.0, "qualified": 0.8, "packaging": 0.85, "filtered": 0.35, "closed": 0.05, "error": 0.6}
# How much each application status is worth. Statuses not listed (rejected, ghosted, withdrawn) are worth nothing.
STATUS_WEIGHT = {"new": 1.0, "ready": 1.05, "applied": 0.9, "interviewing": 1.6, "accepted": 2.0}


def _days_until(iso: str | None) -> int | None:
    """Whole days from today until an ISO date (negative once it has passed), or None when the text isn't a date."""
    try:
        return (date.fromisoformat((iso or "")[:10]) - date.today()).days
    except ValueError:
        return None


def _days_since(iso: str | None) -> int | None:
    """Whole days since an ISO date, or None when the text isn't a date."""
    days = _days_until(iso)
    return -days if days is not None else None


def lead_value(lead: dict) -> float:
    """The opportunity value of one lead: fit score times STAGE_WEIGHT times STATUS_WEIGHT times deadline urgency.
    A deadline within 7 days weighs 1.5, within 14 days 1.25, a deadline that has passed 0.2, and anything else 1.0."""
    left = _days_until(lead.get("deadline"))
    if left is None or left > 14:
        urgency = 1.0
    elif left < 0:
        urgency = 0.2
    elif left <= 7:
        urgency = 1.5
    else:
        urgency = 1.25
    weight = STAGE_WEIGHT.get(lead["stage"], 0.5) * STATUS_WEIGHT.get(lead["app_status"], 0)
    return round((lead.get("score") or 0) * weight * urgency, 1)


def _move(key: str, kind: str, priority: float, lead: dict, text: str, why: str, cta: dict) -> dict:
    """One worklist entry. key names the move so it can be snoozed. cta is its button: a label plus "href" (a link),
    "act" (a dashboard action) or "search" (a Leads search)."""
    return {"key": key, "kind": kind, "priority": round(priority, 1), "lead_id": lead["id"], "company": lead["company"],
            "title": lead["title"], "text": text, "why": why, "cta": cta}


def _lead_moves(lead: dict, open_questions: list[dict], min_score: int) -> list[dict]:
    """The moves one lead calls for right now (see the module docstring). open_questions are the lead's open questions."""
    lead_id, company, title = lead["id"], lead["company"], lead["title"]
    score, stage, status = lead.get("score") or 0, lead["stage"], lead["app_status"]
    package = lead.get("package") or {}
    left = _days_until(lead.get("deadline"))
    closing_soon = left is not None and 0 <= left <= 14
    not_applied = status in NOT_APPLIED
    open_lead = {"label": "Open lead", "href": f"#/lead/{lead_id}"}
    moves = []
    if stage in OPEN_STAGES and not_applied and closing_soon:
        moves.append(_move(f"deadline:{lead_id}", "Closing soon", 100 - left * 3 + score / 5, lead,
                           f"Apply to {company}: {title}. Closes in {left} day{'s' if left != 1 else ''}", f"Fit {score}. Deadline {lead['deadline']}.",
                           open_lead if stage == "ready" else {"label": "Build package", "act": "crm-package"}))
    elif stage == "ready" and not_applied:
        check = package.get("resume_check")
        moves.append(_move(f"ready:{lead_id}", "Ready to apply", 50 + score / 2, lead, f"Apply to {company}: {title}",
                           f"Package ready, fit {score}" + (f", resume check {check.get('score')}" if check else ""), open_lead))
    if stage == "qualified" and not_applied and score >= 78 and not closing_soon:
        moves.append(_move(f"package:{lead_id}", "Build package", 50 + score / 4, lead, f"Build the application package for {company}: {title}",
                           f"Fit {score}, queued without a package yet.", {"label": "Build package", "act": "crm-package"}))
    follow_up = lead.get("follow_up_at")
    if status in AWAITING and follow_up and (_days_until(follow_up) or 0) <= 0:  # a date that can't be read counts as due
        moves.append(_move(f"followup:{lead_id}:{follow_up}", "Follow up", 92, lead, f"Follow up with {company} on {title}",
                           f"Applied {lead.get('applied_at') or 'on an unknown date'}; follow-up was due {follow_up}. "
                           "A follow-up email is pre-written.", {"label": "Open emails", "href": f"#/lead/{lead_id}/emails"}))
    since = _days_since(lead.get("applied_at"))
    if status == "applied" and since is not None and since >= 21:
        moves.append(_move(f"stale:{lead_id}", "Stale application", 40 + min(since, 60) / 3, lead, f"No response from {company} in {since} days",
                           "Send a final nudge to a contact or mark it ghosted so the board stays honest.", open_lead))
    if (stage == "ready" or status in AWAITING) and score >= 60:
        for i, contact in enumerate(package.get("contacts") or []):
            if not contact.get("status") and contact.get("name"):
                found_email = 6 if contact.get("email_confidence") == "found" else 0
                moves.append(_move(f"contact:{lead_id}:{i}", "Reach out", 44 + score / 4 + found_email, lead,
                                   f"Reach out to {contact['name']} ({contact.get('title') or 'contact'}) at {company}",
                                   (contact.get("why") or "")[:180], {"label": "Contacts", "href": f"#/lead/{lead_id}/contacts"}))
                break  # one contact per lead keeps the list readable
    if open_questions and stage in ("ready", "qualified"):
        n = len(open_questions)
        moves.append(_move(f"questions:{lead_id}", "Strengthen", 52 + score / 5, lead,
                           f"Answer {n} question{'s' if n > 1 else ''} to strengthen your {company} resume", open_questions[0]["question"][:160], open_lead))
    triage = lead.get("triage") or {}
    if stage == "filtered" and min_score - 12 <= score < min_score and triage.get("eligibility") != "ineligible":
        flags = ", ".join(triage.get("red_flags") or [])[:140]
        moves.append(_move(f"nearmiss:{lead_id}", "Near miss", 34 + score / 3, lead, f"Almost qualified: {company}: {title} (fit {score})",
                           f"Red flags: {flags}" if flags else "Just under your threshold. Worth a look.", open_lead))
    return moves


def _accounts(leads: list[dict]) -> tuple[list[dict], list[dict]]:
    """Roll the leads up by company. Returns (accounts, moves): a summary of every company with a live lead, highest
    equity first, and the moves that come from looking at a company as a whole."""
    companies: dict[str, dict] = {}
    for lead in leads:
        key = norm_company(lead["company"]) or (lead["company"] or "").lower()
        company = companies.setdefault(key, {"company": lead["company"], "leads": [], "contacts": 0, "contacted": 0,
                                             "last_touch": None, "dream": False})
        contacts = (lead.get("package") or {}).get("contacts") or []
        company["leads"].append(lead)
        company["dream"] = company["dream"] or bool(lead.get("dream"))
        company["contacts"] += len(contacts)
        company["contacted"] += sum(1 for c in contacts if c.get("status"))
        touches = [company["last_touch"], lead.get("applied_at")]
        if lead["app_status"] != "new":
            touches.append((lead.get("updated_at") or "")[:10])  # the user has acted on this lead, so its last change counts
        company["last_touch"] = max(filter(None, touches), default=None)

    accounts, moves = [], []
    for key, company in companies.items():
        live = [lead for lead in company["leads"] if lead["app_status"] in ACTIVE_STATUSES and lead["stage"] != "closed"]
        if not live:
            continue
        open_roles = [lead for lead in live if lead["stage"] in OPEN_STAGES and lead["app_status"] in NOT_APPLIED]
        in_flight = [lead for lead in live if lead["app_status"] in IN_FLIGHT]
        best_values = sorted((lead_value(lead) for lead in live), reverse=True)[:3]
        accounts.append({"company": company["company"],
                         "equity": round(sum(best_values) + 8 * min(company["contacts"], 5), 1),  # 8 per known contact, up to 5
                         "open": len(open_roles), "in_flight": len(in_flight), "best": max((lead.get("score") or 0) for lead in live),
                         "contacts": company["contacts"], "contacted": company["contacted"], "last_touch": company["last_touch"],
                         "dream": company["dream"],
                         "leads": [{"id": lead["id"], "title": lead["title"], "score": lead.get("score"), "stage": lead["stage"],
                                    "status": lead["app_status"]} for lead in sorted(live, key=lambda x: -(x.get("score") or 0))[:6]]})
        if not open_roles:
            continue
        best = max(open_roles, key=lambda x: x.get("score") or 0)
        if len(open_roles) >= 2:
            moves.append(_move(f"account:{key}", "Multi-opening account", 58 + 5 * len(open_roles), best,
                               f"{len(open_roles)} open roles at {company['company']}. One referral could cover them all",
                               ", ".join(f"{lead['title'][:40]} ({lead.get('score')})" for lead in open_roles[:4]),
                               {"label": "See all", "search": company["company"]}))
        rejected = [lead for lead in company["leads"] if lead["app_status"] == "rejected"]
        if rejected:
            moves.append(_move(f"reengage:{key}:{best['id']}", "Re-engage", 62, best, f"New opening at {company['company']}, where you applied before",
                               f"Earlier: {rejected[0]['title'][:50]} ({rejected[0]['app_status']}). Now: {best['title'][:60]}",
                               {"label": "Open lead", "href": f"#/lead/{best['id']}"}))
    accounts.sort(key=lambda a: -a["equity"])
    return accounts, moves


def book() -> dict:
    """Everything the Equity mining page shows: the KPI tiles, the ranked worklist of moves (snoozed ones left out, 80 at
    most) and the company accounts (60 at most). Trashed leads are ignored."""
    min_score = int(settings_mod.get()["run"].get("min_score", 60))
    leads = [db.lead_row(r) for r in db.q("SELECT * FROM leads WHERE app_status != 'trashed'")]
    today = date.today().isoformat()
    snoozed = {key: until for key, until in (db.kv_get("crm.snoozed") or {}).items() if until >= today}
    questions = profile_mod.questions()
    open_by_lead = defaultdict(list)
    for q in questions:
        if q.get("lead_id") and q.get("status") == "open":
            open_by_lead[q["lead_id"]].append(q)

    moves = [move for lead in leads for move in _lead_moves(lead, open_by_lead.get(lead["id"], []), min_score)]
    accounts, account_moves = _accounts(leads)
    moves = [move for move in moves + account_moves if move["key"] not in snoozed]
    moves.sort(key=lambda move: -move["priority"])

    week_ago = (date.today() - timedelta(days=7)).isoformat()
    kpis = {
        # Each lead counts once: an open role not applied to yet, or an application in flight.
        "book": sum(1 for lead in leads if (lead["stage"] in OPEN_STAGES and lead["app_status"] in NOT_APPLIED) or lead["app_status"] in IN_FLIGHT),
        "ready_unworked": sum(1 for lead in leads if lead["stage"] == "ready" and lead["app_status"] in NOT_APPLIED),
        "pipeline_value": round(sum(lead_value(lead) for lead in leads if lead["app_status"] in ACTIVE_STATUSES)),
        "applied_week": sum(1 for lead in leads if (lead.get("applied_at") or "") >= week_ago),
        "followups_due": sum(1 for move in moves if move["kind"] == "Follow up"),
        "open_questions": sum(1 for q in questions if q.get("status") == "open"),
        "accounts": len(accounts),
    }
    return {"kpis": kpis, "actions": moves[:80], "accounts": accounts[:60], "snoozed": len(snoozed)}


def snooze(key: str, days: int) -> None:
    """Hide one move for this many days (the page's Done button uses 30, Snooze uses 3). Expired entries are dropped."""
    today = date.today().isoformat()
    snoozed = db.kv_get("crm.snoozed") or {}
    snoozed[key] = (date.today() + timedelta(days=days)).isoformat()
    db.kv_set("crm.snoozed", {k: until for k, until in snoozed.items() if until >= today})
