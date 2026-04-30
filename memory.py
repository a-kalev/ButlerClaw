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
        "notes": ""
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
