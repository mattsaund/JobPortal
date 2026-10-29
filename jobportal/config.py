"""Paths and default settings. Everything here is editable from the dashboard; stored settings are deep-merged over these
defaults so new keys show up after updates.

Your data never lives in the code folder. It goes in the platform's app-data folder (override with JOBPORTAL_HOME):
  Windows  %LOCALAPPDATA%\\JobPortal
  macOS    ~/Library/Application Support/JobPortal
  Linux    ~/.local/share/JobPortal"""
import os
from pathlib import Path

from platformdirs import user_cache_dir, user_data_dir

from .genres import DEFAULT_GENRES, DEFAULT_INDUSTRIES
from .levels import DEFAULT_LEVELS, title_filters

APP_NAME = "JobPortal"
PKG = Path(__file__).resolve().parent
STATIC = PKG / "static"
RESOURCES = PKG / "resources"

_home_env = os.environ.get("JOBPORTAL_HOME")
DATA = Path(_home_env).expanduser().resolve() if _home_env else Path(user_data_dir(APP_NAME, appauthor=False))
# With JOBPORTAL_HOME set (tests, a second profile) the cache lives inside it too, so instances never share anything.
CACHE = DATA / "cache" if _home_env else Path(user_cache_dir(APP_NAME, appauthor=False))
DB_PATH = DATA / "jobportal.db"
LEADS_DIR = DATA / "leads"
RESUME_DIR = DATA / "resume"
WORKSPACE = DATA / "agent_workspace"  # empty working folder for the AI agents (they get no file access)
HOST = "127.0.0.1"
PORT = int(os.environ.get("JOBPORTAL_PORT") or 8788)

MODELS = ["fable", "opus", "sonnet", "haiku"]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]

APP_STATUSES = ["new", "saved", "applied", "assessment", "interviewing", "offer",
                "rejected", "ghosted", "withdrawn", "trashed"]

# Company job boards with public JSON APIs (verified live in October 2026). Add any company from Sources by pasting its careers URL.
ATS_BOARDS = [
    # Space, defense and deep tech (Greenhouse)
    {"name": "SpaceX", "ats": "greenhouse", "slug": "spacex"},
    {"name": "Rocket Lab", "ats": "greenhouse", "slug": "rocketlab"},
    {"name": "Astranis", "ats": "greenhouse", "slug": "astranis"},
    {"name": "Varda Space", "ats": "greenhouse", "slug": "vardaspace"},
    {"name": "Vast", "ats": "greenhouse", "slug": "vast"},
    {"name": "Muon Space", "ats": "greenhouse", "slug": "muonspace"},
    {"name": "Inversion Space", "ats": "greenhouse", "slug": "inversionspace"},
    {"name": "Ursa Major", "ats": "greenhouse", "slug": "ursamajor"},
    {"name": "Planet", "ats": "greenhouse", "slug": "planetlabs"},
    {"name": "BlackSky", "ats": "greenhouse", "slug": "blacksky"},
    {"name": "HawkEye 360", "ats": "greenhouse", "slug": "hawkeye360"},
    {"name": "Spire Global", "ats": "greenhouse", "slug": "spire"},
    {"name": "Epirus", "ats": "greenhouse", "slug": "epirus"},
    {"name": "GITAI", "ats": "greenhouse", "slug": "gitai"},
    {"name": "Divergent", "ats": "greenhouse", "slug": "divergent"},
    {"name": "Momentus", "ats": "greenhouse", "slug": "momentus"},
    {"name": "Albedo", "ats": "greenhouse", "slug": "albedo"},
    {"name": "Voyager Technologies", "ats": "greenhouse", "slug": "voyagertechnologiesinc"},
    {"name": "Scale AI", "ats": "greenhouse", "slug": "scaleai"},
    # Lever
    {"name": "Hermeus", "ats": "lever", "slug": "hermeus"},
    {"name": "Loft Orbital", "ats": "lever", "slug": "loftorbital"},
    {"name": "Shield AI", "ats": "lever", "slug": "shieldai"},
    {"name": "Merlin Labs", "ats": "lever", "slug": "merlinlabs"},
    {"name": "Palantir", "ats": "lever", "slug": "palantir"},
    # Ashby
    {"name": "Northwood Space", "ats": "ashby", "slug": "northwoodspace"},
    {"name": "Astra", "ats": "ashby", "slug": "astra"},
    {"name": "Radiant", "ats": "ashby", "slug": "radiant"},
    {"name": "Outpost", "ats": "ashby", "slug": "outpost"},
    {"name": "Quindar", "ats": "ashby", "slug": "quindar"},
    {"name": "Lunar Outpost", "ats": "ashby", "slug": "lunar"},
    {"name": "Saronic", "ats": "ashby", "slug": "saronic"},
    {"name": "Skydio", "ats": "ashby", "slug": "skydio"},
    # Defense tech, cyber, quantum and space
    {"name": "Anduril", "ats": "greenhouse", "slug": "andurilindustries"},
    {"name": "AST SpaceMobile", "ats": "greenhouse", "slug": "astspacemobile"},
    {"name": "Relativity Space", "ats": "greenhouse", "slug": "relativity"},
    {"name": "IonQ", "ats": "greenhouse", "slug": "ionq"},
    {"name": "Dragos", "ats": "greenhouse", "slug": "dragos"},
    {"name": "Huntress", "ats": "greenhouse", "slug": "huntress"},
    {"name": "Two Six Technologies", "ats": "greenhouse", "slug": "twosixtechnologies"},
    {"name": "Shift5", "ats": "greenhouse", "slug": "shift5"},
    {"name": "Electra.aero", "ats": "greenhouse", "slug": "electraaero"},
    {"name": "Expel", "ats": "greenhouse", "slug": "expel"},
    {"name": "ICEYE", "ats": "ashby", "slug": "iceye"},
    {"name": "Boom Supersonic", "ats": "ashby", "slug": "boom"},
    {"name": "Skylo", "ats": "ashby", "slug": "skylo"},
    # Social and consumer, fintech, AI, developer tools, health, gov-tech, media and edtech
    {"name": "Reddit", "ats": "greenhouse", "slug": "reddit"},
    {"name": "Discord", "ats": "greenhouse", "slug": "discord"},
    {"name": "Pinterest", "ats": "greenhouse", "slug": "pinterest"},
    {"name": "Nextdoor", "ats": "greenhouse", "slug": "nextdoor"},
    {"name": "Twitch", "ats": "greenhouse", "slug": "twitch"},
    {"name": "Duolingo", "ats": "greenhouse", "slug": "duolingo"},
    {"name": "Figma", "ats": "greenhouse", "slug": "figma"},
    {"name": "Robinhood", "ats": "greenhouse", "slug": "robinhood"},
    {"name": "Stripe", "ats": "greenhouse", "slug": "stripe"},
    {"name": "Coinbase", "ats": "greenhouse", "slug": "coinbase"},
    {"name": "Affirm", "ats": "greenhouse", "slug": "affirm"},
    {"name": "Chime", "ats": "greenhouse", "slug": "chime"},
    {"name": "SoFi", "ats": "greenhouse", "slug": "sofi"},
    {"name": "Brex", "ats": "greenhouse", "slug": "brex"},
    {"name": "Block", "ats": "greenhouse", "slug": "block"},
    {"name": "Mercury", "ats": "greenhouse", "slug": "mercury"},
    {"name": "Betterment", "ats": "greenhouse", "slug": "betterment"},
    {"name": "Carta", "ats": "greenhouse", "slug": "carta"},
    {"name": "Databricks", "ats": "greenhouse", "slug": "databricks"},
    {"name": "Datadog", "ats": "greenhouse", "slug": "datadog"},
    {"name": "Cloudflare", "ats": "greenhouse", "slug": "cloudflare"},
    {"name": "Twilio", "ats": "greenhouse", "slug": "twilio"},
    {"name": "Okta", "ats": "greenhouse", "slug": "okta"},
    {"name": "Elastic", "ats": "greenhouse", "slug": "elastic"},
    {"name": "MongoDB", "ats": "greenhouse", "slug": "mongodb"},
    {"name": "GitLab", "ats": "greenhouse", "slug": "gitlab"},
    {"name": "Vercel", "ats": "greenhouse", "slug": "vercel"},
    {"name": "Dropbox", "ats": "greenhouse", "slug": "dropbox"},
    {"name": "Bitwarden", "ats": "greenhouse", "slug": "bitwarden"},
    {"name": "Airbnb", "ats": "greenhouse", "slug": "airbnb"},
    {"name": "Lyft", "ats": "greenhouse", "slug": "lyft"},
    {"name": "Instacart", "ats": "greenhouse", "slug": "instacart"},
    {"name": "Toast", "ats": "greenhouse", "slug": "toast"},
    {"name": "Gusto", "ats": "greenhouse", "slug": "gusto"},
    {"name": "Checkr", "ats": "greenhouse", "slug": "checkr"},
    {"name": "Squarespace", "ats": "greenhouse", "slug": "squarespace"},
    {"name": "Typeform", "ats": "greenhouse", "slug": "typeform"},
    {"name": "Webflow", "ats": "greenhouse", "slug": "webflow"},
    {"name": "Asana", "ats": "greenhouse", "slug": "asana"},
    {"name": "Airtable", "ats": "greenhouse", "slug": "airtable"},
    {"name": "Calendly", "ats": "greenhouse", "slug": "calendly"},
    {"name": "Roblox", "ats": "greenhouse", "slug": "roblox"},
    {"name": "Riot Games", "ats": "greenhouse", "slug": "riotgames"},
    {"name": "Epic Games", "ats": "greenhouse", "slug": "epicgames"},
    {"name": "Scopely", "ats": "greenhouse", "slug": "scopely"},
    {"name": "Peloton", "ats": "greenhouse", "slug": "peloton"},
    {"name": "Oscar", "ats": "greenhouse", "slug": "oscar"},
    {"name": "Zocdoc", "ats": "greenhouse", "slug": "zocdoc"},
    {"name": "Anthropic", "ats": "greenhouse", "slug": "anthropic"},
    {"name": "Axios", "ats": "greenhouse", "slug": "axios"},
    {"name": "Mozilla", "ats": "greenhouse", "slug": "mozilla"},
    {"name": "Wikimedia", "ats": "greenhouse", "slug": "wikimedia"},
    {"name": "Khan Academy", "ats": "greenhouse", "slug": "khanacademy"},
    {"name": "Coursera", "ats": "greenhouse", "slug": "coursera"},
    {"name": "2U", "ats": "greenhouse", "slug": "2u"},
    {"name": "Nava PBC", "ats": "greenhouse", "slug": "navapbc"},
    {"name": "Oddball", "ats": "greenhouse", "slug": "oddball"},
    {"name": "Code for America", "ats": "greenhouse", "slug": "codeforamerica"},
    {"name": "OpenAI", "ats": "ashby", "slug": "openai"},
    {"name": "Perplexity", "ats": "ashby", "slug": "perplexity"},
    {"name": "Notion", "ats": "ashby", "slug": "notion"},
    {"name": "Linear", "ats": "ashby", "slug": "linear"},
    {"name": "Miro", "ats": "ashby", "slug": "miro"},
    {"name": "Replit", "ats": "ashby", "slug": "replit"},
    {"name": "Supabase", "ats": "ashby", "slug": "supabase"},
    {"name": "Warp", "ats": "ashby", "slug": "warp"},
    {"name": "PostHog", "ats": "ashby", "slug": "posthog"},
    {"name": "Zapier", "ats": "ashby", "slug": "zapier"},
    {"name": "Plaid", "ats": "ashby", "slug": "plaid"},
    {"name": "Ramp", "ats": "ashby", "slug": "ramp"},
    {"name": "1Password", "ats": "ashby", "slug": "1password"},
    {"name": "Confluent", "ats": "ashby", "slug": "confluent"},
    {"name": "Benchling", "ats": "ashby", "slug": "benchling"},
    {"name": "Headway", "ats": "ashby", "slug": "headway"},
    {"name": "Patreon", "ats": "ashby", "slug": "patreon"},
    {"name": "Substack", "ats": "ashby", "slug": "substack"},
    {"name": "Quora", "ats": "ashby", "slug": "quora"},
    {"name": "Strava", "ats": "ashby", "slug": "strava"},
    {"name": "Spotify", "ats": "lever", "slug": "spotify"},
    {"name": "Ro", "ats": "lever", "slug": "ro"},
    {"name": "Wealthfront", "ats": "lever", "slug": "wealthfront"},
    # Workday (defense contractors and large aerospace)
    {"name": "Leidos", "ats": "workday", "url": "https://leidos.wd5.myworkdayjobs.com/External"},
    {"name": "Northrop Grumman", "ats": "workday", "url": "https://ngc.wd1.myworkdayjobs.com/Northrop_Grumman_External_Site"},
    {"name": "Boeing", "ats": "workday", "url": "https://boeing.wd1.myworkdayjobs.com/EXTERNAL_CAREERS"},
    {"name": "RTX", "ats": "workday", "url": "https://globalhr.wd5.myworkdayjobs.com/REC_RTX_Ext_Gateway"},
    {"name": "Booz Allen Hamilton", "ats": "workday", "url": "https://bah.wd1.myworkdayjobs.com/BAH_Jobs"},
    {"name": "KBR", "ats": "workday", "url": "https://kbr.wd5.myworkdayjobs.com/KBR_Careers"},
    {"name": "Blue Origin", "ats": "workday", "url": "https://blueorigin.wd5.myworkdayjobs.com/BlueOrigin"},
    {"name": "GDIT", "ats": "workday", "url": "https://gdit.wd5.myworkdayjobs.com/External_Career_Site"},
    {"name": "CACI", "ats": "workday", "url": "https://caci.wd1.myworkdayjobs.com/External"},
    {"name": "Parsons", "ats": "workday", "url": "https://parsons.wd5.myworkdayjobs.com/Search"},
    {"name": "Sierra Space", "ats": "workday", "url": "https://sierraspace.wd1.myworkdayjobs.com/Sierra_Space_External_Career_Site"},
    {"name": "Maxar / Vantor", "ats": "workday", "url": "https://maxar.wd1.myworkdayjobs.com/Vantor"},
    {"name": "Axiom Space", "ats": "workday", "url": "https://axiomspace.wd5.myworkdayjobs.com/External_Career_Site"},
    {"name": "AeroVironment", "ats": "workday", "url": "https://avav.wd1.myworkdayjobs.com/AVAV"},
    # UKG and iCIMS
    {"name": "Space Telescope Science Institute", "ats": "ukg", "url": "https://recruiting2.ultipro.com/SPA1004AURA/JobBoard/93330e50-7b3a-4ba8-94f2-6f32360aa4e1"},
    {"name": "Peraton", "ats": "icims", "url": "https://careers-peraton.icims.com"},
    {"name": "General Dynamics Mission Systems", "ats": "icims", "url": "https://careers-gdms.icims.com"},
]

TECH_TITLE = [
    r"software", r"engineer", r"develop", r"programm", r"\bdata\b", r"machine learning", r"\bml\b", r"\bai\b",
    r"artificial intelligence", r"computer", r"comput", r"cyber", r"security", r"\bit\b", r"information technology",
    r"system", r"network", r"cloud", r"devops", r"embedded", r"firmware", r"hardware", r"electrical", r"electronic",
    r"aerospace", r"space", r"satellite", r"flight", r"\bgnc\b", r"guidance", r"navigation", r"control",
    r"robot", r"autonom", r"research", r"scien", r"physic", r"math", r"analyst", r"analytics", r"quant",
    r"\btest", r"\bqa\b", r"quality", r"technician", r"\brf\b", r"signal", r"radar", r"avionic", r"mission",
    r"launch", r"propulsion", r"\bgis\b", r"remote sensing", r"geospatial", r"astro", r"\bweb\b", r"mobile",
    r"\bios\b", r"\bapp", r"front[- ]?end", r"back[- ]?end", r"full[- ]?stack", r"infrastructure", r"\bsre\b",
    r"platform", r"simulation", r"modeling", r"digital", r"technolog", r"\btech\b", r"stem\b", r"intelligence",
    r"automation", r"integration", r"product development", r"r&d", r"lab\b",
]

_INCLUDE, _EXCLUDE = title_filters(DEFAULT_LEVELS)

DEFAULT_SETTINGS = {
    "ai": {
        "stages": {
            "prefill": {"model": "haiku", "effort": "low"},
            "triage": {"model": "haiku", "effort": "low"},
            "hunt": {"model": "sonnet", "effort": "high"},
            "package": {"model": "opus", "effort": "high"},
            "revise": {"model": "sonnet", "effort": "medium"},
            "profile": {"model": "opus", "effort": "high"},
            "analysis": {"model": "opus", "effort": "medium"},
        },
        "max_parallel": 3,
        "budget_per_call_usd": 4.0,
        "pause_at_5h_utilization": 0.92,
        "strip_api_key": True,
        "claude_bin": "claude",
    },
    "run": {
        "max_triage": 600,
        "triage_batch": 20,
        "min_score": 60,
        "max_packages": 12,
        "package_web_research": True,
        "resume_review": True,
        "max_age_days": 90,
        "auto_run_hours": 0,
    },
    "locations": {
        "allowed": [],  # filled in from your standard answers (or Settings -> Search area)
        "dream_bypass": True,
        "dream_jobs_bypass": False,
        "unknown_policy": "ai",
    },
    "filters": {
        "title_include": _INCLUDE,
        "title_exclude": _EXCLUDE,
        "require_tech_title": True,
        "tech_title": TECH_TITLE,
        "exclude_companies": [],
        "exclude_keywords": [],
    },
    "search": {"queries": [], "use_profile_plan": True, "levels": list(DEFAULT_LEVELS)},
    "profile": {"auto_sync_answers": True, "sync_delay_sec": 60, "auto_analyze": True, "retriage_on_change": True},
    "analysis": {"genres": DEFAULT_GENRES},
    "industries": DEFAULT_INDUSTRIES,
    "dream_companies": [],
    "dream_jobs": [],
    "dream_exclude": [],
    "sources": {
        "github_lists": {"enabled": True, "urls": [
            "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json",
            "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json",
            "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
        ]},
        "ats_boards": {"enabled": True, "boards": ATS_BOARDS},
        "linkedin": {"enabled": True, "max_requests": 100, "time_window": "r2592000", "experience": ""},  # "" = from your levels
        "hackernews": {"enabled": True, "threads": 2},
        "themuse": {"enabled": True, "pages": 8},
        "usajobs": {"enabled": True, "api_key": "", "email": ""},
        "adzuna": {"enabled": False, "app_id": "", "app_key": ""},
        "serpapi": {"enabled": False, "api_key": ""},
        "remote_boards": {"enabled": True},
        "reddit": {"enabled": True, "subreddits": ["forhire", "jobbit", "hiring", "cscareerquestions", "internships",
                                                    "EngineeringStudents", "remotejs", "techjobs"]},
        "mastodon": {"enabled": True,
                     "instances": ["mastodon.social", "hachyderm.io", "fosstodon.org"],
                     "tags": ["hiring", "internship", "internships", "getfedihired", "fedihired", "techjobs", "jobs"]},
        "rss": {"enabled": True, "feeds": []},
        "bluesky": {"enabled": False, "handle": "", "app_password": ""},
        "ai_hunt": {"enabled": True, "depth": "standard", "missions_per_run": 7, "missions": []},  # filled from prompts.DEFAULT_MISSIONS on first load
    },
    "prompts": {},
}
