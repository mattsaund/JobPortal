import asyncio
from datetime import date

import pytest

from jobportal.core import osutil
from jobportal.documents import render, resumecheck


def test_resume_html(sample_resume):
    html = render.resume_html(sample_resume)
    assert "<h1>Jordan Rivera</h1>" in html
    assert '<div class="line split">' in html  # "left || dates" puts the dates flush right
    assert "<li>" in html and "<script" not in html


def test_links_are_sanitized():
    html = render.inline_html("[click](javascript:alert(1)) and [ok](https://example.com)")
    assert 'href="#"' in html and 'href="https://example.com"' in html


def test_long_date_is_portable():
    assert render.long_date(date(2026, 3, 5)) == "March 5, 2026"


def test_cover_html_uses_facts():
    facts = {"name": "Jordan Rivera", "email": "jordan.rivera@example.com", "city": "Columbus", "state": "OH", "links": {}}
    html = render.cover_html("Dear Hiring Team,\n\nHello.\n\nSincerely,\nJordan Rivera", facts, "Example Co", "Remote")
    assert "Jordan Rivera" in html and "Example Co" in html


def test_resume_check(sample_resume):
    inv = [{"skill": s, "level": "strong"} for s in ("Python", "JavaScript", "React", "Node.js", "SQL", "PostgreSQL", "Git", "Linux")]
    good = resumecheck.check(sample_resume, inventory=inv, keywords=["Python", "SQL"], pages=1, max_pages=1)
    assert good["score"] >= 85, good["issues"]
    assert not any("phone" in i["text"] for i in good["issues"])  # "(555) 010-0199" counts as a phone number
    bad = resumecheck.check("# Name\nno contact\n\n## My Journey\n- I was responsible for stuff", inventory=inv, pages=2, max_pages=1)
    texts = " ".join(i["text"] for i in bad["issues"])
    assert "2 pages" in texts and "Non-standard heading" in texts and "first person" in texts


@pytest.mark.skipif(not osutil.find_chrome(), reason="needs Chrome, Edge or Chromium")
def test_pdf_export(sample_resume, tmp_path):
    info = asyncio.run(render.resume_pdf(sample_resume, tmp_path / "resume.pdf"))
    assert info["pages"] == 1 and (tmp_path / "resume.pdf").stat().st_size > 1000
    render.resume_docx(sample_resume, tmp_path / "resume.docx", render.fit_scale(tmp_path / "resume.pdf"))
    assert (tmp_path / "resume.docx").stat().st_size > 1000
