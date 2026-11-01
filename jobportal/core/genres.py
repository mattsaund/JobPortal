"""Two ways of sorting jobs, each with a keyword classifier: work-type genres and employer industries.

Genres describe the work itself (nursing, teaching, skilled trades, software, ...). The list covers every field, and each
genre belongs to one field group (GROUPS), such as healthcare or the skilled trades. AI triage tags each lead with up to
three genres, and classify() is the keyword fallback. search/pipeline.py also uses classify() to count demand per genre
and to mix work types when it picks what to triage next. search/plan.py classifies the user's own target roles, role
families and queries to learn their fields, which is how the Analysis page and the field-specific sources adapt to each
person. The list is the "analysis.genres" setting, which no page edits. Keep each genre's id the same, or the Analysis
history stops lining up.

Industries describe what the employer does (Healthcare & Biotech, Retail & E-commerce, ...). The list is the "industries"
setting (Settings, Search, "Industries"). AI triage normally picks a lead's industry, and classify_industry() is the
fallback when it doesn't, and the way db.py fills in leads stored before industries existed.

Both classifiers are plain keyword matching: fast, free, and good enough to sort by. They never call the AI. Patterns are
written for American spelling; where a posting may use another spelling, the pattern allows both without spelling the
other one out (for example "theat(?:er|re)")."""
import re
from functools import lru_cache

# The field groups, in the order the Analysis page offers them when it has nothing else to go on. Each genre names one.
GROUPS = {
    "healthcare": "Healthcare",
    "education": "Education",
    "business": "Business and office",
    "service": "Service and hospitality",
    "trades": "Skilled trades and industry",
    "creative": "Arts, design and media",
    "science": "Science, research and engineering",
    "public": "Government, nonprofit and public safety",
    "tech": "Technology",
}

# id: stable key stored with leads and history. label: shown in the dashboard. group: a GROUPS key. keywords: a
# case-insensitive regex. The keywords favor job-title words and specific phrases, because one stray word in a long
# description shouldn't be enough to put a job in a genre (see classify()).
DEFAULT_GENRES = [
    # ---- healthcare
    {"id": "nursing", "label": "Nursing", "group": "healthcare",
     "keywords": r"\bnurs(?:e|es|ing)\b|\b(?:rn|lpn|lvn|cna|bsn|msn)\b|charge nurse|nurse practitioner|"
                 r"patient care (?:tech|technician|assistant)|nursing assistant"},
    {"id": "allied_health", "label": "Allied Health & Therapy", "group": "healthcare",
     "keywords": r"physical therap|occupational therap|speech(?:-language)? patholog|respiratory therap|radiolog(?:ic|y) tech|"
                 r"x-ray tech|sonograph|ultrasound tech|medical assistant|phlebotom|\bemt\b|paramedic|dental (?:assistant|hygienist)|"
                 r"surgical tech|medical lab|clinical lab|pharmacist|pharmacy tech|dietitian|athletic trainer|optician|audiolog|"
                 r"therapy assistant|rehab(?:ilitation)? tech"},
    {"id": "physicians", "label": "Physicians & Advanced Practice", "group": "healthcare",
     "keywords": r"physician|surgeon|psychiatrist|hospitalist|anesthesiolog|dentist|optometrist|pediatrician|obstetric|"
                 r"cardiolog|dermatolog|radiologist|oncolog|podiatr|chiropract|nurse practitioner|\bpa-c\b|medical director"},
    {"id": "behavioral_health", "label": "Mental Health & Social Work", "group": "healthcare",
     "keywords": r"counsel(?:or|ing)\b|social work|case manag|mental health|behavioral health|psycholog|\bbcba\b|\brbt\b|"
                 r"behavior (?:tech|technician|analyst)|substance (?:use|abuse)|addiction|peer (?:support|recovery)|"
                 r"\b(?:lcsw|lpc|lmft|lmhc)\b|youth (?:worker|counselor)|family support"},
    {"id": "health_admin", "label": "Healthcare Administration", "group": "healthcare",
     "keywords": r"medical (?:billing|coding|coder|records|receptionist|office|secretary|scheduler)|health information|"
                 r"patient (?:access|services|registration|coordinator|scheduler)|practice manager|clinic (?:manager|coordinator)|"
                 r"healthcare (?:administration|administrator)|revenue cycle|unit (?:secretary|clerk)|health unit coordinator|"
                 r"insurance verification|prior authorization"},
    {"id": "caregiving", "label": "Caregiving & Home Health", "group": "healthcare",
     "keywords": r"caregiver|home health aide|\bhha\b|personal care (?:aide|assistant|attendant)|direct support (?:professional|staff)|"
                 r"\bdsp\b|resident (?:assistant|aide)|patient sitter|in-home (?:care|support)|senior care|home care"},
    # ---- education
    {"id": "teaching", "label": "Teaching", "group": "education",
     "keywords": r"teacher|teaching|educator|instructor|\btutor|professor|lecturer|paraprofessional|paraeducator|"
                 r"substitute teacher|classroom|faculty|\besl\b|\btefl\b|special education|interventionist"},
    {"id": "early_childhood", "label": "Childcare & Early Childhood", "group": "education",
     "keywords": r"child ?care|preschool|pre-k|day ?care|early childhood|nanny|au pair|infant (?:teacher|room)|toddler|"
                 r"head start|babysit"},
    {"id": "student_services", "label": "Education Administration & Student Services", "group": "education",
     "keywords": r"admissions|registrar|academic advis|student (?:services|affairs|success|life|support)|financial aid|"
                 r"enrollment (?:counselor|advisor|specialist|coordinator)|(?:assistant|vice|school) principal|\bdean of\b|"
                 r"(?:associate|assistant) dean|school counselor|instructional design|career services|residence life|bursar"},
    {"id": "library_museum", "label": "Libraries, Archives & Museums", "group": "education",
     "keywords": r"librarian|library (?:assistant|associate|technician|clerk|aide|manager|director|services|specialist|page)|"
                 r"public library|school library|archivist|museum|curator|conservator|docent|"
                 r"collections (?:manager|specialist|assistant)"},
    # ---- business and office
    {"id": "admin_office", "label": "Administrative & Office", "group": "business",
     "keywords": r"administrative (?:assistant|associate|coordinator|specialist|support)|office (?:manager|assistant|administrator|"
                 r"coordinator|clerk)|receptionist|secretary|executive assistant|clerical|data entry|front desk|file clerk|"
                 r"mail ?room|virtual assistant"},
    {"id": "customer_service", "label": "Customer Service & Support", "group": "business",
     "keywords": r"customer (?:service|support|care|experience|success)|call center|contact center|client (?:services|support)|"
                 r"guest services|member services|chat support|service desk agent"},
    {"id": "sales", "label": "Sales & Business Development", "group": "business",
     "keywords": r"\bsales\b|account (?:executive|manager)|business development|\b(?:bdr|sdr)\b|inside sales|outside sales|"
                 r"territory (?:manager|representative)|real estate agent|realtor|insurance agent|loan officer|"
                 r"leasing (?:agent|consultant)"},
    {"id": "marketing", "label": "Marketing & Communications", "group": "business",
     "keywords": r"marketing|brand (?:manager|ambassador|strategist)|social media|content (?:marketing|strategist|creator)|"
                 r"public relations|communications (?:specialist|manager|coordinator|director|associate)|\bseo\b|copywrit|"
                 r"advertising|media buyer|event (?:planner|coordinator)|community manager"},
    {"id": "finance_accounting", "label": "Finance & Accounting", "group": "business",
     "keywords": r"accountant|accounting|bookkeep|\bcpa\b|auditor|\baudit\b|tax (?:preparer|accountant|associate|analyst|specialist|"
                 r"manager)|payroll|accounts (?:payable|receivable)|financial (?:analyst|advisor|planner)|\bfinance\b|controller|"
                 r"treasury|credit analyst|underwrit|actuar|\bteller\b|loan (?:processor|underwriter)|billing specialist|"
                 r"budget analyst|investment"},
    {"id": "hr", "label": "Human Resources & Recruiting", "group": "business",
     "keywords": r"human resources|\bhr\b|recruit(?:er|ing)|talent acquisition|people (?:operations|partner)|"
                 r"benefits (?:specialist|administrator|coordinator)|compensation|training (?:and|&) development|"
                 r"learning (?:and|&) development|onboarding (?:specialist|coordinator)|employee relations"},
    {"id": "management_ops", "label": "Management, Operations & Projects", "group": "business",
     "keywords": r"project manag|program (?:manager|coordinator|director|specialist)|operations (?:manager|coordinator|analyst|"
                 r"associate|specialist|supervisor|director)|general manager|business (?:analyst|operations)|"
                 r"management consultant|process improvement|\bpmp\b|scrum master|chief of staff|(?:store|district|branch) manager"},
    {"id": "legal", "label": "Legal", "group": "business",
     "keywords": r"attorney|lawyer|paralegal|legal (?:assistant|secretary|counsel|analyst|specialist)|(?:general|associate|"
                 r"in-house) counsel|law clerk|litigation|compliance (?:analyst|officer|specialist|manager)|"
                 r"contracts? (?:manager|administrator|specialist)|court (?:clerk|reporter)|\bj\.?d\.?\b"},
    # ---- service and hospitality
    {"id": "food_hospitality", "label": "Food Service & Hospitality", "group": "service",
     "keywords": r"\bchef\b|\bcook\b|line cook|prep cook|kitchen|culinary|restaurant|waiter|waitress|bartend|barista|hostess|"
                 r"food service|catering|banquet|dishwasher|busser|\bbaker\b|pastry|hotel|hospitality|housekeep|room attendant|"
                 r"concierge|\bvalet\b|resort|food and beverage|\bf&b\b"},
    {"id": "retail", "label": "Retail", "group": "service",
     "keywords": r"retail|cashier|store (?:associate|clerk|team member)|sales (?:associate|floor)|merchandis|stocker|"
                 r"stock associate|shift (?:lead|supervisor)|key ?holder|team member|grocery|loss prevention|department manager"},
    {"id": "personal_care", "label": "Personal Care, Beauty & Fitness", "group": "service",
     "keywords": r"cosmetolog|hair ?stylist|barber|esthetician|aesthetician|nail tech|manicurist|massage therap|\blmt\b|"
                 r"\bday spa\b|med ?spa|spa (?:attendant|manager|coordinator|therapist)|salon|makeup artist|personal trainer|"
                 r"fitness (?:instructor|coach|trainer)|yoga instructor|pilates|lifeguard|recreation (?:aide|leader|coordinator)|"
                 r"camp counselor"},
    # ---- skilled trades and industry
    {"id": "skilled_trades", "label": "Skilled Trades", "group": "trades",
     "keywords": r"electrician|plumb(?:er|ing)|pipefitter|steamfitter|carpent(?:er|ry)|\bhvac|refrigeration tech|weld(?:er|ing)|"
                 r"millwright|sheet metal|boilermaker|ironworker|\bmason\b|bricklayer|roofer|glazier|insulator|lineman|"
                 r"line worker|apprentice|journeym[ae]n|tradesperson|elevator (?:mechanic|installer)|locksmith|solar install"},
    {"id": "construction", "label": "Construction", "group": "trades",
     "keywords": r"construction|laborer|superintendent|estimator|site (?:supervisor|manager)|forem[ae]n|heavy equipment|"
                 r"equipment operator|concrete|framer|framing|drywall|\bpainter\b|flooring|demolition|surveyor|"
                 r"general contractor"},
    {"id": "manufacturing", "label": "Manufacturing & Production", "group": "trades",
     "keywords": r"manufactur|production (?:worker|associate|operator|supervisor|technician|manager)|assembler|assembly "
                 r"(?:line|technician)|machinist|\bcnc\b|fabricat(?:or|ion)|machine operator|quality (?:inspector|control|"
                 r"technician)|plant (?:manager|operator|supervisor)|process technician|tool and die|industrial (?:maintenance|"
                 r"mechanic)"},
    {"id": "maintenance_auto", "label": "Maintenance, Repair & Automotive", "group": "trades",
     "keywords": r"mechanic|maintenance (?:technician|tech|worker|mechanic|supervisor)|repair (?:technician|tech)|automotive|"
                 r"auto (?:technician|body|tech)|diesel|collision|tire (?:technician|tech)|aircraft (?:mechanic|maintenance)|"
                 r"\ba&p\b|facilities (?:technician|maintenance)|building (?:engineer|maintenance)|groundskeep|custodian|janitor|"
                 r"appliance repair|small engine"},
    {"id": "logistics", "label": "Logistics, Warehouse & Driving", "group": "trades",
     "keywords": r"warehouse|logistics|supply chain|forklift|shipping (?:and|&) receiving|(?:shipping|receiving) (?:clerk|"
                 r"associate)|inventory (?:specialist|control|associate|clerk)|material handler|order (?:picker|selector)|"
                 r"\bpicker\b|\bpacker\b|\bcdl\b|(?:truck|delivery|bus|van|route|commercial|shuttle|tow) driver|courier|"
                 r"dispatcher|freight|procurement|purchasing (?:agent|manager|specialist)|distribution center|stockroom"},
    # ---- arts, design and media
    {"id": "art_design", "label": "Art & Design", "group": "creative",
     "keywords": r"graphic design|designer|illustrat|art director|\bartist\b|animat(?:or|ion)|motion (?:graphics|designer)|"
                 r"3d (?:artist|modeler)|photograph|videograph|fashion|interior design|textile|jewelry|tattoo|ceramic|"
                 r"creative director|visual design"},
    {"id": "writing_media", "label": "Writing, Media & Publishing", "group": "creative",
     "keywords": r"writer|copywriter|(?<!code )(?<!text )\beditor\b|editorial|journalis|reporter|correspondent|proofread|"
                 r"publishing|content (?:writer|producer|creator|strategist)|grant writer|broadcast|podcast|"
                 r"news (?:producer|anchor|desk)|translator|interpreter|video editor|(?:video|news|content|associate|segment|"
                 r"audio|tv|television) producer"},
    {"id": "performing_arts", "label": "Music, Film & Performing Arts", "group": "creative",
     "keywords": r"musician|\bmusic\b|singer|vocalist|\bactor\b|actress|theat(?:er|re)|\bdance|choreograph|\bfilm\b|cinema|"
                 r"stage (?:manager|hand|crew)|production assistant|(?:audio|sound) (?:engineer|technician|designer)|"
                 r"lighting (?:technician|designer)|camera operator|cinematograph|composer|orchestra|band director|"
                 r"voice actor|entertain"},
    # ---- science, research and engineering
    {"id": "research", "label": "Research & Lab Science", "group": "science",
     "keywords": r"research|scientist|scientific|laborator|\blab (?:tech|technician|assistant|manager)|chemist|biolog|physic|"
                 r"biochem|genetic|clinical (?:research|trial)|postdoc|simulation|computational|\bhpc\b"},
    {"id": "environment_ag", "label": "Environment, Agriculture & Animals", "group": "science",
     "keywords": r"environmental (?:scientist|specialist|technician|engineer|compliance|health)|sustainab|conservation|ecolog|"
                 r"forestry|forester|park ranger|wildlife|natural resources|agricultur|agronom|\bfarm|ranch|horticultur|"
                 r"landscap|greenhouse|arborist|veterinar|vet tech|animal (?:care|caretaker|shelter|technician)|kennel|"
                 r"groomer|zookeeper|aquarium|fisheries|water (?:quality|resources)|geolog|hydrolog|\bgis\b"},
    {"id": "engineering", "label": "Engineering (civil, mechanical, electrical and more)", "group": "science",
     "keywords": r"(?:mechanical|civil|structural|electrical|chemical|industrial|manufacturing|process|environmental|biomedical|"
                 r"materials|design|project|aerospace|petroleum|nuclear) engineer|\bcad\b|autocad|solidworks|revit|drafter|"
                 r"drafting|professional engineer|engineering technician|architectural|licensed architect|project architect"},
    # ---- government, nonprofit and public safety
    {"id": "government", "label": "Government & Public Administration", "group": "public",
     "keywords": r"public (?:administration|policy|affairs|works|health)|policy (?:analyst|advisor|associate)|"
                 r"government (?:relations|affairs|analyst)|municipal|city of\b|county of\b|legislative|"
                 r"eligibility (?:specialist|worker|technician)|caseworker|benefits (?:counselor|specialist)|"
                 r"grants? (?:manager|specialist|administrator|coordinator)|civil service|city planner|urban planning|"
                 r"planning (?:technician|commission)|postal"},
    {"id": "nonprofit", "label": "Nonprofit & Community", "group": "public",
     "keywords": r"nonprofit|non-profit|community (?:outreach|organizer|health worker|engagement|coordinator|liaison)|"
                 r"outreach (?:worker|coordinator|specialist)|volunteer (?:coordinator|manager)|fundrais|"
                 r"development (?:officer|associate|director|coordinator)|grant writ|advocacy|americorps|food bank|ministry|"
                 r"pastor|youth (?:program|development)"},
    {"id": "public_safety", "label": "Public Safety & Security", "group": "public",
     "keywords": r"police|law enforcement|sheriff|patrol|correctional|corrections officer|detention officer|"
                 r"(?<!information )(?<!cyber )security (?:guard|officer)|firefight|fire (?:fighter|marshal|inspector|chief)|"
                 r"emergency (?:management|dispatcher)|911 dispatch|probation|parole|border patrol|park police"},
    # ---- technology (the ids from before v0.3.0, so the Analysis history of tech users keeps lining up)
    {"id": "swe", "label": "Software Engineering", "group": "tech",
     "keywords": r"software (?:engineer|develop)|\bswe\b|developer|programmer|full[- ]?stack|back[- ]?end|application develop|"
                 r"platform engineer"},
    {"id": "frontend_mobile", "label": "Frontend & Mobile", "group": "tech",
     "keywords": r"front[- ]?end|\bui\b engineer|web (?:app|develop)|react|javascript|typescript|mobile (?:developer|engineer|app)|"
                 r"\bios\b|android|swift|kotlin|flutter"},
    {"id": "data", "label": "Data Science & Analytics", "group": "tech",
     "keywords": r"data scien|data analy|analytics|statistic|business intelligence|data engineer|\betl\b|tableau|power bi|"
                 r"data visuali|\bsql\b"},
    {"id": "ml_ai", "label": "ML & AI", "group": "tech",
     "keywords": r"machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|computer vision|\bnlp\b|\bllms?\b|neural|"
                 r"generative"},
    {"id": "cloud_devops", "label": "Cloud, DevOps & SRE", "group": "tech",
     "keywords": r"devops|\bsre\b|site reliability|cloud|infrastructure engineer|kubernetes|\baws\b|azure|\bgcp\b|platform ops|"
                 r"ci/cd|terraform"},
    {"id": "cyber", "label": "Cybersecurity", "group": "tech",
     "keywords": r"cyber|information security|infosec|security (?:analyst|engineer|architect|operations)|penetration|\bsoc\b|"
                 r"vulnerab|threat (?:intel|hunt|detection)|incident response|\bgrc\b|identity and access"},
    {"id": "it_support", "label": "IT & Technical Support", "group": "tech",
     "keywords": r"\bit\b (?:support|specialist|technician|analyst)|help ?desk|desktop support|sysadmin|system administrator|"
                 r"network (?:admin|technician|engineer)|technical support"},
    {"id": "embedded_hw", "label": "Embedded & Hardware", "group": "tech",
     "keywords": r"embedded|firmware|\bfpga\b|microcontroller|\brtos\b|hardware engineer|\bpcb\b|circuit|electronics|verilog|"
                 r"vhdl"},
    {"id": "robotics", "label": "Robotics & Automation", "group": "tech",
     "keywords": r"robot|autonom|\buav\b|drone|unmanned|perception|\bros2?\b|motion planning|sensor fusion|controls engineer|"
                 r"automation engineer|\bplc\b"},
    {"id": "systems_test", "label": "Systems, QA & Test", "group": "tech",
     "keywords": r"systems engineer|test engineer|\bqa\b|quality assurance (?:engineer|analyst|tester)|software test|"
                 r"\bsdet\b|test automation|verification engineer|validation engineer"},
    {"id": "product_design", "label": "Product & UX", "group": "tech",
     "keywords": r"product manag|product owner|\bux\b|\bui/ux\b|user experience|product design|interaction design|"
                 r"user research"},
    {"id": "solutions", "label": "Solutions & Sales Engineering", "group": "tech",
     "keywords": r"solutions? (?:engineer|architect|consultant)|sales engineer|customer engineer|technical account|"
                 r"pre-?sales|field (?:application|service) engineer"},
]
# The ids of the genres every version before v0.3.0 shipped (all technology). core/settings.py uses them to tell a genre
# list nobody customized from one a user edited.
LEGACY_GENRE_IDS = {"swe", "frontend_mobile", "data", "ml_ai", "cloud_devops", "cyber", "it_support", "embedded_hw",
                    "robotics", "systems_test", "research", "product_design", "solutions"}


def group_of(genre: dict) -> str:
    """The field group of a genre: its "group", or "tech" for a pre-v0.3.0 genre id stored without one, or "other"."""
    if genre.get("group"):
        return genre["group"]
    return "tech" if genre.get("id") in LEGACY_GENRE_IDS - {"research"} else "other"


@lru_cache(maxsize=256)  # the same few dozen patterns are used for every job, so compile each one once
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
    "Healthcare & Biotech", "Education", "Government & Public Sector", "Nonprofit & Social Services", "Finance & Insurance",
    "Professional Services & Consulting", "Legal Services", "Staffing & Recruiting", "Technology & Software",
    "Telecommunications", "Media & Entertainment", "Arts & Culture", "Retail & E-commerce", "Restaurants & Food Service",
    "Hospitality & Travel", "Beauty, Fitness & Personal Care", "Construction & Real Estate", "Manufacturing",
    "Transportation & Logistics", "Energy & Utilities", "Agriculture & Environment", "Automotive & Mobility",
    "Aerospace & Defense", "Research & Academia", "Other",
]
# Industry names from before v0.3.0 and the name each one became. db._migrate() renames them on saved leads,
# core/settings.py in a saved industry list, and candidate/onboarding.py in saved answers to the industries question.
OLD_INDUSTRIES = {
    "Software & SaaS": "Technology & Software", "AI & Machine Learning": "Technology & Software",
    "Social Media & Consumer Tech": "Technology & Software", "Cybersecurity": "Technology & Software",
    "Semiconductors & Hardware": "Technology & Software", "Telecom & Networking": "Telecommunications",
    "Consulting & IT Services": "Professional Services & Consulting", "Fintech & Finance": "Finance & Insurance",
    "Space & Aerospace": "Aerospace & Defense", "Defense & Government Contracting": "Aerospace & Defense",
    "Energy & Climate": "Energy & Utilities", "Robotics & Manufacturing": "Manufacturing", "Gaming & Media": "Media & Entertainment",
    "Nonprofit": "Nonprofit & Social Services",
}
# The industry list every version before v0.3.0 shipped, so core/settings.py can tell it from a list the user edited.
LEGACY_INDUSTRIES = [
    "Software & SaaS", "AI & Machine Learning", "Social Media & Consumer Tech", "Fintech & Finance", "Healthcare & Biotech",
    "Space & Aerospace", "Defense & Government Contracting", "Government & Public Sector", "Cybersecurity", "Telecom & Networking",
    "Semiconductors & Hardware", "Energy & Climate", "Automotive & Mobility", "Robotics & Manufacturing", "Gaming & Media",
    "Retail & E-commerce", "Research & Academia", "Education", "Consulting & IT Services", "Nonprofit", "Other",
]

# (industry, telling words, large employers) for classify_industry(), tried in this order. The first match wins, so
# specific industries come before broad ones. The telling words are phrases a posting uses about its employer; they are
# checked in the company name, the title and the start of the description. Large employers whose names say nothing
# about what they do are only checked in the company name, since "Target" or "Progressive" can be ordinary words in a
# description. Words that every posting's benefits section uses ("health insurance", "medical, dental") are left out.
_INDUSTRY_HINTS = [
    ("Staffing & Recruiting", r"staffing (?:agency|firm|company|services)|recruiting (?:agency|firm)|employment agency|temp agency",
     r"robert half|randstad|adecco|manpower|kelly services|aerotek|insight global|teksystems"),
    ("Healthcare & Biotech", r"hospital|health system|healthcare (?:provider|organization|system|company)|medical (?:center|group|"
                             r"practice|clinic)|clinic\b|nursing home|skilled nursing|senior living|home health|hospice|"
                             r"pharmaceutical|biotech|behavioral health|rehabilitation (?:center|hospital)|dental (?:office|"
                             r"practice|group)|life sciences|urgent care",
     r"kaiser|mayo clinic|walgreens|cvs|hca\b|ascension|pfizer|merck"),
    ("Education", r"school district|public schools|board of education|edtech|child ?care (?:center|provider)|"
                  r"learning cent(?:er|re)|tutoring (?:company|center)",
     r"school\b|schools\b|academy\b|preschool|kindercare|bright horizons"),
    ("Research & Academia", r"research institute|research (?:center|laboratory)|national lab", r"university\b|college\b|smithsonian"),
    ("Government & Public Sector", r"usajobs|federal (?:agency|government)|state agency|county government|city government|"
                                   r"municipal government|public works department|transit authority",
     r"department of\b|city of\b|county of\b|town of\b|township|municipal|postal service|state of\b"),
    ("Nonprofit & Social Services", r"nonprofit|non-profit|501\(c\)|charitable organization|food bank|social services|"
                                    r"community action",
     r"ymca|ywca|boys & girls club|united way|habitat for humanity|goodwill|salvation army|red cross"),
    ("Legal Services", r"law firm|law office|legal services|attorneys at law|legal aid", r"llp\b"),
    ("Finance & Insurance", r"bank\b|banking|credit union|insurance (?:company|agency|carrier|provider|brokerage)|"
                            r"financial (?:services|institution|advisors?)|wealth management|investment (?:firm|bank|management)|"
                            r"asset management|mortgage|lending|fintech|accounting firm|cpa firm",
     r"jpmorgan|wells fargo|goldman|fidelity|state farm|allstate|progressive|capital one|charles schwab|vanguard"),
    ("Professional Services & Consulting", r"consulting (?:firm|group|company)|consultancy|advisory firm|marketing agency|"
                                           r"advertising agency|design agency|creative agency|it services",
     r"deloitte|accenture|pwc|kpmg|ernst & young|booz allen|mckinsey"),
    ("Aerospace & Defense", r"aerospace|aircraft|avionics|defense contractor|department of defense|missile|shipbuild",
     r"boeing|lockheed|northrop|raytheon|general dynamics|l3harris"),
    ("Automotive & Mobility", r"automotive|car dealership|auto (?:repair|body|parts|group)|collision (?:center|repair)",
     r"tesla|ford\b|general motors|toyota|honda|carmax|firestone|jiffy lube"),
    ("Restaurants & Food Service", r"restaurant|cafe\b|coffee (?:shop|house|company)|bakery|catering|food service|"
                                   r"quick service|fast casual",
     r"mcdonald|starbucks|chipotle|subway|wendy|taco bell|darden|aramark|sodexo|compass group"),
    ("Hospitality & Travel", r"hotel|resort|hospitality|casino|cruise line|airline|travel (?:company|agency)|tourism",
     r"marriott|hilton|hyatt|ihg\b|disney"),
    ("Beauty, Fitness & Personal Care", r"hair salon|nail salon|day spa\b|barbershop|beauty (?:company|brand|salon)|"
                                        r"fitness studio|yoga studio",
     r"salon\b|spa\b|fitness|gym\b|ulta\b|sephora|great clips"),
    ("Retail & E-commerce", r"retail|e-?commerce|online store|grocery|supermarket|department store|convenience store",
     r"walmart|target\b|costco|kroger|home depot|lowe'?s|best buy|amazon\b|macy|publix|safeway|aldi\b|dollar general"),
    ("Arts & Culture", r"museum|art gallery|theat(?:er|re) company|orchestra|symphony|opera\b|ballet|arts (?:center|council|"
                       r"organization)|public library", r"smithsonian"),
    ("Media & Entertainment", r"media company|news (?:organization|outlet|station)|newspaper|publishing (?:house|company)|"
                              r"magazine|broadcast|radio station|television|film studio|production company|game studio|"
                              r"video game|streaming service|record label",
     r"netflix|warner|paramount|nbcuniversal|iheart"),
    ("Telecommunications", r"telecom|wireless (?:carrier|provider)|broadband|cable provider|internet service provider",
     r"verizon|at&t|t-mobile|comcast|spectrum\b|charter communications"),
    ("Energy & Utilities", r"energy company|electric (?:company|utility|cooperative)|utility company|public utility|power plant|"
                           r"solar (?:company|installer)|wind farm|oil (?:and|&) gas|nuclear plant|water district",
     r"energy\b|utilities\b|power\b|duke energy|exxon|chevron|shell\b|bp\b"),
    ("Agriculture & Environment", r"farm\b|agricultur|ranch\b|plant nursery|landscaping company|environmental (?:consulting|"
                                  r"services|agency)|forestry|conservation|veterinary (?:clinic|hospital)|animal hospital", ""),
    ("Construction & Real Estate", r"construction (?:company|firm)|general contractor|homebuilder|roofing|plumbing (?:company|"
                                   r"contractor)|electrical contractor|hvac (?:company|contractor)|real estate|property management|"
                                   r"realty",
     r"builders\b|homes\b"),
    ("Transportation & Logistics", r"logistics (?:company|provider|firm)|third-party logistics|3pl\b|trucking|freight|"
                                   r"shipping company|transportation (?:company|provider)|delivery service|distribution center|"
                                   r"courier service",
     r"logistics\b|transport|ups\b|fedex|dhl\b|xpo\b|j\.?b\.? hunt"),
    ("Manufacturing", r"manufacturing (?:company|plant|facility|facilities)|manufacturer|factory|production facility|"
                      r"machine shop|fabrication shop|packaging company|semiconductor",
     r"manufactur|industries\b|industrial\b"),
    ("Technology & Software", r"software company|saas\b|tech company|technology company|cloud (?:computing|platform)|"
                              r"cybersecurity company|startup",
     r"software|tech\b|technologies|google|microsoft|apple\b|meta\b|ibm\b|oracle|salesforce|adobe|nvidia|intel\b"),
]


@lru_cache(maxsize=64)
def _hint_patterns(words: str, employers: str) -> tuple[re.Pattern, re.Pattern]:
    """The compiled hints of one industry: (telling words only, telling words or employers). Each must start at a word."""
    either = "|".join(p for p in (words, employers) if p)
    return _compiled(rf"\b(?:{words})"), _compiled(rf"\b(?:{either})")


def classify_industry(company: str, title: str = "", description: str = "", industries: list[str] | None = None) -> str:
    """A best guess at the employer's industry, from keywords. Only names in `industries` (default: DEFAULT_INDUSTRIES)
    are returned.

    The company name is checked first, since it's the strongest clue, against both the telling words and the large
    employers. Then the title and the first 1500 characters of the description, against the telling words only. When
    nothing matches, the answer is "Other" (or the list's last name, if "Other" isn't in it). An industry the user added
    in Settings has no hint in _INDUSTRY_HINTS, so only AI triage can pick it."""
    allowed = set(industries or DEFAULT_INDUSTRIES)
    hints = [(name, *_hint_patterns(words, employers)) for name, words, employers in _INDUSTRY_HINTS if name in allowed]
    for name, _, words_or_employers in hints:
        if company and words_or_employers.search(company):
            return name
    text = f"{title or ''} {(description or '')[:1500]}"
    for name, words, _ in hints:
        if words.search(text):
            return name
    return "Other" if "Other" in allowed else (industries or DEFAULT_INDUSTRIES)[-1]
