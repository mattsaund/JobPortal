"""What to search for. Combines the user's settings with the search plan the profile derived from the resume and the
standard answers: experience levels, target roles, search queries and dream companies.

Every collector reads its search words from here, and the rule filters (pipeline.RuleFilters) read the dream companies. The
web routes use plan_dreams and all_dreams for the Dream list page. Nothing here writes anything.

Two sources feed it: the settings (Settings, Search: cfg["search"], plus the Dream list) and the profile's search plan
(profile section "search_plan", built from the resume and answers). The setting search.use_profile_plan turns the plan's
queries and dream companies off."""
from jobportal.candidate import profile
from jobportal.core.levels import clean as clean_levels


def _dedupe(items) -> list[str]:
    """Strip each item and drop blanks and repeats, ignoring case. Keeps the first spelling and the original order."""
    seen, out = set(), []
    for x in items:
        k = str(x).strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(str(x).strip())
    return out


def _plan() -> dict:
    """The profile's search plan: role_families, queries, dream_companies and notes (empty before the first build)."""
    return profile.get("search_plan") or {}


def levels(cfg: dict) -> list[str]:
    """The experience levels being searched (from the standard questions, saved in settings), such as ["internship",
    "entry"]. Unknown values are dropped; nothing valid means the default levels."""
    return clean_levels((cfg.get("search") or {}).get("levels"))


def target_roles() -> list[str]:
    """The job titles the user said they want, from the standard questions."""
    roles = (profile.standard_answers() or {}).get("target_roles") or []
    return [str(r).strip() for r in roles if str(r).strip()]


def all_queries(cfg: dict) -> list[str]:
    """Search queries: the user's own (Settings, Search) plus the profile plan's, without repeats. Falls back to the target
    roles when there are none."""
    plan = _plan().get("queries", []) if cfg["search"].get("use_profile_plan", True) else []
    return _dedupe(list(cfg["search"].get("queries", [])) + list(plan)) or target_roles()


def role_words(cfg: dict) -> list[str]:
    """Role phrases that describe what the user wants: the target roles plus the profile plan's role families. Social
    collectors build their post filter from these. Unlike all_queries, this ignores search.use_profile_plan, so cfg is
    currently unused."""
    return _dedupe(target_roles() + list(_plan().get("role_families", [])))


def plan_dreams(cfg: dict) -> list[str]:
    """Dream companies the profile plan suggested, minus the ones the user removed on the Dream list page."""
    excluded = {x.strip().lower() for x in cfg.get("dream_exclude", [])}
    plan = _plan().get("dream_companies", []) if cfg["search"].get("use_profile_plan", True) else []
    return [x for x in plan if x.strip().lower() not in excluded]


def all_dreams(cfg: dict) -> list[str]:
    """Every dream company: the ones in settings (from the standard questions and the Dream list page), then the profile
    plan's, without repeats."""
    return _dedupe(list(cfg.get("dream_companies", [])) + plan_dreams(cfg))
