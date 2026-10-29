"""Rule-based resume checks: ATS safety, length, structure, style, keyword coverage, and whether every skill listed is backed
by the candidate's skills inventory. No AI is involved, so the same resume always gets the same result.

Who calls it: search/pipeline.py checks each resume before and after the AI critic revises it (the critic is told to fix the
issues found here). The lead editor runs it again after each save, after a layout change and from its recheck button,
through web/routes/documents.py. The dashboard shows the score and the issues.

check() returns a 0 to 100 score and a list of issues. An "error" breaks the resume for an ATS or a recruiter (no email, a
table, unverified skills); a "warn" is worth fixing but not fatal. ATS means applicant tracking system: the software
employers use to parse resumes into fields, which is why plain structure and standard headings matter."""
import re

from jobportal.core.textutil import coverage
from jobportal.documents.render import parse_resume

# Section names an ATS maps to its own fields without guessing (compared in lowercase).
STANDARD_HEADINGS = {
    "summary", "professional summary", "education", "experience", "work experience", "professional experience",
    "technical experience", "relevant experience", "projects", "technical projects", "research & technical projects",
    "research and technical projects", "research experience", "skills", "technical skills", "certifications",
    "certifications & training", "licenses & certifications", "relevant coursework", "coursework", "leadership",
    "leadership & activities", "activities", "extracurricular and volunteer work", "volunteer work", "volunteer experience",
    "awards", "honors & awards", "awards & honors", "publications", "clearance", "additional information",
}

_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27bf]")  # emoji, plus the older symbol and dingbat blocks
# First person: "I" before a contraction or a lowercase word, and "me" and "my". A lone "I" before punctuation, "and" or
# "or" is a Roman numeral (Calculus I, Physics I and II), and "I/O" means input/output, so those don't count.
_FIRST_PERSON_RE = re.compile(r"(?<![A-Za-z])(?:I(?='[a-z]|\s+(?!(?:and|or)\b)[a-z])|me|my)(?![A-Za-z])")
_WEAK_START_RE = re.compile(r"(responsible for|worked on|helped|assisted|duties)", re.I)
_MONTH_DATE_RE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{4}")  # May 2027
_NUMERIC_DATE_RE = re.compile(r"\b(0[1-9]|1[0-2])/\d{4}\b")  # 05/2027
MAX_BULLET_CHARS = 215  # about two printed lines at the default size
MAX_SKILLS = 32


def _norm(text: str) -> str:
    """Lowercase with punctuation turned into spaces, keeping + and # (C++, C#), for loose skill comparisons."""
    return re.sub(r"[^a-z0-9+#]+", " ", text.lower()).strip()


def _listed_skills(resume: dict) -> list[str]:
    """Every skill named in the resume's Skills sections. A line like "**Languages:** Python, SQL" loses its bold label, then
    splits at commas, semicolons and middle dots."""
    skills = []
    for section in resume["sections"]:
        if "skill" not in section["title"].lower():
            continue
        for entry in section["entries"]:
            for _, text in entry:
                body = re.sub(r"\*\*", "", re.sub(r"^\*\*[^*]+\*\*:?\s*", "", text))
                skills += [item.strip(" .") for item in re.split(r",|;|\u00b7", body) if item.strip(" .")]
    return skills


def _in_inventory(skill: str, inventory_names: list[str]) -> bool:
    """Whether a listed skill matches an inventory skill, loosely. Parentheses on the resume side are ignored ("Python
    (pandas)" is Python), an inventory name splits into its parts ("HTML/CSS" covers both), and a name longer than three
    letters also matches as part of a longer one ("React" and "React Native")."""
    wanted = _norm(re.sub(r"\(.*?\)", "", skill))
    if not wanted:
        return True
    for name in inventory_names:
        parts = [_norm(p) for p in re.split(r"/|\(|\)|,| and ", name) if _norm(p)]
        if wanted == _norm(name) or any(wanted == p or (len(wanted) > 3 and (wanted in p or p in wanted)) for p in parts):
            return True
    return False


def _gpa_below_3(gpa: str) -> bool:
    """True when the GPA answer (such as "2.8" or "2.8/4.0") starts with a number under 3.0."""
    found = re.findall(r"\d\.\d+", gpa)
    return bool(found) and float(found[0]) < 3.0


def check(md: str, *, inventory: list[dict] | None = None, keywords: list[str] | None = None, pages: int | None = None,
          max_pages: int = 1, archetype: str = "", gpa: str = "") -> dict:
    """Run every check on a resume written in JobPortal's resume Markdown.

    inventory is the profile's skills inventory ([{"skill", "level", ...}]), keywords are the job posting's keywords, pages
    is the printed page count when known (from render.resume_pdf), and gpa is the candidate's GPA answer. The "federal_usajobs"
    archetype skips the date-format and GPA rules, since federal resumes follow their own conventions.

    Returns {"score", "issues", "coverage", "unverified_skills", "pages", "max_pages"}. Each issue is {"level": "error" or
    "warn", "text": ...}. The score starts at 100, loses 14 per error and 5 per warning, gains 5 when the resume holds at
    least 75% of the keywords, and stays within 0 to 100."""
    text = md or ""
    resume = parse_resume(text)
    issues: list[dict] = []

    def add(level: str, message: str) -> None:
        issues.append({"level": level, "text": message})

    # Length and contact details.
    if pages and pages > max_pages:
        add("error", f"Runs to {pages} pages; the limit is {max_pages}. Cut the weakest lines.")
    if not resume["name"]:
        add("error", "Missing the name heading (# Name).")
    contact = " ".join(resume["contact"])
    if "@" not in contact:
        add("error", "No email in the contact line.")
    if not _PHONE_RE.search(contact):
        add("warn", "No phone number in the contact line.")

    # Sections an ATS can map.
    headings = [section["title"] for section in resume["sections"]]
    for heading in headings:
        if heading.lower().strip() not in STANDARD_HEADINGS:
            add("warn", f"Non-standard heading “{heading}”; an ATS may not map it. Use a standard name.")
    for need, names in (("Education", ("education",)), ("Skills", ("skills", "technical skills"))):
        if not any(heading.lower() in names for heading in headings):
            add("error", f"Missing a {need} section.")
    if not any(re.search(r"experience|projects", heading, re.I) for heading in headings):
        add("error", "Missing an Experience or Projects section.")

    # Formatting an ATS reads badly, and first person.
    if re.search(r"^\s*\|.*\|\s*$", text, re.M) or "<table" in text.lower():
        add("error", "Contains a table, which ATS parsers often scramble.")
    if _EMOJI_RE.search(text):
        add("warn", "Contains emoji or symbols that ATS may drop.")
    if _FIRST_PERSON_RE.search(re.sub(r"\[.*?\]\(.*?\)", "", text)):  # link text and addresses don't count
        add("warn", "Uses first person (I / my). Resume bullets should drop pronouns.")

    # Bullets.
    bullets = [line for section in resume["sections"] for entry in section["entries"] for kind, line in entry if kind == "bullet"]
    too_long = [b for b in bullets if len(re.sub(r"\*|\[|\]\(.*?\)", "", b)) > MAX_BULLET_CHARS]  # measured without markup
    if too_long:
        add("warn", f"{len(too_long)} bullet(s) run past two lines: “{too_long[0][:70]}…”")
    weak = [b for b in bullets if _WEAK_START_RE.match(b.strip())]
    if weak:
        add("warn", f"{len(weak)} bullet(s) start weak (“{weak[0][:40]}…”). Lead with an action verb and a result.")

    # Consistency and honesty.
    federal = archetype == "federal_usajobs"
    if _MONTH_DATE_RE.search(text) and _NUMERIC_DATE_RE.search(text) and not federal:
        add("warn", "Mixes date formats (May 2027 and 05/2027). Pick one.")
    if gpa and not federal and _gpa_below_3(gpa) and re.search(r"\bGPA\b", text):
        add("warn", "Shows a GPA below 3.0. Leave it off unless the posting requires it.")
    coursework = " ".join(line for section in resume["sections"] for entry in section["entries"] for _, line in entry
                          if re.search(r"coursework", line, re.I))
    if re.search(r"\((planned|future|upcoming)[^)]*\)", coursework, re.I):
        add("error", "Lists planned (future) coursework. Only completed or in-progress courses belong on a resume.")

    # Skills against the inventory: a skill counts as verified only when the profile has it.
    skills = _listed_skills(resume)
    unverified = []
    if inventory:
        unverified = [s for s in skills if not _in_inventory(s, [item["skill"] for item in inventory])]
        if unverified:
            add("error", f"Skills not found in your skills inventory (unverified): {', '.join(unverified[:8])}")
        listed_only = {_norm(item["skill"]) for item in inventory if item.get("level") == "listed"}  # no project evidence
        weakly_backed = [s for s in skills if _norm(s) in listed_only]
        if len(weakly_backed) > 4:
            add("warn", f"{len(weakly_backed)} skills you've only listed (no project evidence): {', '.join(weakly_backed[:6])}. "
                        "Keep only ones the posting asks for.")

    # The posting's keywords, and padding.
    keyword_share, _, missing = coverage(keywords or [], text)
    if keywords and keyword_share < 0.5:
        add("warn", f"Only {int(keyword_share * 100)}% of the posting's keywords appear. Add true ones: {', '.join(missing[:6])}")
    if len(skills) > MAX_SKILLS:
        add("warn", f"{len(skills)} skills listed. Over 30 looks like padding; trim to the most relevant.")

    score = 100 - sum(14 if issue["level"] == "error" else 5 for issue in issues)
    score = max(0, min(100, score + (5 if keyword_share >= 0.75 else 0)))
    return {"score": score, "issues": issues, "coverage": keyword_share, "unverified_skills": unverified, "pages": pages,
            "max_pages": max_pages}
