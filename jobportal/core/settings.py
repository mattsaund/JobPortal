"""The user's settings: read them, save them, reset a section, and add new built-in defaults after an update.

All settings are one JSON document in the database's kv table, under the key "settings". config.DEFAULT_SETTINGS holds
every setting with its default value, and get() lays what is stored on top of it.

Key ideas:
- Dictionaries merge key by key, so a setting added in a new version appears with its default value, even for people who
  saved their settings long ago.
- A stored list replaces the default list as a whole. That keeps deletions: a company board the user removed stays
  removed. The catch is that boards and AI missions added in later versions would never reach anyone who saved their
  settings, so migrate_defaults() adds those once, at startup. It also retires the tech-only defaults versions before
  v0.3.0 saved (the genre and industry lists, the tech-title filter, the tech subreddits and Mastodon instances), but
  only where the stored value is still exactly the old default, so nothing the user chose is lost.
- The dashboard always saves the whole document (it loads GET /api/settings, edits it, and sends it back with PUT), so
  save() replaces what is stored instead of merging.

Who calls it: almost every package reads settings with get(). web/routes/settings.py saves and resets them for the
Settings and Sources pages, and web/server.py runs migrate_defaults() at startup."""
import copy
import hashlib

from jobportal.core import db
from jobportal.core.config import DEFAULT_SETTINGS, RESOURCES
from jobportal.core.genres import LEGACY_GENRE_IDS, LEGACY_INDUSTRIES, OLD_INDUSTRIES

# Social-source defaults every version before v0.3.0 saved. _retire_tech_defaults() drops a stored list that still equals
# one of these, so the job-agnostic defaults in config.py show through.
_LEGACY_SUBREDDITS = ["forhire", "jobbit", "hiring", "cscareerquestions", "internships", "EngineeringStudents", "remotejs", "techjobs"]
_LEGACY_MASTODON = {"instances": ["mastodon.social", "hachyderm.io", "fosstodon.org"],
                    "tags": ["hiring", "internship", "internships", "getfedihired", "fedihired", "techjobs", "jobs"]}
# The start of the sha1 of each built-in AI hunt mission prompt before v0.3.0, when several leaned on tech (tech staffing
# firms, SBIR grants, Hacker News, tech job boards). A saved mission whose prompt still hashes to its old value was never
# edited, so _retire_tech_defaults() gives it the current wording.
_LEGACY_MISSION_PROMPTS = {
    "broad": "e9e89b9cb095540b", "social": "e15ad55b981676b0", "recruiters": "fde7ee780348b321", "public": "593d760f8067df11",
    "local": "cd8ec20ffe1f5304", "research": "5ccc96b937c0a770", "intel": "8372cf89cd1d3851", "events": "5d9c4e773da80920",
    "insiders": "8a6a971b438e8dfb", "forums": "22ef343ad9c37101", "aggregators": "187beb84ec3f4f0c", "campus": "ceeb2353fe188f01",
    "news": "ee6face50ab21600", "dream": "5952781c44068bb4",
}


def _merge(base, over):
    """`over` laid on top of `base`. Dictionaries merge key by key, all the way down. Anything else in `over` (a list, a
    number, a string) replaces what `base` has. Neither argument is changed, but the result can share nested values with
    them, which is why get() passes in fresh copies."""
    if isinstance(base, dict) and isinstance(over, dict):
        merged = dict(base)
        for key, value in over.items():
            merged[key] = _merge(base[key], value) if key in base else value
        return merged
    return copy.deepcopy(over)


def get() -> dict:
    """The current settings: what the user saved, merged over config.DEFAULT_SETTINGS.

    Returns a new dict on every call, so callers may change it (for example to save it back). An empty AI hunt mission
    list is filled with the built-in missions, so the Sources page always has missions to show."""
    # Imported here, not at the top of the file: ai/prompts.py imports this module, so a top-level import would be a loop.
    from jobportal.ai.prompts import DEFAULT_MISSIONS
    merged = _merge(copy.deepcopy(DEFAULT_SETTINGS), db.kv_get("settings", {}))
    hunt = merged["sources"]["ai_hunt"]
    if not hunt.get("missions"):
        hunt["missions"] = copy.deepcopy(DEFAULT_MISSIONS)
    return merged


def save(new: dict) -> dict:
    """Store `new` as the whole settings document, replacing what was there, and return get(). Writes the kv table."""
    db.kv_set("settings", new)
    return get()


def reset_section(path: str) -> dict:
    """Put one part of the settings back to its default and return get().

    `path` is a dotted key, for example "sources.ai_hunt.missions" (the Sources page's "Reset to defaults" button). The
    key is deleted from the stored settings, so the default shows through again. A path that isn't stored changes nothing."""
    stored = db.kv_get("settings", {})
    *parents, last = path.split(".")
    node = stored
    for key in parents:
        node = node.get(key, {})
    node.pop(last, None)
    db.kv_set("settings", stored)
    return get()


def default_playbook() -> str:
    """The built-in resume playbook (resources/resume_playbook.md): researched resume practices the AI follows when it
    writes or reviews a resume."""
    return (RESOURCES / "resume_playbook.md").read_text(encoding="utf-8")


def resume_playbook(cfg: dict | None = None) -> str:
    """The resume playbook in use: the user's own text from Settings, "Resumes" when they saved one, otherwise the
    built-in playbook. Pass the settings as `cfg` when you already have them, to skip reading them again."""
    cfg = cfg or get()
    return (cfg.get("resume_playbook") or "").strip() or default_playbook()


def migrate_defaults() -> list[str]:
    """Add the built-in company boards and AI hunt missions this user hasn't been offered yet, and retire the tech-only
    defaults of versions before v0.3.0 (_retire_tech_defaults). web/server.py calls it at every startup.

    Each default is offered only once. Its key ("board:<slug or url>" or "mission:<id>") goes into the stored
    "_defaults_seen" list, so a board or mission the user deletes is never added back. Returns a short note for each
    change, such as "mission Apprenticeships and trainee programs". Side effect: rewrites the stored settings. Does nothing
    until the user has saved settings at least once, because until then the defaults apply anyway."""
    from jobportal.ai.prompts import DEFAULT_MISSIONS  # inside the function for the same reason as in get()
    stored = db.kv_get("settings", {})
    if not stored:
        return []
    seen = set(stored.get("_defaults_seen", []))
    added = _retire_tech_defaults(stored)
    boards = stored.get("sources", {}).get("ats_boards", {}).get("boards")
    if boards is not None:
        have = {_board_id(b) for b in boards}
        for board in DEFAULT_SETTINGS["sources"]["ats_boards"]["boards"]:
            key = "board:" + _board_id(board)
            if _board_id(board) not in have and key not in seen:
                boards.append(dict(board))
                added.append(f"board {board['name']}")
            seen.add(key)
    missions = stored.get("sources", {}).get("ai_hunt", {}).get("missions")
    if missions:  # an empty list needs nothing: get() fills it with every built-in mission
        have = {m.get("id") for m in missions}
        for mission in DEFAULT_MISSIONS:
            key = "mission:" + mission["id"]
            if mission["id"] not in have and key not in seen:
                missions.append(dict(mission))
                added.append(f"mission {mission['name']}")
            seen.add(key)
    stored["_defaults_seen"] = sorted(seen)
    db.kv_set("settings", stored)
    return added


def _board_id(board: dict) -> str | None:
    """What identifies a company board: its slug (Greenhouse, Lever, Ashby) or its URL (Workday, UKG, iCIMS)."""
    return board.get("slug") or board.get("url")


def _retire_tech_defaults(stored: dict) -> list[str]:
    """Move settings saved by a version before v0.3.0 off its tech-only defaults, in place, and return a note per change.

    Before v0.3.0 the dashboard saved the whole settings document, defaults included, so these were stored for everyone:
    - analysis.genres: no page edits it, so a list of only the old genre ids is dropped and the genres for every field
      (core/genres.py) show through. The old ids are part of the new list, so the Analysis history keeps lining up.
    - industries: the old default list is dropped the same way. A list the user edited keeps their choices, with the old
      names renamed (genres.OLD_INDUSTRIES), the way db._migrate() renames them on saved leads.
    - filters.require_tech_title and filters.tech_title: the tech-title filter is gone. Someone who had switched it off
      gets the target-role filter that replaced it switched off too.
    - sources.reddit.subreddits and the Mastodon instances and tags: dropped when they still equal the old tech-leaning
      defaults, so the general defaults show through (the collectors add the user's fields on top).
    - the AI hunt missions: a built-in mission whose prompt was never edited (_LEGACY_MISSION_PROMPTS) gets the current
      prompt and level and field limits. Its name and on or off switch stay as the user left them.
    Running it again changes nothing, because nothing it leaves behind matches an old default."""
    from jobportal.ai.prompts import DEFAULT_MISSIONS  # inside the function for the same reason as in get()
    notes = []
    current = {m["id"]: m for m in DEFAULT_MISSIONS}
    updated = 0
    for mission in (stored.get("sources") or {}).get("ai_hunt", {}).get("missions") or []:
        old_hash = _LEGACY_MISSION_PROMPTS.get(mission.get("id"))
        new = current.get(mission.get("id"))
        prompt = str(mission.get("prompt", ""))
        if new and old_hash and prompt != new["prompt"] and hashlib.sha1(prompt.encode()).hexdigest()[:16] == old_hash:
            mission["prompt"] = new["prompt"]
            for limit in ("only_levels", "only_groups"):
                if limit in new:
                    mission[limit] = list(new[limit])
            updated += 1
    if updated:
        notes.append(f"{updated} built-in AI missions reworded for every field")
    analysis = stored.get("analysis") or {}
    genres = analysis.get("genres")
    if isinstance(genres, list) and genres and {g.get("id") for g in genres} <= LEGACY_GENRE_IDS:
        analysis.pop("genres")
        notes.append("genres for every field")
    industries = stored.get("industries")
    if industries == LEGACY_INDUSTRIES:
        stored.pop("industries")
        notes.append("industries for every field")
    elif isinstance(industries, list) and any(name in OLD_INDUSTRIES for name in industries):
        renamed = [OLD_INDUSTRIES.get(name, name) for name in industries]
        stored["industries"] = [name for i, name in enumerate(renamed) if name not in renamed[:i]]
        notes.append("industry names updated")
    filters = stored.get("filters") or {}
    filters.pop("tech_title", None)
    if "require_tech_title" in filters:
        if filters.pop("require_tech_title") is False:
            filters["require_target_match"] = False
        notes.append("tech-title filter replaced by the target-role filter")
    sources = stored.get("sources") or {}
    reddit = sources.get("reddit") or {}
    if reddit.get("subreddits") == _LEGACY_SUBREDDITS:
        reddit.pop("subreddits")
        notes.append("general subreddits")
    mastodon = sources.get("mastodon") or {}
    for key, old in _LEGACY_MASTODON.items():
        if mastodon.get(key) == old:
            mastodon.pop(key)
            notes.append(f"general Mastodon {key}")
    return notes
