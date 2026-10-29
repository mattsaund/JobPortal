"""Two ways of sorting jobs, each with a keyword classifier: work-type genres and employer industries.

Genres describe the work itself (software, data, cybersecurity, ...). They are the spokes of the Analysis page's radar
(insights/analysis.py). AI triage tags each lead with up to three, and classify() is the keyword fallback.
search/pipeline.py also uses classify() to count demand per genre and to mix work types when it picks what to triage
next. The list is the "analysis.genres" setting, which no page edits. Keep each genre's id the same, or the Analysis
history stops lining up.

Industries describe what the employer does (Space & Aerospace, Fintech & Finance, ...). The list is the "industries"
setting (Settings page, "Industries"). AI triage normally picks a lead's industry, and classify_industry() is the
fallback when it doesn't, and the way db.py fills in leads stored before industries existed.

Both classifiers are plain keyword matching: fast, free, and good enough to sort by. They never call the AI."""
import re
from functools import lru_cache

# id: stable key stored with leads and history. label: shown in the dashboard. keywords: a case-insensitive regex.
DEFAULT_GENRES = [
    {"id": "swe", "label": "Software Engineering",
     "keywords": r"software (engineer|develop)|\bswe\b|developer|programmer|full[- ]?stack|back[- ]?end|application develop|platform engineer"},
    {"id": "frontend_mobile", "label": "Frontend & Mobile",
     "keywords": r"front[- ]?end|\bui\b engineer|web (app|develop)|react|javascript|typescript|mobile|\bios\b|android|swift|kotlin|flutter"},
    {"id": "data", "label": "Data Science & Analytics",
     "keywords": r"data scien|data analy|analytics|statistic|business intelligence|data engineer|\betl\b|tableau|power bi|data visuali|\bsql\b"},
    {"id": "ml_ai", "label": "ML & AI",
     "keywords": r"machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|computer vision|\bnlp\b|\bllms?\b|neural|generative"},
    {"id": "cloud_devops", "label": "Cloud, DevOps & SRE",
     "keywords": r"devops|\bsre\b|site reliability|cloud|infrastructure|kubernetes|\baws\b|azure|\bgcp\b|platform ops|ci/cd|terraform"},
    {"id": "cyber", "label": "Cybersecurity",
     "keywords": r"cyber|security|infosec|penetration|\bsoc\b|vulnerab|threat|incident response|\bgrc\b|identity and access"},
    {"id": "it_support", "label": "IT & Technical Support",
     "keywords": r"\bit\b (support|specialist|technician|analyst)|help ?desk|desktop support|sysadmin|system administrator|"
                 r"network (admin|technician)|technical support"},
    {"id": "embedded_hw", "label": "Embedded & Hardware",
     "keywords": r"embedded|firmware|\bfpga\b|microcontroller|\brtos\b|hardware engineer|electrical engineer|\bpcb\b|circuit|electronics|verilog|vhdl"},
    {"id": "robotics", "label": "Robotics & Autonomy",
     "keywords": r"robot|autonom|\buav\b|\buas\b|drone|unmanned|perception|\bros2?\b|motion planning|sensor fusion|controls engineer"},
    {"id": "systems_test", "label": "Systems, QA & Test",
     "keywords": r"systems engineer|integration|test engineer|\bqa\b|quality assurance|verification|validation|\bsdet\b|test automation|requirements"},
    {"id": "research", "label": "Research & Scientific Computing",
     "keywords": r"research|scientific|physic|simulation|modeling and simulation|\bhpc\b|computational|laborator|scientist"},
    {"id": "product_design", "label": "Product & Design",
     "keywords": r"product manag|program manag|product owner|\bux\b|\bui/ux\b|user experience|product design|interaction design|user research"},
    {"id": "solutions", "label": "Solutions & Sales Engineering",
     "keywords": r"solutions? (engineer|architect|consultant)|sales engineer|customer engineer|technical account|implementation|pre-?sales|field engineer"},
]


@lru_cache(maxsize=64)  # the same few dozen patterns are used for every job, so compile each one once
def _compiled(pattern: str) -> re.Pattern:
    """A pattern compiled case-insensitively. A pattern that isn't a valid regex (a typo in an edited list) is matched as
    plain text instead of raising."""
    try:
        return re.compile(pattern, re.I)
    except re.error:
        return re.compile(re.escape(pattern), re.I)


def classify(title: str, description: str = "", genres: list[dict] | None = None, top: int = 3) -> list[str]:
    """The ids of the genres that best fit a posting, best first, at most `top` of them. `genres` defaults to
    DEFAULT_GENRES; a genre without keywords is matched by its label.

    Score: 3 points per keyword hit in the title, plus 1 per hit in the first 3000 characters of the description, capped
    at 4. A genre needs 2 points to count, so one stray word in a long description isn't enough. When there's no
    description, any title hit counts. Equal scores are ordered by id, from Z to A."""
    genres = genres or DEFAULT_GENRES
    t, d = title or "", (description or "")[:3000]
    scored = []
    for g in genres:
        pat = _compiled(g.get("keywords") or re.escape(g["label"]))
        score = 3 * len(pat.findall(t)) + min(4, len(pat.findall(d)))
        if score >= 2 or (score and not d):
            scored.append((score, g["id"]))
    scored.sort(reverse=True)
    return [gid for _, gid in scored[:top]]


# ---------------------------------------------------------------- industries (what the employer does, for sorting leads)
DEFAULT_INDUSTRIES = [
    "Software & SaaS", "AI & Machine Learning", "Social Media & Consumer Tech", "Fintech & Finance", "Healthcare & Biotech",
    "Space & Aerospace", "Defense & Government Contracting", "Government & Public Sector",
    "Cybersecurity", "Telecom & Networking", "Semiconductors & Hardware", "Energy & Climate", "Automotive & Mobility",
    "Robotics & Manufacturing", "Gaming & Media", "Retail & E-commerce", "Research & Academia", "Education",
    "Consulting & IT Services", "Nonprofit", "Other",
]

# (industry, regex) pairs, tried in this order. The first match wins, so specific industries come before broad ones, and
# "Software & SaaS" comes last. Each regex looks for company names and telling words.
_INDUSTRY_HINTS = [
    ("Space & Aerospace", r"\b(nasa|jpl|spacex|blue origin|rocket ?lab|firefly|intuitive machines|space|aerospace|satellite|orbital|"
                          r"launch|astra\b|varda|vast|astranis|planet labs|spire|blacksky|hawkeye|sierra space|axiom|relativity|ursa major|"
                          r"iceye|muon|northwood|hermeus|boom supersonic|stsci|telescope|avionics|aviation|electra|aircraft)"),
    ("Defense & Government Contracting", r"\b(leidos|northrop|lockheed|raytheon|rtx|l3harris|booz allen|saic|caci|gdit|general dynamics|"
                                         r"peraton|kbr|parsons|bae systems|anduril|shield ai|palantir|epirus|saronic|mantech|amentum|"
                                         r"applied physics laboratory|defense|clearance|dod\b|navy|army|air force|missile)"),
    ("Government & Public Sector", r"\b(usajobs|department of|federal|agency|noaa|nist|naval research|census|state of maryland|county|city of)"),
    ("Cybersecurity", r"\b(cyber|security|dragos|huntress|expel|shift5|two six|tenable|crowdstrike|zerofox|infosec)"),
    ("AI & Machine Learning", r"\b(scale ai|openai|anthropic|machine learning|\bai\b company|llm|artificial intelligence)"),
    ("Social Media & Consumer Tech", r"\b(meta|facebook|instagram|tiktok|snap|pinterest|reddit|discord|twitter|\bx corp|linkedin|spotify|"
                                     r"consumer app|social media|figma|notion|duolingo)"),
    ("Fintech & Finance", r"\b(bank|capital one|fintech|trading|jane street|citadel|two sigma|robinhood|stripe|plaid|insurance|"
                          r"t\. rowe|fidelity|jpmorgan|goldman|finance|financial)"),
    ("Healthcare & Biotech", r"\b(health|medical|hospital|biotech|pharma|clinical|carefirst|johns hopkins medicine|genomic)"),
    ("Telecom & Networking", r"\b(telecom|verizon|at&t|t-mobile|comcast|ciena|cisco|network|wireless|5g|iridium|ast spacemobile|skylo)"),
    ("Semiconductors & Hardware", r"\b(semiconductor|nvidia|intel\b|amd\b|qualcomm|chip|silicon|hardware company|ionq|quantum)"),
    ("Energy & Climate", r"\b(energy|solar|nuclear|climate|utility|grid|battery|radiant)"),
    ("Automotive & Mobility", r"\b(automotive|tesla|rivian|vehicle|mobility|bmw|ford|gm\b|autonomous driving)"),
    ("Robotics & Manufacturing", r"\b(robot|manufactur|industrial|divergent|hadrian|skydio|drone|stanley black)"),
    ("Gaming & Media", r"\b(game|gaming|studio|entertainment|media|streaming|zenimax|bethesda)"),
    ("Retail & E-commerce", r"\b(retail|e-?commerce|amazon|walmart|shop|marketplace|fanatics)"),
    ("Research & Academia", r"\b(university|research institute|laborator|usra|aura\b|college|academ|smithsonian|carnegie)"),
    ("Education", r"\b(education|edtech|school|learning platform|prairielearn)"),
    ("Consulting & IT Services", r"\b(consulting|deloitte|accenture|pwc|kpmg|ey\b|it services|staffing|tek ?systems|insight global)"),
    ("Software & SaaS", r"\b(software|saas|platform|cloud|developer tools|app\b|startup)"),
]


def classify_industry(company: str, title: str = "", description: str = "", industries: list[str] | None = None) -> str:
    """A best guess at the employer's industry, from keywords. Only names in `industries` (default: DEFAULT_INDUSTRIES)
    are returned.

    The company name is checked first, since it's the strongest clue. Then the title and the first 1500 characters of the
    description. When nothing matches, the answer is "Other" (or the list's last name, if "Other" isn't in it). An
    industry the user added in Settings has no hint in _INDUSTRY_HINTS, so only AI triage can pick it."""
    allowed = set(industries or DEFAULT_INDUSTRIES)
    for text in (company or "", f"{title} {(description or '')[:1500]}"):
        for name, pat in _INDUSTRY_HINTS:
            if name in allowed and _compiled(pat).search(text):
                return name
    return "Other" if "Other" in allowed else (industries or DEFAULT_INDUSTRIES)[-1]
