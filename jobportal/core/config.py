"""Where JobPortal keeps things, how the server is reached, and the default value of every setting.

The rest of the app imports these values: db.py opens DB_PATH, the web server serves STATIC on HOST:PORT, and settings.py
merges the user's saved settings over DEFAULT_SETTINGS. This module only defines values. It never writes anything.

Your data never lives in the code folder. It goes in the platform's app-data folder:
  Windows  %LOCALAPPDATA%\\JobPortal
  macOS    ~/Library/Application Support/JobPortal
  Linux    ~/.local/share/JobPortal
Two environment variables change that, and both are read once, when this module is first imported:
  JOBPORTAL_HOME  use this folder for all data instead (tests use it to start from an empty folder)
  JOBPORTAL_PORT  serve on this port instead of 8788

Key ideas for DEFAULT_SETTINGS:
- The dashboard reads and writes settings by key name (web/static/js), so renaming or removing a key breaks a page.
- Stored settings are merged over these defaults (see settings.py). A key added here shows up for existing users with its
  default value. A stored list replaces the default list as a whole."""
import os
from pathlib import Path

from platformdirs import user_cache_dir, user_data_dir

from jobportal.core.genres import DEFAULT_GENRES, DEFAULT_INDUSTRIES
from jobportal.core.levels import DEFAULT_LEVELS, title_filters

APP_NAME = "JobPortal"
PKG = Path(__file__).resolve().parent.parent  # the jobportal package folder
STATIC = PKG / "web" / "static"  # the dashboard: HTML, CSS, JavaScript, fonts and the icon
RESOURCES = PKG / "resources"  # files the code reads at run time (resume playbook, Linux desktop entry)

_home_env = os.environ.get("JOBPORTAL_HOME")
DATA = Path(_home_env).expanduser().resolve() if _home_env else Path(user_data_dir(APP_NAME, appauthor=False))
# With JOBPORTAL_HOME set (tests, a second profile) the cache lives inside it too, so instances never share anything.
CACHE = DATA / "cache" if _home_env else Path(user_cache_dir(APP_NAME, appauthor=False))
DB_PATH = DATA / "jobportal.db"  # the SQLite database (see db.py)
LEADS_DIR = DATA / "leads"  # one folder per lead, named by its id: rendered resumes, cover letters and exports
RESUME_DIR = DATA / "resume"  # the resume file the user imported during setup
HOST = "127.0.0.1"  # the server only listens on this computer, never on the network
PORT = int(os.environ.get("JOBPORTAL_PORT") or 8788)

# Reasoning effort choices for each AI stage (Settings, "AI: ChatGPT"). Models come from the signed-in ChatGPT account.
EFFORTS = ["low", "medium", "high"]

# Where the user is with each application (the status menu on a lead's page). "new" is every lead's starting status, and
# "trashed" moves a lead to the Leads page's Trash tab, out of every other list.
APP_STATUSES = ["new", "saved", "applied", "assessment", "interviewing", "offer",
                "rejected", "ghosted", "withdrawn", "trashed"]

# Company job boards searched by default (verified live in October 2026). Each entry has a name and an "ats", the hiring
# system the board runs on. Greenhouse, Lever and Ashby boards are found by "slug" (the company's id in that system's
# public API). Workday, UKG and iCIMS boards are found by "url". The Sources page adds "enabled" and "dream" switches to
# an entry, and adds any company from a pasted careers URL.
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

# The tech-role gate (filters.require_tech_title): a job-board title must contain one of these to pass. They are
# case-insensitive regexes. Most are word stems ("comput" matches computer and computing). \b marks a word edge, so
# r"\bit\b" matches "IT Specialist" but not "Digital".
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

# The title filters for the default levels (internship and entry level), used until the user saves the standard answers.
_TITLE_INCLUDE, _TITLE_EXCLUDE = title_filters(DEFAULT_LEVELS)

# Every setting and its default. settings.get() returns these merged with what the user saved. Comments name the page
# where each setting is edited. Settings with no page keep their default unless code changes them.
DEFAULT_SETTINGS = {
    # Settings page, "AI: ChatGPT". Every AI request names a stage, and the stage picks the model and reasoning effort.
    "ai": {
        "model": "",  # the default model; "" means the first model the signed-in ChatGPT account lists
        "stages": {  # per stage: "model" ("" uses the default above) and "effort" (one of EFFORTS)
            "prefill": {"model": "", "effort": "low"},  # setup: reads the resume to pre-fill the standard questions
            "triage": {"model": "", "effort": "low"},  # scores every job that passes the rule filters, in batches
            "hunt": {"model": "", "effort": "medium"},  # AI hunt missions: agents that search the web
            "package": {"model": "", "effort": "high"},  # builds application packages (research, resume, cover letter)
            "revise": {"model": "", "effort": "low"},  # "Revise with AI", resume reviews and other document edits
            "profile": {"model": "", "effort": "medium"},  # builds and updates the profile, learns the writing voice
            "analysis": {"model": "", "effort": "medium"},  # the Analysis page's assessment
        },
        "max_parallel": 3,  # "Parallel agents": how many AI requests may run at the same time
    },
    # Settings page, "Runs" (and "Resumes" for resume_review). How much one search run does.
    "run": {
        "max_triage": 600,  # most jobs the AI scores per run; the rest wait in a backlog for the next run
        "triage_batch": 20,  # jobs per AI triage request
        "min_score": 60,  # the fit score (0 to 100) a job needs to qualify for an application package
        "max_packages": 12,  # most application packages built per run
        "package_web_research": True,  # packages research the web live: check the posting, company news, contacts
        "resume_review": True,  # a recruiter-style AI review pass on every tailored resume
        "max_age_days": 90,  # postings older than this are dropped
        "auto_run_hours": 0,  # start a full run every N hours (0 = off); web/server.py checks once a minute
    },
    # The search area: where jobs may be. Filled in from the standard answers, then edited in the search area editor (the
    # Leads page header, or Settings, "Search area"). search/pipeline.py checks every job with textutil.LocationMatcher.
    "locations": {
        "allowed": [],  # plain text: states ("Ohio" or "OH"), cities ("Pittsburgh, PA"), "Remote", "Anywhere in the US"
        "dream_bypass": True,  # dream companies skip the search area (search area editor and Dream list page)
        "dream_jobs_bypass": False,  # dream job titles skip it too (Dream list page)
        "unknown_policy": "ai",  # a job whose location can't be told: "ai" lets AI triage decide, "drop" removes it
    },
    # Settings page, "Filters": the rule filters every job passes before any AI sees it (search/pipeline.py).
    "filters": {
        # Regexes for job-board titles. A title must match one include pattern ([] = any title) and no exclude pattern.
        # Saving the standard answers rebuilds both from the levels and target roles (levels.title_filters).
        "title_include": _TITLE_INCLUDE,
        "title_exclude": _TITLE_EXCLUDE,
        "require_tech_title": True,  # job-board titles must contain a tech or science word from tech_title
        "tech_title": TECH_TITLE,  # no page edits this list
        "exclude_companies": [],  # "Never show these companies"
        "exclude_keywords": [],  # "Drop if description contains" (saving the standard answers adds clearance phrases)
    },
    "search": {
        "queries": [],  # Sources page, "Your extra queries": search terms for LinkedIn, The Muse and the aggregators
        "use_profile_plan": True,  # Sources page: also search the queries and dream companies the profile derived
        "levels": list(DEFAULT_LEVELS),  # experience levels to search, from the standard answers (levels.py)
    },
    # How the profile keeps itself current (candidate/profile.py). No page edits these.
    "profile": {
        "auto_sync_answers": True,  # add answers to questions asked along the way to the profile automatically...
        "sync_delay_sec": 60,  # ...once the newest answer is this many seconds old
        "auto_analyze": True,  # re-run the Analysis after every profile update
        "retriage_on_change": True,  # re-score queued and filtered leads after the profile changes
    },
    # Work-type genres: the spokes of the Analysis radar, also tagged on every lead. No page edits them (genres.py).
    "analysis": {"genres": DEFAULT_GENRES},
    "industries": DEFAULT_INDUSTRIES,  # Settings page, "Industries": the list every lead is tagged from (genres.py)
    # The Dream list page. Leads that match get the dream flag, which never changes their score.
    "dream_companies": [],  # companies the user added (saving the standard answers sets it to their dream companies)
    "dream_jobs": [],  # title phrases that make a job a dream job at any company
    "dream_exclude": [],  # profile-suggested dream companies the user removed
    # The Sources page: every job source, each with an "enabled" switch. search/collectors/ reads these.
    "sources": {
        "github_lists": {"enabled": True, "urls": [  # community internship and new-grad lists (skipped above entry level)
            "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json",
            "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json",
            "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
        ]},
        "ats_boards": {"enabled": True, "boards": ATS_BOARDS},  # company job boards (see ATS_BOARDS above)
        # time_window is LinkedIn's "posted within" filter in seconds ("r2592000" = 30 days). experience is LinkedIn's
        # experience filter ("1,2" = internship and entry level); "" picks it from the levels (levels.linkedin_experience).
        "linkedin": {"enabled": True, "max_requests": 100, "time_window": "r2592000", "experience": ""},
        "hackernews": {"enabled": True, "threads": 2},  # how many monthly "Who is hiring?" threads to read
        "themuse": {"enabled": True, "pages": 8},  # result pages per run
        "usajobs": {"enabled": True, "api_key": "", "email": ""},  # free key from developer.usajobs.gov
        "adzuna": {"enabled": False, "app_id": "", "app_key": ""},  # needs a free key, so off by default
        "serpapi": {"enabled": False, "api_key": ""},  # Google Jobs through SerpAPI, needs a key
        "remote_boards": {"enabled": True},  # Remotive and RemoteOK, used only when "Remote" is an allowed location
        "reddit": {"enabled": True, "subreddits": ["forhire", "jobbit", "hiring", "cscareerquestions", "internships",
                                                    "EngineeringStudents", "remotejs", "techjobs"]},
        "mastodon": {"enabled": True,
                     "instances": ["mastodon.social", "hachyderm.io", "fosstodon.org"],
                     "tags": ["hiring", "internship", "internships", "getfedihired", "fedihired", "techjobs", "jobs"]},
        "rss": {"enabled": True, "feeds": []},  # any RSS or Atom feeds: [{"name": ..., "url": ...}]
        "bluesky": {"enabled": False, "handle": "", "app_password": ""},  # needs the user's handle and an app password
        # AI hunt missions. depth is "quick", "standard" or "deep"; missions_per_run is how many missions an "Everything"
        # run rotates through (0 = all). An empty missions list is filled from ai/prompts.DEFAULT_MISSIONS by settings.get().
        "ai_hunt": {"enabled": True, "depth": "standard", "missions_per_run": 7, "missions": []},
    },
    "prompts": {},  # Settings page, "Prompts (advanced)": system prompt overrides by name ("triage", "package", ...)
    "resume_playbook": "",  # Settings page, "Resumes": the user's own playbook; "" uses resources/resume_playbook.md
}
