"""SQLite storage. One shared connection guarded by a lock: this is a single-user app."""
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone

from .config import DATA, DB_PATH

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS profile_history (id INTEGER PRIMARY KEY, key TEXT, value TEXT, saved_at TEXT);
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY,
  fingerprint TEXT UNIQUE,
  url_key TEXT,
  url TEXT, apply_url TEXT,
  title TEXT, company TEXT, location TEXT,
  kind TEXT DEFAULT 'posting',
  category TEXT,
  source TEXT, sources TEXT DEFAULT '[]', source_detail TEXT,
  posted_at TEXT, deadline TEXT,
  description TEXT,
  score INTEGER, verdict TEXT, triage TEXT DEFAULT '{}',
  stage TEXT DEFAULT 'discovered',
  stage_error TEXT,
  app_status TEXT DEFAULT 'new',
  package TEXT DEFAULT '{}',
  resume_md TEXT, cover_md TEXT,
  ats_coverage REAL,
  follow_up_at TEXT, applied_at TEXT,
  notes TEXT DEFAULT '',
  dream INTEGER DEFAULT 0,
  cost_usd REAL DEFAULT 0,
  tokens INTEGER DEFAULT 0,
  run_id INTEGER,
  created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS leads_url_key ON leads(url_key);
CREATE INDEX IF NOT EXISTS leads_stage ON leads(stage);
CREATE INDEX IF NOT EXISTS leads_status ON leads(app_status);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, lead_id INTEGER, ts TEXT, type TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS events_lead ON events(lead_id);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, mode TEXT, status TEXT,
  stats TEXT DEFAULT '{}', cost_usd REAL DEFAULT 0, tokens INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run_log (id INTEGER PRIMARY KEY, run_id INTEGER, ts TEXT, level TEXT, source TEXT, msg TEXT);
CREATE INDEX IF NOT EXISTS run_log_run ON run_log(run_id);
CREATE TABLE IF NOT EXISTS candidates (
  fingerprint TEXT PRIMARY KEY, data TEXT, rule_score REAL, first_seen TEXT, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS ai_calls (
  id INTEGER PRIMARY KEY, ts TEXT, run_id INTEGER, lead_id INTEGER, purpose TEXT, model TEXT, effort TEXT,
  cost_usd REAL, tokens INTEGER DEFAULT 0, duration_ms INTEGER, ok INTEGER, error TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA busy_timeout=5000")
        _conn.executescript(SCHEMA)
        _migrate(_conn)
    return _conn


def _migrate(c: sqlite3.Connection) -> None:
    for table in ("runs", "ai_calls"):
        if "tokens" not in {r[1] for r in c.execute(f"PRAGMA table_info({table})")}:
            c.execute(f"ALTER TABLE {table} ADD COLUMN tokens INTEGER DEFAULT 0")
    cols = {r[1] for r in c.execute("PRAGMA table_info(leads)")}
    if "tokens" not in cols:
        c.execute("ALTER TABLE leads ADD COLUMN tokens INTEGER DEFAULT 0")
    if "found" not in cols:
        # Where each lead was discovered: [{source, label, url}], one entry per place it was seen.
        c.execute("ALTER TABLE leads ADD COLUMN found TEXT DEFAULT '[]'")
        for r in c.execute("SELECT id, source, source_detail, url FROM leads").fetchall():
            url = r[3] or ""
            m = re.search(r"GitHub ([\w.-]+/[\w.-]+)", r[2] or "")
            if r[1] == "github" and m:
                url = f"https://github.com/{m.group(1)}"
            c.execute("UPDATE leads SET found=? WHERE id=?", (json.dumps([{"source": r[1], "label": r[2] or r[1], "url": url}]), r[0]))
    if "dream_manual" not in cols:
        c.execute("ALTER TABLE leads ADD COLUMN dream_manual INTEGER")  # NULL = automatic, 0/1 = set by hand
    if "industry" not in cols:
        from .genres import classify_industry
        c.execute("ALTER TABLE leads ADD COLUMN industry TEXT")
        for r in c.execute("SELECT id, company, title, description FROM leads").fetchall():
            c.execute("UPDATE leads SET industry=? WHERE id=?", (classify_industry(r[1], r[2], r[3]), r[0]))


def close() -> None:
    """Close the shared connection (tests and shutdown)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def q(sql: str, args=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql: str, args=()) -> dict | None:
    with _lock:
        r = conn().execute(sql, args).fetchone()
        return dict(r) if r else None


def ex(sql: str, args=()) -> int:
    """Execute and return lastrowid."""
    with _lock:
        return conn().execute(sql, args).lastrowid


def kv_get(key: str, default=None):
    r = one("SELECT value FROM kv WHERE key=?", (key,))
    return json.loads(r["value"]) if r else default


def kv_set(key: str, value) -> None:
    ex("INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
       (key, json.dumps(value), now()))


def update_lead(lead_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = now()
    for k, v in list(fields.items()):
        if isinstance(v, (dict, list)):
            fields[k] = json.dumps(v)
    cols = ", ".join(f"{k}=?" for k in fields)
    ex(f"UPDATE leads SET {cols} WHERE id=?", (*fields.values(), lead_id))


def add_event(lead_id: int, type_: str, text: str = "") -> None:
    ex("INSERT INTO events(lead_id,ts,type,text) VALUES(?,?,?,?)", (lead_id, now(), type_, text))


JSON_COLS = ("sources", "triage", "package", "found")


def lead_row(r: dict | None) -> dict | None:
    if r is None:
        return None
    for c in JSON_COLS:
        if c in r and isinstance(r[c], str):
            try:
                r[c] = json.loads(r[c])
            except json.JSONDecodeError:
                r[c] = {} if c != "sources" else []
    return r
