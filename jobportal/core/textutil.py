"""Text helpers for the search, the documents and the dashboard routes.

What's here:
- Cleaning text: html_to_text() turns a posting's HTML into plain text, and clean() collapses whitespace.
- Spotting duplicates: fingerprint() and url_key() give the same answer for the same job found on two sites.
- Dates: parse_date() reads the many date formats job boards use, and age_days() says how old a date is.
- Locations: state_of() works out where a location string is, and LocationMatcher checks a job's locations against the
  user's search area. search/pipeline.py drops jobs outside the area before any AI sees them.
- Keywords: extract_terms() finds tech terms in a posting, and coverage() measures how many of a job's keywords a resume
  contains, roughly the way applicant tracking systems scan resumes.

Nothing here touches the network, the database or the AI, so every function is easy to try out and test (see
tests/test_core.py)."""
import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------- places

# Two-letter code to name, for the 50 states and DC.
STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
NAME_TO_ABBR = {v.lower(): k for k, v in STATES.items()}  # "ohio" -> "OH"

# Cities that postings often name without their state, mapped to the state. state_of() checks them in this order and the
# first match wins. search/collectors/feeds.py also takes a state's first few cities from here as search locations.
CITY_STATE = {
    # Washington, DC area, Maryland, Virginia, Pennsylvania and Delaware
    "baltimore": "MD", "columbia": "MD", "greenbelt": "MD", "laurel": "MD", "annapolis": "MD", "annapolis junction": "MD",
    "bethesda": "MD", "rockville": "MD", "gaithersburg": "MD", "germantown": "MD", "silver spring": "MD",
    "college park": "MD", "hanover": "MD", "linthicum": "MD", "fort meade": "MD", "aberdeen": "MD",
    "aberdeen proving ground": "MD", "patuxent river": "MD", "lexington park": "MD", "elkton": "MD",
    "hunt valley": "MD", "towson": "MD", "lanham": "MD", "beltsville": "MD", "adelphi": "MD", "frederick": "MD",
    "owings mills": "MD", "ellicott city": "MD", "middle river": "MD", "glen burnie": "MD", "odenton": "MD",
    "indian head": "MD", "white oak": "MD", "landover": "MD", "largo": "MD", "sparks": "MD", "catonsville": "MD",
    "arlington": "VA", "herndon": "VA", "reston": "VA", "chantilly": "VA", "mclean": "VA", "dulles": "VA",
    "fairfax": "VA", "alexandria": "VA", "springfield": "VA", "sterling": "VA", "falls church": "VA",
    "tysons": "VA", "vienna": "VA", "hampton": "VA", "norfolk": "VA", "virginia beach": "VA", "richmond": "VA",
    "wallops island": "VA", "dahlgren": "VA", "quantico": "VA", "manassas": "VA", "ashburn": "VA",
    "philadelphia": "PA", "pittsburgh": "PA", "king of prussia": "PA", "valley forge": "PA", "harrisburg": "PA",
    "state college": "PA", "lancaster": "PA", "allentown": "PA", "york": "PA", "mechanicsburg": "PA",
    "wilmington": "DE", "dover": "DE", "washington dc": "DC", "washington d.c.": "DC",
    # Other big metros, tech hubs and space and defense hubs
    "nyc": "NY", "new york city": "NY", "brooklyn": "NY", "manhattan": "NY", "sf": "CA", "south sf": "CA",
    "san francisco": "CA", "bay area": "CA", "los angeles": "CA", "la": "CA", "san jose": "CA", "palo alto": "CA",
    "mountain view": "CA", "sunnyvale": "CA", "menlo park": "CA", "san diego": "CA", "pasadena": "CA", "hawthorne": "CA",
    "long beach": "CA", "el segundo": "CA", "irvine": "CA", "seattle": "WA", "redmond": "WA", "bellevue": "WA",
    "kent": "WA", "boston": "MA", "cambridge, ma": "MA", "chicago": "IL", "austin": "TX", "houston": "TX",
    "dallas": "TX", "cedar park": "TX", "starbase": "TX", "denver": "CO", "boulder": "CO", "colorado springs": "CO",
    "louisville, co": "CO", "littleton": "CO", "centennial": "CO", "atlanta": "GA", "huntsville": "AL",
    "cape canaveral": "FL", "titusville": "FL", "merritt island": "FL", "orlando": "FL", "melbourne, fl": "FL",
    "phoenix": "AZ", "tucson": "AZ", "salt lake city": "UT", "albuquerque": "NM", "detroit": "MI", "minneapolis": "MN",
    "portland": "OR", "raleigh": "NC", "durham": "NC", "nashville": "TN", "miami": "FL", "tampa": "FL",
}
# Text that names another country or region (EMEA, APAC, LATAM), or a Canadian province code after a comma ("Toronto,
# ON"). Country names are case-insensitive. Province codes must be uppercase, so ", on-site" isn't read as Ontario.
FOREIGN_RE = re.compile(
    r"\b(uk|u\.k\.|united kingdom|england|scotland|wales|ireland|canada|germany|france|spain|italy|netherlands|"
    r"switzerland|sweden|norway|denmark|finland|poland|india|china|japan|korea|singapore|australia|new zealand|"
    r"israel|mexico|brazil|argentina|uae|united arab emirates|dubai|philippines|vietnam|taiwan|hong kong|portugal|"
    r"belgium|austria|czech|romania|ukraine|luxembourg|estonia|emea|apac|latam)\b"
    r"|,\s*(?-i:ON|QC|BC|AB|MB|SK|NS|NB|NL|PE)\b", re.I)
# Location text that says nothing useful about where a job is: blank, "N/A", "TBD", "Various", "Multiple locations",
# "3 locations", or only the country ("United States", "USA", "Nationwide", "North America").
UNKNOWN_LOC = re.compile(r"^\s*(|n/?a|tbd|various|multiple( locations)?|\d+ locations?|united states( of america)?|usa?|"
                         r"u\.s\.a?\.?|nationwide|us-?nationwide|north america)\s*$", re.I)
# Words that mark a remote job.
REMOTE_RE = re.compile(r"\b(remote|anywhere|work from home|wfh|virtual|telework|teleworking|distributed)\b", re.I)
# Text that names the US. Case-sensitive on purpose, so the word "us" in "join us" doesn't count.
_US_RE = re.compile(r"\b(US|USA|United States)\b")
# The same plus "U.S." and "U.S.A.", used only by LocationMatcher's remote check, so "Remote - U.S. & Canada" counts as
# open to the US. state_of() keeps using _US_RE, because job fingerprints are built from it.
_US_OR_DOTTED_RE = re.compile(r"\b(?:US|USA|United States)\b|\bU\.S\.(?:A\.)?")
# A hybrid listing: part remote, part on-site at the place it names.
_HYBRID_RE = re.compile(r"\bhybrid\b", re.I)
# An allowed-location entry that means "anywhere in the US", matched against the whole entry in lowercase. Keep it in
# step with NATIONWIDE_RE in web/static/js/components/search-area.js, which reads the same entries.
_NATIONWIDE_RE = re.compile(r"(anywhere( in the)?( us| usa| united states)?|nationwide|united states|usa|us)")
# Vague location text (see UNKNOWN_LOC) that still says the job is in the US.
_SAYS_US_RE = re.compile(r"united states|\bus\b|usa|nationwide", re.I)
# What separates the locations of a job that lists several: ";", "|", "/", " or " and line breaks.
_LOCATION_SPLIT_RE = re.compile(r"\s*(?:;|\||/| or |\n)\s*")


# ---------------------------------------------------------------- cleaning text

def html_to_text(h: str | None) -> str:
    """Plain text from a posting's HTML: tags removed, entities decoded, list items as "• " bullets, and never more than
    one blank line in a row. Returns "" for None or empty input."""
    if not h:
        return ""
    # Some boards send HTML escaped twice ("&lt;p&gt;" instead of "<p>"). Unescape it once first, so the tags show up.
    if "&lt;" in h and "<" not in h[:200]:
        h = html.unescape(h)
    h = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", h)  # blocks whose content isn't readable text
    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    h = re.sub(r"(?i)</(p|div|h[1-6]|tr|section|article|ul|ol|header|footer)>", "\n", h)  # the end of a block is a line break
    h = re.sub(r"(?i)<li[^>]*>", "\n• ", h)
    h = re.sub(r"<[^>]+>", " ", h)  # every other tag
    h = html.unescape(h)
    h = re.sub(r"[ \t\xa0\u200b]+", " ", h)  # spaces, tabs, non-breaking and zero-width spaces become one space
    h = re.sub(r" *\n *", "\n", h)
    h = re.sub(r"\n{3,}", "\n\n", h)
    return h.strip()


def clean(s) -> str:
    """`s` as text, with every run of whitespace (spaces, tabs, line breaks) made one space, and trimmed. None gives ""."""
    return re.sub(r"\s+", " ", str(s or "")).strip()


# ---------------------------------------------------------------- spotting duplicates

# Words in a company name that don't tell companies apart: legal endings ("Inc", "LLC"), "The", "USA", "Group" and so on.
_CO_SUFFIX = re.compile(r"\b(inc|llc|l\.l\.c|corp|corporation|co|company|ltd|limited|the|plc|lp|usa|us|holdings|group)\b\.?", re.I)


def norm_company(c: str) -> str:
    """A company name reduced for comparing: lowercase, without legal endings or punctuation. "The Acme Company, Inc."
    and "ACME" both give "acme"."""
    c = _CO_SUFFIX.sub(" ", (c or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", c).strip()


def norm_title(t: str) -> str:
    """A job title reduced for comparing: lowercase letters and digits separated by single spaces."""
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def state_of(loc: str) -> str | None:
    """Where a location string is, as far as the text tells: a two-letter state code ("OH", "DC"), "REMOTE", "FOREIGN"
    (another country), or None when it can't be told.

    The checks run in this order, and the order matters:
    1. A remote word wins, so "Remote, Canada" gives "REMOTE". LocationMatcher looks for the country separately.
    2. Washington, DC, before "Washington" can be read as the state.
    3. Another country, unless the text also names the US.
    4. A two-letter code in the usual places: "USA - TX", ", TX", or "TX" at the end (a ZIP code may follow).
    5. A full state name. "West Virginia" is never read as "Virginia".
    6. A well-known city without its state, from CITY_STATE.
    Steps 2 to 4 are case-sensitive ("DC", "TX"); steps 5 and 6 aren't."""
    if not loc:
        return None
    if REMOTE_RE.search(loc):
        return "REMOTE"
    if re.search(r"\bD\.?C\.?\b|District of Columbia", loc):
        return "DC"
    if _names_foreign_place(loc):
        return "FOREIGN"
    code = (re.search(r"\bUSA?\s*-\s*([A-Z]{2})\b", loc) or re.search(r",\s*([A-Z]{2})\b", loc)
            or re.search(r"\b([A-Z]{2})\s*(?:\d{5})?\s*$", loc))
    if code and code.group(1) in STATES:
        return code.group(1)
    low = loc.lower()
    for name, abbr in NAME_TO_ABBR.items():
        # "virginia" comes before "west virginia" in this dict, so the lookbehind stops it from claiming West Virginia.
        if re.search(rf"(?<!west )\b{re.escape(name)}\b", low):
            return abbr
    for city, abbr in CITY_STATE.items():
        if re.search(rf"\b{re.escape(city)}\b", low):
            return abbr
    return None


def _names_foreign_place(loc: str, us_pattern: re.Pattern = _US_RE) -> bool:
    """True when the text names another country (FOREIGN_RE) and doesn't also name the US (`us_pattern`)."""
    return bool(FOREIGN_RE.search(loc)) and not us_pattern.search(loc)


def outside_us(loc: str) -> bool:
    """True when a location names another country and not the US ("Toronto, ON", "Remote, Canada"). The Dream list's
    location bypass uses it: dream jobs may be anywhere in the US, not anywhere in the world."""
    return _names_foreign_place(clean(loc), _US_OR_DOTTED_RE)


def fingerprint(company: str, title: str, location: str = "") -> str:
    """A short id that is the same for the same job wherever it was found: company, title and state, normalized, then
    hashed. leads.fingerprint is unique, so a job seen on two sites is stored once.

    Don't change how this is worked out. Existing databases hold the old fingerprints, so every job would come back as
    a new lead."""
    key = f"{norm_company(company)}|{norm_title(title)}|{state_of(location) or ''}"
    return hashlib.sha1(key.encode()).hexdigest()[:20]  # 20 hex digits (80 bits) is plenty to keep ids from colliding


def url_key(url: str | None) -> str | None:
    """A job link reduced for spotting duplicates, or None for an empty or unreadable link.

    It keeps the host (lowercase, without "www."), the path (lowercase, without a trailing slash) and only the query
    parameters that identify a job, such as gh_jid (Greenhouse) or jk (Indeed). Tracking parameters are dropped.
    LinkedIn job links become "linkedin:<job id>", because one LinkedIn job has many different links."""
    if not url:
        return None
    try:
        parts = urlparse(url.strip())
    except ValueError:  # for example "http://[::1" (an unclosed IPv6 address)
        return None
    host = (parts.netloc or "").lower().removeprefix("www.")
    # /jobs/view/<id> or /jobs/view/<title-words>-<id>. LinkedIn job ids have at least 6 digits.
    linkedin = re.search(r"linkedin\.com/jobs/view/(?:[^/?]*-)?(\d{6,})", url)
    if linkedin:
        return f"linkedin:{linkedin.group(1)}"
    query = parse_qs(parts.query)
    job_params = [f"{k}={query[k][0]}" for k in ("gh_jid", "jobId", "jobid", "jk", "id", "opportunityId", "job") if k in query]
    return f"{host}{parts.path.rstrip('/').lower()}" + (("?" + "&".join(job_params)) if job_params else "")


# ---------------------------------------------------------------- dates

def parse_date(v) -> str | None:
    """A date as "YYYY-MM-DD", read from whatever a job board sends, or None when it can't be read.

    Understands Unix timestamps (seconds or milliseconds, as numbers or digit strings), relative phrases ("today",
    "3 hours ago", "yesterday", "Posted 3 Days Ago", "30+ days ago"), ISO dates ("2026-10-01T12:00:00Z"), email-style
    dates ("Tue, 01 Oct 2026 10:00:00 GMT") and a few written forms ("10/01/2026", "October 1, 2026", "1 October 2026").
    Relative phrases count back from today in UTC, and a month counts as 30 days."""
    if v in (None, "", 0):
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
            seconds = float(v)
            if seconds > 1e12:  # milliseconds: a timestamp in seconds won't reach 1e12 for thousands of years
                seconds /= 1000
            return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()
        text = str(v).strip()
        low = text.lower()
        today = datetime.now(timezone.utc).date()
        if "today" in low or "just now" in low or re.search(r"\b\d+\s*(hour|minute)s?\b", low):
            return today.isoformat()
        if "yesterday" in low:
            return (today - timedelta(days=1)).isoformat()
        ago = re.search(r"(\d+)\+?\s*(day|week|month)s?\s*ago", low)
        if ago:
            days = int(ago.group(1)) * {"day": 1, "week": 7, "month": 30}[ago.group(2)]
            return (today - timedelta(days=days)).isoformat()
        iso = re.match(r"\d{4}-\d{2}-\d{2}", text)
        if iso:
            return iso.group(0)
        try:
            return parsedate_to_datetime(text).date().isoformat()  # the email date format (RFC 2822), common in RSS
        except (TypeError, ValueError):
            pass
        for fmt in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
    except (ValueError, OverflowError, OSError):  # for example a timestamp outside the range the system clock handles
        return None
    return None


def age_days(iso: str | None) -> int | None:
    """Days from an ISO date (only its first 10 characters are read) to today in UTC. Negative for a date in the future,
    None when there's no date or it can't be read."""
    if not iso:
        return None
    try:
        return (datetime.now(timezone.utc).date() - datetime.fromisoformat(iso[:10]).date()).days
    except ValueError:
        return None


# ---------------------------------------------------------------- the search area

class LocationMatcher:
    """Checks job locations against the user's search area (the "locations.allowed" setting).

    Each allowed entry is sorted into one of four kinds when the matcher is made:
      "Anywhere in the US", "Nationwide", "USA" or "US"   anywhere_us: any US state passes
      an entry with a remote word, such as "Remote"      allow_remote: remote jobs pass
      a state ("Ohio", "OH") or DC ("Washington, DC")    added to states
      anything else, read as a city ("Pittsburgh, PA")   only the name before the first comma is matched, as a whole
                                                         word, so "Portland, OR" also matches "Portland, ME"

    match_one() answers True (inside the area), False (known, and outside it) or None (can't tell). search/pipeline.py
    drops False, and treats None as the "unknown location" setting says. Letting dream companies skip the area
    (locations.dream_bypass) is decided in pipeline.py, not here."""

    def __init__(self, allowed: list[str]):
        self.allow_remote = False
        self.anywhere_us = False
        self.states: set[str] = set()  # two-letter codes, "DC" included
        self.cities: list[re.Pattern] = []
        for entry in allowed:
            entry = entry.strip()
            if not entry:
                continue
            if _NATIONWIDE_RE.fullmatch(entry.lower()):  # checked before remote, since "anywhere" is also a remote word
                self.anywhere_us = True
            elif REMOTE_RE.search(entry):
                self.allow_remote = True
            else:
                state = _state_code(entry)
                if state:
                    self.states.add(state)
                else:
                    city = entry.split(",")[0].strip()
                    if city:
                        self.cities.append(re.compile(rf"\b{re.escape(city)}\b", re.I))

    def match_one(self, loc: str) -> bool | None:
        """Check one location: True (inside the search area), False (known, and outside it) or None (can't tell)."""
        loc = clean(loc)

        # 1. Vague text ("TBD", "Multiple locations", "United States") passes only a nationwide search, and only when it
        #    actually says US or nationwide. Otherwise nobody can tell.
        if UNKNOWN_LOC.match(loc):
            return True if self.anywhere_us and _SAYS_US_RE.search(loc) else None

        # 2. A nationwide search takes any US state. A hybrid job that names a US place ("Hybrid Remote - Austin, TX") is
        #    partly on-site there, so it passes too. A fully remote US job passes only if Remote is allowed as well.
        if self.anywhere_us:
            where = state_of(loc)
            if where and where not in ("FOREIGN", "REMOTE"):
                return True
            if where == "REMOTE" and not _names_foreign_place(loc):
                if _HYBRID_RE.search(loc) and state_of(REMOTE_RE.sub("", loc)) not in (None, "FOREIGN", "REMOTE"):
                    return True
                return self.allow_remote

        # 3. A remote job passes when Remote is allowed, unless it's tied to another country ("Remote, Canada").
        if REMOTE_RE.search(loc) and self.allow_remote and not _names_foreign_place(loc, _US_OR_DOTTED_RE):
            return True
        # Otherwise keep going: "Remote" plus a city can still be inside the area (a hybrid listing).

        # 4. One of the chosen cities is named.
        if any(city.search(loc) for city in self.cities):
            return True

        # 5. The state, read with the remote words taken out, so "Remote, OH" counts as Ohio.
        where = state_of(REMOTE_RE.sub("", loc))
        if where and where in self.states:
            return True
        # A known place that isn't chosen (another state, or FOREIGN), or a remote job Remote didn't allow, is outside.
        if where or REMOTE_RE.search(loc):
            return False
        return None

    def match(self, locations: list[str] | str) -> bool | None:
        """Check a job that may list several locations: True if any of them passes, False if every one is outside the
        area, otherwise None. A string is split into locations first (on ";", "|", "/", " or " and line breaks), so
        "Austin, TX / Remote" counts as two."""
        if isinstance(locations, str):
            parts = [p for p in _LOCATION_SPLIT_RE.split(locations) if p.strip()] or [locations]
        else:
            parts = locations or [""]
        results = [self.match_one(p) for p in parts]
        if any(r is True for r in results):
            return True
        if all(r is False for r in results):
            return False
        return None


def _state_code(entry: str) -> str | None:
    """The two-letter code when an allowed-location entry names a state ("OH" or "Ohio") or DC, else None."""
    if entry.upper() in STATES:
        return entry.upper()
    if entry.lower() in NAME_TO_ABBR:
        return NAME_TO_ABBR[entry.lower()]
    if re.search(r"\bD\.?C\.?\b|district of columbia", entry, re.I):
        return "DC"
    return None


# ---------------------------------------------------------------- keywords

# Tech terms extract_terms() looks for when the AI didn't list a job's keywords.
TECH_TERMS = [
    "c", "c++", "c#", "rust", "python", "java", "javascript", "typescript", "swift", "go", "ada", "matlab", "simulink",
    "sql", "html", "css", "react", "node.js", "linux", "unix", "git", "docker", "kubernetes", "aws", "azure", "gcp",
    "cuda", "vulkan", "pytorch", "tensorflow", "numpy", "pandas", "machine learning", "deep learning", "computer vision",
    "embedded", "rtos", "microcontroller", "fpga", "verilog", "vhdl", "firmware", "flight software", "gnc", "guidance",
    "navigation", "controls", "orbital mechanics", "astrodynamics", "kalman", "simulation", "systems engineering",
    "requirements", "verification", "validation", "test", "ci/cd", "agile", "jira", "rf", "sdr", "dsp",
    "signal processing", "remote sensing", "gis", "satellite", "spacecraft", "avionics", "ground software",
    "telemetry", "data analysis", "data science", "statistics", "linear algebra", "rest", "api", "networking",
    "security", "cybersecurity", "cloud", "devops", "bash", "shell", "ros", "robotics", "autonomy", "mission",
    "hardware", "soldering", "cad", "3d printing", "llm", "ai", "nlp", "ios", "swiftui", "mobile", "web",
]

# Letters, digits, + and # count as part of a word, so "c" isn't found inside "c++" or "c#", and "go" isn't found
# inside "google".
_WORD_CHARS = "a-z0-9+#"
_WORD_RE = re.compile(rf"[{_WORD_CHARS}]+")


def _whole_word(term: str) -> str:
    """A regex that finds `term` in lowercase text only as a whole word (see _WORD_CHARS)."""
    return rf"(?<![{_WORD_CHARS}]){re.escape(term)}(?![{_WORD_CHARS}])"


def extract_terms(text: str) -> list[str]:
    """The TECH_TERMS found in `text`, in TECH_TERMS order. search/pipeline.py uses them as a job's keywords when the AI
    didn't list any."""
    low = (text or "").lower()
    return [term for term in TECH_TERMS if re.search(_whole_word(term), low)]


# Words too common to count when a keyword phrase is compared word by word.
_STOP = {"and", "or", "the", "of", "to", "in", "for", "with", "a", "an", "on", "experience", "knowledge", "skills", "concepts"}


def _stem(w: str) -> str:
    """A rough word stem, so "testing", "tested" and "tests" all become "test". Drops one common ending, then one letter
    of a doubled final pair ("running" -> "runn" -> "run")."""
    w = re.sub(r"(ations?|ings?|ed|ers?|ments?|ies|es|s)$", "", w)
    return w[:-1] if len(w) > 3 and w[-1] == w[-2] else w


def _phrase_hit(phrase: str, low: str, stems: set[str]) -> bool:
    """Does the resume (`low`: its text in lowercase, `stems`: the stems of its words) contain this keyword phrase?

    Yes when the exact phrase appears as whole words. Otherwise the phrase's words, minus filler like "and" or
    "experience", are compared by stem. One word must be longer than 3 letters and have its stem present. A phrase of 2
    or 3 words needs every stem. A longer phrase needs at least three quarters of them."""
    if re.search(_whole_word(phrase), low):
        return True
    words = [t for t in _WORD_RE.findall(phrase) if t not in _STOP]
    if not words:
        return False
    if len(words) == 1:
        return len(words[0]) > 3 and _stem(words[0]) in stems
    share = sum(_stem(t) in stems for t in words) / len(words)
    return share == 1 if len(words) <= 3 else share >= 0.75


def coverage(keywords: list[str], text: str) -> tuple[float, list[str], list[str]]:
    """How much of a job's keyword list a resume covers: (share found, keywords found, keywords missing).

    Text in parentheses is ignored, and "A / B" or "A or B" counts when either one is found. A keyword is found when it
    appears exactly, or when enough of its words appear in some form (see _phrase_hit), roughly how applicant tracking
    systems scan a resume. The share is rounded to 3 decimals, and is 0.0 when there are no keywords."""
    low = (text or "").lower()
    stems = {_stem(t) for t in _WORD_RE.findall(low)}
    hit, miss = [], []
    for k in keywords:
        bare = re.sub(r"\(.*?\)", "", k.lower()).strip()
        if not bare:
            continue
        alternatives = [a.strip() for a in re.split(r"\s*/\s*|\s+or\s+", bare) if a.strip()] or [bare]
        (hit if any(_phrase_hit(a, low, stems) for a in alternatives) else miss).append(k)
    total = len(hit) + len(miss)
    return (round(len(hit) / total, 3) if total else 0.0), hit, miss
