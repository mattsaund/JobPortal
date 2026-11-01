"""The SQLite database: every lead, run, event and saved value lives in one file, DATA/jobportal.db (see config.py).

Who calls it: nearly every package. Read with q() (many rows) or one() (a single row), and write with ex(), or ex_many()
for a batch of rows. Small JSON values go in the kv table through kv_get() and kv_set(). Leads have their own helpers:
update_lead(), add_event() and lead_row().

Key ideas:
- One shared connection, opened on first use. FastAPI runs requests on several threads, so every query holds _lock (a
  re-entrant lock, so a function that holds it can still call q() or ex()). This is a single-user app, so one connection
  is plenty.
- Autocommit: each statement is saved the moment it runs, and there is nothing to commit. The one exception is ex_many(),
  which writes a whole batch in one transaction, since one disk sync per row adds up to seconds for thousands of rows.
- Rows come back as plain dicts keyed by column name. Columns that hold JSON stay text until lead_row() decodes them.
- Timestamps are UTC text from now(), so sorting them as text sorts them by time.
- The tables are created by SCHEMA and upgraded by _migrate(). People installed v0.1.0, so their databases must keep
  opening: add columns in _migrate(), and never rename or drop one.

The tables (columns not listed are plain and named for what they hold):
  kv               one JSON value per key: "settings" (settings.py), "profile.<section>", "profile.answers",
                   "profile.questions", "profile.documents" and the other profile keys (candidate/), "analysis.latest" and
                   "analysis.history" (insights/analysis.py), "hunt.rotation" (where the AI missions rotation resumes)
  profile_history  the previous value of a profile section, saved before every change (candidate/profile.py)
  leads            one row per job (or program, event or company lead) JobPortal found. Important columns:
                     fingerprint       company + title + state, hashed (textutil.fingerprint): one row per job
                     url_key           the link, normalized (textutil.url_key): a second duplicate check
                     kind              "posting", "program", "event" or "intel" (a company worth contacting cold)
                     source, sources   the first source that found it, and the JSON list of every source that did
                     found             JSON list of {source, label, url}: each place the job was seen
                     score, verdict    the AI triage fit score (0 to 100) and "strong", "possible", "stretch" or "no"
                     triage, package   JSON from AI triage, and the application package (research, contacts, emails)
                     stage             where the pipeline is: filtered, qualified, packaging, ready, closed or error
                     app_status        where the user is with the application (config.APP_STATUSES)
                     resume_md, cover_md   the tailored resume and cover letter, as Markdown
                     ats_coverage      the share of the job's keywords the resume contains (textutil.coverage)
                     dream             1 when the lead matches the Dream list
                     dream_manual      NULL when dream is automatic, 0 or 1 when the user set the star by hand
                     industry          the employer's industry (genres.DEFAULT_INDUSTRIES)
                     tokens            AI tokens spent on this lead
                     cost_usd          always 0. Left from before v0.1.0, when JobPortal counted dollars, not tokens
  events           a lead's history (status changes, notes, packages built), shown on the lead page
  runs             one row per search run: mode, status, stats (JSON counters) and tokens. cost_usd is always 0
  run_log          the log lines of each run, shown on the Runs page
  candidates       the triage backlog: jobs that passed the rule filters but haven't been scored yet (RawJob as JSON)
  ai_calls         one row per AI request: purpose, model, effort, tokens, how long it took and any error. Open
                   /api/ai_calls to look at it while developing. cost_usd is always 0
  resume_library   saved resumes on the Resumes page (candidate/library.py). Storage only: they never feed the profile"""
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone

from jobportal.core.config import DATA, DB_PATH, OLD_STATUSES
from jobportal.core.genres import OLD_INDUSTRIES, classify_industry

_lock = threading.RLock()  # held for every query; re-entrant, so code holding it can call q() and ex()
_conn: sqlite3.Connection | None = None  # the shared connection, opened by conn()

# The tables exactly as v0.1.0 created them. Don't edit this text: add new columns in _migrate() instead.
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
-- v0.1.0 created this table on first use from candidate/library.py. It lives here now, with the same columns.
CREATE TABLE IF NOT EXISTS resume_library (
  id INTEGER PRIMARY KEY, name TEXT, md TEXT, style TEXT DEFAULT '{}', source TEXT, lead_id INTEGER, tags TEXT DEFAULT '[]',
  notes TEXT DEFAULT '', original_file TEXT, created_at TEXT, updated_at TEXT
);
"""


def now() -> str:
    """The current time in UTC as ISO 8601 text, to the second (for example "2026-10-29T14:03:12+00:00"). Every timestamp
    in the database uses this format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    """The shared connection, opened on first use. Opening it creates the data folder and the database file if needed,
    creates any missing tables, and upgrades an older database (_migrate)."""
    global _conn
    with _lock:  # two threads asking at once must not both open (and upgrade) the database
        if _conn is None:
            DATA.mkdir(parents=True, exist_ok=True)
            # check_same_thread=False lets every thread share the connection (_lock keeps them taking turns).
            # isolation_level=None is autocommit: each statement is saved at once.
            new = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
            new.row_factory = sqlite3.Row  # rows can be read by column name
            new.execute("PRAGMA journal_mode=WAL")  # write-ahead log: reading never waits for a write in progress
            new.execute("PRAGMA busy_timeout=5000")  # if another process holds the file, wait up to 5 s instead of failing
            new.executescript(SCHEMA)
            _migrate(new)
            _conn = new  # only now, so a failed open is tried again next time instead of leaving a half-ready connection
        return _conn


def _migrate(c: sqlite3.Connection) -> None:
    """Add the columns that older databases lack. Runs every time the connection opens.

    CREATE TABLE IF NOT EXISTS never changes a table that already exists, so a column added after a table first shipped
    is added here with ALTER TABLE, and only when it's missing. Each step checks first, so running this again changes
    nothing. Two steps also fill the new column in for the rows already there.

    found, dream_manual and industry aren't in SCHEMA at all, so even a brand-new database gets them from here."""
    # tokens replaced the old dollar counts (cost_usd) before v0.1.0.
    for table in ("runs", "ai_calls", "leads"):
        if "tokens" not in _columns(c, table):
            c.execute(f"ALTER TABLE {table} ADD COLUMN tokens INTEGER DEFAULT 0")
    lead_columns = _columns(c, "leads")
    if "found" not in lead_columns:
        c.execute("ALTER TABLE leads ADD COLUMN found TEXT DEFAULT '[]'")
        # Every existing lead was seen in one place: where its source found it.
        for row in c.execute("SELECT id, source, source_detail, url FROM leads").fetchall():
            url = row["url"] or ""
            # Leads from a GitHub list point at the list's repository, named in source_detail ("GitHub owner/repo, ...").
            repo = re.search(r"GitHub ([\w.-]+/[\w.-]+)", row["source_detail"] or "")
            if row["source"] == "github" and repo:
                url = f"https://github.com/{repo.group(1)}"
            found = [{"source": row["source"], "label": row["source_detail"] or row["source"], "url": url}]
            c.execute("UPDATE leads SET found=? WHERE id=?", (json.dumps(found), row["id"]))
    if "dream_manual" not in lead_columns:
        c.execute("ALTER TABLE leads ADD COLUMN dream_manual INTEGER")  # NULL = automatic, 0 or 1 = set by hand
    if "industry" not in lead_columns:
        c.execute("ALTER TABLE leads ADD COLUMN industry TEXT")
        for row in c.execute("SELECT id, company, title, description FROM leads").fetchall():
            industry = classify_industry(row["company"], row["title"], row["description"])
            c.execute("UPDATE leads SET industry=? WHERE id=?", (industry, row["id"]))
    # v0.3.0 cut the application statuses down to the Tracker's five columns (config.OLD_STATUSES). This is a row update,
    # not a column change, and it finds nothing to change once it has run.
    for old, new in OLD_STATUSES.items():
        c.execute("UPDATE leads SET app_status=? WHERE app_status=?", (new, old))
    # v0.3.0 also replaced the tech-heavy industry list with one for every field (genres.OLD_INDUSTRIES says what each old
    # name became). Another row update that finds nothing to change once it has run.
    for old, new in OLD_INDUSTRIES.items():
        c.execute("UPDATE leads SET industry=? WHERE industry=?", (new, old))
    # v0.3.0 dropped the Equity mining page. Its only saved value was the list of snoozed moves, which nothing reads now.
    c.execute("DELETE FROM kv WHERE key='crm.snoozed'")


def _columns(c: sqlite3.Connection, table: str) -> set[str]:
    """The column names of a table. `table` comes from code, never from a user, so formatting it into the SQL is safe."""
    return {row["name"] for row in c.execute(f"PRAGMA table_info({table})")}


def close() -> None:
    """Close the shared connection. The next query opens it again. Tests use this to start each test with a fresh
    database."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def q(sql: str, args=()) -> list[dict]:
    """Run a query and return every row as a dict, for example q("SELECT * FROM leads WHERE stage=?", ("ready",)).
    Always pass values through `args` (the ? marks) rather than formatting them into `sql`."""
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql: str, args=()) -> dict | None:
    """Run a query and return its first row as a dict, or None when there are no rows."""
    with _lock:
        r = conn().execute(sql, args).fetchone()
        return dict(r) if r else None


def ex(sql: str, args=()) -> int:
    """Run a statement that changes data (INSERT, UPDATE, DELETE). Returns the new row's id after an INSERT."""
    with _lock:
        return conn().execute(sql, args).lastrowid


def ex_many(sql: str, rows) -> None:
    """Run one statement for every set of values in `rows`, all in one transaction: either every row is written or none.

    In autocommit each statement is its own transaction, and each one waits for the disk to confirm the write. For a
    few rows that doesn't matter, but saving a triage backlog of thousands of candidates took about 10 seconds that way
    (on the event loop, so the dashboard froze), and well under one second as one transaction."""
    with _lock:
        c = conn()
        c.execute("BEGIN")
        try:
            c.executemany(sql, rows)
        except BaseException:
            c.execute("ROLLBACK")
            raise
        c.execute("COMMIT")


def kv_get(key: str, default=None):
    """The JSON value stored under `key` in the kv table, decoded, or `default` when there is none."""
    r = one("SELECT value FROM kv WHERE key=?", (key,))
    return json.loads(r["value"]) if r else default


def kv_set(key: str, value) -> None:
    """Store `value` (anything JSON can hold) under `key` in the kv table, replacing any old value."""
    ex("INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
       (key, json.dumps(value), now()))


def update_lead(lead_id: int, **fields) -> None:
    """Change some columns of one lead, for example update_lead(7, stage="ready", package={...}).

    Dicts and lists are stored as JSON, and updated_at is set to now. The keyword names go into the SQL as column names,
    so only pass names written in code, never keys taken from a request (web/routes/leads.py checks them against a list)."""
    if not fields:
        return
    fields["updated_at"] = now()
    values = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
    assignments = ", ".join(f"{column}=?" for column in fields)
    ex(f"UPDATE leads SET {assignments} WHERE id=?", (*values, lead_id))


def add_event(lead_id: int, type_: str, text: str = "") -> None:
    """Add a line to a lead's history (the events table), for example add_event(7, "note", "Called the recruiter")."""
    ex("INSERT INTO events(lead_id,ts,type,text) VALUES(?,?,?,?)", (lead_id, now(), type_, text))


# Lead columns that hold JSON text. lead_row() decodes them; update_lead() encodes dicts and lists on the way in.
JSON_COLS = ("sources", "triage", "package", "found")
_LIST_COLS = {"sources", "found"}  # the JSON columns that hold lists; the others hold objects


def lead_row(r: dict | None) -> dict | None:
    """Decode the JSON columns of a lead row from q() or one(), in place, and return the row. None stays None.

    A value that isn't valid JSON becomes an empty list or object, so one damaged row can't break a page."""
    if r is None:
        return None
    for col in JSON_COLS:
        if isinstance(r.get(col), str):
            try:
                r[col] = json.loads(r[col])
            except json.JSONDecodeError:
                r[col] = [] if col in _LIST_COLS else {}
    return r
