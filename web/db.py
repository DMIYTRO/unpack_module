import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "history.db"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rename_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      TEXT NOT NULL,
            timestamp   TEXT NOT NULL,
            folder_name TEXT NOT NULL,
            original    TEXT NOT NULL,
            new_name    TEXT NOT NULL,
            mode        TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS run_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id    TEXT UNIQUE NOT NULL,
            started   TEXT NOT NULL,
            finished  TEXT,
            trigger   TEXT NOT NULL,
            status    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conflicts (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id         TEXT NOT NULL,
            timestamp      TEXT NOT NULL,
            folder_name    TEXT NOT NULL,
            files_json     TEXT NOT NULL,
            suborders_json TEXT NOT NULL,
            mapping_json   TEXT NOT NULL,
            status         TEXT DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS schedule_config (
            id              INTEGER PRIMARY KEY,
            cron_expression TEXT DEFAULT '',
            enabled         INTEGER DEFAULT 0,
            target_dir      TEXT DEFAULT 'original_archives',
            last_run        TEXT
        );
        INSERT OR IGNORE INTO schedule_config (id, cron_expression, enabled, target_dir)
        VALUES (1, '', 0, 'original_archives');
    """)
    conn.commit()
    conn.close()


# ── Run log ────────────────────────────────────────────────────────────────

def log_run(run_id, trigger):
    conn = get_db()
    conn.execute(
        "INSERT INTO run_log (run_id, started, trigger, status) VALUES (?, ?, ?, 'running')",
        (run_id, datetime.now().isoformat(), trigger),
    )
    conn.commit()
    conn.close()


def finish_run(run_id, status):
    conn = get_db()
    conn.execute(
        "UPDATE run_log SET finished=?, status=? WHERE run_id=?",
        (datetime.now().isoformat(), status, run_id),
    )
    conn.commit()
    conn.close()


def get_recent_runs(limit=10):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM run_log ORDER BY started DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Rename events ───────────────────────────────────────────────────────────

def log_rename(run_id, folder_name, original, new_name, mode):
    conn = get_db()
    conn.execute(
        "INSERT INTO rename_events (run_id, timestamp, folder_name, original, new_name, mode) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, datetime.now().isoformat(), folder_name, original, new_name, mode),
    )
    conn.commit()
    conn.close()


def get_rename_history(limit=300, search=None, date_from=None):
    conn = get_db()
    query = "SELECT * FROM rename_events WHERE 1=1"
    params = []
    if search:
        query += " AND (original LIKE ? OR new_name LIKE ? OR folder_name LIKE ?)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if date_from:
        query += " AND timestamp >= ?"
        params.append(date_from)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Conflicts ───────────────────────────────────────────────────────────────

def save_conflict(run_id, folder_name, files, suborders, mapping):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO conflicts (run_id, timestamp, folder_name, files_json, suborders_json, mapping_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            run_id,
            datetime.now().isoformat(),
            folder_name,
            json.dumps(files),
            json.dumps(suborders),
            json.dumps(mapping),
        ),
    )
    conflict_id = cur.lastrowid
    conn.commit()
    conn.close()
    return conflict_id


def get_conflict(conflict_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM conflicts WHERE id=?", (conflict_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def resolve_conflict(conflict_id, status):
    conn = get_db()
    conn.execute("UPDATE conflicts SET status=? WHERE id=?", (status, conflict_id))
    conn.commit()
    conn.close()


def get_pending_conflicts():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM conflicts WHERE status='pending' ORDER BY timestamp DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Stats ───────────────────────────────────────────────────────────────────

def get_stats():
    conn = get_db()
    today = datetime.now().date().isoformat()
    renamed_today = conn.execute(
        "SELECT COUNT(*) FROM rename_events WHERE timestamp >= ?", (today,)
    ).fetchone()[0]
    pending_conflicts = conn.execute(
        "SELECT COUNT(*) FROM conflicts WHERE status='pending'"
    ).fetchone()[0]
    total_renamed = conn.execute("SELECT COUNT(*) FROM rename_events").fetchone()[0]
    last_run = conn.execute(
        "SELECT * FROM run_log ORDER BY started DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return {
        "renamed_today": renamed_today,
        "pending_conflicts": pending_conflicts,
        "total_renamed": total_renamed,
        "last_run": dict(last_run) if last_run else None,
    }


# ── Schedule ────────────────────────────────────────────────────────────────

def get_schedule():
    conn = get_db()
    row = conn.execute("SELECT * FROM schedule_config WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else {}


def save_schedule(cron_expression, enabled, target_dir):
    conn = get_db()
    conn.execute(
        "UPDATE schedule_config SET cron_expression=?, enabled=?, target_dir=?, last_run=last_run WHERE id=1",
        (cron_expression, 1 if enabled else 0, target_dir),
    )
    conn.commit()
    conn.close()


def update_last_run():
    conn = get_db()
    conn.execute(
        "UPDATE schedule_config SET last_run=? WHERE id=1",
        (datetime.now().isoformat(),),
    )
    conn.commit()
    conn.close()
