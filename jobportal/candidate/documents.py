"""Extra documents: certificates, licenses, awards, transcripts, cover letters and other resumes the user adds next to their
resume.

They're optional. Setup still needs only the resume and the standard questions. But every document added here goes into
the next profile build together with the resume, so the profile, and the search plan made from it, covers everything the
user has done. That's how a certificate the resume never mentions can still lead to jobs that ask for it, and why more
documents mean a wider spread of job matches.

Where they're added: the setup page (the resume step) and Profile, Resume and documents. Each file is read with
documents/extract.py and kept as text in "profile.documents", and a copy of the file goes in the data folder (documents/).
Adding or removing one stamps "profile.documents_changed_at". profile.answers_watcher() then rebuilds the profile once the
user has paused for a minute, so dropping ten files at once means one rebuild, not ten.

Reading a document's details ("parsed"): what it is (kind), its title ("AWS Certified Cloud Practitioner", "Dean's List"),
who issued it, when it was issued and when it expires ("YYYY-MM", "YYYY" or ""), up to eight skills or topics it shows, and
a one-sentence summary. It happens in two steps:
  1. parse_rules(), a quick reading with patterns ("issued by", "has completed", "Expires:", known issuers), the moment a
     document is added, so the dashboard has something right away. "parsed_by" is "rules".
  2. parse_with_ai(), when the user is signed in with ChatGPT: a cheap AI reading (stage "documents", prompts.DOCUMENT_SYSTEM)
     in the background, which replaces the rules' reading. "parsed_by" is "ai". While it runs, the listing says
     "parsing": true, and the "documents" event goes out when it starts and when it ends.
Documents added before this existed get their rules reading the first time the list is read, and their AI reading from
parse_pending(), which the server runs at startup and after a sign-in. Neither reading ever uses the user's own name as a
title or an issuer. The profile build reads each document's details as a DETAILS line above its text (for_prompt), so
licenses, certifications and awards land in the profile's record reliably.

Not to be confused with saved resumes on the Resumes page (candidate/library.py): that's a collection of resume versions to
reuse, and it never feeds the profile."""
import asyncio
import hashlib
import re
import threading
import time
import uuid
from pathlib import Path

from jobportal.ai import client as ai, prompts, signin
from jobportal.core import background, bus, db
from jobportal.core.config import DATA, RESUME_DIR
from jobportal.core.textutil import clean, extract_terms
from jobportal.documents import extract

DOCS_DIR = DATA / "documents"
MAX_DOCUMENTS = 40  # plenty for one person, and it keeps the profile build's prompt a sane size
MIN_CHARS = 20  # a certificate can be one line ("CPR certified, 2025"), so documents may be much shorter than a resume
MAX_CHARS_EACH = 15000  # how much of each document the profile build reads
MAX_CHARS_TOTAL = 90000  # how much of all documents together the profile build reads
AI_CHARS = 8000  # how much of a document the AI reading gets: its details are near the top
MAX_SKILLS = 8
LISTED = ("id", "name", "kind", "chars", "added_at")  # what the dashboard gets of a document: everything but the text...
# ...plus "parsed" (the details, or None), "parsed_by" ("rules", "ai" or None) and "parsing" (an AI reading runs now).
KINDS = prompts.DOCUMENT_KINDS

# What a document looks like, guessed from its file name first and then its opening text. The first match wins, so the
# order matters: a "letter of recommendation" isn't a cover letter, and a license isn't any certificate. The AI reading
# refines it later. "licen[cs]e" also reads the British spelling some certificates use.
KIND_HINTS = [
    ("reference letter", r"letter of (?:recommendation|reference)|recommendation letter|reference letter|to whom it may concern"),
    ("cover letter", r"cover[ _-]?letter|dear (?:hiring|recruit|sir|madam|team)"),
    ("license", r"licen[cs]e(?!d? to\b)|licensure|board of (?:nursing|pharmacy|cosmetology|education|medicine)|commercial driver"),
    ("certificate", r"certif|credential|badge|course completion|successfully completed|has completed|provider card|"
                    r"bls provider|\bcpr\b|first aid"),
    ("award", r"award|honou?r|dean'?s list|president'?s list|scholarship|recognition|accolade|commendation"),
    ("transcript", r"transcript|cumulative gpa|credits earned|semester gpa"),
    ("diploma", r"\bdiploma\b|has conferred|degree of (?:bachelor|master|associate|doctor)"),
    ("training record", r"training record|continuing education|\bceus?\b|contact hours"),
    ("resume", r"resume|résumé|curriculum vitae|\bcv\b"),
]
# Kinds that name a credential, for which the first date in the text is most likely when it was earned.
CREDENTIAL_KINDS = {"certificate", "license", "award", "diploma", "training record"}

_lock = threading.RLock()  # documents change from the event loop and from FastAPI's worker threads; one change at a time
_parsing: set[str] = set()  # ids with an AI reading running now


def _looks_like_resume(text: str) -> bool:
    """True when the text has the sections of a resume (at least two of experience, education, skills, summary)."""
    found = {m.lower() for m in re.findall(r"^\W*(experience|education|skills|summary|employment)\b", text[:6000], re.I | re.M)}
    return len(found) >= 2


def _kind(filename: str, text: str) -> str:
    """A best guess at what the document is: one of KINDS. The file name decides when it says, then the text: a text with
    a resume's sections is a resume, whatever certificates it mentions."""
    for kind, pattern in KIND_HINTS:
        if re.search(pattern, filename.lower()):
            return kind
    if _looks_like_resume(text):
        return "resume"
    for kind, pattern in KIND_HINTS:
        if re.search(pattern, text[:1500].lower()):
            return kind
    return "document"


# ---------------------------------------------------------------- the rule-based reading

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
# A month name or its abbreviation. It must start a word, or the end of "Grammar 2025" would read as March 2025.
_MONTH = r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
# A date as certificates write them: "March 15, 2025", "15 March 2025", "Mar 2025", "03/15/2025", "03/2025", "2025-03-15",
# "Fall 2025" or a lone year.
_DATE = (rf"(?:{_MONTH}\s+(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s+)?\d{{4}}|\d{{1,2}}\s+{_MONTH},?\s+\d{{4}}|\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{4}}"
         rf"|\d{{1,2}}[/-]\d{{4}}|\d{{4}}-\d{{2}}(?:-\d{{2}})?|(?:spring|summer|fall|autumn|winter)\s+\d{{4}}|\b(?:19|20)\d{{2}}\b)")
_ISSUED_RE = re.compile(rf"\b(?:issued(?: on)?|issue date|date of issue|date issued|awarded(?: on)?|granted(?: on)?|completed(?: on)?|"
                        rf"completion date|date of completion|earned(?: on)?|conferred(?: on)?|effective date|valid from|certified on|"
                        rf"passed(?: on)?|date of award)\s*:?\s*({_DATE})", re.I)
_EXPIRES_RE = re.compile(rf"\b(?:expires?(?: on)?|expiration(?: date)?|expiry(?: date)?|exp\.|valid (?:through|thru|until|till)|"
                         rf"renew(?:al)? (?:by|date)|good through)\s*:?\s*({_DATE})", re.I)
_ANY_DATE_RE = re.compile(_DATE, re.I)

# Organizations that issue many of the credentials people add, found by a telling word in the text.
KNOWN_ISSUERS = [
    (r"\baws\b|amazon web services", "Amazon Web Services"), (r"\bcomptia\b", "CompTIA"), (r"\bcisco\b", "Cisco"),
    (r"microsoft", "Microsoft"), (r"\bgoogle\b", "Google"), (r"american heart association", "American Heart Association"),
    (r"red cross", "American Red Cross"), (r"servsafe", "National Restaurant Association"),
    (r"project management institute|\bpmi\b", "Project Management Institute"), (r"\bshrm\b", "SHRM"),
    (r"\bnremt\b|national registry of emergency medical technicians", "National Registry of Emergency Medical Technicians"),
    (r"\bnccer\b", "NCCER"), (r"\bosha\b|occupational safety and health", "Occupational Safety and Health Administration"),
    (r"\bptcb\b|pharmacy technician certification board", "Pharmacy Technician Certification Board"),
    (r"hubspot", "HubSpot Academy"), (r"\bcoursera\b", "Coursera"), (r"\bedx\b", "edX"), (r"linkedin learning", "LinkedIn Learning"),
    (r"\budemy\b", "Udemy"), (r"\bfaa\b|federal aviation administration", "Federal Aviation Administration"),
]
# A line or phrase that names an issuing organization.
_ORG_RE = re.compile(r"\b(university|college|institute|academy|association|board of|department of|council|society|foundation|"
                     r"school|hospital|medical center|center for|bureau|commission|inc\.?|llc|corporation|company|agency)\b", re.I)
_ISSUER_PHRASE_RE = re.compile(r"\b(?:issued|presented|awarded|granted|conferred|provided|offered|certified|accredited|approved)"
                               r" by\s+(?:the\s+)?([A-Z][\w&.,'/ -]{2,80}?)(?=\s+(?:on|in|this|dated|to|for)\b|[.;\n]|$)")
_BOARD_RE = re.compile(r"\b((?:[A-Z][a-z]+ ){0,3}(?:State )?Board of [A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,3})")
# Phrases that introduce what was earned: "has successfully completed Food Handler Training", "is licensed as a Registered
# Nurse", "has earned the AWS Certified Cloud Practitioner credential".
_EARNED_RE = re.compile(r"\b(?:has (?:successfully )?(?:completed|earned|achieved|passed|fulfilled the requirements (?:for|of))|"
                        r"is (?:hereby )?(?:certified|licensed|registered|recognized) (?:as|for|in)|for (?:successfully )?completing|"
                        r"completion of|awarded the|earned the|recipient of the)\s+(?:an? |the )?(.{3,90}?)"
                        r"(?=\s+(?:on|in (?:the )?(?:year|month)|from|by|issued|with|this|dated|at)\b|[.;,\n]|$)", re.I)
# Award names to recognize as they are.
_AWARD_RE = re.compile(r"\b(dean'?s list|president'?s list|honor roll|employee of the (?:month|year|quarter)|"
                       r"(?:[A-Z][\w'&-]*\s){1,5}(?:scholarship|award|prize|medal|fellowship))\b", re.I)
# Words that make a line a credential's name rather than filler.
_CREDENTIAL_WORDS_RE = re.compile(r"\b(certified|certification|certificate|license|licensed|licensure|award|diploma|degree|honors?|"
                                  r"scholarship|training|course|program|credential|endorsement|registered)\b", re.I)
# Boilerplate a certificate wraps around the name, removed from the front of a title.
_BOILERPLATE_RE = re.compile(r"^(?:(?:certificate|certification|award|diploma|license) of (?:completion|achievement|participation|"
                             r"attendance|excellence|recognition|appreciation|merit)\b[\s:,-]*|this (?:is to )?certif(?:y|ies) that\s*|"
                             r"presented to\s*|awarded to\s*|in recognition of\s*)", re.I)
_RECIPIENT_RE = re.compile(r"(?:certif(?:y|ies) that|presented to|awarded to|granted to|issued to|this is to certify)\s*:?\s*$", re.I)


def _norm_date(value) -> str:
    """A date as "YYYY-MM" when the month is known, "YYYY" when only the year is, or "" when it can't be read. Accepts what
    _DATE finds, and what the AI writes ("2025-03", "2025", "March 2025")."""
    text = clean(value).lower().rstrip(".")
    if not text:
        return ""
    if m := re.fullmatch(r"((?:19|20)\d{2})-(\d{1,2})(?:-\d{1,2})?", text):
        year, month = m.group(1), int(m.group(2))
    elif m := re.fullmatch(r"(\d{1,2})[/.-](?:\d{1,2}[/.-])?((?:19|20)\d{2})", text):
        year, month = m.group(2), int(m.group(1))
    elif m := re.search(rf"\b({_MONTH})\s.*?((?:19|20)\d{{2}})|\d{{1,2}}\s+({_MONTH}),?\s+((?:19|20)\d{{2}})", text):
        name = m.group(1) or m.group(3)
        year, month = m.group(2) or m.group(4), _MONTHS.get(name.strip(".")[:3], 0)
    elif m := re.search(r"\b((?:19|20)\d{2})\b", text):
        return m.group(1)
    else:
        return ""
    return f"{year}-{month:02d}" if 1 <= month <= 12 else year


def _readable_date(value: str) -> str:
    """"2025-03" as "March 2025", "2025" as itself, for the summary sentence."""
    if m := re.fullmatch(r"(\d{4})-(\d{2})", value or ""):
        names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
                 "December"]
        return f"{names[int(m.group(2)) - 1]} {m.group(1)}"
    return value or ""


def owner_names() -> list[str]:
    """The user's own name, as far as JobPortal knows it: the standard answers, the profile's facts and the resume's first
    line. Readings never use it as a document's title or issuer."""
    from jobportal.candidate import profile  # imported here: profile sits next to this module and loads first
    names = [profile.standard_answers().get("name"), (profile.get("facts") or {}).get("name")]
    first = next((line.strip().lstrip("# ").strip() for line in ((profile.resume() or {}).get("text") or "").splitlines()
                  if line.strip()), "")
    if 2 <= len(first.split()) <= 4 and not re.search(r"[@\d|/:]", first):
        names.append(first)
    return [n for i, n in enumerate(names) if n and str(n).strip() and n not in names[:i]]


_RECIPIENT_INLINE_RE = re.compile(r"(?:certif(?:y|ies) that|presented to|awarded to|granted to|issued to)\s+"
                                  r"([A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){1,3})")


def recipients(text: str) -> list[str]:
    """The names a certificate gives as its recipient: the words after "This certifies that", "presented to" or "awarded
    to", on the same line or the next one. That's the user, even before JobPortal knows their name."""
    names = [m.group(1) for m in _RECIPIENT_INLINE_RE.finditer(text or "")]
    lines = [clean(line) for line in (text or "").splitlines() if clean(line)]
    for i, line in enumerate(lines[:-1]):
        nxt = lines[i + 1]
        if _RECIPIENT_RE.search(line) and 2 <= len(nxt.split()) <= 5 and re.fullmatch(r"[A-Za-z .,'-]+", nxt):
            names.append(nxt)
    return [n for i, n in enumerate(names) if n not in names[:i]]


def _mentions_owner(value: str, owners: list[str]) -> bool:
    """True when `value` contains the user's name: every word (of two letters or more) of one of their names."""
    words = set(re.findall(r"[a-z]+", (value or "").lower()))
    for owner in owners:
        parts = {p for p in re.findall(r"[a-z]+", owner.lower()) if len(p) > 1}
        if len(parts) >= 2 and parts <= words:
            return True
    return False


def _tidy_title(value: str) -> str:
    """A title candidate without boilerplate in front, a trailing "credential", stray punctuation or extra spaces."""
    value = clean(value).strip(" .,:;-")
    for _ in range(2):  # boilerplate can be stacked: "Certificate of Completion: This certifies that ..."
        value = _BOILERPLATE_RE.sub("", value).strip(" .,:;-")
    value = re.sub(r"\s+credential$", "", value, flags=re.I)
    return value[:120]


def _lines(text: str) -> list[str]:
    """The non-blank lines of a document, with sentence breaks inside a line treated as line breaks too."""
    out = []
    for line in text.splitlines():
        out += [clean(part) for part in re.split(r"(?<=[a-z0-9)])\.\s+(?=[A-Z])", line) if clean(part)]
    return out


def _rule_title(kind: str, name: str, text: str, owners: list[str], issuer: str = "") -> str:
    """The best title the patterns find: a phrase saying what was earned, a known award name, a line that names a
    credential, the first meaningful line, then the file name. Lines naming the user, the line right after "this certifies
    that" (where the user's name goes) and the issuer's own line are never used."""
    lines = _lines(text)
    after_recipient = {i + 1 for i, line in enumerate(lines) if _RECIPIENT_RE.search(line)}
    usable = [line for i, line in enumerate(lines) if i not in after_recipient and not _mentions_owner(line, owners)
              and line.strip(" .,").lower() != issuer.lower()]
    if kind == "resume":
        return "Resume"
    if kind == "transcript":
        return "Official transcript" if re.search(r"official transcript", text, re.I) else "Transcript"
    if kind in ("cover letter", "reference letter"):
        role = re.search(r"\b(?:position|role) of (?:an? )?([A-Z][\w &/,-]{2,60}?)(?=[.,;\n]| at | with |$)"
                         r"|\bapply(?:ing)? for (?:the |an? )?([A-Z][\w &/-]{2,60}?) (?:position|role|opening)", text)
        label = "Cover letter" if kind == "cover letter" else "Reference letter"
        return f"{label} for {(role.group(1) or role.group(2)).strip()}" if role else label
    candidates = []
    if kind == "award":
        candidates += [m.group(1) for m in _AWARD_RE.finditer(text)]
    candidates += [m.group(1) for m in _EARNED_RE.finditer(text)]
    if kind != "award":
        candidates += [m.group(1) for m in _AWARD_RE.finditer(text)]
    candidates += [line for line in usable if _CREDENTIAL_WORDS_RE.search(line) and len(line) <= 90]
    candidates += [line for line in usable if 3 <= len(line) <= 90 and not _ANY_DATE_RE.fullmatch(line)]
    for candidate in candidates:
        title = _tidy_title(candidate)
        if (len(title) >= 3 and not _mentions_owner(title, owners) and title.lower() != issuer.lower()
                and not re.fullmatch(r"(?:certificate|award|license|diploma)s?", title, re.I)):
            if kind == "license" and not re.search(r"licen[cs]e", title, re.I):
                title += " License"
            return title[0].upper() + title[1:]
    stem = clean(re.sub(r"[_-]+", " ", Path(name).stem))
    return stem if stem and not _mentions_owner(stem, owners) else kind.capitalize()


def _known_issuer(text: str) -> str:
    """The name of a well-known issuer (KNOWN_ISSUERS) that `text` names, or ""."""
    low = (text or "").lower()
    return next((issuer for pattern, issuer in KNOWN_ISSUERS if re.search(pattern, low)), "")


def _rule_issuer(text: str, owners: list[str]) -> str:
    """Who issued the document, in this order: an "issued by" phrase or a licensing board ("Ohio Board of Nursing"), then
    one of the first lines that names an organization (a university, an association, a company) and isn't a credential's
    name, then a well-known issuer the text names. A well-known issuer inside a phrase gives its usual name ("Issued by
    Amazon Web Services Training and Certification" gives "Amazon Web Services"). "" when nothing turns up."""
    phrases = [m.group(1) for m in _ISSUER_PHRASE_RE.finditer(text)] + [m.group(1) for m in _BOARD_RE.finditer(text)]
    lines = [line for line in _lines(text)[:12] if _ORG_RE.search(line) and len(line) <= 90 and not _CREDENTIAL_WORDS_RE.search(line)]
    for candidate in phrases + lines:
        issuer = clean(candidate).strip(" .,:;-")
        if len(issuer) >= 3 and not _mentions_owner(issuer, owners):
            return _known_issuer(issuer) or issuer[:100]
    return _known_issuer(text[:1500])


def _rule_dates(text: str, kind: str) -> tuple[str, str]:
    """(issued, expires) as _norm_date gives them. Labeled dates come first ("Issued: 06/15/2024", "Expires March 2028").
    A credential without an issue label takes the first other date in the text, never one that follows "birth" or "DOB"."""
    expires_m = _EXPIRES_RE.search(text)
    issued_m = _ISSUED_RE.search(text)
    issued = _norm_date(issued_m.group(1)) if issued_m else ""
    if not issued and kind in CREDENTIAL_KINDS:
        for m in _ANY_DATE_RE.finditer(text):
            if expires_m and expires_m.start(1) <= m.start() < expires_m.end(1):
                continue
            if re.search(r"birth|\bdob\b", text[max(0, m.start() - 24):m.start()], re.I):
                continue
            issued = _norm_date(m.group(0))
            break
    return issued, (_norm_date(expires_m.group(1)) if expires_m else "")


def _summary(details: dict) -> str:
    """One plain sentence from the details: "License: Registered Nurse License from Ohio Board of Nursing, issued June 2024,
    valid until August 2026."."""
    kind, title = details.get("kind") or "document", details.get("title") or ""
    if title.lower().startswith(kind):  # "Cover letter for Marketing Coordinator" says what it is already
        sentence = title
    else:
        sentence = kind.capitalize() + (f": {title}" if title else "")
    if details.get("issuer"):
        sentence += f" from {details['issuer']}"
    if details.get("issued"):
        sentence += f", issued {_readable_date(details['issued'])}"
    if details.get("expires"):
        sentence += f", valid until {_readable_date(details['expires'])}"
    return sentence + "."


def parse_rules(name: str, text: str, kind: str | None = None, owners: list[str] | None = None) -> dict:
    """A quick reading of a document's details with patterns, no AI: {"kind", "title", "issuer", "issued", "expires",
    "skills", "summary"}. `kind` defaults to the guess from the file name and text, and `owners` to the user's names
    (owner_names, plus the document's own recipient: recipients), which never become the title or the issuer. Skills are
    the terms extract_terms() finds in the text."""
    text = text or ""
    owners = (owner_names() if owners is None else owners) + recipients(text)
    kind = kind or _kind(name, text)
    issued, expires = _rule_dates(text, kind)
    issuer = _rule_issuer(text, owners) if kind not in ("resume", "cover letter") else ""
    details = {"kind": kind, "title": _rule_title(kind, name, text, owners, issuer), "issuer": issuer,
               "issued": issued if kind != "resume" else "", "expires": expires,
               "skills": [t for t in extract_terms(text, limit=MAX_SKILLS * 2) if not _mentions_owner(t, owners)][:MAX_SKILLS]}
    details["summary"] = _summary(details)
    return details


def _clean_ai_details(out: dict, fallback: dict, owners: list[str]) -> dict:
    """The AI's reading, made safe to keep: a kind from KINDS (else the rules' kind), titles and issuers that don't name the
    user (else the rules' ones), dates as "YYYY-MM", "YYYY" or "", at most MAX_SKILLS short skills, and a summary of 240
    characters at most (the rules' one when the AI wrote none)."""
    def text_field(key: str, limit: int) -> str:
        value = clean(out.get(key))[:limit]
        return "" if _mentions_owner(value, owners) else value
    skills = []
    for skill in out.get("skills") or []:
        skill = clean(skill)[:60]
        if skill and not _mentions_owner(skill, owners) and skill.lower() not in {s.lower() for s in skills}:
            skills.append(skill)
    details = {"kind": out.get("kind") if out.get("kind") in KINDS else fallback.get("kind", "document"),
               "title": text_field("title", 120) or fallback.get("title", ""),
               "issuer": text_field("issuer", 100) or ("" if out.get("issuer") == "" else fallback.get("issuer", "")),
               "issued": _norm_date(out.get("issued")), "expires": _norm_date(out.get("expires")),
               "skills": skills[:MAX_SKILLS]}
    details["summary"] = text_field("summary", 240) or _summary(details)
    return details


# ---------------------------------------------------------------- the list


def _entry(doc: dict) -> dict:
    """One document as the dashboard gets it: LISTED, its details, who read them and whether an AI reading runs now."""
    return {**{key: doc.get(key) for key in LISTED}, "parsed": doc.get("parsed"), "parsed_by": doc.get("parsed_by"),
            "parsing": doc["id"] in _parsing}


def all_documents() -> list[dict]:
    """Every extra document, oldest first. Each one holds id, name, kind, text, chars, added_at, sha1, stored_as, parsed
    and parsed_by. A document added before readings existed gets its rules reading here, once, and its kind is guessed
    again with today's finer kinds (a license is no longer just a certificate). It's saved quietly: the document itself
    didn't change, so the profile isn't rebuilt."""
    with _lock:
        docs = db.kv_get("profile.documents") or []
        unread = [doc for doc in docs if not doc.get("parsed")]
        if unread:
            owners = owner_names()
            for doc in unread:
                doc["parsed"] = parse_rules(doc["name"], doc.get("text", ""), None, owners)
                doc["parsed_by"] = "rules"
                doc["kind"] = doc["parsed"]["kind"]
            db.kv_set("profile.documents", docs)
        return docs


def listing() -> list[dict]:
    """The documents for the dashboard: everything but their text, with their details (see _entry)."""
    return [_entry(doc) for doc in all_documents()]


def _publish() -> None:
    """Tell open dashboards the current list."""
    bus.publish("documents", listing())


def _save(docs: list[dict], changed: bool = True) -> None:
    """Store the list and tell open dashboards. `changed` stamps the change for answers_watcher(), so the profile is built
    again with it; the readings of a document that was already there don't need that."""
    db.kv_set("profile.documents", docs)
    if changed:
        db.kv_set("profile.documents_changed_at", time.time())
    _publish()


def add(filename: str, data: bytes) -> dict:
    """Read one document and keep it, with its rules reading, and start its AI reading in the background when the user is
    signed in with ChatGPT (_start_ai_reading). Returns its listing entry. The same file added again changes nothing and
    comes back with "duplicate": True. Raises extract.ExtractError when no text can be read (a scanned image, an unsupported
    type), and ValueError when MAX_DOCUMENTS are kept already."""
    with _lock:
        docs = all_documents()
        sha1 = hashlib.sha1(data).hexdigest()
        same = next((doc for doc in docs if doc["sha1"] == sha1), None)
        if same:
            return {**_entry(same), "duplicate": True}
        if len(docs) >= MAX_DOCUMENTS:
            raise ValueError(f"You can keep up to {MAX_DOCUMENTS} documents. Remove one first.")
        text = extract.extract_text(filename, data, min_chars=MIN_CHARS).strip()
        # A file name with no folder parts and no characters Windows forbids.
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", Path(filename or "document.txt").name).strip() or "document.txt"
        doc_id = uuid.uuid4().hex[:12]
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        stored = DOCS_DIR / f"{doc_id} {name}"
        stored.write_bytes(data)
        parsed = parse_rules(name, text)
        doc = {"id": doc_id, "name": name, "kind": parsed["kind"], "text": text, "chars": len(text), "added_at": db.now(),
               "sha1": sha1, "stored_as": stored.name, "parsed": parsed, "parsed_by": "rules"}
        _start_ai_reading(doc_id)  # before saving, so the first "documents" event already says it's being read
        _save(docs + [doc])
        return _entry(doc)


def remove(doc_id: str) -> bool:
    """Forget one document and delete its copy in the data folder. Returns False when there's no such document."""
    with _lock:
        docs = all_documents()
        doc = next((d for d in docs if d["id"] == doc_id), None)
        if not doc:
            return False
        if doc.get("stored_as"):  # without a name, DOCS_DIR / "" would be the documents folder itself
            (DOCS_DIR / doc["stored_as"]).unlink(missing_ok=True)
        _save([d for d in docs if d["id"] != doc_id])
        return True


# ---------------------------------------------------------------- the AI reading


def _signed_in() -> bool:
    """True when someone is signed in with ChatGPT, so an AI reading can run."""
    return bool(signin.status().get("signed_in"))


def _start_ai_reading(doc_id: str) -> bool:
    """Start the AI reading of one document in the background, when someone is signed in and this code runs inside the
    server's event loop (an upload route). Returns True when it started. Outside the loop (a worker thread, a test, a
    script) nothing starts, and parse_pending() reads the document later."""
    if not _signed_in():
        return False
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    _parsing.add(doc_id)
    background.spawn(_read_in_background(doc_id))
    return True


async def _read_in_background(doc_id: str) -> None:
    """The background AI reading of a document just added. It stamps the documents as changed when it's done, so the
    profile build that follows the upload reads the AI's details. A failure keeps the rules reading and shows a toast."""
    try:
        await parse_with_ai(doc_id, changed=True)
    except KeyError:
        pass  # removed while it was being read
    except ai.AIError as e:
        bus.publish("toast", {"title": "Couldn't read a document with AI", "body": str(e)[:300], "level": "error"})


async def parse_with_ai(doc_id: str, changed: bool = False) -> dict:
    """Read one document's details with AI (stage "documents") and keep them, replacing the rules reading. Returns the
    document's listing entry. Publishes the "documents" event when it starts and when it ends, with "parsing" true while
    it runs. `changed` also stamps the documents as changed (see _save).

    Raises KeyError for an unknown id, and ai.AIError (with NotSignedIn and UsageLimitError) when the AI fails; the
    details already there stay then."""
    doc = next((d for d in all_documents() if d["id"] == doc_id), None)
    if not doc:
        _parsing.discard(doc_id)
        raise KeyError(doc_id)
    owners = owner_names() + recipients(doc.get("text", ""))
    fallback = doc.get("parsed") or parse_rules(doc["name"], doc.get("text", ""), doc.get("kind"), owners)
    prompt = (f"DOCUMENT FILE NAME: {doc['name']}\nLOOKS LIKE: {doc.get('kind') or 'document'}\n"
              f"THE CANDIDATE'S NAME (never the title or the issuer): {'; '.join(owners) or 'unknown'}\n\n"
              f"TEXT:\n{(doc.get('text') or '')[:AI_CHARS]}")
    _parsing.add(doc_id)
    _publish()
    try:
        out = await ai.run(prompt, system=prompts.system("documents", prompts.DOCUMENT_SYSTEM), schema=prompts.DOCUMENT_SCHEMA,
                           stage="documents", purpose="document-parse", label=f"read document: {doc['name'][:40]}", timeout=300)
        details = _clean_ai_details(out, fallback, owners)
        with _lock:
            docs = all_documents()  # read again: documents may have been added or removed while the AI worked
            current = next((d for d in docs if d["id"] == doc_id), None)
            if not current:
                raise KeyError(doc_id)
            current.update(parsed=details, parsed_by="ai", kind=details["kind"], parsed_at=db.now())
            _parsing.discard(doc_id)
            _save(docs, changed=changed)
            return _entry(current)
    finally:
        if doc_id in _parsing:  # it failed: the list must stop saying it's being read
            _parsing.discard(doc_id)
            _publish()


async def parse_pending() -> int:
    """Read with AI, one at a time, every document that only has its rules reading, when someone is signed in with
    ChatGPT. web/server.py runs it at startup and web/routes/chatgpt.py after a sign-in, both in the background. The first
    AI failure ends the round with one toast, so a missing plan or a usage cap isn't hit again and again. Returns how many
    documents were read."""
    if not _signed_in():
        return 0
    done = 0
    for doc in all_documents():
        if doc.get("parsed_by") == "ai" or doc["id"] in _parsing:
            continue
        try:
            await parse_with_ai(doc["id"])
            done += 1
        except KeyError:
            continue  # removed meanwhile
        except ai.AIError as e:
            bus.publish("toast", {"title": "Couldn't read your documents with AI", "body": str(e)[:300], "level": "error"})
            break
    return done


# ---------------------------------------------------------------- the profile build


def _details_line(doc: dict) -> str:
    """A document's details as the line above its text in the profile build prompt, or "" without details. A rules
    reading says it's rough, so the AI trusts the text over it."""
    details = doc.get("parsed") or {}
    if not details:
        return ""
    parts = [f"kind: {details.get('kind') or doc.get('kind')}"]
    parts += [f"{key}: {details[key]}" for key in ("title", "issuer", "issued", "expires") if details.get(key)]
    if details.get("skills"):
        parts.append("skills: " + ", ".join(details["skills"]))
    source = "read by AI" if doc.get("parsed_by") == "ai" else "a rough reading by patterns; the text wins"
    line = f"DETAILS ({source}): " + "; ".join(parts)
    return line + (f"\nSUMMARY: {details['summary']}" if details.get("summary") else "")


def for_prompt() -> str:
    """The documents as a section of the profile build prompt: each one labeled, with its DETAILS line (_details_line), cut
    to MAX_CHARS_EACH, and all together cut to MAX_CHARS_TOTAL, so a pile of long documents can't crowd out the resume."""
    docs = all_documents()
    if not docs:
        return "(none)"
    parts, budget = [], MAX_CHARS_TOTAL
    for number, doc in enumerate(docs, 1):
        if budget <= 0:
            parts.append(f"({len(docs) - number + 1} more documents left out: there was too much text)")
            break
        text = doc["text"][:min(MAX_CHARS_EACH, budget)]
        budget -= len(text)
        cut = " (cut short)" if len(text) < len(doc["text"]) else ""
        details = _details_line(doc)
        parts.append(f"--- DOCUMENT {number}: {doc['name']} (looks like: {doc['kind']}){cut} ---\n" + (f"{details}\n" if details else "")
                     + text)
    return "\n\n".join(parts)


def best_resume() -> dict | None:
    """The document most likely to be the user's main resume: of the ones that look like a resume, the longest (a full
    resume beats a one-page variant). None when no document looks like a resume."""
    return max((doc for doc in all_documents() if doc["kind"] == "resume"), key=lambda doc: doc["chars"], default=None)


def changed_at() -> float | None:
    """When the documents last changed (seconds since the epoch), or None when they never have."""
    return db.kv_get("profile.documents_changed_at")


async def make_main(doc_id: str) -> dict:
    """Make one document the main resume. The old main resume becomes an extra document, so nothing is lost. Before the
    standard answers are saved, the new resume pre-fills them again, like a first import. Returns the new resume's details.
    Raises KeyError for an unknown id, and extract.ExtractError when the document is too short to be a resume."""
    from jobportal.candidate import onboarding, profile  # imported here: both modules sit next to this one and load first
    doc = next((d for d in all_documents() if d["id"] == doc_id), None)
    if not doc:
        raise KeyError(doc_id)
    copy = DOCS_DIR / doc.get("stored_as", "")
    data = copy.read_bytes() if copy.is_file() else doc["text"].encode("utf-8")
    old = profile.resume()
    old_copy = RESUME_DIR / old["stored_as"] if old and old.get("stored_as") else None
    old_data = old_copy.read_bytes() if old_copy and old_copy.is_file() else (old or {}).get("text", "").encode("utf-8")
    answered = bool(profile.standard_answers().get("_saved_at"))
    await onboarding.import_resume(doc["name"], data=data, do_prefill=not answered)
    remove(doc_id)
    if old and old_data.strip():
        try:
            add(old["filename"], old_data)
        except ValueError:  # extract.ExtractError is a ValueError, and so is the document limit
            pass
    return profile.resume_info()
