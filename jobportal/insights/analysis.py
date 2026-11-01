"""The Analysis page: which roles fit the user, where the jobs are, and what to work on next.

The radar chart compares the user across a handful of job titles, its role axes. They aren't fixed: pick_roles() chooses 3
to 8 of them from what JobPortal has learned about this person, so a nurse sees nursing titles and a carpenter sees trades
titles, and the chart changes as their profile, documents, answers and leads change. A title can come from these places,
in priority order (a role keeps the tag of the first place that names it, so the page can say where it came from):
  target      the job titles in their standard answers
  added       titles they typed in the page's "Add a role" box (settings analysis.pinned_roles): these always show
  plan        the profile's search plan, which the profile build writes from the resume, documents and answers: its role
              families, then its search queries
  experience  the job titles of their most recent jobs in the profile's record (project_bank)
  suggested   other roles the last AI assessment said they could realistically go for
  market      the titles that come up most in their own qualified leads and search results
Titles are compared by role_key(), so "RN", "Registered Nurse" and "registered nurses" are one role. A title from anywhere
but the user's own words that's a less specific form of a role already found ("Nursing" after "Registered Nurse") folds
into it. Removing a role on the page hides it for good (settings analysis.hidden_roles), whichever place names it later.

It works in two layers:
1. market() is plain counting over the user's own search data, with no AI call. Per role: demand (the postings that passed
   the rule filters, saved as leads or waiting in the triage backlog, whose titles match the role), how many of its leads
   qualified and their average score, and the skills the tailored resumes for its leads couldn't show. Across every lead:
   skill gaps and strengths (each application package records its keyword coverage), the funnel from postings scanned to
   offers, and which sources and industries produce qualified leads.
2. run_ai() sends the roles, those numbers and the full profile to the AI. It scores fit and interest (0 to 100) for every
   role, suggests 2 to 4 more roles the person could go for (they become role candidates from then on), and suggests
   concrete moves: projects, certifications, things to add to the profile, and search changes. The result is stored as
   "analysis.latest", and a short history of scores by role id ("analysis.history") lets the page show how fit changed.

An "analysis.latest" saved before roles existed scored work genres instead. It reads as not analyzed yet, and the page says
why. The genres themselves stay in settings for triage and the search (core/genres.py, search/plan.py); they just aren't
the chart's axes anymore.

The profile runs run_ai() after every build or update (unless settings profile.auto_analyze is off), and the page has a Run
button. Nothing here changes the profile. Called by web/routes/insights.py for web/static/js/pages/analysis.js."""
import asyncio
import json
import re
import sqlite3
from collections import Counter, defaultdict
from functools import lru_cache
from statistics import mean

from jobportal.ai import client as ai, prompts
from jobportal.candidate import profile as profile_mod
from jobportal.core import bus, db, settings as settings_mod

# The stemmer and word lists TargetMatcher compares job titles with. Reused so a role and the search's target-role check
# read titles the same way.
from jobportal.core.textutil import _GENERIC_ROLE_WORDS, _TARGET_FILLER, NAME_TO_ABBR, STATES, TargetMatcher, _role_stem
from jobportal.search import plan

# Lead stages that mean triage said yes: qualified, and every stage after it (packaging, ready, a failed package, a closed posting).
QUALIFIED = ("qualified", "packaging", "ready", "closed", "error")
# How many roles the chart shows. Fewer than 3 axes isn't a radar, so the page asks for more titles instead, and more than 8
# labels crowd the rim.
ROLES_MIN, ROLES_MAX = 3, 8
# Seats kept for roles beyond the ones the user named, so a long list of target roles can't crowd out what their work
# history, the AI and their own leads point to.
OTHER_SEATS = 2
SOURCES = ("target", "added", "plan", "experience", "suggested", "market")  # in priority order (see the module docstring)
OWN_SOURCES = ("target", "added")  # the user's own words: shown as typed, and never folded into another role
SUGGESTIONS_MAX = 4  # the AI suggests 2 to 4 roles
EXPERIENCE_MAX = 2  # the latest jobs in the record: older ones say less about where the user is headed
MARKET_MAX = 6  # the most titles the user's own search offers as roles
TITLE_MAX = 80  # the longest title a role keeps
_lock = asyncio.Lock()  # one AI assessment at a time


def _avg(scores: list[int]) -> int | None:
    """The rounded average score, or None when there are no scores."""
    return round(mean(scores)) if scores else None


# ---------------------------------------------------------------- job titles: keys, ids and labels

# Abbreviations that stand for a whole job title. They're spelled out before titles are compared, so "RN" and "Registered
# Nurse" are one role, and a found title that's nothing but one shows spelled out. Only abbreviations that mean the same in
# any posting are here: "PA" (a physician assistant, or Pennsylvania) and "PT" (a physical therapist, or part time) aren't.
ABBREVIATIONS = {
    "rn": "registered nurse", "lpn": "licensed practical nurse", "lvn": "licensed vocational nurse",
    "cna": "certified nursing assistant", "np": "nurse practitioner", "crna": "certified registered nurse anesthetist",
    "emt": "emergency medical technician", "pct": "patient care technician", "cma": "certified medical assistant",
    "hha": "home health aide", "dsp": "direct support professional", "lcsw": "licensed clinical social worker",
    "bcba": "board certified behavior analyst", "rbt": "registered behavior technician", "slp": "speech language pathologist",
    "rdh": "registered dental hygienist", "cpa": "certified public accountant", "swe": "software engineer",
    "sde": "software development engineer", "sre": "site reliability engineer", "csr": "customer service representative",
    "hr": "human resources", "qa": "quality assurance",
}
# Other forms of a role word that the stemmer (textutil._role_stem) doesn't join by itself, so "Software Engineering" is
# Software Engineer and "Project Management" is Project Manager. It already joins most pairs (nurse and nursing, teacher and
# teaching, accountant and accounting). Short forms are spelled out too ("Pharmacy Tech", "Admin Assistant").
WORD_FORMS = {
    "engineering": "engineer", "management": "manager", "administration": "administrator", "administrative": "administrator",
    "admin": "administrator", "analysis": "analyst", "analytics": "analyst", "carpentry": "carpenter", "architecture": "architect",
    "tech": "technician", "techs": "technicians", "mgr": "manager", "asst": "assistant", "rep": "representative",
    "reps": "representatives", "coord": "coordinator", "dev": "developer",
}
# Words that only say "a person who does this", so "IT Support Specialist" and "IT Support" are one role. A title with
# nothing else keeps them.
_EMPTY_WORDS = {"specialist", "specialists", "professional", "professionals", "personnel", "employee", "employees"}
_WORD = re.compile(r"[a-z0-9+#]+")

# Levels, schedules and job types at either end of a found title. They say how a job is offered, not what the role is, so
# "New Grad RN" shows as Registered Nurse and "Senior Software Engineer II" as Software Engineer. Only the ends are trimmed:
# inside a title such words can matter ("Day Care Teacher").
_EDGE = (r"new grad(?:uate)?s?|recent grad(?:uate)?s?|entry[ -]level|mid[ -]level|early[ -]career|part[ -]time|full[ -]time|"
         r"per diem|on[ -]?site|senior|sr|junior|jr|intern(?:ship)?s?|apprentice(?:ship)?s?|i{1,3}|iv|[1-4]|experienced|"
         r"remote|hybrid|temporary|temp|seasonal|prn|jobs?|positions?|roles?|openings?|opportunit(?:y|ies)")
_LEADING = re.compile(rf"^(?:{_EDGE})\b\.?[\s,/-]*", re.I)
_TRAILING = re.compile(rf"[\s,/-]*\b(?:{_EDGE})\.?$", re.I)
# Where the role part of a found title ends: "Registered Nurse, Med-Surg", "RN - Night Shift", "Line Cook | Full Time". A
# hyphen inside a word ("Med-Surg") isn't a break.
_CUT = re.compile(r"\s+[-\u2013\u2014]+\s+|\s*[,|:;\u2022\u2013\u2014]\s*")
# Short words job titles write in capitals, for titles typed all in lowercase.
_ACRONYMS = {"rn", "lpn", "lvn", "cna", "np", "emt", "ems", "icu", "nicu", "picu", "pacu", "er", "it", "hr", "qa", "ui", "ux",
             "hvac", "cdl", "cnc", "esl", "ehr", "ai", "ml", "sql", "seo", "gis", "cad", "ceo", "cfo", "coo", "cto", "vp", "dsp",
             "hha", "pct", "cma", "bcba", "rbt", "slp", "lcsw", "cpa", "swe", "sde", "sre", "csr", "ar", "ap"}
# Small words that stay lowercase inside a title ("Director of Nursing").
_SMALL = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}


@lru_cache(maxsize=8192)  # postings repeat the same titles, and every page load reads them all
def _words(title: str) -> tuple[str, ...]:
    """The words of a title for comparing: lowercase, without dots ("R.N." is RN), with other word forms joined
    (WORD_FORMS) and abbreviations spelled out (ABBREVIATIONS)."""
    out: list[str] = []
    for word in _WORD.findall(title.lower().replace(".", "")):
        word = WORD_FORMS.get(word, word)
        out += ABBREVIATIONS.get(word, word).split()
    return tuple(out)


def role_key(title: str) -> frozenset:
    """What makes two titles the same role: the stems of their words (textutil._role_stem), without levels, job types and
    other filler (the words TargetMatcher skips) and without words that only say "a person who does this" (_EMPTY_WORDS).
    "RN", "Registered Nurse", "registered nurses" and "New Grad RN" all give {"register", "nurs"}. Word order doesn't
    matter. Empty when nothing in the title names a role ("Intern", "Full time")."""
    words = [w for w in _words(str(title or "")) if w not in _TARGET_FILLER]
    words = [w for w in words if w not in _EMPTY_WORDS] or words
    return frozenset(_role_stem(w) for w in words)


def role_id(title: str) -> str:
    """A readable, stable id for a role: its words joined by hyphens, with abbreviations spelled out and levels and filler
    left out, so "RN", "Registered Nurse" and "New Grad RN" are all "registered-nurse". The AI's scores, the fit history and
    the page's remove buttons use it. "+" and "#" are spelled out, so "C++ Developer" and "C# Developer" stay apart, and a
    word is used once ("Registered Nurse (RN)" is "registered-nurse" too)."""
    words = (re.sub(r"[^a-z0-9]", "", w.replace("+", "plus").replace("#", "sharp")) for w in _words(str(title or "")) if w not in _TARGET_FILLER)
    return "-".join(dict.fromkeys(w for w in words if w))[:TITLE_MAX].strip("-")


def _keystr(key: frozenset) -> str:
    """A role key as text, so it can be stored in JSON."""
    return " ".join(sorted(key))


@lru_cache(maxsize=8192)
def _title_stems(title: str) -> frozenset:
    """Every word stem of a posting's title. The posting counts for a role when the role's key is a subset of these: every
    word that names the role is in the title ("Registered Nurse, Med-Surg" and "RN - ICU" count for Registered Nurse, and
    "Charge Nurse" doesn't)."""
    return frozenset(_role_stem(w) for w in _words(title))


def _title_case(text: str) -> str:
    """A title written the way job titles are, so every label on the chart reads alike: "it support specialist" is "IT
    Support Specialist", "Hospice nursing" is "Hospice Nursing" and "director of nursing" is "Director of Nursing". A word
    with a capital letter in it is the writer's choice and stays ("iOS", "McDonald's")."""
    out, first = [], True
    for part in re.split(r"([\s/-]+)", text):  # the words, and the spaces, slashes and hyphens between them
        if part and not re.fullmatch(r"[\s/-]+", part):
            core = re.sub(r"^\W+|\W+$", "", part)  # without brackets or punctuation around it
            if part == part.lower() and core:
                if core in _ACRONYMS:
                    part = part.replace(core, core.upper())
                elif first or core not in _SMALL:
                    part = re.sub(r"[a-z]", lambda m: m.group().upper(), part, count=1)
            first = False
        out.append(part)
    return "".join(out)


@lru_cache(maxsize=8192)
def clean_title(text: str, own: bool = False) -> str:
    """A job title ready for the chart, or "" when nothing is left of it.

    The user's own titles (own=True: target roles and roles they added) are only tidied: Markdown dropped, spaces collapsed,
    and lowercase words capitalized (_title_case: "registered nurse" is "Registered Nurse"). A title found anywhere else (the
    search plan, the work history, the AI, a posting) is also cut down to the role: anything in parentheses and anything
    after a comma or a spaced dash goes ("Registered Nurse (RN), Med-Surg" is "Registered Nurse"), so do levels and job
    types at either end ("Senior Software Engineer II" is "Software Engineer"), and a lone abbreviation is spelled out ("RN"
    is "Registered Nurse")."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # a Markdown link keeps its text
    text = " ".join(re.sub(r"[*_`]+", "", text).split())
    if not own:
        text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)
        text = next((part.strip() for part in _CUT.split(text) if re.search(r"[A-Za-z]", part)), "")
        for _ in range(4):  # one level word or phrase off each end per pass: "Senior Software Engineer II"
            trimmed = _TRAILING.sub("", _LEADING.sub("", text)).strip(" -,/.")
            if trimmed == text:
                break
            text = trimmed
        text = ABBREVIATIONS.get(text.lower().replace(".", ""), text)
    return _title_case(" ".join(text.split()).strip(" -,/:;."))[:TITLE_MAX].strip()


# ---------------------------------------------------------------- job titles in the work history

# The record's "## " sections that list jobs. A "### " heading anywhere else is a degree, a project, a license, an award or
# a club office, not a job title.
_WORK_SECTION = re.compile(r"experience|employment|work|career|military|professional", re.I)
_OTHER_SECTION = re.compile(r"education|project|licen|certif|award|honor|skill|course|publication|training|volunteer|leadership|"
                            r"activit", re.I)
# Where one part of a record heading ends. A heading holds the employer, the title, the place and the dates in any order:
# "Example General Hospital - Registered Nurse", "Registered Nurse, Example General Hospital (2023 to present)",
# "Line Cook | Example Bistro | Columbus, OH".
_HEADING_PARTS = re.compile(r"\s+[-\u2013\u2014]+\s+|\s*[|,;:()\[\]\u2022\u2013\u2014]\s*|\s+(?:at|@)\s+", re.I)
# Last words of an employer's name: "Example General Hospital", "Example City Schools", "Example Builders LLC".
_ORG_WORDS = {
    "inc", "llc", "llp", "ltd", "corp", "corporation", "company", "co", "group", "hospital", "hospitals", "clinic", "clinics",
    "center", "centers", "university", "college", "school", "schools", "academy", "institute", "foundation", "district",
    "department", "agency", "bank", "church", "store", "stores", "restaurant", "bistro", "cafe", "bar", "grill", "hotel",
    "resort", "market", "lab", "labs", "studio", "studios", "systems", "services", "solutions", "partners", "associates",
    "network", "council", "society", "office", "union", "county", "city", "state", "government", "army", "navy", "corps",
    "health", "healthcare", "care", "staffing", "logistics", "construction", "builders", "contractors", "industries",
    "technologies", "media", "press", "museum", "library", "farm", "farms", "ranch", "shop", "salon", "spa", "gym",
}
# Job words that don't end like one. Words ending in -er, -or, -ist, -ian, -ant, -ent or -eer ("Teacher", "Counselor",
# "Therapist", "Technician", "Engineer") are spotted by their ending, and textutil's generic role words (manager,
# assistant, clerk, aide, ...) count too.
_ROLE_NOUNS = {
    "nurse", "cook", "chef", "barista", "mechanic", "paralegal", "attorney", "secretary", "salesperson", "coach", "tutor",
    "principal", "dean", "nanny", "midwife", "paramedic", "emt", "analyst", "intern", "handyman", "foreman", "guard",
    "lifeguard", "chaplain", "deputy", "pilot", "cashier", "host", "hostess", "teller", "doctor", "surgeon", "dentist",
    "therapist", "pharmacist", "physician", "hygienist", "technologist", "scientist", "artist", "electrician", "librarian",
    "custodian", "janitor", "caregiver", "server", "bartender", "busser", "dishwasher", "housekeeper", "cleaner", "driver",
    "courier", "laborer", "welder", "plumber", "carpenter", "machinist", "painter", "roofer", "installer", "inspector",
    "estimator", "drafter", "architect", "engineer", "developer", "programmer", "designer", "writer", "editor", "reporter",
    "journalist", "photographer", "producer", "teacher", "instructor", "professor", "lecturer", "counselor", "recruiter",
    "receptionist", "bookkeeper", "accountant", "auditor", "baker", "butcher", "farmer", "groundskeeper", "landscaper",
    "firefighter", "sergeant", "volunteer", "scribe", "phlebotomist", "sonographer", "dietitian", "nutritionist", "optician",
    "paraprofessional", "paraeducator", "veterinarian", "rn", "lpn", "lvn", "cna", "np",
}
_ROLE_ENDING = re.compile(r"(?:er|or|ist|ian|ant|ent|eer)$")
# A firm named for its partners ("Smith & Baker", "Lee, Cook & Porter"), whose last name can look like a job.
_FIRM = re.compile(r"^[A-Z][\w'.-]*(?:,? [A-Z][\w'.-]*)* & [A-Z][\w'.-]*$")


def _is_place(part: str) -> bool:
    """True for a heading part that only says where or when: a state ("OH", "Ohio"), Remote, Present."""
    low = part.lower()
    return part.upper() in STATES or low in NAME_TO_ABBR or low in {"remote", "hybrid", "present", "current", "now"}


def _title_score(part: str) -> int:
    """How much one part of a record heading looks like a job title: 3 when it ends in a job word ("Registered Nurse",
    "Student Technician"), 2 when a job word is inside it ("Nurse Residency"), 1 when its last word only ends like one
    ("Brewer"), and 0 for anything else: dates, places and employers ("Example General Hospital", "Smith & Baker")."""
    words = re.findall(r"[a-z]+", part.lower())
    if not words or len(part) > 60 or re.search(r"\d", part) or _is_place(part) or words[-1] in _ORG_WORDS or _FIRM.match(part):
        return 0
    if words[-1] in _ROLE_NOUNS or words[-1] in _GENERIC_ROLE_WORDS:
        return 3
    if any(w in _ROLE_NOUNS for w in words):
        return 2
    return 1 if _ROLE_ENDING.search(words[-1]) else 0


def _heading_title(heading: str) -> str:
    """The job title in one "### " heading of the record: the part that looks most like one (_title_score), the first of
    equals. "" when no part does. Dates after "||" (the resume format's right-aligned dates) are dropped first."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading).split("||")[0]
    best, best_score = "", 0
    for part in _HEADING_PARTS.split(re.sub(r"[*_`]+", "", text)):
        part = part.strip(" -.")
        score = _title_score(part)
        if score > best_score:
            best, best_score = part, score
    return best


def experience_titles(record: str) -> list[str]:
    """The job titles in the work sections of the profile's record, newest first (the record lists jobs that way), each
    role once. Facts hold no job titles (contact details, school and skills), so the record is where they are."""
    titles, keys, inside = [], set(), False
    for line in (record or "").splitlines():
        if line.startswith("## "):
            inside = bool(_WORK_SECTION.search(line)) and not _OTHER_SECTION.search(line)
        elif inside and line.startswith("### "):
            title = _heading_title(line[4:])
            key = role_key(title)
            if key and key not in keys:  # a title that's only a level ("Intern") names no role
                keys.add(key)
                titles.append(title)
    return titles


# ---------------------------------------------------------------- the user's postings

# Lead kinds that are job postings. An event (a career fair) or an intel lead (a company worth contacting) isn't demand for
# a role.
_POSTING_KINDS = ("posting", "program")


def _leads() -> list[dict]:
    """Every saved lead, with the columns the page counts."""
    return db.q("SELECT id, title, kind, score, stage, app_status, source, package, applied_at, industry, "
                "resume_md IS NOT NULL AS has_resume FROM leads")


def _backlog() -> list[tuple[str, str]]:
    """(title, kind) of every posting in the triage backlog (the candidates table). SQLite reads just those two fields out
    of each saved job, so thousands of long descriptions are never loaded. A SQLite build without JSON support reads the
    whole job instead."""
    try:
        rows = db.q("SELECT json_extract(data, '$.title') AS title, json_extract(data, '$.kind') AS kind FROM candidates")
        return [(str(row["title"] or ""), str(row["kind"] or "")) for row in rows]
    except sqlite3.OperationalError:  # no JSON support in this SQLite, or a damaged row: read each job here instead
        out = []
        for row in db.q("SELECT data FROM candidates"):
            try:
                job = json.loads(row["data"] or "{}")
            except ValueError:
                continue
            out.append((str(job.get("title") or ""), str(job.get("kind") or "")))
        return out


def _postings(leads: list[dict]) -> list[dict]:
    """Every job posting the user's searches turned up that passed the rule filters: the saved leads (all of them, scored
    high or low, since both are jobs out there) and the backlog still waiting for AI triage. Each is {title, stems, lead_id
    (None in the backlog), qualified, score, trashed}."""
    out = [{"title": str(lead["title"] or ""), "lead_id": lead["id"], "qualified": lead["stage"] in QUALIFIED, "score": lead["score"],
            "trashed": lead["app_status"] == "trashed"} for lead in leads if (lead["kind"] or "posting") in _POSTING_KINDS]
    out += [{"title": title, "lead_id": None, "qualified": False, "score": None, "trashed": False}
            for title, kind in _backlog() if (kind or "posting") in _POSTING_KINDS]
    for posting in out:
        posting["stems"] = _title_stems(posting["title"])
    return out


def _market_titles(postings: list[dict], near: TargetMatcher, known: list[frozenset]) -> list[str]:
    """The titles that come up most in the user's own search, as role candidates: postings grouped by role, the ones with
    the most qualified leads first, then the most postings, then the best score. A title needs a qualified lead, or three
    postings near the user's targets (textutil.TargetMatcher, the search's own target check), so a stray posting never
    becomes a role. Leads the user deleted don't count.

    known: the keys of the candidates found before (targets, plan, ...). A title that's one of those roles still comes back
    (it tags that role as one the leads show too), but only new roles count toward MARKET_MAX."""
    found: dict[frozenset, dict] = {}
    for posting in postings:
        if posting["trashed"]:
            continue
        label = clean_title(posting["title"])
        key = role_key(label)
        if not key:
            continue
        entry = found.setdefault(key, {"label": label, "qualified": 0, "seen": 0, "best": 0, "near": False})
        entry["seen"] += 1
        if posting["qualified"]:
            entry["qualified"] += 1
            entry["best"] = max(entry["best"], posting["score"] or 0)
        entry["near"] = entry["near"] or near.matches(posting["title"])
    ranked = sorted(((key, e) for key, e in found.items() if e["qualified"] or (e["seen"] >= 3 and e["near"])),
                    key=lambda item: (-item[1]["qualified"], -item[1]["seen"], -item[1]["best"]))
    titles, new = [], 0
    for key, entry in ranked:
        repeats = any(key <= k for k in known)  # the same role, or a less specific form of one (see _group)
        if not repeats and new == MARKET_MAX:
            continue
        new += not repeats
        titles.append(entry["label"])
    return titles


# ---------------------------------------------------------------- picking the roles

def _setting(cfg: dict, name: str) -> list[str]:
    """One of the role lists in settings (analysis.pinned_roles or analysis.hidden_roles), as clean titles."""
    return [str(x).strip() for x in (cfg.get("analysis") or {}).get(name) or [] if str(x).strip()]


def _is_roles(latest) -> bool:
    """True when a stored assessment scored roles. One saved before roles existed scored work genres instead."""
    return isinstance(latest, dict) and latest.get("axes") == "roles"


def _latest_suggestions() -> list[dict]:
    """The roles the last AI assessment suggested: [] before the first one, or when the last one is from before roles."""
    latest = db.kv_get("analysis.latest")
    if not _is_roles(latest):
        return []
    return [s for s in (latest.get("result") or {}).get("suggested_roles") or [] if isinstance(s, dict)]


def _candidates(cfg: dict, postings: list[dict]) -> list[tuple[str, str]]:
    """Every title that could be a role, as (title, source), in priority order (SOURCES)."""
    search_plan = profile_mod.get("search_plan") or {}
    # Words of the user's search area, which a plan query sometimes names ("registered nurse columbus").
    places = {w for place in cfg["locations"].get("allowed") or [] for w in _WORD.findall(str(place).lower())}
    queries = [" ".join(w for w in str(q).split() if w.lower().strip(",.") not in places) for q in search_plan.get("queries") or []]
    found = [(clean_title(str(t), own=True), "target") for t in plan.target_roles()]
    found += [(clean_title(t, own=True), "added") for t in _setting(cfg, "pinned_roles")]
    found += [(clean_title(str(t)), "plan") for t in list(search_plan.get("role_families") or []) + queries]
    found += [(clean_title(t), "experience") for t in experience_titles(profile_mod.get("project_bank"))[:EXPERIENCE_MAX]]
    found += [(clean_title(str(s.get("title") or "")), "suggested") for s in _latest_suggestions()]
    near = TargetMatcher(plan.target_phrases(cfg), cfg["locations"].get("allowed"))
    known = [role_key(title) for title, _ in found if title]
    found += [(title, "market") for title in _market_titles(postings, near, known)]
    return [(title, source) for title, source in found if title]


def _group(candidates: list[tuple[str, str]]) -> list[dict]:
    """The candidates as roles, one per role_key(). A title with the same key joins the role already there and adds its
    source. A title from anywhere but the user's own words that's a less specific form of a role already there (its key is
    a subset: "Nursing" after "Registered Nurse") folds into that role too, so the chart doesn't show both. The user's own
    titles only ever join an exact match: they asked for that title. The first title names the role and gives it its id and
    its source."""
    roles: list[dict] = []
    for title, source in candidates:
        key = role_key(title)
        if not key:
            continue
        same = next((r for r in roles if r["key"] == key), None)
        if same is None and source not in OWN_SOURCES:
            same = next((r for r in roles if key < r["key"]), None)
        if same is None:
            roles.append({"id": role_id(title), "label": title, "key": key, "source": source, "sources": [source]})
        elif source not in same["sources"]:
            same["sources"].append(source)
    return roles


def _role_groups(cfg: dict, postings: list[dict]) -> list[dict]:
    """Every role candidate (see _group), each marked pinned (the user added it) or hidden (the user removed it). A removed
    role stays hidden whichever place names it later, since it's matched by role_key()."""
    hidden = {role_key(t) for t in _setting(cfg, "hidden_roles")}
    roles = _group(_candidates(cfg, postings))
    for role in roles:
        role["pinned"] = "added" in role["sources"]
        role["hidden"] = not role["pinned"] and role["key"] in hidden
    return roles


def pick_roles(cfg: dict | None = None, postings: list[dict] | None = None) -> dict:
    """The job titles the chart shows, picked from the user's own data. Returns {"roles": the picked roles in chart order
    (by source, then priority), "removed": the roles the user removed that are still candidates ({id, label, source}, so the
    page can bring them back), "more": the titles of the candidates that didn't fit}. Each role is {id, label, key, source,
    sources, pinned, hidden}.

    Up to ROLES_MAX are picked:
    1. every role the user added;
    2. their target roles, leaving OTHER_SEATS for the other sources;
    3. one role from each other source in turn (search plan, work history, AI suggestions, their leads) until the chart is
       full;
    4. the rest of the target roles, while there's room.
    So the chart shows what the user asked for first, and always something of what their history, the AI and the market
    point to. Fewer than ROLES_MIN means there isn't enough to go on yet, and the page asks for more titles."""
    cfg = cfg or settings_mod.get()
    roles = _role_groups(cfg, _postings(_leads()) if postings is None else postings)
    shown = [r for r in roles if not r["hidden"]]
    picked = [r for r in shown if r["pinned"]][:ROLES_MAX]
    targets = [r for r in shown if r["source"] == "target" and r not in picked]
    for role in targets:
        if len(picked) >= ROLES_MAX - OTHER_SEATS:
            break
        picked.append(role)
    queues = [[r for r in shown if r["source"] == source and r not in picked] for source in SOURCES[2:]]
    while len(picked) < ROLES_MAX and any(queues):
        for queue in queues:
            if queue and len(picked) < ROLES_MAX:
                picked.append(queue.pop(0))
    picked += [r for r in targets if r not in picked][:ROLES_MAX - len(picked)]
    picked.sort(key=lambda r: (SOURCES.index(r["source"]), roles.index(r)))
    return {"roles": picked, "removed": [{"id": r["id"], "label": r["label"], "source": r["source"]} for r in roles if r["hidden"]],
            "more": [r["label"] for r in shown if r not in picked][:12]}


# ---------------------------------------------------------------- the market numbers

def _skill_coverage(leads: list[dict], roles_of: dict[int, list[str]]) -> dict:
    """The keywords postings asked for, split by whether the tailored resume could show them. Every package records
    {"hit": [...], "miss": [...]} as its coverage. Leads the user deleted don't count.

    Returns gaps (the most often missed keywords), strengths (often requested and never missed), packaged (how many leads
    the numbers come from) and missed_by_role (a Counter of missed keywords per role id)."""
    requested, missed, label, missed_by_role, packaged = Counter(), Counter(), {}, defaultdict(Counter), 0
    for lead in leads:
        if lead["app_status"] == "trashed":
            continue
        coverage = json.loads(lead["package"] or "{}").get("coverage") or {}
        if not coverage:
            continue
        packaged += 1
        for keyword in (coverage.get("hit") or []) + (coverage.get("miss") or []):
            key = keyword.lower().strip()
            label.setdefault(key, keyword.strip())  # the first spelling seen is the one shown
            requested[key] += 1
        for keyword in coverage.get("miss") or []:
            key = keyword.lower().strip()
            missed[key] += 1
            for role in roles_of.get(lead["id"], []):
                missed_by_role[role][label[key]] += 1
    return {"gaps": [{"skill": label[k], "missing_in": n, "requested_in": requested[k]} for k, n in missed.most_common(18)],
            "strengths": [{"skill": label[k], "requested_in": n} for k, n in requested.most_common(60) if missed[k] == 0][:14],
            "packaged": packaged, "missed_by_role": missed_by_role}


def _funnel(leads: list[dict]) -> list[dict]:
    """How many jobs reached each step, from postings scanned (across every run) to accepted offers.

    The last three steps count only applications (leads with an applied date), so every step is a part of the one before
    it. A lead the user moved straight to Rejected without applying is left out of Responses."""
    scanned = Counter()
    for run in db.q("SELECT stats FROM runs"):
        stats = json.loads(run["stats"] or "{}")
        scanned.update({k: stats.get(k, 0) for k in ("found", "candidates")})
    applied = [lead for lead in leads if lead["applied_at"] is not None]
    statuses = Counter(lead["app_status"] for lead in applied)
    return [
        {"stage": "Postings scanned", "n": scanned["found"]},
        {"stage": "Passed your filters", "n": scanned["candidates"]},
        {"stage": "AI-triaged", "n": len(leads)},
        {"stage": "Qualified", "n": sum(1 for lead in leads if lead["stage"] in QUALIFIED)},
        {"stage": "Package ready", "n": sum(1 for lead in leads if lead["has_resume"])},
        {"stage": "Applied", "n": len(applied)},
        {"stage": "Responses", "n": sum(statuses[s] for s in ("interviewing", "accepted", "rejected"))},
        {"stage": "Interviews", "n": statuses["interviewing"] + statuses["accepted"]},
        {"stage": "Accepted", "n": statuses["accepted"]},
    ]


def _quality(leads: list[dict], column: str, missing: str) -> list[dict]:
    """How many leads from each value of one column (source or industry) were triaged and qualified, and their average
    score. Rows are named by the column, missing values count as missing, and the most qualified come first."""
    groups = defaultdict(lambda: {"triaged": 0, "qualified": 0, "scores": []})
    for lead in leads:
        group = groups[lead[column] or missing]
        group["triaged"] += 1
        if lead["stage"] in QUALIFIED:
            group["qualified"] += 1
            group["scores"].append(lead["score"] or 0)
    rows = [{column: k, "triaged": g["triaged"], "qualified": g["qualified"], "avg_score": _avg(g["scores"])} for k, g in groups.items()]
    return sorted(rows, key=lambda row: -row["qualified"])


def _demand_source(in_leads: int, waiting: int) -> str:
    """Where the demand numbers come from, in words for the page and the AI."""
    if not in_leads and not waiting:
        return "no search results yet"
    parts = [f"{in_leads} lead{'s' if in_leads != 1 else ''}"] if in_leads else []
    if waiting:
        parts.append(f"{waiting} posting{'s' if waiting != 1 else ''} waiting to be scored")
    return " and ".join(parts)


def market(cfg: dict | None = None) -> dict:
    """The numbers behind the page, counted from the user's own leads, backlog and search runs (no AI call).

    "roles" holds the roles pick_roles() chose, each with its numbers: demand_count (postings whose titles match the role),
    demand_share (of every posting counted), demand_index (the busiest role shown is 100), qualified (its qualified leads),
    avg_score (their average triage score) and top_missing (the skills its tailored resumes most often couldn't show).
    "removed_roles" and "more_roles" come from pick_roles() too. The rest covers every lead: see the module docstring."""
    cfg = cfg or settings_mod.get()
    leads = _leads()
    postings = _postings(leads)
    picked = pick_roles(cfg, postings)
    matches = {role["id"]: [p for p in postings if role["key"] <= p["stems"]] for role in picked["roles"]}
    roles_of: dict[int, list[str]] = defaultdict(list)
    for rid, found in matches.items():
        for posting in found:
            if posting["lead_id"] is not None:
                roles_of[posting["lead_id"]].append(rid)
    skills = _skill_coverage(leads, roles_of)
    total = len(postings)
    busiest = max((len(found) for found in matches.values()), default=0) or 1
    rows = []
    for role in picked["roles"]:
        found = matches[role["id"]]
        scores = [p["score"] or 0 for p in found if p["qualified"]]
        rows.append({**role, "demand_count": len(found), "demand_share": round(len(found) / total, 4) if total else 0.0,
                     "demand_index": round(100 * len(found) / busiest), "qualified": len(scores), "avg_score": _avg(scores),
                     "top_missing": [k for k, _ in skills["missed_by_role"][role["id"]].most_common(5)]})
    in_leads = sum(1 for p in postings if p["lead_id"] is not None)
    return {"roles": rows, "removed_roles": picked["removed"], "more_roles": picked["more"],
            "demand_source": _demand_source(in_leads, total - in_leads), "demand_total": total,
            "industries": _quality(leads, "industry", "Other"), "gaps": skills["gaps"], "strengths": skills["strengths"],
            "packaged_leads": skills["packaged"], "funnel": _funnel(leads), "sources": _quality(leads, "source", "other")}


# ---------------------------------------------------------------- the page

def _scores(latest: dict | None) -> dict:
    """The latest assessment's scores as {fit, interest, assessment, why}, filed by role id and by "key:" plus the role key,
    so a role still finds its scores after the title that names it changes spelling. A role the AI suggested carries the
    scores it gave with the suggestion, and its reason (why)."""
    if not latest:
        return {}
    result = latest.get("result") or {}
    keys = {r.get("id"): r.get("key") for r in latest.get("roles") or [] if isinstance(r, dict)}
    found: dict[str, dict] = {}
    for item in result.get("roles") or []:
        entry = {"fit": item.get("fit"), "interest": item.get("interest"), "assessment": item, "why": ""}
        found[item.get("id")] = entry
        if keys.get(item.get("id")):
            found["key:" + keys[item["id"]]] = entry
    for item in result.get("suggested_roles") or []:
        names = (item.get("id"), "key:" + str(item.get("key") or ""))
        entry = next((found[n] for n in names if n in found), None) or {"fit": item.get("fit"), "interest": item.get("interest"),
                                                                         "assessment": None}
        entry["why"] = str(item.get("why") or "")
        for name in names:
            found.setdefault(name, entry)
    return found


def _fit_before(earlier: list[dict], rid: str, key: str) -> int | None:
    """The role's fit in the newest assessment before the latest one that scored it, matched by id or else by role key.
    None when no earlier assessment scored it, so the page shows no change."""
    for entry in reversed(earlier):
        fit = entry.get("fit") or {}
        if rid in fit:
            return fit[rid]
        old = next((i for i, k in (entry.get("keys") or {}).items() if k == key), None)
        if old in fit:
            return fit[old]
    return None


def get() -> dict:
    """Everything the Analysis page shows:
    - roles: the chart's roles, each {id, label, source, sources, pinned, the market numbers (see market()), fit, interest,
      fit_before, assessment (the AI's evidence, gaps and moves, or None), why (the AI's reason when it suggested the
      role)}. fit and interest are None until an assessment scores the role.
    - removed_roles, more_roles: roles the user removed, and titles that didn't fit on the chart.
    - unscored: ids of roles on the chart the latest assessment didn't score (they're new since), so the page can offer to
      run it again. limits: the fewest and most roles the chart shows.
    - market: the rest of the market numbers. latest: the latest assessment, or None. history: the scores of every
      assessment by role id. running: whether one is running now.
    - outdated: True when the stored assessment is from before roles existed (it scored genres). latest is None then, so
      the page reads as not analyzed yet."""
    cfg = settings_mod.get()
    numbers = market(cfg)
    stored = db.kv_get("analysis.latest")
    latest = stored if _is_roles(stored) else None
    history = [h for h in db.kv_get("analysis.history") or [] if isinstance(h, dict) and h.get("axes") == "roles"]
    # The entries before the latest assessment's own. Found by place, not by time: two runs can share a second.
    own = max((i for i, h in enumerate(history) if latest and h.get("ts") == latest["ts"]), default=len(history))
    earlier = history[:own]
    scores = _scores(latest)
    roles, unscored = [], []
    for role in numbers.pop("roles"):
        key = _keystr(role["key"])
        score = scores.get(role["id"]) or scores.get("key:" + key)
        if latest and not score:
            unscored.append(role["id"])
        score = score or {}
        roles.append({**{k: v for k, v in role.items() if k not in ("key", "hidden")},
                      "fit": score.get("fit"), "interest": score.get("interest"), "assessment": score.get("assessment"),
                      "why": score.get("why") or "", "fit_before": _fit_before(earlier, role["id"], key) if score else None})
    return {"roles": roles, "removed_roles": numbers.pop("removed_roles"), "more_roles": numbers.pop("more_roles"),
            "unscored": unscored, "limits": {"min": ROLES_MIN, "max": ROLES_MAX}, "market": numbers, "latest": latest,
            "outdated": bool(stored) and latest is None, "history": history, "running": _lock.locked()}


# ---------------------------------------------------------------- the user's own changes

def _find(cfg: dict, rid: str) -> dict | None:
    """The role candidate with this id, shown or not, or None."""
    return next((r for r in _role_groups(cfg, _postings(_leads())) if r["id"] == rid), None)


def add_role(title: str) -> str:
    """Add a job title of the user's own to the chart and return its role id. It goes into settings analysis.pinned_roles,
    so it always shows, and it leaves analysis.hidden_roles if the user had removed it. Adding a title that's already
    added again keeps the new spelling.

    Raises ValueError (with a message for the user) when the title is empty or too long, when it's only a level or a job
    type ("Intern", "Part time"), or when ROLES_MAX titles are added already."""
    title = str(title or "").strip()
    label, key = clean_title(title, own=True), role_key(title)
    if not label:
        raise ValueError("Type a job title first.")
    if len(title) > TITLE_MAX:
        raise ValueError(f"Keep the title under {TITLE_MAX} characters.")
    if not key:
        raise ValueError("Type the job title itself, not only a level or a job type.")
    cfg = settings_mod.get()
    pinned = [t for t in _setting(cfg, "pinned_roles") if role_key(t) != key]
    if len(pinned) >= ROLES_MAX:
        raise ValueError(f"You can add up to {ROLES_MAX} roles of your own. Remove one first.")
    cfg["analysis"]["pinned_roles"] = pinned + [label]
    cfg["analysis"]["hidden_roles"] = [t for t in _setting(cfg, "hidden_roles") if role_key(t) != key]
    settings_mod.save(cfg)
    return role_id(label)


def remove_role(rid: str) -> None:
    """Take the role with id `rid` off the chart for good: its title goes into settings analysis.hidden_roles (so no place
    brings it back), and out of analysis.pinned_roles when the user had added it. An unknown id changes nothing."""
    cfg = settings_mod.get()
    role = _find(cfg, rid)
    if not role:
        return
    hidden = _setting(cfg, "hidden_roles")
    if role["key"] not in {role_key(t) for t in hidden}:
        hidden.append(role["label"])
    cfg["analysis"]["hidden_roles"] = hidden
    cfg["analysis"]["pinned_roles"] = [t for t in _setting(cfg, "pinned_roles") if role_key(t) != role["key"]]
    settings_mod.save(cfg)


def restore_role(rid: str) -> None:
    """Bring back the removed role with id `rid`: its title leaves settings analysis.hidden_roles."""
    cfg = settings_mod.get()
    role = _find(cfg, rid)
    key = role["key"] if role else None
    cfg["analysis"]["hidden_roles"] = [t for t in _setting(cfg, "hidden_roles") if role_key(t) != key and role_id(t) != rid]
    settings_mod.save(cfg)


# ---------------------------------------------------------------- the AI assessment

# How each source reads in the prompt, after "from".
_FROM = {"target": "their target roles", "added": "they added it", "plan": "their search plan", "experience": "their work history",
         "suggested": "your earlier suggestion", "market": "their search results"}


def _prompt(roles: list[dict], numbers: dict, removed: list[str]) -> str:
    """The assessment prompt: the roles (with ids and where each came from), the titles the user removed, the market
    numbers per role, the skill gaps, the full profile and the search plan."""
    role_lines = "\n".join(f"- {r['id']}: {r['label']} (from {', '.join(_FROM[s] for s in r['sources'])})" for r in roles)
    market_lines = "\n".join(
        f"- {r['id']}: {r['demand_count']} of {numbers['demand_total']} postings ({r['demand_share'] * 100:.1f}%); "
        f"{r['qualified']} qualified leads; avg lead score {r['avg_score'] if r['avg_score'] is not None else 'n/a'}; "
        f"missing skills seen: {', '.join(r['top_missing']) or 'n/a'}" for r in roles)
    gaps = ", ".join(f"{x['skill']} (missing in {x['missing_in']}/{x['requested_in']})" for x in numbers["gaps"]) or "not enough packaged leads yet"
    return f"""ROLES (assess every one, using these ids):
{role_lines or "(none yet: suggest roles from the profile)"}

ROLES THE CANDIDATE REMOVED FROM THE CHART (never suggest these): {"; ".join(removed) or "none"}

MARKET DATA (postings whose titles match each role, from {numbers['demand_source']}):
{market_lines or "(no roles yet)"}

MOST-REQUESTED SKILLS THE TAILORED RESUMES COULDN'T SHOW: {gaps}

=== CANDIDATE PROFILE ===
{profile_mod.full_context()}

=== SEARCH PLAN ===
{json.dumps(profile_mod.get('search_plan'), indent=1)}"""


def _score(value) -> int | None:
    """A score from the AI held to 0..100, or None when it isn't a number."""
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError, OverflowError):
        return None


def _strings(value) -> list[str]:
    """The non-empty strings in a list from the AI, or [] when it isn't a list."""
    return [str(x).strip() for x in value if str(x).strip()] if isinstance(value, list) else []


def _assessed(items, roles: list[dict]) -> list[dict]:
    """The AI's role scores, kept only for roles on the chart (matched by id, or by role key when it wrote the id another
    way), one each, with scores held to 0..100 and every field the page reads in place, so a stray answer can't break the
    chart."""
    by_id, by_key = {r["id"]: r for r in roles}, {r["key"]: r for r in roles}
    out, done = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        written = str(item.get("id") or "")
        role = by_id.get(written) or by_key.get(role_key(written.replace("-", " ")))
        fit, interest = _score(item.get("fit")), _score(item.get("interest"))
        if not role or role["id"] in done or fit is None or interest is None:
            continue
        done.add(role["id"])
        moves = [{k: str(m.get(k) or "") for k in ("type", "title", "detail", "effort", "impact")}
                 for m in item.get("moves") or [] if isinstance(m, dict) and m.get("title")]
        out.append({"id": role["id"], "fit": fit, "interest": interest,
                    "confidence": item.get("confidence") if item.get("confidence") in ("low", "medium", "high") else "low",
                    "evidence": _strings(item.get("evidence")), "gaps": _strings(item.get("gaps")), "moves": moves})
    return out


def _suggested(items, roles: list[dict], removed: list[str]) -> list[dict]:
    """The AI's suggested roles, each {id, title, key, why, fit, interest}, at most SUGGESTIONS_MAX. A suggestion that
    repeats a role already on the chart from another source, or is a less specific form of one ("Nurse" next to
    "Registered Nurse"), or that the user removed, is dropped: it wouldn't add a role. Earlier suggestions may come back."""
    taken = [r["key"] for r in roles if r["source"] != "suggested"] + [role_key(t) for t in removed]
    out: list[dict] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        title = clean_title(str(item.get("title") or ""))
        key = role_key(title)
        fit, interest = _score(item.get("fit")), _score(item.get("interest"))
        if not key or fit is None or interest is None or any(key <= k for k in taken):
            continue
        taken.append(key)
        out.append({"id": role_id(title), "title": title, "key": _keystr(key), "why": str(item.get("why") or "").strip(),
                    "fit": fit, "interest": interest})
        if len(out) == SUGGESTIONS_MAX:
            break
    return out


async def run_ai(reason: str = "manual") -> dict:
    """Ask the AI to score fit and interest for every role on the chart, suggest more roles and suggest moves (one AI call),
    and store the result.

    Publishes "analysis" events so the page shows the progress, then a toast with the summary. Returns
    {"ok": True, ...the stored result}, or ok=False when an assessment is already running. On failure it shows an error
    toast and raises."""
    if _lock.locked():
        return {"ok": False, "message": "Analysis already running."}
    async with _lock:
        bus.publish("analysis", {"running": True})
        try:
            cfg = settings_mod.get()
            numbers = market(cfg)
            roles, removed = numbers["roles"], _setting(cfg, "hidden_roles")
            out = await ai.run(_prompt(roles, numbers, removed), system=prompts.system("analysis", prompts.ANALYSIS_SYSTEM),
                               schema=prompts.ANALYSIS_SCHEMA, stage="analysis", purpose="analysis", label="analysis: role radar",
                               timeout=1200)
            tokens = out.pop("_tokens", 0)
            out.pop("_tools", None)
            out.pop("genres", None)  # a prompt override written for the old genre chart may still send these
            out["roles"] = _assessed(out.get("roles"), roles)
            out["suggested_roles"] = _suggested(out.get("suggested_roles"), roles, removed)
            out["summary"] = str(out.get("summary") or "")
            for name in ("top_priorities", "profile_suggestions"):
                out[name] = [x for x in out.get(name) or [] if isinstance(x, dict)]
            out["search_steering"] = out.get("search_steering") if isinstance(out.get("search_steering"), dict) else {}
            latest = {"ts": db.now(), "reason": reason, "axes": "roles", "result": out, "tokens": tokens,
                      "roles": [{"id": r["id"], "label": r["label"], "source": r["source"], "key": _keystr(r["key"])} for r in roles],
                      "demand": {r["id"]: r["demand_index"] for r in roles}}
            db.kv_set("analysis.latest", latest)
            scored = out["suggested_roles"] + out["roles"]  # a role assessed in full wins over the same role suggested
            fit_history = db.kv_get("analysis.history") or []
            fit_history.append({"ts": latest["ts"], "axes": "roles", "fit": {x["id"]: x["fit"] for x in scored},
                                "interest": {x["id"]: x["interest"] for x in scored},
                                "keys": {**{s["id"]: s["key"] for s in out["suggested_roles"]}, **{r["id"]: r["key"] for r in latest["roles"]}}})
            db.kv_set("analysis.history", fit_history[-40:])
            bus.publish("analysis", {"running": False, "ts": latest["ts"]})
            bus.publish("toast", {"title": "Analysis updated", "body": out["summary"][:160]})
            return {"ok": True, **latest}
        except Exception as e:
            bus.publish("analysis", {"running": False, "error": str(e)[:300]})
            bus.publish("toast", {"title": "Analysis failed", "body": str(e)[:300], "level": "error"})
            raise
