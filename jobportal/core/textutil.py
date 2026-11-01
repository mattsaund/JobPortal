"""Text helpers for the search, the documents and the dashboard routes.

What's here:
- Cleaning text: html_to_text() turns a posting's HTML into plain text, and clean() collapses whitespace.
- Spotting duplicates: fingerprint() and url_key() give the same answer for the same job found on two sites.
- Dates: parse_date() reads the many date formats job boards use, and age_days() says how old a date is.
- Locations: state_of() works out where a location string is, and LocationMatcher checks a job's locations against the
  user's search area. search/pipeline.py drops jobs outside the area before any AI sees them.
- Keywords: extract_terms() finds the skills, tools, certifications and licenses a posting (or any document) names, for
  any field, and coverage() measures how many of a job's keywords a resume contains, roughly the way applicant tracking
  systems scan resumes.
- Target roles: TargetMatcher tells whether a job title is near the user's target roles, role families and search
  queries. It's the rule filters' cheap pre-filter, so AI triage doesn't spend tokens on jobs from unrelated fields.

Nothing here touches the network, the database or the AI, so every function is easy to try out and test (see
tests/test_core.py)."""
import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
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
# first match wins. Job fingerprints are built from state_of(), so an entry here should never be removed or changed (see
# fingerprint()). Search locations come from MAJOR_CITIES instead.
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
    # Other big metros and places postings name often
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
# The largest cities of every state and DC, biggest first: the places a search covers when the user names only a state
# (search/collectors/feeds.py turns "Ohio" into these for The Muse, whose location filter wants cities).
MAJOR_CITIES = {
    "AL": ["Birmingham", "Huntsville", "Montgomery", "Mobile"], "AK": ["Anchorage", "Fairbanks", "Juneau"],
    "AZ": ["Phoenix", "Tucson", "Mesa", "Scottsdale"], "AR": ["Little Rock", "Fayetteville", "Fort Smith"],
    "CA": ["Los Angeles", "San Diego", "San Jose", "San Francisco", "Sacramento", "Fresno"],
    "CO": ["Denver", "Colorado Springs", "Aurora", "Boulder"], "CT": ["Hartford", "New Haven", "Stamford", "Bridgeport"],
    "DE": ["Wilmington", "Dover", "Newark"], "FL": ["Miami", "Orlando", "Tampa", "Jacksonville"],
    "GA": ["Atlanta", "Savannah", "Augusta"], "HI": ["Honolulu", "Hilo"], "ID": ["Boise", "Meridian", "Idaho Falls"],
    "IL": ["Chicago", "Naperville", "Rockford", "Springfield"], "IN": ["Indianapolis", "Fort Wayne", "Evansville"],
    "IA": ["Des Moines", "Cedar Rapids", "Iowa City"], "KS": ["Wichita", "Overland Park", "Kansas City", "Topeka"],
    "KY": ["Louisville", "Lexington", "Bowling Green"], "LA": ["New Orleans", "Baton Rouge", "Shreveport", "Lafayette"],
    "ME": ["Portland", "Bangor", "Augusta"], "MD": ["Baltimore", "Columbia", "Rockville", "Frederick", "Annapolis"],
    "MA": ["Boston", "Worcester", "Springfield", "Cambridge"], "MI": ["Detroit", "Grand Rapids", "Ann Arbor", "Lansing"],
    "MN": ["Minneapolis", "Saint Paul", "Rochester", "Duluth"], "MS": ["Jackson", "Gulfport", "Hattiesburg"],
    "MO": ["Kansas City", "St. Louis", "Springfield", "Columbia"], "MT": ["Billings", "Missoula", "Bozeman", "Helena"],
    "NE": ["Omaha", "Lincoln"], "NV": ["Las Vegas", "Reno", "Henderson"], "NH": ["Manchester", "Nashua", "Concord"],
    "NJ": ["Newark", "Jersey City", "Trenton", "Princeton"], "NM": ["Albuquerque", "Santa Fe", "Las Cruces"],
    "NY": ["New York", "Buffalo", "Rochester", "Albany", "Syracuse"], "NC": ["Charlotte", "Raleigh", "Durham", "Greensboro"],
    "ND": ["Fargo", "Bismarck", "Grand Forks"], "OH": ["Columbus", "Cleveland", "Cincinnati", "Dayton", "Toledo"],
    "OK": ["Oklahoma City", "Tulsa", "Norman"], "OR": ["Portland", "Salem", "Eugene", "Bend"],
    "PA": ["Philadelphia", "Pittsburgh", "Harrisburg", "Allentown"], "RI": ["Providence", "Warwick", "Newport"],
    "SC": ["Charleston", "Columbia", "Greenville"], "SD": ["Sioux Falls", "Rapid City"],
    "TN": ["Nashville", "Memphis", "Knoxville", "Chattanooga"], "TX": ["Houston", "Dallas", "Austin", "San Antonio", "Fort Worth"],
    "UT": ["Salt Lake City", "Provo", "Ogden"], "VT": ["Burlington", "Montpelier"],
    "VA": ["Richmond", "Virginia Beach", "Arlington", "Norfolk", "Alexandria"], "WA": ["Seattle", "Spokane", "Tacoma", "Bellevue"],
    "WV": ["Charleston", "Morgantown", "Huntington"], "WI": ["Milwaukee", "Madison", "Green Bay"],
    "WY": ["Cheyenne", "Casper", "Laramie"], "DC": ["Washington"],
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

# Letters, digits, + and # count as part of a word, so "c" isn't found inside "c++" or "c#", and "go" isn't found
# inside "google".
_WORD_CHARS = "a-z0-9+#"
_WORD_RE = re.compile(rf"[{_WORD_CHARS}]+")


def _whole_word(term: str) -> str:
    """A regex that finds `term` in lowercase text only as a whole word (see _WORD_CHARS)."""
    return rf"(?<![{_WORD_CHARS}]){re.escape(term)}(?![{_WORD_CHARS}])"


# The vocabulary extract_terms() looks for, grouped by field only to keep it readable: every group is looked for in every
# text. An entry is the term as it should read, or (term, regex) when the plain term would also match ordinary words (the
# regex runs on lowercase text). Credentials come first because postings and certificates name them the most exactly.
VOCABULARY = {
    "credentials": [
        ("RN", r"\brn\b|registered nurse"), ("LPN", r"\blpn\b|licensed practical nurse"), ("LVN", r"\blvn\b"),
        ("CNA", r"\bcna\b|certified nursing assistant"), ("BSN", r"\bbsn\b"), ("NCLEX", r"\bnclex"),
        ("EMT", r"\bemt\b|emergency medical technician"), ("Paramedic", r"paramedic"), ("BLS", r"\bbls\b|basic life support"),
        ("ACLS", r"\bacls\b"), ("PALS", r"\bpals\b"), ("CPR", r"\bcpr\b"), ("First aid", r"first aid"),
        ("CPhT", r"\bcpht\b|certified pharmacy technician"), ("CMA", r"\bcma\b"), ("CPC", r"\bcpc\b|certified professional coder"),
        ("RHIT", r"\brhit\b"), ("BCBA", r"\bbcba\b"), ("RBT", r"\brbt\b"), ("LCSW", r"\blcsw\b"), ("LPC", r"\blpc\b"),
        ("CDL Class A", r"class a cdl|cdl[- ]a\b|cdl class a"), ("CDL", r"\bcdl\b|commercial driver'?s licen[cs]e"),
        ("HAZMAT endorsement", r"hazmat endorsement"), ("Forklift certification", r"forklift (?:certif|operator card)"),
        ("OSHA 10", r"\bosha[- ]?10\b"), ("OSHA 30", r"\bosha[- ]?30\b"), ("EPA 608", r"\bepa[- ]?608"),
        ("ASE certification", r"\base\b(?:[- ]certified| certification)"), ("A&P license", r"\ba&p\b"),
        ("Journeyman license", r"journeym[ae]n (?:licen[cs]e|card)"), ("ServSafe", r"servsafe"), ("Food handler card", r"food handler"),
        ("TIPS certification", r"\btips (?:certif|trained)"), ("CPA", r"\bcpa\b"), ("CFA", r"\bcfa\b"), ("Series 7", r"\bseries 7\b"),
        ("PMP", r"\bpmp\b"), ("Six Sigma", r"six sigma"), ("SHRM-CP", r"\bshrm-?cp\b"), ("PHR", r"\bphr\b"), ("Notary public", r"\bnotary"),
        ("Real estate license", r"real estate licen[cs]e"),
        ("Teaching license", r"teaching (?:licen[cs]e|certificat)|teacher certification|certified teacher"),
        ("Praxis", r"\bpraxis\b"), ("CDA", r"\bcda\b|child development associate"), ("TEFL/TESOL", r"\btefl\b|\btesol\b"),
        ("CompTIA A+", r"comptia a\+|\ba\+ certif"), ("CompTIA Security+", r"security\+"), ("CCNA", r"\bccna\b"),
        ("AWS certification", r"\baws certified|\baws certification"), ("CISSP", r"\bcissp\b"),
        ("PE license", r"professional engineer|\bpe licen[cs]e"), ("EIT", r"\beit\b|engineer in training"), ("LEED", r"\bleed\b"),
        ("Driver's license", r"driver'?s licen[cs]e"), ("Security clearance", r"security clearance|secret clearance"),
    ],
    "healthcare": [
        "patient care", "vital signs", "phlebotomy", "medication administration", ("EHR", r"\behr\b|\bemr\b|electronic (?:health|medical) record"),
        ("Epic", r"\bepic (?:ehr|emr|systems?|certified|charting|experience)"), "Cerner", "Meditech", ("HIPAA", r"\bhipaa\b"),
        "triage", "wound care", ("IV therapy", r"\biv (?:therapy|insertion|starts|access)|intravenous"), "charting",
        "infection control", "medical terminology", ("ICD-10", r"\bicd-?10"), ("CPT coding", r"\bcpt\b"), "medical billing",
        "medical coding", "telemetry", "dementia care", "home health", "hospice", "pediatrics", "geriatrics", "behavioral health",
        "case management", "crisis intervention", "care planning", "patient education", "sterile technique", "specimen collection",
        ("Med-surg", r"\bmed[- ]?surg"), ("ICU", r"\bicu\b"), "dialysis", "physical therapy", "occupational therapy", "radiology",
        "insurance verification", "prior authorization",
    ],
    "trades": [
        "forklift", "pallet jack", "power tools", "hand tools", ("Blueprint reading", r"blueprint"), "welding",
        ("MIG welding", r"\bmig\b"), ("TIG welding", r"\btig\b"), "stick welding", ("HVAC", r"\bhvac"), "refrigeration",
        ("Electrical wiring", r"\bwiring\b"), ("NEC", r"\bnec\b|national electrical code"), "plumbing", "carpentry", "framing",
        "drywall", "concrete", "roofing", ("CNC", r"\bcnc\b"), "machining", ("Lockout/tagout", r"lockout[/ -]?tagout|\bloto\b"),
        "preventive maintenance", "troubleshooting", "hydraulics", "pneumatics", ("PLC", r"\bplc\b"), "diesel", "inventory control",
        "shipping and receiving", "order picking", ("DOT regulations", r"\bdot (?:regulations|physical|compliance|medical)"),
        ("HAZMAT", r"\bhazmat\b"), "safety compliance", "quality control", ("GD&T", r"\bgd&t\b"), "soldering", "avionics",
        "landscaping", "irrigation", "heavy equipment", "excavator", ("Crane operation", r"crane operat"), "scaffolding",
        ("OSHA", r"\bosha\b"),
    ],
    "service": [
        ("POS systems", r"\bpos\b|point of sale"), "cash handling", "food safety", ("Food preparation", r"food prep"),
        "knife skills", "bartending", "mixology", "espresso", "customer service", "upselling", "merchandising",
        "visual merchandising", "loss prevention", "housekeeping", "front desk", "reservations", "guest relations", "catering",
        "baking", "cake decorating", "cosmetology", ("Hair cutting", r"hair ?cut"), ("Hair color", r"hair colou?r"),
        "massage therapy", "personal training", "lifeguarding",
    ],
    "business": [
        ("Microsoft Excel", r"microsoft excel|\bms excel|\bexcel\b(?! in\b| at\b| as\b)"), ("Microsoft Word", r"microsoft word|\bms word"),
        ("Microsoft Office", r"microsoft office|\bms office|office 365|microsoft 365"), ("Outlook", r"microsoft outlook"),
        "Google Workspace", "Google Sheets", "QuickBooks", ("SAP", r"\bsap\b"), "Salesforce", ("CRM", r"\bcrm\b"), ("ERP", r"\berp\b"),
        "HubSpot", "accounts payable", "accounts receivable", "bookkeeping", "payroll", ("GAAP", r"\bgaap\b"), "financial reporting",
        "budgeting", "forecasting", "reconciliation", ("Auditing", r"\baudit"), "tax preparation", "data entry",
        "calendar management", "recruiting", "onboarding", ("HRIS", r"\bhris\b"), ("ADP", r"\badp\b"),
        ("Workday", r"\bworkday (?:hcm|hris|experience|system)"), "cold calling", "lead generation", "negotiation",
        "account management", "contract management", "compliance", "risk management", "project management", "scrum", "kanban",
        ("Lean", r"\blean (?:manufacturing|principles|methodolog)"), ("SEO", r"\bseo\b"), ("SEM", r"\bsem\b"),
        "Google Analytics", "Google Ads", "social media marketing", "email marketing", "content creation", "copywriting",
        "public relations", "event planning", "market research", "legal research", "Westlaw", ("LexisNexis", r"\blexis"),
        "litigation", "contract drafting", ("E-discovery", r"\be-?discovery"),
    ],
    "education": [
        "lesson planning", "classroom management", "curriculum development", "differentiated instruction", ("IEP", r"\biep\b"),
        "special education", ("ESL", r"\besl\b|english as a second language"), "tutoring", "early childhood education",
        "child development", "student engagement", "behavior management", "Google Classroom", ("Canvas", r"\bcanvas (?:lms|learning)"),
        "Blackboard", "instructional design", "literacy", "phonics",
    ],
    "creative": [
        ("Adobe Creative Suite", r"adobe creative (?:suite|cloud)"), "Photoshop", ("Illustrator", r"adobe illustrator"), "InDesign",
        ("Premiere Pro", r"premiere pro|adobe premiere"), "After Effects", "Lightroom", "Figma", "Canva", "Final Cut Pro",
        "DaVinci Resolve", "Pro Tools", "Logic Pro", "Ableton", "Blender", ("Maya", r"autodesk maya"), "typography", "branding",
        "photography", "videography", "video editing", "copy editing", ("AP style", r"\bap style"), "storytelling", "illustration",
        "animation", "graphic design", "UX design", "UI design", "drawing", "painting", "music production", "sound design",
        "lighting design", "stage management", "set design",
    ],
    "science": [
        ("Laboratory techniques", r"lab(?:oratory)? techniques"), ("PCR", r"\bpcr\b"), "cell culture", "microscopy",
        "chromatography", ("HPLC", r"\bhplc\b"), "spectroscopy", ("GC-MS", r"\bgc-?ms\b"), ("GLP", r"\bglp\b"),
        ("GMP", r"\bgmp\b|good manufacturing practice"), ("SPSS", r"\bspss\b"), ("SAS", r"\bsas\b"), ("Stata", r"\bstata\b"),
        ("R", r"\brstudio\b|\br programming|\bin r\b"), "statistics", "data analysis", ("GIS", r"\bgis\b|arcgis"),
        ("Field work", r"field ?work"), "sample collection", "lab safety", "experimental design", "environmental compliance",
        "water quality", "animal handling",
    ],
    "public": [
        "grant writing", "fundraising", "community outreach", "volunteer management", "program evaluation", "policy analysis",
        "public speaking", "de-escalation", "report writing", "emergency response", "conflict resolution", ("Spanish", r"\bspanish\b"),
        "bilingual", ("ASL", r"\basl\b|american sign language"),
    ],
    "tech": [
        "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Rust", ("SQL", r"\bsql\b"), "HTML", "CSS", "Node.js", "Linux",
        "Unix", "Git", "Docker", "Kubernetes", ("AWS", r"\baws\b"), "Azure", ("GCP", r"\bgcp\b"), "CUDA", "PyTorch", "TensorFlow",
        "NumPy", "pandas", "MATLAB", "Simulink", "machine learning", "deep learning", "computer vision", "RTOS", "microcontroller",
        "FPGA", "Verilog", "VHDL", "firmware", "CI/CD", "Jira", "data science", "linear algebra", "signal processing",
        "cybersecurity", "DevOps", "LLM", "NLP", "SwiftUI", "Tableau", "Power BI", "Kotlin", "PHP", "Ruby", "Terraform",
        "ServiceNow", "Active Directory",
    ],
}
# Tech terms that are also everyday words ("go", "rest", "shell", "security"). They only count in a text that is clearly
# technical: one that names at least two of the "tech" terms above.
TECH_WEAK = ["C", "Go", "Ada", "Swift", "React", "REST", "API", "testing", "web", "mobile", "shell", "Bash", "cloud", "security",
             "networking", "hardware", "embedded", "controls", "requirements", "verification", "validation", "simulation",
             "systems engineering", "agile", "RF", "DSP", "remote sensing", "robotics", "ROS", "CAD", "3D printing", "AI", "iOS"]


def _vocabulary_patterns(entries) -> list[tuple[str, re.Pattern]]:
    """(term, compiled regex) for each vocabulary entry: its own regex, or the term as a whole word."""
    out = []
    for entry in entries:
        term, pattern = entry if isinstance(entry, tuple) else (entry, _whole_word(entry.lower()))
        out.append((term, re.compile(pattern)))
    return out


_VOCAB = [(field, _vocabulary_patterns(entries)) for field, entries in VOCABULARY.items()]
_TECH_WEAK = _vocabulary_patterns(TECH_WEAK)
# "X certification", "certified X", "licensed X": the X a posting or certificate names (checked on the original text, so a
# capitalized name can be told from ordinary words).
_CREDENTIAL_PHRASE_RE = re.compile(
    r"\b((?:[A-Z][\w+&/-]*|\d+)(?: (?:[A-Z][\w+&/-]*|of|in|and|\d+)){0,5}) (?:[Cc]ertification|[Cc]ertificate|[Ll]icen[cs]e|"
    r"[Ll]icensure|[Cc]redential)\b"
    r"|\b(?:[Cc]ertified|[Ll]icensed|[Rr]egistered) ((?:[A-Z][\w+&/-]*)(?: [A-Z][\w+&/-]*){0,4})")
# Phrases on requirement lines that introduce what the job asks for: "experience with X", "proficient in X, Y and Z".
_ASKS_FOR_RE = re.compile(r"\b(?:experience (?:with|in|using|operating)|proficien(?:t|cy) (?:in|with)|knowledge of|familiar(?:ity)? "
                          r"with|skilled (?:in|with)|ability to operate|trained in|expertise in|working knowledge of)\s+([^.;:!?()\n]{2,140})",
                          re.I)
# Requirement phrases too vague to be a keyword, phrase endings that describe a setting rather than a skill, and words to
# drop from the front of a phrase.
_VAGUE = {"team", "teams", "others", "people", "customers", "clients", "the public", "deadlines", "details", "all ages",
          "a variety", "various", "multiple", "computers", "a computer", "basic computer skills", "it", "this", "them"}
_VAGUE_END = re.compile(r"\b(?:environment|setting|settings|industry|role|position|field|capacity|manner|basis)$", re.I)
_ADJECTIVES = re.compile(r"^(?:the|a|an|basic|strong|excellent|good|solid|proven|demonstrated|general|advanced|working|some|"
                         r"hands-on|current|common|standard|relevant|related|similar|various)\s+", re.I)
# Words a credential phrase may start with that aren't part of the credential's name ("a Valid CPR Certification").
_CREDENTIAL_LEAD = {"This", "The", "A", "An", "Your", "Our", "Valid", "Current", "Active", "Any", "Of", "In", "And", "Required"}


def _asked_phrases(text: str) -> list[str]:
    """What the posting's requirement lines ask for, as short phrases: "experience with point of sale systems and cash
    handling" gives "point of sale systems" and "cash handling". Phrases longer than four words, vague ones and ones that
    describe a setting ("a fast-paced environment") are skipped."""
    out = []
    for match in _ASKS_FOR_RE.finditer(text):
        for part in re.split(r",|\band/or\b|\band\b|\bor\b|\bas well as\b|\bincluding\b|\bsuch as\b", match.group(1), flags=re.I):
            phrase = clean(_ADJECTIVES.sub("", clean(part).strip(" -")))
            if (2 <= len(phrase) <= 40 and len(phrase.split()) <= 4 and phrase.lower() not in _VAGUE
                    and not _VAGUE_END.search(phrase) and not phrase[0].isdigit()):
                out.append(phrase)
    return out


def _credential_phrases(text: str) -> list[str]:
    """Certifications and licenses named in the usual ways ("Pharmacy Technician Certification", "Certified Welder",
    "Licensed Massage Therapist"), without a leading word such as "a" or "valid"."""
    out = []
    for match in _CREDENTIAL_PHRASE_RE.finditer(text):
        words = match.group(0).split()
        while words and words[0] in _CREDENTIAL_LEAD:
            words = words[1:]
        name = " ".join(words)
        # "Training and Certification" or "Department of Licensing" names an office, not a credential.
        if len(words) >= 2 and len(name) <= 60 and words[-2].lower() not in ("and", "of", "in"):
            out.append(name)
    return out


def _covered(term: str, kept: list[str]) -> bool:
    """True when `term` repeats a kept term: the same, ignoring case, or either one found as whole words in the other."""
    key = term.lower()
    return any(key == k.lower() or re.search(_whole_word(key), k.lower()) or re.search(_whole_word(k.lower()), key) for k in kept)


def extract_terms(text: str, limit: int = 25) -> list[str]:
    """Keywords for any field, found in a job posting (or a certificate, a transcript, any document): at most `limit`.

    In order: the credentials and licenses it names (VOCABULARY's "credentials", then phrases such as "Pharmacy
    Technician Certification"); the terms of every field's vocabulary it uses, with the everyday-word tech terms
    (TECH_WEAK) only in a clearly technical text; then what its requirement lines ask for ("experience with point of sale
    systems"). Repeats are dropped, ignoring case, and so is a phrase already covered by a term found earlier.
    search/packages.py uses them as a job's keywords when the AI didn't list any, and candidate/documents.py as the
    skills a document shows."""
    text = text or ""
    low = text.lower()
    found: list[str] = []
    for field, patterns in _VOCAB:
        hits = [term for term, pattern in patterns if pattern.search(low)]
        found += hits
        if field == "credentials":
            found += _credential_phrases(text)
    if sum(1 for term, pattern in dict(_VOCAB)["tech"] if pattern.search(low)) >= 2:
        found += [term for term, pattern in _TECH_WEAK if pattern.search(low)]
    found += _asked_phrases(text)
    out: list[str] = []
    for term in found:
        if len(out) >= limit:
            break
        if not _covered(term, out):
            out.append(term)
    return out


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


# ---------------------------------------------------------------- target roles (the rule filters' cheap pre-filter)

# Words in a target phrase that say nothing about the field: levels, job types, schedules, places and connectors.
_TARGET_FILLER = {
    "and", "or", "the", "of", "for", "with", "in", "at", "to", "a", "an", "on", "by", "&", "senior", "sr", "junior", "jr", "entry",
    "level", "mid", "new", "grad", "graduate", "intern", "internship", "interns", "co", "op", "coop", "remote", "hybrid", "onsite",
    "part", "time", "full", "fulltime", "parttime", "contract", "temporary", "temp", "seasonal", "per", "diem", "prn", "summer",
    "fall", "spring", "winter", "i", "ii", "iii", "iv", "1", "2", "3", "4", "job", "jobs", "role", "roles", "position", "positions",
    "opening", "openings", "hiring", "work", "career", "careers", "opportunity", "opportunities", "near", "me", "local",
    "experienced", "early", "first", "year", "years", "shift", "night", "day", "weekend", "nights", "days", "weekends",
}
# Words that name a kind of position in any field. A target phrase only uses them when it has no more telling word, so
# "Medical Assistant" is matched by "medical" (a "Teaching Assistant" isn't a medical assistant) and "Assistant Manager" by
# "assistant" and "manager".
_GENERIC_ROLE_WORDS = {
    "manager", "management", "specialist", "assistant", "associate", "coordinator", "technician", "tech", "representative", "rep",
    "officer", "director", "consultant", "administrator", "admin", "clerk", "worker", "operator", "agent", "supervisor", "lead",
    "head", "member", "team", "staff", "professional", "aide", "helper", "attendant", "advisor", "adviser", "planner", "executive",
    "partner", "generalist", "expert", "trainee", "apprentice", "fellow", "leader", "president", "vice", "vp", "chief", "owner",
    "services", "service", "support", "operations",
}
# Other words for the same work, so a target "Registered Nurse" also finds "RN - Med Surg" and "Software Developer" finds
# "Backend Engineer". The keys are stems (see _role_stem); _ROLE_ALIASES is filled in from the plain words below.
_ALIAS_WORDS = {
    "nurse": ["rn", "lpn", "lvn", "cna", "bsn", "np"], "software": ["developer", "programmer", "swe", "sde", "engineer"],
    "developer": ["software", "programmer", "swe", "engineer"], "programmer": ["developer", "software", "engineer"],
    "physician": ["doctor", "md", "hospitalist"], "doctor": ["physician", "md"], "attorney": ["lawyer", "counsel", "esq"],
    "lawyer": ["attorney", "counsel"], "chef": ["cook", "culinary", "kitchen"], "cook": ["chef", "culinary", "kitchen"],
    "server": ["waiter", "waitress", "banquet"], "driver": ["cdl", "trucker", "courier", "chauffeur", "delivery"],
    "teacher": ["educator", "instructor", "tutor", "faculty", "paraprofessional"], "educator": ["teacher", "instructor"],
    "instructor": ["teacher", "educator", "trainer"], "accountant": ["cpa", "bookkeeper"], "bookkeeper": ["accounting", "accountant"],
    "caregiver": ["aide", "hha", "cna", "dsp", "companion"], "human": ["hr"], "hr": ["recruiter", "recruiting", "talent"],
    "it": ["technical", "helpdesk", "desktop", "sysadmin", "network"], "qa": ["quality", "tester"], "quality": ["qa", "qc"],
    "emt": ["paramedic", "ems"], "paramedic": ["emt", "ems"], "pharmacy": ["cpht"], "artist": ["art", "illustrator"],
    "writer": ["copywriter", "editor", "author"], "welder": ["fabricator"], "mechanic": ["automotive", "diesel"],
    "warehouse": ["forklift", "picker", "packer", "shipping", "receiving"], "cashier": ["retail", "checkout"],
    "retail": ["store", "cashier"], "barista": ["coffee", "cafe"], "housekeeper": ["housekeeping", "custodian", "janitor", "cleaner"],
    "janitor": ["custodian", "housekeeping", "cleaner"], "custodian": ["janitor", "housekeeping", "cleaner"],
    "counselor": ["therapist", "clinician"], "therapist": ["counselor", "clinician"], "social": ["lcsw", "msw", "caseworker"],
    "paralegal": ["legal"], "dental": ["dentist", "hygienist"], "hygienist": ["dental", "rdh"],
}
# Endings _role_stem() drops, longest first, so "nurse" and "nursing", "teacher" and "teaching", "therapist" and "therapy"
# come out the same.
_ROLE_SUFFIXES = ("ational", "ations", "ation", "icians", "ician", "ments", "ment", "ings", "ing", "ists", "ist", "ers", "er",
                  "ors", "or", "ies", "ics", "ant", "ance", "ence", "ent", "ive", "ity", "ed", "al", "st", "es", "s", "y", "e", "ic")
_TOKEN_RE = re.compile(r"[a-z0-9+#&]+")


@lru_cache(maxsize=20000)  # the same title and description words come back in job after job
def _role_stem(word: str) -> str:
    """A rough stem for comparing job-title words: one common ending dropped, as long as four letters remain."""
    for suffix in _ROLE_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[:-len(suffix)]
    return word


_ROLE_ALIASES = {_role_stem(word): aliases for word, aliases in _ALIAS_WORDS.items()}
# Place words in a search query ("nurse jobs Columbus OH") aren't about the work, so they're never target words.
_PLACE_WORDS = {code.lower() for code in STATES} | set(NAME_TO_ABBR) | {city for city in CITY_STATE if " " not in city}


class TargetMatcher:
    """Tells whether a job is near what the user is after: their target roles, the profile's role families and the
    search queries (search/plan.target_phrases). search/pipeline.RuleFilters uses it as the cheap pre-filter before AI
    triage, which costs tokens for every job it reads.

    It's lenient on purpose, since a dropped job is a job the user never sees:
    - Each phrase gives its telling words ("Registered Nurse" gives registered and nurse). Generic role words such as
      "assistant" or "manager" are used only when a phrase has nothing more telling. Levels, job types and places never
      count.
    - Words are compared by stem, so "nurse" finds "Nursing Assistant" and "teacher" finds "Teaching Fellow". Short words
      (three letters or fewer, such as RN or IT) must match a whole word.
    - A few aliases add other words for the same work (_ALIAS_WORDS): RN for nurse, developer for software.
    - A title passes with any one target word. A title without one still passes when the description uses two different
      target words.
    `places` is the user's search area ("Columbus, OH", "Remote"): its words are left out too, since queries often name
    the city. With no phrases at all the matcher is empty (bool() is False), and the pipeline lets every job through."""

    def __init__(self, phrases: list[str], places: list[str] | None = None):
        ignore = _TARGET_FILLER | _PLACE_WORDS | {w for place in places or [] for w in _TOKEN_RE.findall(str(place).lower())}
        terms: set[str] = set()
        for phrase in phrases or []:
            words = [w for w in _TOKEN_RE.findall(str(phrase).lower()) if w not in ignore]
            telling = [w for w in words if w not in _GENERIC_ROLE_WORDS]
            for word in telling or words:
                term = word if len(word) <= 3 else _role_stem(word)
                terms.add(term)
                for alias in _ROLE_ALIASES.get(term, []):
                    terms.add(alias if len(alias) <= 3 else _role_stem(alias))
        self.short = {t for t in terms if len(t) <= 3}  # whole words only
        self.stems = terms - self.short
        # Stems of five or more letters also match a longer or shorter stem that starts the same way ("electric" and
        # "electr"). Such a pair always shares its first five letters, so the stems are filed by those.
        self.by_start: dict[str, list[str]] = {}
        for stem in self.stems:
            if len(stem) >= 5:
                self.by_start.setdefault(stem[:5], []).append(stem)

    def __bool__(self) -> bool:
        return bool(self.short or self.stems)

    def hits(self, text: str) -> set[str]:
        """The target words found in `text` (as their stems)."""
        found = set()
        for token in set(_TOKEN_RE.findall((text or "").lower())):
            if len(token) <= 3:
                if token in self.short:
                    found.add(token)
                continue
            stem = _role_stem(token)
            if stem in self.stems:
                found.add(stem)
            if len(stem) >= 5:
                found.update(t for t in self.by_start.get(stem[:5], []) if stem.startswith(t) or t.startswith(stem))
        return found

    def matches(self, title: str, description: str = "") -> bool:
        """True when the title uses a target word, or the first 1,500 characters of the description use two of them.
        Always True for an empty matcher."""
        if not self:
            return True
        return bool(self.hits(title)) or len(self.hits((description or "")[:1500])) >= 2
