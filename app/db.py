"""
Storage. Uses Postgres when DATABASE_URL is set (the hosted version, e.g. Neon),
otherwise a local SQLite file (your laptop). The rest of the app doesn't know which.

Five tables:
  vendors   - the vendor master (approved vendors we already pay)
  runs      - one row per submission processed
  stages    - the 6 stages of each run, with every check's result (audit trail)
  documents - files uploaded with a submission (stored in the database itself)
  messages  - every email drafted / sent (the outbox)

All SQL below is written once, with "?" placeholders, and works on both databases.
"""
import json
import sqlite3
import threading
from datetime import datetime, timezone

from . import config
from .reference_data import SEED_VENDORS

_lock = threading.Lock()
_conn = None
IS_PG = bool(config.DATABASE_URL)

STAGES = [
    ("intake", "Intake & completeness"),
    ("format", "Format validation"),
    ("consistency", "Cross-field consistency"),
    ("risk", "Risk & duplicate check"),
    ("decision", "Decision"),
    ("communicate", "Communicate"),
]

# Only the auto-increment id and the binary column differ between the two databases.
_ID = "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
_BLOB = "BYTEA" if IS_PG else "BLOB"

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS vendors (
        code TEXT PRIMARY KEY,
        legal_name TEXT NOT NULL,
        country TEXT NOT NULL,
        tax_id TEXT,
        secondary_id TEXT,
        bank_account TEXT,
        bank_code TEXT,
        source TEXT NOT NULL DEFAULT 'seed',
        run_id BIGINT,
        created_at TEXT NOT NULL
    )""",
    f"""CREATE TABLE IF NOT EXISTS runs (
        id {_ID},
        created_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        decision TEXT,
        legal_name TEXT,
        country TEXT,
        contact_email TEXT,
        submission_json TEXT NOT NULL,
        decision_reason TEXT,
        top_issue TEXT,
        reviewer_summary TEXT,
        summary_source TEXT,
        vendor_code TEXT,
        issue_count INTEGER DEFAULT 0,
        updated_seq INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS stages (
        run_id BIGINT NOT NULL,
        idx INTEGER NOT NULL,
        key TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        checks_json TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY (run_id, idx)
    )""",
    f"""CREATE TABLE IF NOT EXISTS documents (
        id {_ID},
        run_id BIGINT NOT NULL,
        doc_type TEXT NOT NULL,
        filename TEXT,
        size INTEGER,
        detected_type TEXT,
        sha256 TEXT,
        path TEXT,
        content {_BLOB}
    )""",
    f"""CREATE TABLE IF NOT EXISTS messages (
        id {_ID},
        run_id BIGINT NOT NULL,
        kind TEXT NOT NULL,
        to_addr TEXT,
        intended_to TEXT,
        subject TEXT,
        body TEXT,
        status TEXT NOT NULL,
        provider TEXT,
        error TEXT,
        written_by TEXT,
        created_at TEXT NOT NULL
    )""",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# --------------------------------------------------------------------------
# Connection handling
# --------------------------------------------------------------------------

def _connect():
    if IS_PG:
        import psycopg  # only needed for the hosted version
        from psycopg.rows import dict_row
        # prepare_threshold=None: Neon's pooled endpoint doesn't keep prepared statements.
        return psycopg.connect(config.DATABASE_URL, autocommit=True, row_factory=dict_row,
                               prepare_threshold=None, connect_timeout=15)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _conn_get():
    global _conn
    if _conn is None:
        _conn = _connect()
    return _conn


def _sql(sql: str) -> str:
    return sql.replace("?", "%s") if IS_PG else sql


def _run(sql, params=(), fetch=False):
    """Run one statement. On Postgres, a dropped connection (e.g. Neon idling) is reopened once."""
    global _conn
    with _lock:
        for attempt in (1, 2):
            try:
                cur = _conn_get().execute(_sql(sql), params)
                if fetch:
                    return [dict(r) for r in cur.fetchall()]
                return cur
            except Exception as exc:
                if IS_PG and attempt == 1 and _is_connection_error(exc):
                    try:
                        _conn.close()
                    except Exception:
                        pass
                    _conn = None
                    continue
                raise


def _is_connection_error(exc) -> bool:
    import psycopg
    return isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError))


def execute(sql, params=()):
    _run(sql, params)


def insert(sql, params=()) -> int:
    """INSERT that returns the new row's id."""
    if IS_PG:
        return _run(sql + " RETURNING id", params, fetch=True)[0]["id"]
    return _run(sql, params).lastrowid


def query(sql, params=()):
    return _run(sql, params, fetch=True)


def query_one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def init():
    for statement in SCHEMA:
        execute(statement)
    if not IS_PG:  # local databases created by an earlier version of this app
        run_cols = {r["name"] for r in query("PRAGMA table_info(runs)")}
        if "decision" not in run_cols:
            execute("ALTER TABLE runs ADD COLUMN decision TEXT")
        doc_cols = {r["name"] for r in query("PRAGMA table_info(documents)")}
        if "content" not in doc_cols:
            execute("ALTER TABLE documents ADD COLUMN content BLOB")
    if not query_one("SELECT code FROM vendors LIMIT 1"):
        seed_vendors()


def backend_name() -> str:
    return "Postgres" if IS_PG else "SQLite"


def seed_vendors():
    for code, name, country, tax, sec, acct, bcode in SEED_VENDORS:
        execute(
            "INSERT INTO vendors (code, legal_name, country, tax_id, secondary_id, bank_account, bank_code, "
            "source, created_at) VALUES (?,?,?,?,?,?,?, 'seed', ?) ON CONFLICT (code) DO NOTHING",
            (code, name, country, tax, sec, acct, bcode, now()),
        )


def reset_demo():
    """Clear all runs and restore the vendor master to its original seed."""
    if IS_PG:
        execute("TRUNCATE runs, stages, documents, messages, vendors RESTART IDENTITY")
    else:
        for table in ("runs", "stages", "documents", "messages", "vendors"):
            execute(f"DELETE FROM {table}")
        execute("DELETE FROM sqlite_sequence WHERE name IN ('runs','documents','messages')")
    seed_vendors()


# --------------------------------------------------------------------------
# Runs and stages
# --------------------------------------------------------------------------

def create_run(submission: dict) -> int:
    run_id = insert(
        "INSERT INTO runs (created_at, status, legal_name, country, contact_email, submission_json) "
        "VALUES (?, 'running', ?, ?, ?, ?)",
        (now(), submission.get("legal_name"), submission.get("country"),
         submission.get("contact_email"), json.dumps(submission)),
    )
    for idx, (key, name) in enumerate(STAGES):
        execute("INSERT INTO stages (run_id, idx, key, name, status) VALUES (?,?,?,?, 'waiting')",
                (run_id, idx, key, name))
    return run_id


def bump(run_id: int):
    execute("UPDATE runs SET updated_seq = updated_seq + 1 WHERE id = ?", (run_id,))


def start_stage(run_id: int, idx: int):
    execute("UPDATE stages SET status='running', started_at=? WHERE run_id=? AND idx=?",
            (now(), run_id, idx))
    bump(run_id)


def finish_stage(run_id: int, idx: int, status: str, checks: list):
    execute("UPDATE stages SET status=?, finished_at=?, checks_json=? WHERE run_id=? AND idx=?",
            (status, now(), json.dumps(checks), run_id, idx))
    bump(run_id)


def update_run(run_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    execute(f"UPDATE runs SET {cols} WHERE id = ?", (*fields.values(), run_id))
    bump(run_id)


def add_document(run_id, doc_type, filename, size, detected_type, sha256, content: bytes):
    execute(
        "INSERT INTO documents (run_id, doc_type, filename, size, detected_type, sha256, content) "
        "VALUES (?,?,?,?,?,?,?)",
        (run_id, doc_type, filename, size, detected_type, sha256, content),
    )


def get_document(run_id: int, doc_id: int):
    return query_one("SELECT * FROM documents WHERE id = ? AND run_id = ?", (doc_id, run_id))


def add_message(run_id, kind, to_addr, intended_to, subject, body, status, provider, error, written_by):
    execute(
        "INSERT INTO messages (run_id, kind, to_addr, intended_to, subject, body, status, provider, "
        "error, written_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, kind, to_addr, intended_to, subject, body, status, provider, error, written_by, now()),
    )
    bump(run_id)


def get_run(run_id: int):
    run = query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    if not run:
        return None
    run["submission"] = json.loads(run.pop("submission_json"))
    stages = query("SELECT * FROM stages WHERE run_id = ? ORDER BY idx", (run_id,))
    for s in stages:
        s["checks"] = json.loads(s.pop("checks_json") or "[]")
    run["stages"] = stages
    run["documents"] = query(
        "SELECT id, doc_type, filename, size, detected_type FROM documents WHERE run_id = ? ORDER BY id",
        (run_id,))
    run["messages"] = query("SELECT * FROM messages WHERE run_id = ? ORDER BY id", (run_id,))
    return run


def list_runs(status=None, q=None, limit=200):
    sql = ("SELECT id, created_at, finished_at, status, legal_name, country, top_issue, issue_count, "
           "vendor_code FROM runs")
    where, params = [], []
    if status and status != "all":
        where.append("status = ?")
        params.append(status)
    if q:
        where.append("(LOWER(legal_name) LIKE LOWER(?) OR CAST(id AS TEXT) = ?)")
        params += [f"%{q}%", q.lstrip("#")]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return query(sql, params)


def _seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def stats():
    rows = query("SELECT status, COUNT(*) AS n FROM runs GROUP BY status")
    counts = {r["status"]: r["n"] for r in rows}
    done = query("SELECT created_at, finished_at FROM runs WHERE finished_at IS NOT NULL")
    durations = [_seconds(r["created_at"], r["finished_at"]) for r in done]
    return {
        "total": sum(counts.values()),
        "approved": counts.get("approved", 0),
        "pending": counts.get("pending", 0),
        "rejected": counts.get("rejected", 0),
        "error": counts.get("error", 0),
        "running": counts.get("running", 0),
        "avg_seconds": round(sum(durations) / len(durations), 1) if durations else None,
    }


def next_vendor_code() -> str:
    rows = query("SELECT code FROM vendors")
    nums = [int(r["code"].split("-")[1]) for r in rows if r["code"].startswith("V-")]
    return f"V-{(max(nums) if nums else 1000) + 1}"
