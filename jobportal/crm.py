"""Equity mining: treat the lead database like a CRM book of business and mine it for the highest-value moves right now.
Everything here is deterministic (no AI calls): triggers turn leads, contacts, deadlines and questions into a ranked worklist,
and companies roll up into accounts with an equity value."""
from collections import defaultdict
from datetime import date, timedelta

from . import db
from . import profile as profile_mod
from . import settings as settings_mod
from .textutil import norm_company

ACTIVE_STATUSES = ("new", "saved", "applied", "assessment", "interviewing", "offer")


def _days_until(iso: str | None) -> int | None:
    try:
        return (date.fromisoformat((iso or "")[:10]) - date.today()).days
    except ValueError:
        return None


def _days_since(iso: str | None) -> int | None:
    d = _days_until(iso)
    return -d if d is not None else None


def lead_value(l: dict) -> float:
    """Opportunity value of one lead: fit × how close it is to an application × urgency."""
    score = l.get("score") or 0
    stage_mult = {"ready": 1.0, "qualified": 0.8, "packaging": 0.85, "filtered": 0.35, "closed": 0.05, "error": 0.6}.get(l["stage"], 0.5)
    status_mult = {"new": 1.0, "saved": 1.05, "applied": 0.9, "assessment": 1.3, "interviewing": 1.6, "offer": 2.0}.get(l["app_status"], 0)
    left = _days_until(l.get("deadline"))
    urgency = 1.5 if left is not None and 0 <= left <= 7 else 1.25 if left is not None and 0 <= left <= 14 else 0.2 if left is not None and left < 0 else 1.0
    return round(score * stage_mult * status_mult * urgency, 1)


def book() -> dict:
    cfg = settings_mod.get()
    min_score = int(cfg["run"].get("min_score", 60))
    rows = [db.lead_row(r) for r in db.q("SELECT * FROM leads WHERE app_status != 'trashed'")]
    snoozed = {k: v for k, v in (db.kv_get("crm.snoozed") or {}).items() if v >= date.today().isoformat()}
    questions = profile_mod.questions()
    q_by_lead = defaultdict(list)
    for q in questions:
        if q.get("lead_id") and q.get("status") == "open":
            q_by_lead[q["lead_id"]].append(q)

    actions: list[dict] = []

    def act(key, kind, priority, lead, text, why, cta):
        if key in snoozed:
            return
        actions.append({"key": key, "kind": kind, "priority": round(priority, 1), "lead_id": lead["id"] if lead else None,
                        "company": lead["company"] if lead else "", "title": lead["title"] if lead else "", "text": text,
                        "why": why, "cta": cta})

    for l in rows:
        score, stage, st = l.get("score") or 0, l["stage"], l["app_status"]
        left = _days_until(l.get("deadline"))
        pkg = l.get("package") or {}
        open_lead = {"label": "Open lead", "href": f"#/lead/{l['id']}"}
        not_applied = st in ("new", "saved")
        if stage in ("ready", "qualified", "packaging") and not_applied and left is not None and 0 <= left <= 14:
            act(f"deadline:{l['id']}", "Closing soon", 100 - left * 3 + score / 5, l,
                f"Apply to {l['company']}: {l['title']}. Closes in {left} day{'s' if left != 1 else ''}",
                f"Fit {score}. Deadline {l['deadline']}.", open_lead if stage == "ready" else {"label": "Build package", "act": "crm-package"})
        elif stage == "ready" and not_applied:
            act(f"ready:{l['id']}", "Ready to apply", 50 + score / 2, l, f"Apply to {l['company']}: {l['title']}",
                f"Package ready, fit {score}" + (f", resume check {pkg.get('resume_check', {}).get('score')}" if pkg.get("resume_check") else ""), open_lead)
        if stage == "qualified" and not_applied and score >= 78 and not (left is not None and 0 <= left <= 14):
            act(f"package:{l['id']}", "Build package", 50 + score / 4, l, f"Build the application package for {l['company']}: {l['title']}",
                f"Fit {score}, queued without a package yet.", {"label": "Build package", "act": "crm-package"})
        if st in ("applied", "assessment", "interviewing") and l.get("follow_up_at") and (_days_until(l["follow_up_at"]) or 0) <= 0:
            act(f"followup:{l['id']}:{l['follow_up_at']}", "Follow up", 92, l, f"Follow up with {l['company']} on {l['title']}",
                f"Applied {l.get('applied_at') or 'on an unknown date'}; follow-up was due {l['follow_up_at']}. A follow-up email is pre-written.",
                {"label": "Open emails", "href": f"#/lead/{l['id']}/emails"})
        since = _days_since(l.get("applied_at"))
        if st == "applied" and since is not None and since >= 21:
            act(f"stale:{l['id']}", "Stale application", 40 + min(since, 60) / 3, l, f"No response from {l['company']} in {since} days",
                "Send a final nudge to a contact or mark it ghosted so the board stays honest.", open_lead)
        if (stage == "ready" or st in ("applied", "assessment", "interviewing")) and score >= 60:
            for i, c in enumerate(pkg.get("contacts") or []):
                if not c.get("status") and c.get("name"):
                    act(f"contact:{l['id']}:{i}", "Reach out", 44 + score / 4 + (6 if c.get("email_confidence") == "found" else 0), l,
                        f"Reach out to {c['name']} ({c.get('title') or 'contact'}) at {l['company']}",
                        (c.get("why") or "")[:180], {"label": "Contacts", "href": f"#/lead/{l['id']}/contacts"})
                    break  # one contact action per lead keeps the list readable
        if q_by_lead.get(l["id"]) and stage in ("ready", "qualified"):
            n = len(q_by_lead[l["id"]])
            act(f"questions:{l['id']}", "Strengthen", 52 + score / 5, l, f"Answer {n} question{'s' if n > 1 else ''} to strengthen your {l['company']} resume",
                q_by_lead[l["id"]][0]["question"][:160], open_lead)
        if stage == "filtered" and min_score - 12 <= score < min_score and (l.get("triage") or {}).get("eligibility") != "ineligible":
            flags = ", ".join((l.get("triage") or {}).get("red_flags") or [])[:140]
            act(f"nearmiss:{l['id']}", "Near miss", 34 + score / 3, l, f"Almost qualified: {l['company']}: {l['title']} (fit {score})",
                f"Red flags: {flags}" if flags else "Just under your threshold. Worth a look.", open_lead)

    # ---- accounts (companies)
    acc: dict[str, dict] = {}
    for l in rows:
        k = norm_company(l["company"]) or l["company"].lower()
        a = acc.setdefault(k, {"company": l["company"], "leads": [], "contacts": 0, "contacted": 0, "last_touch": None, "dream": False})
        a["leads"].append(l)
        a["dream"] = a["dream"] or bool(l.get("dream"))
        cs = (l.get("package") or {}).get("contacts") or []
        a["contacts"] += len(cs)
        a["contacted"] += sum(1 for c in cs if c.get("status"))
        a["last_touch"] = max(filter(None, [a["last_touch"], l.get("applied_at"), (l.get("updated_at") or "")[:10] if l["app_status"] != "new" else None]), default=None)
    accounts = []
    for k, a in acc.items():
        live = [l for l in a["leads"] if l["app_status"] in ACTIVE_STATUSES and l["stage"] not in ("closed",)]
        open_ops = [l for l in live if l["stage"] in ("ready", "qualified", "packaging") and l["app_status"] in ("new", "saved")]
        in_flight = [l for l in live if l["app_status"] in ("applied", "assessment", "interviewing", "offer")]
        values = sorted((lead_value(l) for l in live), reverse=True)
        equity = round(sum(values[:3]) + 8 * min(a["contacts"], 5), 1)
        if not live:
            continue
        accounts.append({"company": a["company"], "equity": equity, "open": len(open_ops), "in_flight": len(in_flight),
                         "best": max((l.get("score") or 0) for l in live), "contacts": a["contacts"], "contacted": a["contacted"],
                         "last_touch": a["last_touch"], "dream": a["dream"],
                         "leads": [{"id": l["id"], "title": l["title"], "score": l.get("score"), "stage": l["stage"], "status": l["app_status"]}
                                   for l in sorted(live, key=lambda x: -(x.get("score") or 0))[:6]]})
        if len(open_ops) >= 2:
            best = max(open_ops, key=lambda x: x.get("score") or 0)
            act(f"account:{k}", "Multi-opening account", 58 + 5 * len(open_ops), best,
                f"{len(open_ops)} open roles at {a['company']}. One referral could cover them all",
                ", ".join(f"{l['title'][:40]} ({l.get('score')})" for l in open_ops[:4]),
                {"label": "See all", "search": a["company"]})
        rejected = [l for l in a["leads"] if l["app_status"] in ("rejected", "ghosted")]
        if rejected and open_ops:
            best = max(open_ops, key=lambda x: x.get("score") or 0)
            act(f"reengage:{k}:{best['id']}", "Re-engage", 62, best, f"New opening at {a['company']}, where you applied before",
                f"Earlier: {rejected[0]['title'][:50]} ({rejected[0]['app_status']}). Now: {best['title'][:60]}", {"label": "Open lead", "href": f"#/lead/{best['id']}"})
    accounts.sort(key=lambda a: -a["equity"])
    actions.sort(key=lambda a: -a["priority"])

    week = (date.today() - timedelta(days=7)).isoformat()
    kpis = {
        "book": sum(1 for l in rows if l["app_status"] in ACTIVE_STATUSES and l["stage"] in ("ready", "qualified", "packaging")) +
                sum(1 for l in rows if l["app_status"] in ("applied", "assessment", "interviewing", "offer")),
        "ready_unworked": sum(1 for l in rows if l["stage"] == "ready" and l["app_status"] in ("new", "saved")),
        "pipeline_value": round(sum(lead_value(l) for l in rows if l["app_status"] in ACTIVE_STATUSES)),
        "applied_week": sum(1 for l in rows if (l.get("applied_at") or "") >= week),
        "followups_due": sum(1 for a in actions if a["kind"] == "Follow up"),
        "open_questions": sum(1 for q in questions if q.get("status") == "open"),
        "accounts": len(accounts),
    }
    return {"kpis": kpis, "actions": actions[:80], "accounts": accounts[:60], "snoozed": len(snoozed)}


def snooze(key: str, days: int) -> None:
    s = db.kv_get("crm.snoozed") or {}
    s[key] = (date.today() + timedelta(days=days)).isoformat()
    s = {k: v for k, v in s.items() if v >= date.today().isoformat()}
    db.kv_set("crm.snoozed", s)
