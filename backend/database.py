import sqlite3
import json
import os
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "data/gateway.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else '.', exist_ok=True)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                door_id INTEGER,
                card_id TEXT,
                event_type INTEGER
            )
        ''')
        conn.commit()

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def get_setting(key, default=None):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return json.loads(row['value']) if row else default

def set_setting(key, value):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        conn.commit()

def save_events(events_list):
    with get_db() as conn:
        cursor = conn.cursor()
        for ev in events_list:
            # Simple deduplication strategy: check if exact event exists
            cursor.execute('''
                SELECT id FROM events 
                WHERE timestamp = ? AND door_id = ? AND event_type = ? AND card_id = ?
            ''', (ev['timestamp'], ev.get('door_id', 0), ev.get('event_type', 0), ev.get('card_id', '')))
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO events (timestamp, door_id, card_id, event_type)
                    VALUES (?, ?, ?, ?)
                ''', (ev['timestamp'], ev.get('door_id', 0), ev.get('card_id', ''), ev.get('event_type', 0)))
        conn.commit()

def get_latest_events(limit=50):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]
