"""Settings live in the kv table and are deep-merged over config.DEFAULT_SETTINGS."""
import copy

from jobportal.core import db
from jobportal.core.config import DEFAULT_SETTINGS


def _merge(base, over):
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = _merge(base.get(k), v) if k in base else v
        return out
    return copy.deepcopy(over)


def get() -> dict:
    from jobportal.ai.prompts import DEFAULT_MISSIONS
    s = _merge(copy.deepcopy(DEFAULT_SETTINGS), db.kv_get("settings", {}))
    if not s["sources"]["ai_hunt"].get("missions"):
        s["sources"]["ai_hunt"]["missions"] = copy.deepcopy(DEFAULT_MISSIONS)
    return s


def save(new: dict) -> dict:
    db.kv_set("settings", new)
    return get()


def reset_section(path: str) -> dict:
    """Reset a dotted section (e.g. 'sources.ats_boards') back to its default."""
    stored = db.kv_get("settings", {})
    node = stored
    parts = path.split(".")
    for p in parts[:-1]:
        node = node.get(p, {})
    node.pop(parts[-1], None)
    db.kv_set("settings", stored)
    return get()


def default_playbook() -> str:
    from jobportal.core.config import RESOURCES
    return (RESOURCES / "resume_playbook.md").read_text(encoding="utf-8")


def resume_playbook(cfg: dict | None = None) -> str:
    """The researched resume playbook (Settings -> Resume playbook overrides the built-in one)."""
    cfg = cfg or get()
    return (cfg.get("resume_playbook") or "").strip() or default_playbook()


def migrate_defaults() -> list[str]:
    """Merge NEW built-in company boards and AI missions into stored settings (stored lists replace defaults wholesale,
    which would otherwise freeze them). Remembers what it has offered so anything you delete stays deleted."""
    from jobportal.ai.prompts import DEFAULT_MISSIONS
    from jobportal.core.config import DEFAULT_SETTINGS
    stored = db.kv_get("settings", {})
    if not stored:
        return []
    seen = set(stored.get("_defaults_seen", []))
    notes = []
    boards = stored.get("sources", {}).get("ats_boards", {}).get("boards")
    if boards is not None:
        have = {b.get("slug") or b.get("url") for b in boards}
        for b in DEFAULT_SETTINGS["sources"]["ats_boards"]["boards"]:
            key = "board:" + (b.get("slug") or b.get("url"))
            if (b.get("slug") or b.get("url")) not in have and key not in seen:
                boards.append(dict(b))
                notes.append(f"board {b['name']}")
            seen.add(key)
    missions = stored.get("sources", {}).get("ai_hunt", {}).get("missions")
    if missions:
        have = {m.get("id") for m in missions}
        for m in DEFAULT_MISSIONS:
            key = "mission:" + m["id"]
            if m["id"] not in have and key not in seen:
                missions.append(dict(m))
                notes.append(f"mission {m['name']}")
            seen.add(key)
    stored["_defaults_seen"] = sorted(seen)
    db.kv_set("settings", stored)
    return notes
