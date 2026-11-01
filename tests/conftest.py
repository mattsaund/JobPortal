"""Test setup. Every test starts from zero data: an empty data folder and database, exactly like a fresh install.
OpenAI is never called; tests that need AI output use the fake_ai fixture."""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Must happen before anything imports jobportal.core.config, which reads JOBPORTAL_HOME once.
_HOME = Path(tempfile.mkdtemp(prefix="jobportal-test-"))
os.environ["JOBPORTAL_HOME"] = str(_HOME)
os.environ.pop("JOBPORTAL_PORT", None)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def zero_data():
    from jobportal.ai import client as ai, signin
    from jobportal.candidate import profile
    from jobportal.core import bus, config, db
    db.close()
    for p in config.DATA.glob("*"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
    profile.status.update(busy=False, phase="", error=None)
    profile._last_failure.clear()
    bus.state.update(running=False, active_agents={}, tokens=0)
    ai.web_search_ok, ai._limit_hit_at = None, 0.0
    ai._models.update(at=0.0, ids=[])
    signin._pending.clear()
    yield
    db.close()


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_HOME, ignore_errors=True)


@pytest.fixture
def sample_resume() -> str:
    return (FIXTURES / "sample_resume.md").read_text(encoding="utf-8")


class FakeAI:
    def __init__(self):
        self.calls: list[dict] = []
        self.responses: dict = {}

    async def run(self, prompt, *, system, schema, stage, purpose, **kw):
        self.calls.append({"purpose": purpose, "stage": stage, "prompt": prompt, "system": system})
        out = self.responses.get(purpose)
        if callable(out):
            out = out(prompt)
        if out is None:
            from jobportal.ai.client import AIError
            raise AIError(f"no fake response for {purpose}")
        return {**out, "_tokens": 0, "_tools": {}}


@pytest.fixture
def fake_ai(monkeypatch) -> FakeAI:
    from jobportal.ai import client as ai
    fake = FakeAI()
    monkeypatch.setattr(ai, "run", fake.run)
    return fake


STANDARD_ANSWERS = {
    "name": "Jordan Rivera", "email": "jordan.rivera@example.com", "phone": "(555) 010-0199", "city": "Columbus", "state": "Ohio",
    "country": "United States", "linkedin": "https://www.linkedin.com/in/jordan-rivera-example", "github": "", "website": "",
    "work_authorized": "yes", "sponsorship": "no", "citizenship": "us_citizen", "clearance": "none", "over_18": "yes",
    "education_level": "bachelor", "school": "Example State University", "field_of_study": "Computer Science",
    "graduation": "May 2027", "gpa": "3.4", "enrolled": "yes",
    "target_roles": ["Software Engineer", "IT Support Specialist"], "levels": ["internship", "entry"], "experience_years": "lt1",
    "job_types": ["internship", "full_time"], "work_modes": ["remote", "hybrid", "onsite"], "locations": ["Ohio", "Pittsburgh, PA"],
    "anywhere_us": "no", "relocate": "depends", "dream_companies": ["Example Robotics"], "gender": "decline",
    "writing_sample": "", "extra": "I also volunteer teaching Scratch to middle schoolers.",
}

PROFILE_OUT = {
    "facts": {"name": "Jordan Rivera", "email": "old@example.com", "phone": "", "city": "Columbus", "state": "OH",
              "links": {"site": "", "github": "https://github.com/jordan-rivera-example", "linkedin": ""},
              "school": "Example State University", "degree": "B.S. Computer Science", "graduation": "May 2027", "gpa": "",
              "work_authorization": "", "clearance": "", "skills": "Python, JavaScript, React, SQL"},
    "project_bank": "## Work Experience\n### Campus IT Help Desk - Student Technician\n- 40+ tickets a week\n\n## Projects\n### Budget Buddy - budgeting app\n- 120 users",
    "story_bank": "## Faster laptop imaging\nSituation: imaging took 45 minutes...",
    "targeting": "Target roles: Software Engineer, IT Support Specialist",
    "search_plan": {"role_families": ["Software engineering", "IT support"], "queries": ["software engineer intern", "it support intern"],
                    "dream_companies": ["Example Robotics"], "notes": "Lead with the help desk automation."},
    "provenance": [{"field": "school", "value": "Example State University", "source": "resume", "date": "2026-10-28"}],
    "skills_inventory": [{"skill": "Python", "category": "Languages", "level": "strong", "evidence": ["imaging script"]},
                         {"skill": "React", "category": "Frameworks", "level": "working", "evidence": ["Budget Buddy"]}],
    "changes": ["Built the profile from the resume and standard answers"],
    "open_questions": [{"question": "How many people used the imaging script?", "why": "A number strengthens the bullet.", "field": "project_bank"}],
}
