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

# Where the user is with each application. "new" is every lead's starting status: found, ranked and on the Leads page, but
# not on the Tracker yet. The five in TRACKER_STATUSES are the Tracker's columns, left to right. "trashed" is a lead the
# user deleted: it leaves every list, and a later search never adds the same job again.
APP_STATUSES = ["new", "ready", "applied", "interviewing", "accepted", "rejected", "trashed"]
TRACKER_STATUSES = ["ready", "applied", "interviewing", "accepted", "rejected"]
# The statuses that mean the user has applied. Reaching one records the application date (applied_at), even when a card
# is dragged straight from Ready to apply to In interview, so the Tracker's and Analysis's numbers still add up.
APPLIED_STATUSES = ("applied", "interviewing", "accepted")
STATUS_LABELS = {"new": "New", "ready": "Ready to apply", "applied": "Application sent", "interviewing": "In interview",
                 "accepted": "Accepted", "rejected": "Rejected", "trashed": "Deleted"}
# Statuses from v0.2.0 and earlier, and the status each one became. db._migrate() moves old leads over.
OLD_STATUSES = {"saved": "ready", "assessment": "interviewing", "offer": "accepted", "ghosted": "rejected", "withdrawn": "rejected"}

# Company job boards searched by default: none. Which companies are worth reading depends entirely on the person (a nurse
# in Ohio and a designer in Denver share no employers), so the user adds their own: the Sources page turns any pasted
# careers URL into a board (POST /api/sources/detect, search/sources.py), and the AI hunt's "Dream companies" mission
# checks the careers sites of the user's dream companies either way. Each entry has a name and an "ats", the hiring
# system the board runs on. Greenhouse, Lever and Ashby boards are found by "slug" (the company's id in that system's
# public API). Workday, UKG and iCIMS boards are found by "url". The Sources page adds "enabled" and "dream" switches to
# an entry. core/settings.migrate_defaults() offers any board added here later to existing users once.
ATS_BOARDS: list[dict] = []

# The title filters for the default levels (every level, so nothing is assumed), used until the user saves the standard
# answers.
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
            "documents": {"model": "", "effort": "low"},  # reads each extra document's details: title, issuer, dates
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
        # Job-board titles must share a word with the user's target roles, role families or search queries
        # (textutil.TargetMatcher). It's lenient, and it lets everything through until the user has targets.
        "require_target_match": True,
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
    "analysis": {
        # Work-type genres: triage tags every lead with them, and the search mixes kinds of work by them. No page edits
        # them (genres.py). The Analysis radar's axes are job titles instead (insights/analysis.py).
        "genres": DEFAULT_GENRES,
        # The Analysis page's role controls: job titles the user removed from the radar (they stay off it, whatever
        # suggests them again) and job titles they added themselves (they always show).
        "hidden_roles": [],
        "pinned_roles": [],
    },
    "industries": DEFAULT_INDUSTRIES,  # Settings page, "Industries": the list every lead is tagged from (genres.py)
    # The Dream list page. Leads that match get the dream flag, which never changes their score.
    "dream_companies": [],  # companies the user added (saving the standard answers sets it to their dream companies)
    "dream_jobs": [],  # title phrases that make a job a dream job at any company
    "dream_exclude": [],  # profile-suggested dream companies the user removed
    # The Sources page: every job source, each with an "enabled" switch. search/collectors/ reads these. Sources that only
    # carry one field's jobs adapt to the user (search/plan.py works out their fields from their targets): the GitHub lists
    # and Hacker News carry tech jobs, so they skip themselves for everyone else, and Reddit, Mastodon, The Muse and the
    # remote boards add communities, hashtags, categories and feeds for the user's fields on top of the general ones here.
    "sources": {
        # Community tech internship and new-grad lists. Used only when the user's targets are in tech and their levels
        # include internship or entry level.
        "github_lists": {"enabled": True, "urls": [
            "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json",
            "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json",
            "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
        ]},
        "ats_boards": {"enabled": True, "boards": ATS_BOARDS},  # company job boards (see ATS_BOARDS above)
        # time_window is LinkedIn's "posted within" filter in seconds ("r2592000" = 30 days). experience is LinkedIn's
        # experience filter ("1,2" = internship and entry level); "" picks it from the levels (levels.linkedin_experience).
        "linkedin": {"enabled": True, "max_requests": 100, "time_window": "r2592000", "experience": ""},
        # How many monthly "Who is hiring?" threads to read. Used only when the user's targets are in tech.
        "hackernews": {"enabled": True, "threads": 2},
        "themuse": {"enabled": True, "pages": 8},  # result pages per run
        "usajobs": {"enabled": True, "api_key": "", "email": ""},  # free key from developer.usajobs.gov
        "adzuna": {"enabled": False, "app_id": "", "app_key": ""},  # needs a free key, so off by default
        "serpapi": {"enabled": False, "api_key": ""},  # Google Jobs through SerpAPI, needs a key
        # Remotive, RemoteOK and We Work Remotely, used only when "Remote" is an allowed location.
        "remote_boards": {"enabled": True},
        # General hiring subreddits (each one checked to carry job posts). The collector adds the ones for the user's fields.
        "reddit": {"enabled": True, "subreddits": ["forhire", "jobbit", "hiring"]},
        # General instances and hiring hashtags. The collector adds instances and hashtags for the user's fields and levels.
        "mastodon": {"enabled": True,
                     "instances": ["mastodon.social", "mastodon.online", "mas.to"],
                     "tags": ["hiring", "jobs", "getfedihired", "fedihired", "nowhiring"]},
        "rss": {"enabled": True, "feeds": []},  # any RSS or Atom feeds: [{"name": ..., "url": ...}]
        "bluesky": {"enabled": False, "handle": "", "app_password": ""},  # needs the user's handle and an app password
        # AI hunt missions. depth is "quick", "standard" or "deep"; missions_per_run is how many missions an "Everything"
        # run rotates through (0 = all). An empty missions list is filled from ai/prompts.DEFAULT_MISSIONS by settings.get().
        "ai_hunt": {"enabled": True, "depth": "standard", "missions_per_run": 7, "missions": []},
    },
    "prompts": {},  # Settings page, "Prompts (advanced)": system prompt overrides by name ("triage", "package", ...)
    "resume_playbook": "",  # Settings page, "Resumes": the user's own playbook; "" uses resources/resume_playbook.md
}
