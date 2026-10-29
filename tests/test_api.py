import copy
import time

import pytest
from fastapi.testclient import TestClient

from conftest import PROFILE_OUT, STANDARD_ANSWERS


@pytest.fixture
def client():
    from jobportal.main import app
    with TestClient(app) as c:
        yield c


def test_dashboard_and_meta(client):
    r = client.get("/")
    assert r.status_code == 200 and "JobPortal" in r.text
    meta = client.get("/api/meta").json()
    assert meta["version"] and meta["os"] in ("windows", "macos", "linux") and meta["data_dir"]


def test_refuses_foreign_host_headers(client):
    assert client.get("/api/meta", headers={"host": "evil.example:8788"}).status_code == 403
    assert client.get("/api/meta", headers={"host": "localhost:8788"}).status_code == 200


def test_fresh_install_is_empty(client):
    ob = client.get("/api/onboarding").json()
    assert ob["resume"] is None and not ob["complete"] and ob["questions"]
    assert client.get("/api/leads").json()["leads"] == []
    assert client.get("/api/settings").json()["locations"]["allowed"] == []
    assert client.get("/api/questions").json() == []
    r = client.post("/api/run", json={"mode": "full"})
    assert r.status_code == 409 and "resume" in r.json()["detail"]


def test_setup_flow(client, fake_claude, sample_resume):
    fake_claude.responses["onboarding-prefill"] = {"name": "Jordan Rivera", "target_roles": ["Software Engineer"], "levels": ["entry"]}
    fake_claude.responses["library-import"] = {"resume_md": sample_resume, "suggested_name": "Jordan Rivera"}
    fake_claude.responses["profile-build"] = copy.deepcopy(PROFILE_OUT)
    fake_claude.responses["analysis"] = {"genres": [], "summary": "", "top_priorities": [], "profile_suggestions": [],
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
