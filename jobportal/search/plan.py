"""What to search for. Combines your settings with the search plan your profile derived from the resume and the standard
answers: the experience levels, target roles, search queries and dream companies every collector and the search run use."""
from jobportal.candidate import profile
from jobportal.core.levels import clean as clean_levels


def _dedupe(items) -> list[str]:
    seen, out = set(), []
    for x in items:
        k = str(x).strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(str(x).strip())
    return out


def _plan() -> dict:
    return profile.get("search_plan") or {}


def levels(cfg: dict) -> list[str]:
    """The experience levels you are searching for (from the standard questions)."""
    return clean_levels((cfg.get("search") or {}).get("levels"))


def target_roles() -> list[str]:
    """The job titles you said you want, from the standard questions."""
    roles = (profile.standard_answers() or {}).get("target_roles") or []
    return [str(r).strip() for r in roles if str(r).strip()]


def all_queries(cfg: dict) -> list[str]:
    """Your extra queries + the queries your profile's search plan derived, falling back to your target roles."""
    plan = _plan().get("queries", []) if cfg["search"].get("use_profile_plan", True) else []
    return _dedupe(list(cfg["search"].get("queries", [])) + list(plan)) or target_roles()


def role_words(cfg: dict) -> list[str]:
    """Role phrases that describe what you are looking for: target roles plus the search plan's role families."""
    return _dedupe(target_roles() + list(_plan().get("role_families", [])))


def plan_dreams(cfg: dict) -> list[str]:
    """Dream companies your profile derived, minus the ones you removed on the Dream list page."""
    excluded = {x.strip().lower() for x in cfg.get("dream_exclude", [])}
    plan = _plan().get("dream_companies", []) if cfg["search"].get("use_profile_plan", True) else []
    return [x for x in plan if x.strip().lower() not in excluded]


def all_dreams(cfg: dict) -> list[str]:
    return _dedupe(list(cfg.get("dream_companies", [])) + plan_dreams(cfg))
