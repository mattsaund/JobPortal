"""Experience levels, from internship to lead, and what each one means for the search.

The user picks one or more levels in the standard questions (candidate/onboarding.py stores them in the "search.levels"
setting). The levels then decide:
- which job titles pass the rule filters: title_filters() builds the "filters.title_include" and "filters.title_exclude"
  settings, which search/pipeline.py applies to every job-board title
- what the job boards are asked for: ats_search_terms() (Workday, iCIMS), linkedin_experience() (LinkedIn) and
  muse_levels() (The Muse)
- which free-text hiring posts count as relevant: posting_regex() (Hacker News, Reddit, Mastodon, Bluesky)

Key idea: early-career titles usually say their level ("Intern", "New Grad", "Junior"), so for internship and entry level
a title must contain one of those words. Mid-level titles rarely do ("Backend Engineer"), so picking mid level drops that
rule. Excluded words (too senior, or intern words for experienced searches) are never applied to the user's own target
roles, so a target like "Staff Accountant" isn't blocked by "staff"."""
import re

LEVELS = [  # (id, label shown in the standard questions)
    ("internship", "Internship or co-op"),
    ("entry", "Entry level or new grad"),
    ("mid", "Mid level (about 2-5 years)"),
    ("senior", "Senior (5+ years)"),
    ("lead", "Lead, staff or manager"),
]
LEVEL_IDS = [k for k, _ in LEVELS]
DEFAULT_LEVELS = ["internship", "entry"]  # used until the user answers the standard questions
EARLY = {"internship", "entry"}  # the early-career levels

# Title words that mark a posting as being at a level (case-insensitive regexes; \b marks a word edge). Mid level has none
# on purpose, see the module docstring.
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
# Title words excluded for searches that don't include the level they belong to (see title_filters).
SENIOR_WORDS = [r"\bsenior\b", r"\bsr\.?\b", r"\bstaff\b", r"principal", r"\blead\b", r"\bii\b", r"\biii\b", r"\biv\b",
                r"engineer 2\b", r"engineer 3\b", r"\bexpert\b", r"architect"]
EXEC_WORDS = [r"manager", r"director", r"head of", r"\bvp\b", r"vice president", r"\bchief\b", r"\bdistinguished\b"]
INTERN_WORDS = [r"\bintern\b", r"\binterns\b", r"internship", r"co-?op\b"]
ALWAYS_EXCLUDE = [r"high school", r"postdoc"]  # never a fit, whatever the levels


def clean(levels) -> list[str]:
    """The valid level ids from `levels`, in the order given, or DEFAULT_LEVELS when none are valid."""
    out = [x for x in (levels or []) if x in LEVEL_IDS]
    return out or list(DEFAULT_LEVELS)


def early_career(levels) -> bool:
    """True when every level picked is internship or entry level."""
    return set(clean(levels)) <= EARLY


def title_filters(levels, roles: list[str] | None = None) -> tuple[list[str], list[str]]:
    """The (include, exclude) regex lists for job titles at these levels. `roles` are the user's target job titles.

    include: the title words of every level picked, plus each target role. A title must match one of them. It's empty
    (any title passes) when mid level is picked, because mid-level titles rarely name their level.
    exclude: words for levels the user didn't pick. Early-career searches drop senior and management titles. Other
    searches without lead drop executive titles but keep "manager", since roles like Product Manager are not management.
    Searches without internship drop intern titles. An exclude word found in a target role is left out, so "Staff
    Accountant" or "Associate Product Manager" still get through.

    candidate/onboarding.py saves the result as the title filter settings, which the Settings page shows for editing."""
    picked = set(clean(levels))
    roles = [r.strip() for r in (roles or []) if r and r.strip()]
    include: list[str] = []
    if "mid" not in picked:
        include = [p for k in LEVEL_IDS if k in picked for p in TITLE_MARKERS.get(k, [])]
        include += [re.escape(r.lower()) for r in roles]  # the titles the user asked for always count
    exclude = list(ALWAYS_EXCLUDE)
    if picked <= EARLY:
        exclude += SENIOR_WORDS + EXEC_WORDS
    elif "lead" not in picked:
        exclude += [w for w in EXEC_WORDS if w != r"manager"] + [r"principal", r"\bdistinguished\b"]
    if "internship" not in picked:
        exclude += INTERN_WORDS
    exclude = [p for p in exclude if not any(re.search(p, r, re.I) for r in roles)]
    return _unique(include), _unique(exclude)


def ats_search_terms(levels, queries: list[str] | None = None, limit: int = 8) -> list[str]:
    """Search words for company boards that need one (Workday and iCIMS can't list every job at once).

    Early-career levels search their own words ("intern", "new grad"). Mid level and above search the user's queries
    instead (at most `limit` of them), because those titles carry no level word. Each word costs one request per board,
    so the result is capped at `limit` words, with repeats (ignoring case) removed."""
    picked = set(clean(levels))
    terms: list[str] = []
    if "internship" in picked:
        terms += ["intern", "co-op", "student"]
    if "entry" in picked:
        terms += ["new grad", "entry level", "early career", "associate"]
    if picked - EARLY:
        terms += [q for q in (queries or []) if q][:limit]
    return _unique(terms, key=str.lower)[:limit]


def linkedin_experience(levels) -> str:
    """LinkedIn's experience filter (the f_E search parameter) for these levels, for example "1,2".
    LinkedIn's codes: 1 internship, 2 entry level, 3 associate, 4 mid-senior level, 5 director."""
    codes = {"internship": ["1"], "entry": ["2"], "mid": ["3", "4"], "senior": ["4"], "lead": ["4", "5"]}
    out: list[str] = []
    for k in clean(levels):
        out += [c for c in codes[k] if c not in out]
    return ",".join(sorted(out))


def muse_levels(levels) -> list[str]:
    """The Muse's level names for these levels (its "level" search parameter)."""
    names = {"internship": "Internship", "entry": "Entry Level", "mid": "Mid Level", "senior": "Senior Level", "lead": "Management"}
    return [names[k] for k in clean(levels)]


# Words that show a free-text post is about early-career hiring.
EARLY_POST_RE = re.compile(r"\b(intern(ship)?s?|co-?op|new grads?|entry[- ]level|junior|jr\.?|university grads?|students?|"
                           r"early[- ]career|recent grad(uate)?s?|apprentice(ship)?)\b", re.I)


def posting_regex(levels, roles: list[str] | None = None) -> re.Pattern:
    """A regex that picks which free-text hiring posts (Hacker News comments, Reddit, Mastodon, Bluesky) are worth
    keeping.

    Early-career searches look for early-career words. Other searches look for words from the user's target roles (3 or
    more letters, without filler like "senior" or "remote"). There's no word edge at the end, so "engineer" also finds
    "engineering". With no usable role words, a list of common job words is used instead."""
    if early_career(levels):
        return EARLY_POST_RE
    filler = {"and", "the", "for", "with", "level", "senior", "junior", "entry", "remote"}
    words = {re.escape(w) for r in (roles or []) for w in re.findall(r"[A-Za-z+#.]{3,}", r) if w.lower() not in filler}
    # Longest first, since longer words are the most specific and only the first 40 are kept. Ties sort alphabetically,
    # so the same roles always give the same regex.
    words = sorted(words, key=lambda w: (-len(w), w))[:40]
    if not words:
        return re.compile(r"\b(engineer|developer|analyst|scientist|designer|manager|specialist|technician)\b", re.I)
    return re.compile(r"\b(" + "|".join(words) + r")", re.I)


def _unique(items: list[str], key=None) -> list[str]:
    """`items` without repeats, keeping the first of each in order. `key` (for example str.lower) decides what counts as
    a repeat."""
    seen: set[str] = set()
    out = []
    for item in items:
        k = key(item) if key else item
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out
