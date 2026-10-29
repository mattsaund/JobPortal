"""Experience levels (internship through lead). The levels you pick in the standard questions decide which job titles pass
the rule filters, which search terms the job boards get, and which hiring posts count as relevant."""
import re

LEVELS = [
    ("internship", "Internship or co-op"),
    ("entry", "Entry level or new grad"),
    ("mid", "Mid level (about 2-5 years)"),
    ("senior", "Senior (5+ years)"),
    ("lead", "Lead, staff or manager"),
]
LEVEL_IDS = [k for k, _ in LEVELS]
DEFAULT_LEVELS = ["internship", "entry"]
EARLY = {"internship", "entry"}

# Title words that mark a posting as belonging to a level.
TITLE_MARKERS = {
    "internship": [r"intern", r"co-?op\b", r"\bstudent", r"apprentic", r"trainee", r"\bsummer\b", r"\bfellow", r"pathways",
                   r"\bscholar", r"research assistant"],
    "entry": [r"new grad", r"\bgraduate\b", r"entry[- ]level", r"\bjunior\b", r"\bjr\.?\b", r"early[- ]career", r"university",
              r"campus", r"\bassociate\b(?! (?:director|professor|general counsel|vice president|partner))",
              r"(?:software|engineer|developer|data|systems|research|technical) associate", r"engineer i\b", r"engineer 1\b",
              r"developer i\b", r"analyst i\b", r"level i\b", r"technician", r"\brotational\b"],
    "senior": [r"\bsenior\b", r"\bsr\.?\b", r"\bstaff\b", r"principal", r"\bii\b", r"\biii\b", r"engineer 2\b", r"engineer 3\b"],
    "lead": [r"\blead\b", r"manager", r"director", r"head of", r"principal", r"architect", r"\bvp\b", r"vice president"],
}
SENIOR_WORDS = [r"\bsenior\b", r"\bsr\.?\b", r"\bstaff\b", r"principal", r"\blead\b", r"\bii\b", r"\biii\b", r"\biv\b",
                r"engineer 2\b", r"engineer 3\b", r"\bexpert\b", r"architect"]
EXEC_WORDS = [r"manager", r"director", r"head of", r"\bvp\b", r"vice president", r"\bchief\b", r"\bdistinguished\b"]
INTERN_WORDS = [r"\bintern\b", r"\binterns\b", r"internship", r"co-?op\b"]
ALWAYS_EXCLUDE = [r"high school", r"postdoc"]


def clean(levels) -> list[str]:
    out = [x for x in (levels or []) if x in LEVEL_IDS]
    return out or list(DEFAULT_LEVELS)


def early_career(levels) -> bool:
    """True when every level picked is internship or entry level."""
    return set(clean(levels)) <= EARLY


def title_filters(levels, roles: list[str] | None = None) -> tuple[list[str], list[str]]:
    """(include, exclude) regex lists for job titles. Include is empty (= everything passes) when a level without title
    markers (mid level) is picked, since mid-level postings rarely say so in the title. An exclude word that appears in one
    of your target roles is dropped, so "Staff Accountant" or "Associate Product Manager" still get through."""
    lv = set(clean(levels))
    roles = [r.strip() for r in (roles or []) if r and r.strip()]
    include: list[str] = []
    if "mid" not in lv:
        for k in LEVEL_IDS:
            if k in lv:
                include += [p for p in TITLE_MARKERS.get(k, []) if p not in include]
        include += [re.escape(r.lower()) for r in roles if re.escape(r.lower()) not in include]  # titles you asked for always count
    exclude = list(ALWAYS_EXCLUDE)
    if lv <= EARLY:
        exclude += SENIOR_WORDS + EXEC_WORDS
    elif "lead" not in lv:
        exclude += [w for w in EXEC_WORDS if w != r"manager"] + [r"principal", r"\bdistinguished\b"]
    if "internship" not in lv:
        exclude += INTERN_WORDS
    exclude = [p for p in exclude if not any(re.search(p, r, re.I) for r in roles)]
    seen: set[str] = set()
    return include, [x for x in exclude if not (x in seen or seen.add(x))]


def ats_search_terms(levels, queries: list[str] | None = None, limit: int = 8) -> list[str]:
    """Keywords for company boards that need a search term (Workday, iCIMS)."""
    lv = set(clean(levels))
    terms: list[str] = []
    if "internship" in lv:
        terms += ["intern", "co-op", "student"]
    if "entry" in lv:
        terms += ["new grad", "entry level", "early career", "associate"]
    if lv - EARLY:
        terms += [q for q in (queries or []) if q][:limit]
    seen: set[str] = set()
    return [t for t in terms if not (t.lower() in seen or seen.add(t.lower()))][: max(limit, 6)]


def linkedin_experience(levels) -> str:
    """LinkedIn's f_E filter: 1 internship, 2 entry, 3 associate, 4 mid-senior, 5 director."""
    codes = {"internship": ["1"], "entry": ["2"], "mid": ["3", "4"], "senior": ["4"], "lead": ["4", "5"]}
    out: list[str] = []
    for k in clean(levels):
        out += [c for c in codes[k] if c not in out]
    return ",".join(sorted(out))


def muse_levels(levels) -> list[str]:
    names = {"internship": "Internship", "entry": "Entry Level", "mid": "Mid Level", "senior": "Senior Level", "lead": "Management"}
    return [names[k] for k in clean(levels)]


EARLY_POST_RE = re.compile(r"\b(intern(ship)?s?|co-?op|new grads?|entry[- ]level|junior|jr\.?|university grads?|students?|"
                           r"early[- ]career|recent grad(uate)?s?|apprentice(ship)?)\b", re.I)


def posting_regex(levels, roles: list[str] | None = None) -> re.Pattern:
    """Which free-text hiring posts (HN comments, Reddit, Mastodon, Bluesky) are worth keeping."""
    if early_career(levels):
        return EARLY_POST_RE
    words = [re.escape(w) for r in (roles or []) for w in re.findall(r"[A-Za-z+#.]{3,}", r)
             if w.lower() not in {"and", "the", "for", "with", "level", "senior", "junior", "entry", "remote"}]
    words = sorted(set(words), key=len, reverse=True)[:40]
    if not words:
        return re.compile(r"\b(engineer|developer|analyst|scientist|designer|manager|specialist|technician)\b", re.I)
    return re.compile(r"\b(" + "|".join(words) + r")", re.I)
