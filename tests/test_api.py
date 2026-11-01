import copy
import json
import time

import pytest
from conftest import PROFILE_OUT, STANDARD_ANSWERS
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from jobportal.web.server import app
    with TestClient(app) as c:
        yield c


def test_dashboard_and_meta(client):
    r = client.get("/")
    assert r.status_code == 200 and "JobPortal" in r.text
    meta = client.get("/api/meta").json()
    assert meta["version"] and meta["os"] in ("windows", "macos", "linux") and meta["data_dir"]


def test_equity_mining_is_gone(client):
    from jobportal.core import db
    db.kv_set("crm.snoozed", {"move:1": "2099-01-01"})  # what an older version saved
    db.close()  # reopening runs the migration, which drops the old value
    assert db.kv_get("crm.snoozed") is None
    assert client.get("/api/crm").status_code == 404 and client.post("/api/crm/snooze", json={"key": "x"}).status_code == 404
    assert client.get("/api/dreams").status_code == 200  # the Dream list stays


def test_refuses_foreign_host_headers(client):
    assert client.get("/api/meta", headers={"host": "evil.example:8788"}).status_code == 403
    assert client.get("/api/meta", headers={"host": "localhost:8788"}).status_code == 200


def test_refuses_changes_from_other_sites(client):
    assert client.post("/api/run/stop", headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/run/stop", headers={"origin": "http://127.0.0.1:9999", "host": "127.0.0.1:8788"}).status_code == 403
    assert client.post("/api/run/stop", headers={"origin": "http://127.0.0.1:8788", "host": "127.0.0.1:8788"}).status_code == 200
    assert client.post("/api/run/stop").status_code == 200  # no Origin: not from a web page
    assert client.get("/api/meta", headers={"origin": "https://evil.example"}).status_code == 200


def test_open_external_only_opens_web_and_mail_links(client, monkeypatch):
    from jobportal.core import osutil
    opened = []
    monkeypatch.setattr(osutil, "open_url", lambda url: opened.append(url) or True)
    assert client.post("/api/open-external", json={"url": "https://example.com/job"}).json() == {"ok": True}
    assert client.post("/api/open-external", json={"url": "file:///etc/passwd"}).status_code == 400
    assert opened == ["https://example.com/job"]


def test_quit_stops_the_server(client):
    from jobportal.web.server import app
    assert client.post("/api/quit").status_code == 409

    class Server:
        should_exit = False
    app.state.server = server = Server()
    try:
        assert client.post("/api/quit").json() == {"ok": True} and server.should_exit
    finally:
        del app.state.server


def test_fresh_install_is_empty(client):
    ob = client.get("/api/onboarding").json()
    assert ob["resume"] is None and not ob["complete"] and ob["questions"]
    assert client.get("/api/leads").json()["leads"] == []
    assert client.get("/api/settings").json()["locations"]["allowed"] == []
    assert client.get("/api/questions").json() == []
    r = client.post("/api/run", json={"mode": "full"})
    assert r.status_code == 409 and "resume" in r.json()["detail"]


def test_setup_flow(client, fake_ai, sample_resume):
    fake_ai.responses["onboarding-prefill"] = {"name": "Jordan Rivera", "target_roles": ["Software Engineer"], "levels": ["entry"]}
    fake_ai.responses["library-import"] = {"resume_md": sample_resume, "suggested_name": "Jordan Rivera"}
    fake_ai.responses["profile-build"] = copy.deepcopy(PROFILE_OUT)
    fake_ai.responses["analysis"] = {"genres": [], "summary": "", "top_priorities": [], "profile_suggestions": [],
                                         "search_steering": {"emphasize": [], "deemphasize": [], "add_queries": [], "add_companies": [], "notes": ""}}
    r = client.put("/api/onboarding/resume?filename=resume.md", content=sample_resume.encode())
    assert r.status_code == 200, r.text
    assert r.json()["prefill"]["target_roles"] == ["Software Engineer"]
    bad = client.put("/api/onboarding/answers", json={"answers": {"name": "Jordan"}})
    assert bad.status_code == 400
    r = client.put("/api/onboarding/answers", json={"answers": STANDARD_ANSWERS, "build": True})
    assert r.status_code == 200 and r.json()["building"]
    for _ in range(100):
        st = client.get("/api/profile/status").json()
        if st["built"] and not st["busy"]:
            break
        time.sleep(0.05)
    assert st["built"] and st["open_questions"] == 1
    assert client.get("/api/onboarding").json()["complete"]
    over = client.get("/api/profile/overview").json()
    assert over["identity"]["name"] == "Jordan Rivera" and over["knows"]["skills_total"] == 2
    q = client.get("/api/questions").json()[0]["question"]
    r = client.post("/api/questions/answer", json={"question": q, "answer": "About 300 students."})
    assert r.json()["status"]["unsynced"] == 1
    for _ in range(100):
        if client.get("/api/library").json():
            break
        time.sleep(0.05)
    assert client.get("/api/library").json()[0]["name"] == "resume"  # markdown imports keep the file name and skip the AI


def test_resume_upload_errors(client):
    r = client.put("/api/onboarding/resume?filename=photo.png", content=b"\x89PNG" + b"0" * 300)
    assert r.status_code == 400 and "supported" in r.json()["detail"]


def test_chatgpt_sign_in_endpoints(client):
    assert client.get("/api/ai/status").json()["signed_in"] is False
    url = client.post("/api/ai/signin").json()["url"]
    assert url.startswith("https://auth.openai.com/api/accounts/authorize?") and "127.0.0.1%3A8788%2Fauth%2Fcallback" in url
    page = client.get("/auth/callback?state=bogus&code=x")
    assert page.status_code == 200 and "Sign-in didn" in page.text
    assert client.get("/api/ai/models").status_code == 401


def _lead_with_documents() -> int:
    """A lead with a resume and a package, as if a search had built one."""
    from jobportal.core import db
    from jobportal.search import packages
    lead_id = packages.add_manual_lead("https://jobs.example.com/123", "Build internal tools in Python.", "Software Engineering Intern",
                                       "Example Robotics", "Columbus, OH")
    db.update_lead(lead_id, resume_md="# Jordan Rivera\njordan.rivera@example.com\n\n## Projects\n- Budget Buddy",
                   package={"interview_prep_md": "## Likely questions\n- Tell me about Budget Buddy.",
                            "emails": [{"kind": "recruiter", "to_addr": "recruiting@example.com", "subject": "Internship", "body": "Hello!"}],
                            "contacts": [{"name": "Sam Lee", "title": "Recruiter", "org": "Example Robotics", "email": "sam@example.com"}]})
    return lead_id


def test_lead_downloads(client):
    lead_id = _lead_with_documents()
    get = lambda name: client.get(f"/api/leads/{lead_id}/export/{name}")  # noqa: E731
    assert "Budget Buddy" in get("resume.md").text
    assert "Sam Lee" in get("contacts.csv").text and "Build internal tools" in get("posting.txt").text
    assert "Subject: Internship" in get("email-0.eml").text
    assert get("interview_prep.docx").content[:2] == b"PK"  # a Word file is a zip
    assert get("email-5.eml").status_code == 404 and get("cover_letter.md").status_code == 404 and get("resume.exe").status_code == 404


def test_manual_lead_needs_a_link_or_text(client, fake_ai):
    assert client.post("/api/leads/manual", json={}).status_code == 400
    lead = client.post("/api/leads/manual", json={"url": "https://jobs.example.com/9"}).json()
    assert lead["source"] == "manual" and lead["stage"] == "qualified"


def test_dream_list(client):
    r = client.put("/api/dreams", json={"companies": ["Example Robotics", " "], "jobs": ["Robotics Intern"], "bypass": False}).json()
    assert r["companies"] == ["Example Robotics"] and r["jobs"] == ["Robotics Intern"] and r["bypass"] is False
    _lead_with_documents()
    assert client.post("/api/dreams/recheck").json()["changed"] == 1  # the lead's company is now a dream company


def test_source_check_counts_what_passes(client, monkeypatch):
    from jobportal.search import collectors
    from jobportal.search.collectors.base import RawJob

    async def fake_collector(ctx):
        return [RawJob("fake", "Software Engineering Intern", "Example Robotics", "https://jobs.example.com/1", location="Remote"),
                RawJob("fake", "Senior Staff Engineer", "Example Robotics", "https://jobs.example.com/2", location="Remote")]
    monkeypatch.setitem(collectors.COLLECTORS, "fake", ("Fake source", fake_collector))
    r = client.post("/api/sources/test/fake").json()
    assert r["ok"] and r["found"] == 2 and r["pass_filters"] <= 1
    assert client.post("/api/sources/test/nope").status_code == 404


def test_pasting_the_same_job_twice_opens_the_saved_lead(client, fake_ai):
    first = client.post("/api/leads/manual", json={"url": "https://jobs.example.com/77"}).json()
    again = client.post("/api/leads/manual", json={"url": "https://jobs.example.com/77"}).json()
    assert again["id"] == first["id"] and again["existing"] is True
    assert "existing" not in client.post("/api/leads/manual", json={"text": "Robotics intern, Columbus."}).json()
    assert client.post("/api/leads/manual", json={"text": "Robotics intern, Columbus."}).json()["existing"] is True


def test_extra_documents(client, fake_ai, sample_resume):
    upload = lambda name, data: client.put(f"/api/profile/documents?filename={name}", content=data)  # noqa: E731
    cert = upload("AWS certificate.txt", b"AWS Certified Cloud Practitioner. Jordan Rivera, 2025.")  # one line is enough
    assert cert.status_code == 200 and cert.json()["kind"] == "certificate"
    # Its details are read right away by patterns (no AI: nobody is signed in), so the dashboard has something to show.
    assert cert.json()["parsing"] is False and cert.json()["parsed_by"] == "rules"
    assert {k: cert.json()["parsed"][k] for k in ("title", "issuer", "issued", "expires")} == {
        "title": "AWS Certified Cloud Practitioner", "issuer": "Amazon Web Services", "issued": "2025", "expires": ""}
    assert upload("AWS certificate.txt", b"AWS Certified Cloud Practitioner. Jordan Rivera, 2025.").json()["duplicate"] is True
    assert upload("photo.png", b"\x89PNG not text").status_code == 400  # images can't be read
    letter = upload("cover letter.txt", b"Dear Hiring Team, I build robots and tools people use every day.").json()
    listed = client.get("/api/profile/documents").json()
    assert [d["kind"] for d in listed] == ["certificate", "cover letter"] and "text" not in listed[0]
    assert client.get("/api/onboarding").json()["documents"] == listed
    assert client.delete(f"/api/profile/documents/{letter['id']}").json() == {"ok": True}
    assert client.delete(f"/api/profile/documents/{letter['id']}").status_code == 404
    # Swap: a document becomes the main resume, and the old main resume is kept as a document.
    fake_ai.responses["onboarding-prefill"] = {}
    client.post("/api/onboarding/resume-text", json={"text": sample_resume, "name": "old resume.md", "prefill": False, "save_to_library": False})
    newer = upload("newer resume.md", sample_resume.replace("Budget Buddy", "Budget Buddy 2").encode()).json()
    assert client.post(f"/api/profile/documents/{newer['id']}/main").json()["resume"]["filename"] == "newer resume.md"
    assert "old resume.md" in [d["name"] for d in client.get("/api/profile/documents").json()]


AI_DETAILS = {"kind": "license", "title": "Registered Nurse License", "issuer": "Ohio Board of Nursing", "issued": "June 2024",
              "expires": "2026-08-31", "skills": ["patient care", "Jordan Rivera", "medication administration"],
              "summary": "An active Ohio RN license."}
LICENSE = b"Ohio Board of Nursing\nThis certifies that\nJordan Rivera\nis licensed as a Registered Nurse\nIssued: 06/15/2024"


def test_reading_a_document_with_ai(client, fake_ai):
    upload = client.put("/api/profile/documents?filename=RN license.txt", content=LICENSE).json()
    assert upload["parsed"]["title"] == "Registered Nurse License" and upload["parsed_by"] == "rules"
    assert client.post("/api/profile/documents/nope/parse").status_code == 404
    fake_ai.responses["document-parse"] = AI_DETAILS
    read = client.post(f"/api/profile/documents/{upload['id']}/parse").json()
    assert read["parsed_by"] == "ai" and read["parsing"] is False and read["kind"] == "license"
    assert read["parsed"] == {**AI_DETAILS, "issued": "2024-06", "expires": "2026-08",  # dates as YYYY-MM
                              "skills": ["patient care", "medication administration"]}  # never the user's own name
    call = next(c for c in fake_ai.calls if c["purpose"] == "document-parse")
    assert call["stage"] == "documents" and "is licensed as a Registered Nurse" in call["prompt"]
    assert client.get("/api/profile/documents").json() == [read] == client.get("/api/onboarding").json()["documents"]


def test_a_signed_out_reading_asks_to_sign_in(client):
    upload = client.put("/api/profile/documents?filename=RN license.txt", content=LICENSE).json()
    r = client.post(f"/api/profile/documents/{upload['id']}/parse")
    assert r.status_code == 401 and client.get("/api/profile/documents").json()[0]["parsed_by"] == "rules"  # the rules reading stays


def test_documents_are_read_by_ai_in_the_background_when_signed_in(client, fake_ai, monkeypatch):
    from jobportal.candidate import documents
    from jobportal.core import bus
    monkeypatch.setattr(documents, "_signed_in", lambda: True)
    fake_ai.responses["document-parse"] = AI_DETAILS
    events = bus.subscribe()
    upload = client.put("/api/profile/documents?filename=RN license.txt", content=LICENSE).json()
    assert upload["parsing"] is True  # the AI reading has started
    for _ in range(100):
        listed = client.get("/api/profile/documents").json()[0]
        if not listed["parsing"]:
            break
        time.sleep(0.02)
    assert listed["parsed_by"] == "ai" and listed["parsed"]["issuer"] == "Ohio Board of Nursing"
    seen = []
    while not events.empty():
        seen.append(json.loads(events.get_nowait()))
    bus.unsubscribe(events)
    documents_events = [e["data"] for e in seen if e["kind"] == "documents"]
    assert documents_events[0][0]["parsing"] is True and documents_events[-1][0]["parsed_by"] == "ai"


def test_quick_add_delete_and_tracker_columns(client, fake_ai):
    assert client.post("/api/leads/manual", json={"title": "Pharmacy Technician"}).status_code == 400  # a company too
    assert client.post("/api/leads/manual", json={"title": "Chef", "company": "Example Bistro", "app_status": "bogus"}).status_code == 400
    lead = client.post("/api/leads/manual", json={"title": "Pharmacy Technician", "company": "Example Health",
                                                  "app_status": "applied"}).json()
    assert lead["stage"] == "ready" and lead["app_status"] == "applied"  # nothing to build a package from
    board = client.get("/api/tracker").json()
    assert list(board["columns"]) == ["ready", "applied", "interviewing", "accepted", "rejected"]
    assert [x["id"] for x in board["columns"]["applied"]] == [lead["id"]]
    assert client.get("/api/stats").json()["tracked"] == 1
    assert client.delete(f"/api/leads/{lead['id']}").json() == {"ok": True}
    assert client.get(f"/api/leads/{lead['id']}").status_code == 404
    assert client.delete(f"/api/leads/{lead['id']}").status_code == 404


def test_old_statuses_move_to_the_tracker_columns(client):
    from jobportal.core import db
    from jobportal.search import packages
    ids = {old: packages.insert_lead({"fingerprint": f"fp-{old}", "title": "Role", "company": "Example Co", "app_status": old})
           for old in ("saved", "assessment", "offer", "ghosted", "withdrawn")}
    db.close()  # the next query reopens the database, which runs the migration
    assert {old: db.one("SELECT app_status FROM leads WHERE id=?", (i,))["app_status"] for old, i in ids.items()} == {
        "saved": "ready", "assessment": "interviewing", "offer": "accepted", "ghosted": "rejected", "withdrawn": "rejected"}


def test_home_saves_answers_one_at_a_time(client, fake_ai, sample_resume):
    fake_ai.responses["onboarding-prefill"] = {}
    client.put("/api/onboarding/resume?filename=resume.md&save_to_library=0", content=sample_resume.encode())
    out = client.patch("/api/onboarding/answers", json={"answers": {"city": "Columbus"}}).json()
    assert not out["building"] and out["missing"]
    fake_ai.responses["profile-build"] = PROFILE_OUT
    out = client.patch("/api/onboarding/answers", json={"answers": STANDARD_ANSWERS}).json()
    assert out["complete"] and out["building"] and out["missing"] == []


def test_dropping_several_files_picks_the_main_resume(client, fake_ai, sample_resume):
    upload = lambda name, data: client.put(f"/api/profile/documents?filename={name}", content=data)  # noqa: E731
    upload("Food handler certificate.txt", b"Certificate of completion: Food Handler Training. Issued March 2025.")
    upload("short resume.md", sample_resume[:900].encode())
    upload("full resume.md", sample_resume.encode())
    fake_ai.responses["onboarding-prefill"] = {}
    out = client.post("/api/profile/documents/auto-main").json()
    assert out["picked"] == "full resume.md" and out["resume"]["filename"] == "full resume.md"
    assert sorted(d["name"] for d in client.get("/api/profile/documents").json()) == ["Food handler certificate.txt", "short resume.md"]
    assert client.post("/api/profile/documents/auto-main").json()["picked"] is None  # there's a main resume now


def test_skipping_application_sent_still_records_the_date(client, fake_ai):
    lead = client.post("/api/leads/manual", json={"title": "Electrician Apprentice", "company": "Example Electric",
                                                  "app_status": "ready"}).json()
    moved = client.patch(f"/api/leads/{lead['id']}", json={"app_status": "interviewing"}).json()
    assert moved["applied_at"] and not moved.get("follow_up_at")  # applied, but not waiting on a reply anymore
    quick = client.post("/api/leads/manual", json={"title": "Line Cook", "company": "Example Diner", "app_status": "accepted"}).json()
    assert quick["applied_at"]
