"""Collector registry. Each deterministic collector is `async fn(ctx) -> list[RawJob]`."""
from . import ats, feeds, github_lists, linkedin

COLLECTORS = {
    "github_lists": ("GitHub internship & new-grad lists", github_lists.collect),
    "ats_boards": ("Company job boards (Greenhouse / Lever / Ashby / Workday / UKG / iCIMS)", ats.collect),
    "linkedin": ("LinkedIn public job search", linkedin.collect),
    "usajobs": ("USAJobs (federal, Pathways)", feeds.usajobs),
    "hackernews": ("Hacker News (hiring threads + all recent comments)", feeds.hackernews),
    "themuse": ("The Muse", feeds.themuse),
    "reddit": ("Reddit search feeds", feeds.reddit),
    "mastodon": ("Mastodon hiring hashtags", feeds.mastodon),
    "bluesky": ("Bluesky search (app password)", feeds.bluesky),
    "remote_boards": ("Remote boards (Remotive, RemoteOK)", feeds.remote_boards),
    "rss": ("Custom RSS / Atom feeds", feeds.rss),
    "adzuna": ("Adzuna aggregator (API key)", feeds.adzuna),
    "serpapi": ("Google Jobs via SerpAPI (API key)", feeds.serpapi),
}
