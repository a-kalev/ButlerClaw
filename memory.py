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
        "usuals": [], #AI-learnt usuals
        "usuals_products": [],       # User-added usuals — full product objects (name, upc, image, price, brand)
        "unusuals": [],              # One-time adds for next scheduled run — cleared after use
        "budget": None,
        "notes": "",
        # ── Claw Engine additions ──
        "timezone": None,
        "claw_mode": False,
        "push_subscription": None,
        "claws": {
            "weekly_autopilot": {
                "enabled": False,
                "mode": "remind",        # "auto" | "remind"
                "day": "friday",
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
# ── Usuals helpers ─────────────────────────────────────────────────────────────
# usuals_products schema per item:
# { "upc": "...", "name": "...", "brand": "...", "image": "...",
#   "regular_price": 3.99, "sale_price": null, "term": "whole milk" }

def get_usuals_products(user_id: str) -> list:
    profile = load_profile(user_id)
    return profile.get("usuals_products", [])

def add_usual_product(user_id: str, product: dict) -> list:
    """Adds product to usuals_products (deduped by upc). Syncs plain usuals for AI."""
    profile = load_profile(user_id)
    products = profile.get("usuals_products", [])
    upc = product.get("upc", "")
    if upc and any(p.get("upc") == upc for p in products):
        return products
    products.append(product)
    profile["usuals_products"] = products
    profile["usuals"] = [p.get("term") or p.get("name", "") for p in products]
    save_profile(user_id, profile)
    return products

def remove_usual_product(user_id: str, upc: str) -> list:
    """Removes product by upc. Syncs plain usuals for AI."""
    profile = load_profile(user_id)
    products = [p for p in profile.get("usuals_products", []) if p.get("upc") != upc]
    profile["usuals_products"] = products
    profile["usuals"] = [p.get("term") or p.get("name", "") for p in products]
    save_profile(user_id, profile)
    return products

# ── Unusuals helpers ───────────────────────────────────────────────────────────

def get_unusuals(user_id: str) -> list:
    return load_profile(user_id).get("unusuals", [])

def add_unusual(user_id: str, product: dict) -> list:
    """One-time add for next scheduled run. Deduped by upc."""
    profile = load_profile(user_id)
    unusuals = profile.get("unusuals", [])
    upc = product.get("upc", "")
    if upc and any(p.get("upc") == upc for p in unusuals):
        return unusuals
    unusuals.append(product)
    profile["unusuals"] = unusuals
    save_profile(user_id, profile)
    return unusuals

def remove_unusual(user_id: str, upc: str) -> list:
    profile = load_profile(user_id)
    unusuals = [p for p in profile.get("unusuals", []) if p.get("upc") != upc]
    profile["unusuals"] = unusuals
    save_profile(user_id, profile)
    return unusuals

def clear_unusuals(user_id: str):
    """Called after scheduled run completes."""
    profile = load_profile(user_id)
    profile["unusuals"] = []
    save_profile(user_id, profile)

# ── Analytics ─────────────────────────────────────────────────────────────────
# Anonymous only — no user_id, no names, no emails.
# event_type | data (json) | created_at

def init_analytics():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analytics (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            data       TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

def log_event(event_type: str, data: dict):
    """Log an anonymous analytics event. Never include PII."""
    try:
        init_analytics()
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO analytics (event_type, data) VALUES (?, ?)",
            (event_type, json.dumps(data))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[analytics] log_event failed: {e}")

def get_analytics_summary() -> dict:
    """Returns aggregated event counts and top items. Used by /analytics endpoint."""
    try:
        init_analytics()
        conn = sqlite3.connect(DB_PATH)

        # Total counts per event type
        rows = conn.execute(
            "SELECT event_type, COUNT(*) as cnt FROM analytics GROUP BY event_type ORDER BY cnt DESC"
        ).fetchall()
        totals = {r[0]: r[1] for r in rows}

        # Top search terms
        searches = conn.execute(
            """SELECT json_extract(data, '$.term') as term, COUNT(*) as cnt
               FROM analytics WHERE event_type = 'search'
               GROUP BY term ORDER BY cnt DESC LIMIT 10"""
        ).fetchall()

        # Top cart adds
        cart_adds = conn.execute(
            """SELECT json_extract(data, '$.name') as name, COUNT(*) as cnt
               FROM analytics WHERE event_type = 'cart_add'
               GROUP BY name ORDER BY cnt DESC LIMIT 10"""
        ).fetchall()

        # Top task runs
        tasks = conn.execute(
            """SELECT json_extract(data, '$.task_type') as task, COUNT(*) as cnt
               FROM analytics WHERE event_type = 'task_run'
               GROUP BY task ORDER BY cnt DESC LIMIT 10"""
        ).fetchall()

        # Top usual adds
        usual_adds = conn.execute(
            """SELECT json_extract(data, '$.name') as name, COUNT(*) as cnt
               FROM analytics WHERE event_type = 'usual_add'
               GROUP BY name ORDER BY cnt DESC LIMIT 10"""
        ).fetchall()

        conn.close()
        return {
            "totals": totals,
            "top_searches": [{"term": r[0], "count": r[1]} for r in searches if r[0]],
            "top_cart_adds": [{"name": r[0], "count": r[1]} for r in cart_adds if r[0]],
            "top_tasks": [{"task": r[0], "count": r[1]} for r in tasks if r[0]],
            "top_usual_adds": [{"name": r[0], "count": r[1]} for r in usual_adds if r[0]],
        }
    except Exception as e:
        print(f"[analytics] get_analytics_summary failed: {e}")
        return {}
