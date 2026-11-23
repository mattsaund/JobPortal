"""The registry of job sources a search run collects from.

Each entry maps a settings key (the Sources dialog on Leads: cfg["sources"][key]) to a label for the dashboard and an
async function `collect(ctx) -> list[RawJob]` (see base.py). The search run (pipeline.py) runs every enabled source at
the same time, and the Sources dialog can test any one of them by itself (sources.py).

To add a job site or public job service, add one entry to the table in catalog.py: it needs no settings and reaches
existing users by itself. For a new kind of source, write its function in the module for its family, list it here, and
give it default settings in core/config.py.

The AI hunt (hunt.py) is not listed here. It hands over its leads mission by mission as they finish, so the run starts it
separately."""
from jobportal.search.collectors import ats, catalog, feeds, github_lists, linkedin

COLLECTORS = {
    "github_lists": ("GitHub tech internship & new-grad lists (tech targets only)", github_lists.collect),
    "ats_boards": ("Company job boards", ats.collect),
    "catalog": ("Job sites", catalog.collect),
    "linkedin": ("LinkedIn public job search", linkedin.collect),
    "usajobs": ("USAJobs (U.S. federal jobs)", feeds.usajobs),
    "hackernews": ("Hacker News hiring threads (tech targets only)", feeds.hackernews),
    "reddit": ("Reddit search feeds", feeds.reddit),
    "mastodon": ("Mastodon hiring hashtags", feeds.mastodon),
    "bluesky": ("Bluesky search (app password)", feeds.bluesky),
    "x": ("X recent search (your own paid developer key)", feeds.x_search),
    "remote_boards": ("Remote boards (Remotive, RemoteOK, We Work Remotely, Himalayas, Jobicy, Working Nomads)", feeds.remote_boards),
    "rss": ("Custom RSS / Atom feeds", feeds.rss),
    "adzuna": ("Adzuna aggregator (API key)", feeds.adzuna),
    "serpapi": ("Google Jobs via SerpAPI (API key)", feeds.serpapi),
}
