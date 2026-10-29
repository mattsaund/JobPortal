"""Text helpers: HTML → text, dedupe fingerprints, date parsing, location matching."""
import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlparse

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
NAME_TO_ABBR = {v.lower(): k for k, v in STATES.items()}

# Cities that often appear without a state, mapped to their state (US metros and common employer hubs).
CITY_STATE = {
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
}
CITY_STATE.update({
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
})
FOREIGN_RE = re.compile(
    r"\b(uk|u\.k\.|united kingdom|england|scotland|wales|ireland|canada|germany|france|spain|italy|netherlands|"
    r"switzerland|sweden|norway|denmark|finland|poland|india|china|japan|korea|singapore|australia|new zealand|"
    r"israel|mexico|brazil|argentina|uae|united arab emirates|dubai|philippines|vietnam|taiwan|hong kong|portugal|"
    r"belgium|austria|czech|romania|ukraine|luxembourg|estonia|emea|apac|latam)\b"
    r"|,\s*(ON|QC|BC|AB|MB|SK|NS|NB|NL|PE)\b", re.I)
UNKNOWN_LOC = re.compile(r"^\s*(|n/?a|tbd|various|multiple( locations)?|\d+ locations?|united states( of america)?|usa?|u\.s\.a?\.?|nationwide|us-?nationwide|north america)\s*$", re.I)
REMOTE_RE = re.compile(r"\b(remote|anywhere|work from home|wfh|virtual|telework|teleworking|distributed)\b", re.I)


def html_to_text(h: str | None) -> str:
    if not h:
        return ""
    if "&lt;" in h and "<" not in h[:200]:
        h = html.unescape(h)
    h = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    h = re.sub(r"(?i)</(p|div|h[1-6]|tr|section|article|ul|ol|header|footer)>", "\n", h)
    h = re.sub(r"(?i)<li[^>]*>", "\n• ", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = html.unescape(h)
    h = re.sub(r"[ \t\xa0​]+", " ", h)
    h = re.sub(r" *\n *", "\n", h)
    h = re.sub(r"\n{3,}", "\n\n", h)
    return h.strip()


def clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


_CO_SUFFIX = re.compile(r"\b(inc|llc|l\.l\.c|corp|corporation|co|company|ltd|limited|the|plc|lp|usa|us|holdings|group)\b\.?", re.I)


def norm_company(c: str) -> str:
    c = _CO_SUFFIX.sub(" ", (c or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", c).strip()


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def state_of(loc: str) -> str | None:
    """Best-effort two-letter state (or 'REMOTE') for a location string."""
    if not loc:
        return None
    if REMOTE_RE.search(loc):
        return "REMOTE"
    if re.search(r"\bD\.?C\.?\b|District of Columbia", loc):
        return "DC"
    if FOREIGN_RE.search(loc) and not re.search(r"\b(US|USA|United States)\b", loc):
        return "FOREIGN"
    m = (re.search(r"\bUSA?\s*-\s*([A-Z]{2})\b", loc) or re.search(r",\s*([A-Z]{2})\b", loc)
         or re.search(r"\b([A-Z]{2})\s*(?:\d{5})?\s*$", loc))
    if m and m.group(1) in STATES:
        return m.group(1)
    low = loc.lower()
    for name, ab in NAME_TO_ABBR.items():
        if re.search(rf"(?<!west )\b{re.escape(name)}\b", low):
            return ab
    for city, ab in CITY_STATE.items():
        if re.search(rf"\b{re.escape(city)}\b", low):
            return ab
    return None


def fingerprint(company: str, title: str, location: str = "") -> str:
    key = f"{norm_company(company)}|{norm_title(title)}|{state_of(location) or ''}"
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def url_key(url: str | None) -> str | None:
    if not url:
        return None
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    host = (u.netloc or "").lower().removeprefix("www.")
    m = re.search(r"linkedin\.com/jobs/view/(?:[^/?]*-)?(\d{6,})", url)
    if m:
        return f"linkedin:{m.group(1)}"
    qs = parse_qs(u.query)
    keep = [f"{k}={qs[k][0]}" for k in ("gh_jid", "jobId", "jobid", "jk", "id", "opportunityId", "job") if k in qs]
    return f"{host}{u.path.rstrip('/').lower()}" + (("?" + "&".join(keep)) if keep else "")


def parse_date(v) -> str | None:
    """Return an ISO date (YYYY-MM-DD) from epoch seconds/ms, ISO strings, RFC 2822, or 'Posted 3 Days Ago'."""
    if v in (None, "", 0):
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
            n = float(v)
            if n > 1e12:
                n /= 1000
            return datetime.fromtimestamp(n, tz=timezone.utc).date().isoformat()
        s = str(v).strip()
        low = s.lower()
        today = datetime.now(timezone.utc).date()
        if "today" in low or "just now" in low or re.search(r"\b\d+\s*(hour|minute)s?\b", low):
            return today.isoformat()
        if "yesterday" in low:
            return (today - timedelta(days=1)).isoformat()
        m = re.search(r"(\d+)\+?\s*(day|week|month)s?\s*ago", low)
        if m:
            n = int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2)]
            return (today - timedelta(days=n)).isoformat()
        m = re.match(r"\d{4}-\d{2}-\d{2}", s)
        if m:
            return m.group(0)
        try:
            return parsedate_to_datetime(s).date().isoformat()
        except (TypeError, ValueError):
            pass
        for fmt in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
            try:
                return datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                continue
    except (ValueError, OverflowError, OSError):
        return None
    return None


def age_days(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return (datetime.now(timezone.utc).date() - datetime.fromisoformat(iso[:10]).date()).days
    except ValueError:
        return None


class LocationMatcher:
    """Matches a job's location text against the user's allowed locations.

    Returns True (allowed), False (known and not allowed) or None (unknown/ambiguous)."""

    def __init__(self, allowed: list[str]):
        self.allow_remote = False
        self.anywhere_us = False
        self.states: set[str] = set()
        self.cities: list[re.Pattern] = []
        for a in allowed:
            a = a.strip()
            if not a:
                continue
            if re.fullmatch(r"(anywhere( in the)?( us| usa| united states)?|nationwide|united states|usa|us)", a.lower()):
                self.anywhere_us = True
                continue
            if REMOTE_RE.search(a):
                self.allow_remote = True
                continue
            st = None
            if a.upper() in STATES:
                st = a.upper()
            elif a.lower() in NAME_TO_ABBR:
                st = NAME_TO_ABBR[a.lower()]
            elif re.search(r"\bD\.?C\.?\b|district of columbia", a, re.I):
                st = "DC"
            if st:
                self.states.add(st)
            else:
                city = a.split(",")[0].strip()
                if city:
                    self.cities.append(re.compile(rf"\b{re.escape(city)}\b", re.I))

    def match_one(self, loc: str) -> bool | None:
        loc = clean(loc)
        if UNKNOWN_LOC.match(loc):
            return True if self.anywhere_us and re.search(r"united states|\bus\b|usa|nationwide", loc, re.I) else None
        if self.anywhere_us:
            st = state_of(loc)
            if st and st not in ("FOREIGN", "REMOTE"):
                return True
            if st == "REMOTE" and not (FOREIGN_RE.search(loc) and not re.search(r"\b(US|USA|United States)\b", loc)):
                return self.allow_remote
        if REMOTE_RE.search(loc):
            foreign = FOREIGN_RE.search(loc) and not re.search(r"\b(US|USA|United States|U\.S\.)\b", loc)
            if self.allow_remote and not foreign:
                return True
            # "Remote" plus a city can still be in range (hybrid listings)
        if any(p.search(loc) for p in self.cities):
            return True
        st = state_of(re.sub(REMOTE_RE, "", loc))
        if st and st in self.states:
            return True
        if st or REMOTE_RE.search(loc):
            return False
        return None

    def match(self, locations: list[str] | str) -> bool | None:
        if isinstance(locations, str):
            parts = [p for p in re.split(r"\s*(?:;|\||/| or |\n)\s*", locations) if p.strip()] or [locations]
        else:
            parts = locations or [""]
        results = [self.match_one(p) for p in parts]
        if any(r is True for r in results):
            return True
        if all(r is False for r in results):
            return False
        return None


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


def extract_terms(text: str, extra: list[str] | None = None) -> list[str]:
    low = (text or "").lower()
    found = []
    for t in TECH_TERMS + [e.lower() for e in (extra or [])]:
        pat = rf"(?<![a-z0-9+#]){re.escape(t)}(?![a-z0-9+#])"
        if t not in found and re.search(pat, low):
            found.append(t)
    return found


_STOP = {"and", "or", "the", "of", "to", "in", "for", "with", "a", "an", "on", "experience", "knowledge", "skills", "concepts"}


def _stem(w: str) -> str:
    w = re.sub(r"(ations?|ings?|ed|ers?|ments?|ies|es|s)$", "", w)
    return w[:-1] if len(w) > 3 and w[-1] == w[-2] else w


def _phrase_hit(phrase: str, low: str, stems: set[str]) -> bool:
    if re.search(rf"(?<![a-z0-9+#]){re.escape(phrase)}(?![a-z0-9+#])", low):
        return True
    toks = [t for t in re.findall(r"[a-z0-9+#]+", phrase) if t not in _STOP]
    if not toks:
        return False
    if len(toks) == 1:
        return len(toks[0]) > 3 and _stem(toks[0]) in stems
    share = sum(_stem(t) in stems for t in toks) / len(toks)
    return share == 1 if len(toks) <= 3 else share >= 0.75


def coverage(keywords: list[str], text: str) -> tuple[float, list[str], list[str]]:
    """Share of job keywords present in the resume. A keyword counts if any '/'-separated alternative matches
    exactly, or (for phrases) most of its words appear in stemmed form, roughly how ATS keyword scans behave."""
    low = (text or "").lower()
    stems = {_stem(t) for t in re.findall(r"[a-z0-9+#]+", low)}
    hit, miss = [], []
    for k in keywords:
        k2 = re.sub(r"\(.*?\)", "", k.lower()).strip()
        if not k2:
            continue
        alts = [a.strip() for a in re.split(r"\s*/\s*|\s+or\s+", k2) if a.strip()] or [k2]
        (hit if any(_phrase_hit(a, low, stems) for a in alts) else miss).append(k)
    total = len(hit) + len(miss)
    return (round(len(hit) / total, 3) if total else 0.0), hit, miss
