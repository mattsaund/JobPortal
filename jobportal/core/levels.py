"""Experience levels, from internship and apprenticeship to lead and management, and what each one means for the search.

The user picks one or more levels in the standard questions (candidate/onboarding.py stores them in the "search.levels"
setting). The levels then decide:
- which job titles pass the rule filters: title_filters() builds the "filters.title_include" and "filters.title_exclude"
  settings, which search/pipeline.py applies to every job-board title
- what the job boards are asked for: ats_search_terms() (Workday, iCIMS), linkedin_experience() (LinkedIn) and
  muse_levels() (The Muse)
- which free-text hiring posts count as relevant: posting_regex() (Hacker News, Reddit, Mastodon, Bluesky)

Key ideas:
- Early-career titles often say their level ("Intern", "Apprentice", "Junior", "Trainee", "Accountant I"), so for the
  early levels a company-board title must contain one of those words, or one of the user's own target roles (hourly
  jobs such as "Cashier" or "Line Cook" rarely name a level, which is why the target roles always count). Mid-level titles
  rarely say their level in any field ("Registered Nurse", "Backend Engineer"), so picking mid level drops that rule.
- Excluded words (too senior, or intern words for experienced searches) are never applied to the user's own target roles,
  so a target like "Lead Teacher" isn't blocked by "lead".
- The words work for every field: "staff" only counts as senior next to the titles where it means a senior level (Staff
  Engineer), never in "Staff Nurse" or "Staff Accountant", and trade levels count too (journeyman, master electrician,
  foreman, supervisor)."""
import re

LEVELS = [  # (id, label shown in the standard questions)
    ("internship", "Internship, co-op or fellowship"),
    ("apprenticeship", "Apprenticeship or trainee program"),
    ("entry", "Entry level, new grad or first job"),
    ("mid", "Mid level (about 2-5 years)"),
    ("senior", "Senior or experienced (5+ years)"),
    ("lead", "Lead, supervisor, manager or director"),
]
LEVEL_IDS = [k for k, _ in LEVELS]
# Used until the user answers the standard questions: every level, so nothing about the user is assumed.
DEFAULT_LEVELS = list(LEVEL_IDS)
EARLY = {"internship", "apprenticeship", "entry"}  # the early-career levels

# A level numeral at the end of a title or before a separator: "Accountant I", "Engineer 2 - Payments", "Analyst II (Remote)".
_NUMERAL_END = r"(?=\s*(?:$|[-,(|/:]))"
# Numbers and numerals that name something other than a level: "Teacher - Grade 3", "Class 2 Driver", "Title IV Specialist".
_NOT_A_LEVEL = r"(?<!grade )(?<!class )(?<!title )"
# In front of these words "IV" means intravenous, not level four: "IV Therapy RN", "IV Team Nurse".
_INTRAVENOUS = r"(?! (?:therapy|team|infusion|access|insertion|starts?|nurse|rn)\b)"
_SENIOR_NUMERALS = [_NOT_A_LEVEL + r"\b(?:ii|iii)\b", _NOT_A_LEVEL + r"\biv\b" + _INTRAVENOUS,
                    _NOT_A_LEVEL + r"\b[234]\b" + _NUMERAL_END]
# Title words that mark a posting as being at a level (case-insensitive regexes; \b marks a word edge). Mid level has none
# on purpose, see the module docstring.
TITLE_MARKERS = {
    "internship": [r"intern", r"co-?op\b", r"\bstudent", r"\bsummer\b", r"\bfellow", r"pathways", r"\bscholar", r"externship",
                   r"research assistant"],
    "apprenticeship": [r"apprentic", r"trainee", r"\btraining program", r"\bhelper\b", r"\bcadet\b", r"learn(?:er|ing) program"],
    "entry": [r"new grad", r"\bgraduate\b", r"entry[- ]level", r"\bentry\b", r"\bjunior\b", r"\bjr\.?\b", r"early[- ]career",
              r"university", r"campus", r"first[- ]year", r"\bresidency\b",
              r"\bassociate\b(?! (?:director|professor|general counsel|vice president|partner|dean|principal))",
              r"\bassistant\b(?! (?:director|professor|vice president|dean|general counsel|principal|superintendent|chief))",
              r"\baide\b", r"\bclerk\b", r"\battendant\b", r"\btechnician\b", r"\bcrew member\b", r"\bteam member\b",
              r"\brotational\b", r"\blevel (?:i|1)\b", r"\b(?:i|1)\b" + _NUMERAL_END],
    "senior": [r"\bsenior\b", r"\bsr\.?\b", r"\bstaff (?:\w+ )?(?:engineer|developer|scientist|architect|designer|researcher)",
               r"principal", *_SENIOR_NUMERALS, r"\blevel (?:ii|iii|iv|2|3|4)\b", r"\bexperienced\b",
               r"\bjourneym[ae]n\b", r"\bmaster (?:electrician|plumber|carpenter|technician|mechanic|welder|barber|stylist)"],
    "lead": [r"\blead\b", r"manager", r"director", r"head of", r"\bhead\b", r"principal", r"architect", r"\bvp\b",
             r"vice president", r"supervisor", r"superintendent", r"\bforem[ae]n\b", r"\bchief\b", r"\bdean\b", r"\bpresident\b",
             r"charge nurse"],
}
# Title words excluded for searches that don't include the level they belong to (see title_filters).
SENIOR_WORDS = [r"\bsenior\b", r"\bsr\.?\b", r"\bstaff (?:\w+ )?(?:engineer|developer|scientist|architect|designer|researcher)",
                r"principal", r"\blead\b", *_SENIOR_NUMERALS, r"\bexpert\b", r"architect",
                r"\bjourneym[ae]n\b", r"\bmaster (?:electrician|plumber|carpenter|technician|mechanic|welder)", r"\bsupervisor\b",
                r"\bsuperintendent\b", r"\bforem[ae]n\b"]
# "manager" is an executive word, except in titles that are front-line work in their fields.
MANAGER_WORD = r"manager(?<!case manager)(?<!care manager)(?<!assistant manager)"
EXEC_WORDS = [MANAGER_WORD, r"director", r"head of", r"\bvp\b", r"vice president", r"\bchief\b", r"\bdistinguished\b",
              r"\bpresident\b"]
INTERN_WORDS = [r"\bintern\b", r"\binterns\b", r"internship", r"co-?op\b"]
APPRENTICE_WORDS = [r"\bapprentice", r"\btrainee\b"]


def clean(levels) -> list[str]:
    """The valid level ids from `levels`, in the order given, or DEFAULT_LEVELS when none are valid."""
    out = [x for x in (levels or []) if x in LEVEL_IDS]
    return out or list(DEFAULT_LEVELS)


def early_career(levels) -> bool:
    """True when every level picked is an early-career one: internship, apprenticeship or entry level."""
    return set(clean(levels)) <= EARLY


def title_filters(levels, roles: list[str] | None = None) -> tuple[list[str], list[str]]:
    """The (include, exclude) regex lists for job titles at these levels. `roles` are the user's target job titles.

    include: the title words of every level picked, plus each target role. A title must match one of them. It's empty
    (any title passes) when mid level is picked, because mid-level titles rarely name their level.
    exclude: words for levels the user didn't pick. Early-career searches drop senior, supervisor and management titles.
    Other searches without lead drop executive titles but keep "manager", since roles like Product Manager or Store Manager
    are not always management. Searches without internship drop intern titles, and searches with no early level at all
    drop apprentice and trainee titles. An exclude word found in a target role is left out, so "Staff Accountant", "Lead
    Teacher" or "Associate Product Manager" still get through.

    candidate/onboarding.py saves the result as the title filter settings, which Settings, Search shows for editing."""
    picked = set(clean(levels))
    roles = [r.strip() for r in (roles or []) if r and r.strip()]
    include: list[str] = []
    if "mid" not in picked:
        include = [p for k in LEVEL_IDS if k in picked for p in TITLE_MARKERS.get(k, [])]
        include += [re.escape(r.lower()) for r in roles]  # the titles the user asked for always count
    exclude: list[str] = []
    if picked <= EARLY:
        exclude += SENIOR_WORDS + EXEC_WORDS
    elif "lead" not in picked:
        exclude += [w for w in EXEC_WORDS if w != MANAGER_WORD] + [r"principal", r"\bdistinguished\b"]
    if "internship" not in picked:
        exclude += INTERN_WORDS
    if not picked & EARLY:
        exclude += APPRENTICE_WORDS
    exclude = [p for p in exclude if not any(re.search(p, r, re.I) for r in roles)]
    return _unique(include), _unique(exclude)


def ats_search_terms(levels, queries: list[str] | None = None, limit: int = 8) -> list[str]:
    """Search words for company boards that need one (Workday and iCIMS can't list every job at once).

    Early levels start with up to four of their own words ("intern", "apprentice", "entry level"), then come the
    user's queries, which name their field. Mid level and above search only the queries, because those titles carry no
    level word. Each word costs one request per board, so the result is capped at `limit` words, with repeats (ignoring
    case) removed."""
    picked = set(clean(levels))
    words: list[str] = []
    if "internship" in picked:
        words += ["intern", "co-op", "student"]
    if "apprenticeship" in picked:
        words += ["apprentice", "trainee"]
    if "entry" in picked:
        words += ["entry level", "new grad", "associate"]
    terms = words[:4] + [q for q in (queries or []) if q]
    return _unique(terms, key=str.lower)[:limit]


def linkedin_experience(levels) -> str:
    """LinkedIn's experience filter (the f_E search parameter) for these levels, for example "1,2".
    LinkedIn's codes: 1 internship, 2 entry level, 3 associate, 4 mid-senior level, 5 director, 6 executive. LinkedIn has
    no apprenticeship level, so apprenticeships search internship and entry level."""
    codes = {"internship": ["1"], "apprenticeship": ["1", "2"], "entry": ["2"], "mid": ["3", "4"], "senior": ["4"],
             "lead": ["4", "5", "6"]}
    out: list[str] = []
    for k in clean(levels):
        out += [c for c in codes[k] if c not in out]
    return ",".join(sorted(out))


def muse_levels(levels) -> list[str]:
    """The Muse's level names for these levels (its "level" search parameter). The Muse has no apprenticeship level, so
    apprenticeships search its internship and entry levels."""
    names = {"internship": ["Internship"], "apprenticeship": ["Internship", "Entry Level"], "entry": ["Entry Level"],
             "mid": ["Mid Level"], "senior": ["Senior Level"], "lead": ["Management"]}
    return _unique([name for k in clean(levels) for name in names[k]])


# Words that show a free-text post is about early-career hiring.
EARLY_POST_RE = re.compile(r"\b(intern(ship)?s?|co-?op|new grads?|entry[- ]level|junior|jr\.?|university grads?|students?|"
                           r"early[- ]career|recent grad(uate)?s?|apprentice(ship)?s?|trainees?|first job)\b", re.I)
# Words that name a job in almost any field. A post must use one when the user has no target roles to go by.
ANY_JOB_RE = re.compile(r"\b(engineer|developer|analyst|scientist|designer|manager|specialist|technician|assistant|associate|"
                        r"coordinator|nurse|teacher|instructor|driver|cook|chef|clerk|cashier|representative|writer|editor|"
                        r"artist|accountant|mechanic|electrician|welder|caregiver|operator|consultant|officer|therapist|"
                        r"counselor|director|administrator|agent|worker|aide|server|barista|stylist|supervisor|lead)", re.I)


def posting_regex(levels, roles: list[str] | None = None) -> re.Pattern:
    """A regex that picks which free-text hiring posts (Hacker News comments, Reddit, Mastodon, Bluesky) are worth
    keeping.

    Early-career searches look for early-career words. Other searches look for words from the user's target roles (3 or
    more letters, without filler like "senior" or "remote"). There's no word edge at the end, so "nurse" also finds
    "nursing". With no usable role words, ANY_JOB_RE is used instead: a list of job words from many fields."""
    if early_career(levels):
        return EARLY_POST_RE
    filler = {"and", "the", "for", "with", "level", "senior", "junior", "entry", "remote"}
    words = {re.escape(w) for r in (roles or []) for w in re.findall(r"[A-Za-z+#.]{3,}", r) if w.lower() not in filler}
    # Longest first, since longer words are the most specific and only the first 40 are kept. Ties sort alphabetically,
    # so the same roles always give the same regex.
    words = sorted(words, key=lambda w: (-len(w), w))[:40]
    if not words:
        return ANY_JOB_RE
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
