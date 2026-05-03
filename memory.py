import sqlite3
import json
import os

DB_PATH = os.path.expanduser("~/butlerclaw2/butler.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id TEXT PRIMARY KEY,
            profile TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def load_profile(user_id):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT profile FROM profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return {
        "user_id": user_id,
        "zip_code": None,
        "family": {},
        "dietary": [],
        "preferences": [],
        "usuals": [],
        "budget": None,
        "notes": "",
        # ── Claw Engine additions ──
        "timezone": None,
        "claw_mode": False,
        "push_subscription": None,
        "claws": {
            "weekly_autopilot": {
                "enabled": False,
                "day": "sunday",
                "time": "18:00"
            },
            "sale_hunter": {
                "enabled": False,
                "auto_add": False
            },
            "meal_planner": {
                "enabled": False,
                "days": 7
            },
            "restock": {
                "enabled": False,
                "items": []
            }
        }
    }

def save_profile(user_id, profile):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO profiles (user_id, profile, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            profile = excluded.profile,
            updated_at = CURRENT_TIMESTAMP
    """, (user_id, json.dumps(profile)))
    conn.commit()
    conn.close()
def init_messages():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            message TEXT NOT NULL,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_message(user_id, message, email=None):
    init_messages()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO messages (user_id, message, email) VALUES (?, ?, ?)",
        (user_id, message, email)
    )
    conn.commit()
    conn.close()
def init_jobs():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id           TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL,
            task_type    TEXT NOT NULL,
            status       TEXT DEFAULT 'pending',
            payload      TEXT,
            result       TEXT,
            schedule     TEXT,
            created_at   TEXT DEFAULT (datetime('now')),
            scheduled_at TEXT,
            last_run_at  TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_job(job: dict):
    init_jobs()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO jobs (id, user_id, task_type, status, payload, result,
                          schedule, scheduled_at, last_run_at)
        VALUES (:id, :user_id, :task_type, :status, :payload, :result,
                :schedule, :scheduled_at, :last_run_at)
        ON CONFLICT(id) DO UPDATE SET
            status       = excluded.status,
            result       = excluded.result,
            last_run_at  = excluded.last_run_at,
            scheduled_at = excluded.scheduled_at
    """, {
        "id":           job["id"],
        "user_id":      job["user_id"],
        "task_type":    job["task_type"],
        "status":       job.get("status", "pending"),
        "payload":      json.dumps(job.get("payload") or {}),
        "result":       json.dumps(job.get("result") or {}),
        "schedule":     job.get("schedule"),
        "scheduled_at": job.get("scheduled_at"),
        "last_run_at":  job.get("last_run_at"),
    })
    conn.commit()
    conn.close()

def load_job(job_id: str):
    init_jobs()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT * FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    cols = ["id", "user_id", "task_type", "status", "payload", "result",
            "schedule", "created_at", "scheduled_at", "last_run_at"]
    job = dict(zip(cols, row))
    job["payload"] = json.loads(job["payload"] or "{}")
    job["result"]  = json.loads(job["result"]  or "{}")
    return job

def list_jobs(user_id: str):
    init_jobs()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    cols = ["id", "user_id", "task_type", "status", "payload", "result",
            "schedule", "created_at", "scheduled_at", "last_run_at"]
    jobs = []
    for row in rows:
        job = dict(zip(cols, row))
        job["payload"] = json.loads(job["payload"] or "{}")
        job["result"]  = json.loads(job["result"]  or "{}")
        jobs.append(job)
    return jobs

def get_all_scheduled_jobs():
    """Used by APScheduler to find recurring jobs across all users."""
    init_jobs()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT * FROM jobs WHERE schedule IS NOT NULL AND status != 'disabled'"
    ).fetchall()
    conn.close()
    cols = ["id", "user_id", "task_type", "status", "payload", "result",
            "schedule", "created_at", "scheduled_at", "last_run_at"]
    jobs = []
    for row in rows:
        job = dict(zip(cols, row))
        job["payload"] = json.loads(job["payload"] or "{}")
        job["result"]  = json.loads(job["result"]  or "{}")
        jobs.append(job)
    return jobs
