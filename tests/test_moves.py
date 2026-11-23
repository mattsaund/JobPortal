"""Home's Next moves card (insights/moves.py): no reply after three weeks, a second chance at a company that turned the user
down, several openings at one company, Hide, and the routes."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from jobportal.core import db
from jobportal.insights import moves


def lead(title, company, stage="ready", status="new", applied_days_ago=None, created=None, score=70) -> int:
    """Save one fictional lead and return its id."""
    now = db.now()
    applied = (date.today() - timedelta(days=applied_days_ago)).isoformat() if applied_days_ago is not None else None
    db.ex("INSERT INTO leads(fingerprint, title, company, stage, app_status, applied_at, score, created_at, updated_at) "
          "VALUES(?,?,?,?,?,?,?,?,?)", (f"{company}|{title}", title, company, stage, status, applied, score, created or now, now))
    return db.one("SELECT id FROM leads ORDER BY id DESC LIMIT 1")["id"]


def test_an_application_with_no_reply_for_three_weeks():
    waiting = lead("Medical Assistant", "Northwind Clinic", status="applied", applied_days_ago=24)
    lead("Front Desk Associate", "Contoso Dental", status="applied", applied_days_ago=5)  # too soon to follow up
    lead("Line Cook", "Fabrikam Grill", status="interviewing", applied_days_ago=40)  # they replied
    lead("Cashier", "Tailspin Market", status="trashed", applied_days_ago=40)  # deleted
    (move,) = moves.moves()
    assert move["kind"] == "No reply" and move["text"] == "No reply from Northwind Clinic in 24 days"
    assert move["cta"] == {"label": "Follow up", "href": f"#/leads/{waiting}/emails"}


def test_several_openings_at_one_company():
    lead("Registered Nurse", "Example Health", score=80)
    lead("Nurse Aide", "Example Health, Inc.", stage="qualified", score=72)  # the same company, written another way
    lead("Charge Nurse", "Example Health", stage="filtered")  # didn't pass scoring
    lead("Barista", "Contoso Coffee")
    (move,) = moves.moves()
    assert move["kind"] == "Several openings" and move["text"] == "2 openings at Example Health"
    assert move["why"] == "Registered Nurse, Nurse Aide"
    assert move["cta"] == {"label": "View", "search": "Example Health"}


def test_a_new_opening_where_the_user_was_turned_down():
    before = lead("Welder", "Contoso Fabrication", status="rejected", created="2026-09-01T10:00:00+00:00")
    db.add_event(before, "status", "applied → rejected")
    db.ex("UPDATE events SET ts='2026-10-01T10:00:00+00:00' WHERE lead_id=?", (before,))
    newer = lead("Welder Fitter", "Contoso Fabrication", created="2026-11-10T10:00:00+00:00")
    lead("Shop Helper", "Contoso Fabrication", created="2026-09-15T10:00:00+00:00")  # found before they turned the user down
    found = moves.moves()
    assert [m["kind"] for m in found] == ["Second chance", "Several openings"]
    assert found[0]["why"] == "Welder Fitter"
    assert found[0]["cta"] == {"label": "Open", "href": f"#/leads/{newer}"}


def test_the_card_stays_small():
    for n in range(8):
        lead(f"Role {n}", f"Company {n}", status="applied", applied_days_ago=30 + n)
    found = moves.moves()
    assert len(found) == moves.MAX_MOVES and found[0]["text"].endswith("in 37 days")  # the longest wait first


def test_hide_keeps_a_move_off_the_card_for_a_while():
    from jobportal.web.server import app
    lead("Medical Assistant", "Northwind Clinic", status="applied", applied_days_ago=30)
    with TestClient(app) as client:
        (move,) = client.get("/api/moves").json()["moves"]
        assert client.post("/api/moves/hide", json={"key": move["key"]}).json() == {"ok": True}
        assert client.get("/api/moves").json()["moves"] == []
        assert client.post("/api/moves/hide", json={}).status_code == 400
    db.kv_set("moves.hidden", {move["key"]: (date.today() - timedelta(days=1)).isoformat()})  # its 30 days are up
    assert len(moves.moves()) == 1
