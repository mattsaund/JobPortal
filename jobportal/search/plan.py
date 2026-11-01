"""What to search for. Combines the user's settings with the search plan the profile derived from the resume and the
standard answers: experience levels, target roles, search queries, dream companies, and the fields all of these point at.

Every collector reads its search words from here, and the rule filters (pipeline.RuleFilters) read the dream companies and
the target phrases. The web routes use plan_dreams and all_dreams for the Dream list (in Settings, Search), and
insights/analysis.py reads target_roles and target_phrases for the job titles on the Analysis radar. Nothing here writes
anything.

Two sources feed it: the settings (cfg["search"]: the levels from Settings, Search and the extra queries from the Sources
dialog, plus the Dream list) and the profile's search plan (profile section "search_plan", built from the resume and
answers). The setting search.use_profile_plan turns the plan's
queries, role families and dream companies off.

Key idea for the fields: nothing assumes a field. field_weights() runs the genre classifier (core/genres.py) over the
user's own target roles, role families, queries and dream job titles, so a nurse's sources look for nursing jobs and a
developer's for tech jobs, and sources that only carry one field (the GitHub internship lists, Hacker News) can tell
whether they're any use to this person (in_tech)."""
from collections import Counter

from jobportal.candidate import profile
from jobportal.core.genres import DEFAULT_GENRES, classify, group_of
from jobportal.core.levels import clean as clean_levels
from jobportal.core.textutil import unique

# How much each kind of phrase says about the user's fields: their own target roles most, then the role families the
# profile build ranked, then dream job titles, then each search query (there are many of those).
_FIELD_WEIGHTS = {"roles": 3, "families": 2, "dream_jobs": 2, "queries": 1}
TECH_SHARE = 0.25  # in_tech() needs at least this share of the field weight on technology genres


def _dedupe(items) -> list[str]:
    """Strip each item and drop blanks and repeats, ignoring case. Keeps the first spelling and the original order."""
    return unique((text for text in (str(x).strip() for x in items) if text), key=str.lower)


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
    """Search queries: the user's own (the Sources dialog) plus the profile plan's, without repeats. Falls back to the
    target roles when there are none."""
    plan = _plan().get("queries", []) if cfg["search"].get("use_profile_plan", True) else []
    return _dedupe(list(cfg["search"].get("queries", [])) + list(plan)) or target_roles()


def role_families(cfg: dict) -> list[str]:
    """The kinds of roles the profile build ranked for the user, when search.use_profile_plan is on."""
    return list(_plan().get("role_families", [])) if cfg["search"].get("use_profile_plan", True) else []


def role_words(cfg: dict) -> list[str]:
    """Role phrases that describe what the user wants: the target roles, plus the profile plan's role families when
    search.use_profile_plan is on (as for all_queries and plan_dreams). Social collectors build their post filter from these."""
    return _dedupe(target_roles() + role_families(cfg))


def target_phrases(cfg: dict) -> list[str]:
    """Everything that says what the user is after: the target roles, the plan's role families and every search query,
    plus the dream job titles, without repeats. The rule filters' target-role check (textutil.TargetMatcher) reads these.
    An empty list means the user hasn't said yet, and the check lets every job through. Dream job titles only widen a list
    that has something else in it: on their own they would narrow the whole search down to a few titles."""
    phrases = _dedupe(role_words(cfg) + all_queries(cfg))
    return _dedupe(phrases + list(cfg.get("dream_jobs") or [])) if phrases else []


def plan_dreams(cfg: dict) -> list[str]:
    """Dream companies the profile plan suggested, minus the ones the user removed from the Dream list."""
    excluded = {x.strip().lower() for x in cfg.get("dream_exclude", [])}
    plan = _plan().get("dream_companies", []) if cfg["search"].get("use_profile_plan", True) else []
    return [x for x in plan if x.strip().lower() not in excluded]


def all_dreams(cfg: dict) -> list[str]:
    """Every dream company: the ones in settings (from the standard questions and the Dream list), then the profile
    plan's, without repeats."""
    return _dedupe(list(cfg.get("dream_companies", [])) + plan_dreams(cfg))


# ---------------------------------------------------------------- the user's fields


def _genres(cfg: dict) -> list[dict]:
    """The genre list in use (settings analysis.genres, or the built-in one)."""
    return (cfg.get("analysis") or {}).get("genres") or DEFAULT_GENRES


def field_weights(cfg: dict) -> Counter:
    """How strongly the user's targets point at each work genre: {genre id: weight}. Each target role adds 3 to the genres
    it classifies into, each role family 2, each dream job title 2 and each search query 1 (_FIELD_WEIGHTS). Empty when
    the user has no targets yet, or none of them names a known kind of work."""
    weights: Counter = Counter()
    genres = _genres(cfg)
    kinds = {"roles": target_roles(), "families": role_families(cfg), "dream_jobs": list(cfg.get("dream_jobs") or []),
             "queries": all_queries(cfg) if cfg["search"].get("queries") or _plan().get("queries") else []}
    for kind, phrases in kinds.items():
        for phrase in _dedupe(phrases):
            for genre in classify(phrase, "", genres, top=2):
                weights[genre] += _FIELD_WEIGHTS[kind]
    return weights


def fields(cfg: dict, top: int = 6) -> list[str]:
    """The ids of the genres the user's targets point at most, strongest first, at most `top` of them. Genres with less
    than a tenth of the strongest one's weight are left out, so one stray query doesn't count as a field."""
    weights = field_weights(cfg)
    if not weights:
        return []
    strongest = max(weights.values())
    return [g for g, w in weights.most_common() if w * 10 >= strongest][:top]


def groups(cfg: dict) -> list[str]:
    """The field groups (core/genres.GROUPS, such as "healthcare" or "trades") of the user's fields, strongest first."""
    by_id = {g["id"]: g for g in _genres(cfg)}
    weights: Counter = Counter()
    for genre, weight in field_weights(cfg).items():
        if genre in by_id:
            weights[group_of(by_id[genre])] += weight
    return [group for group, _ in weights.most_common()]


def in_tech(cfg: dict) -> bool:
    """True when technology is one of the user's fields: at least TECH_SHARE of the weight their targets put on known kinds
    of work falls on technology genres. False when they have no targets, since tech is never assumed."""
    by_id = {g["id"]: g for g in _genres(cfg)}
    weights = field_weights(cfg)
    total = sum(weights.values())
    tech = sum(w for genre, w in weights.items() if genre in by_id and group_of(by_id[genre]) == "tech")
    return bool(total) and tech / total >= TECH_SHARE
