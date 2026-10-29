"""Deterministic resume checks: ATS-safety, one-page/length, truthfulness of the Skills section against the skills inventory,
consistency and style. Produces a 0-100 score plus issues the AI critic is asked to fix (and that the editor shows)."""
import re

from .render import parse_resume
from .textutil import coverage

STANDARD_HEADINGS = {
    "summary", "professional summary", "education", "experience", "work experience", "professional experience",
    "technical experience", "relevant experience", "projects", "technical projects", "research & technical projects",
    "research and technical projects", "research experience", "skills", "technical skills", "certifications",
    "certifications & training", "licenses & certifications", "relevant coursework", "coursework", "leadership",
    "leadership & activities", "activities", "extracurricular and volunteer work", "volunteer work", "volunteer experience",
    "awards", "honors & awards", "awards & honors", "publications", "clearance", "additional information",
}
_norm = lambda x: re.sub(r"[^a-z0-9+#]+", " ", x.lower()).strip()  # noqa: E731


def _skills_items(doc: dict) -> list[str]:
    out = []
    for s in doc["sections"]:
        if "skill" not in s["title"].lower():
            continue
        for e in s["entries"]:
            for _, text in e:
                body = re.sub(r"^\*\*[^*]+\*\*:?\s*", "", text)
                out += [x.strip(" .") for x in re.split(r",|;|\u00b7", re.sub(r"\*\*", "", body)) if x.strip(" .")]
    return out


def _in_inventory(item: str, inv_names: list[str]) -> bool:
    n = _norm(re.sub(r"\(.*?\)", "", item))
    if not n:
        return True
    for name in inv_names:
        parts = [_norm(p) for p in re.split(r"/|\(|\)|,| and ", name) if _norm(p)]
        if n == _norm(name) or n in parts or any(n == p or (len(n) > 3 and (n in p or p in n)) for p in parts):
            return True
    return False


def check(md: str, *, inventory: list[dict] | None = None, keywords: list[str] | None = None, pages: int | None = None,
          max_pages: int = 1, archetype: str = "", gpa: str = "") -> dict:
    doc = parse_resume(md or "")
    issues: list[dict] = []

    def add(level, text):
        issues.append({"level": level, "text": text})

    text = md or ""
    if pages and pages > max_pages:
        add("error", f"Runs to {pages} pages; the limit is {max_pages}. Cut the weakest lines.")
    if not doc["name"]:
        add("error", "Missing the name heading (# Name).")
    contact = " ".join(doc["contact"])
    if not re.search(r"@", contact):
        add("error", "No email in the contact line.")
    if not re.search(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", contact):
        add("warn", "No phone number in the contact line.")
    heads = [s["title"] for s in doc["sections"]]
    for h in heads:
        if h.lower().strip() not in STANDARD_HEADINGS:
            add("warn", f"Non-standard heading “{h}”; an ATS may not map it. Use a standard name.")
    for need, alts in (("Education", ("education",)), ("Skills", ("skills", "technical skills"))):
        if not any(h.lower() in alts for h in heads):
            add("error", f"Missing a {need} section.")
    if not any(re.search(r"experience|projects", h, re.I) for h in heads):
        add("error", "Missing an Experience or Projects section.")
    if re.search(r"^\s*\|.*\|\s*$", text, re.M) or "<table" in text.lower():
        add("error", "Contains a table, which ATS parsers often scramble.")
    if re.search(r"[\U0001F300-\U0001FAFF☀-➿]", text):
        add("warn", "Contains emoji or symbols that ATS may drop.")
    if re.search(r"(?<![A-Za-z])(I|me|my|I'm|I've)(?![A-Za-z])", re.sub(r"\[.*?\]\(.*?\)", "", text)):
        add("warn", "Uses first person (I / my). Resume bullets should drop pronouns.")
    bullets = [t for s in doc["sections"] for e in s["entries"] for k, t in e if k == "bullet"]
    long_b = [b for b in bullets if len(re.sub(r"\*|\[|\]\(.*?\)", "", b)) > 215]
    if long_b:
        add("warn", f"{len(long_b)} bullet(s) run past two lines: “{long_b[0][:70]}…”")
    weak = [b for b in bullets if re.match(r"(responsible for|worked on|helped|assisted|duties)", b.strip(), re.I)]
    if weak:
        add("warn", f"{len(weak)} bullet(s) start weak (“{weak[0][:40]}…”). Lead with an action verb and a result.")
    fmts = {"mon": bool(re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{4}", text)),
            "num": bool(re.search(r"\b(0[1-9]|1[0-2])/\d{4}\b", text))}
    if fmts["mon"] and fmts["num"] and archetype != "federal_usajobs":
        add("warn", "Mixes date formats (May 2027 and 05/2027). Pick one.")
    if gpa and archetype != "federal_usajobs":
        try:
            if float(re.findall(r"\d\.\d+", gpa)[0]) < 3.0 and re.search(r"\bGPA\b", text):
                add("warn", "Shows a GPA below 3.0. Leave it off unless the posting requires it.")
        except (IndexError, ValueError):
            pass
    cw = " ".join(t for s in doc["sections"] for e in s["entries"] for _, t in e if re.search(r"coursework", t, re.I))
    if re.search(r"\((planned|future|upcoming)[^)]*\)", cw, re.I):
        add("error", "Lists planned (future) coursework. Only completed or in-progress courses belong on a resume.")
    unverified = []
    if inventory:
        names = [x["skill"] for x in inventory]
        unverified = [s for s in _skills_items(doc) if not _in_inventory(s, names)]
        if unverified:
            add("error", f"Skills not found in your skills inventory (unverified): {', '.join(unverified[:8])}")
        listed_only = {_norm(x["skill"]) for x in inventory if x.get("level") == "listed"}
        lo = [s for s in _skills_items(doc) if _norm(s) in listed_only]
        if len(lo) > 4:
            add("warn", f"{len(lo)} skills you've only listed (no project evidence): {', '.join(lo[:6])}. Keep only ones the posting asks for.")
    cov, hit, miss = coverage(keywords or [], text)
    if keywords and cov < 0.5:
        add("warn", f"Only {int(cov * 100)}% of the posting's keywords appear. Add true ones: {', '.join(miss[:6])}")
    n_skills = len(_skills_items(doc))
    if n_skills > 32:
        add("warn", f"{n_skills} skills listed. Over 30 looks like padding; trim to the most relevant.")
    score = 100 - sum(14 if i["level"] == "error" else 5 for i in issues)
    score = max(0, min(100, score + (5 if cov >= 0.75 else 0)))
    return {"score": score, "issues": issues, "coverage": cov, "unverified_skills": unverified, "pages": pages, "max_pages": max_pages}
