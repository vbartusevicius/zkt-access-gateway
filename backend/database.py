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
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                door_id INTEGER,
                card_id TEXT,
                pin TEXT,
                event_type INTEGER
            )
        ''')
            
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                pin TEXT PRIMARY KEY,
                card TEXT,
                password TEXT,
                group_id TEXT,
                start_time TEXT,
                end_time TEXT,
                super_authorize BOOLEAN
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS hardware (
                key TEXT PRIMARY KEY,
                value TEXT
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


def save_events(events_list):
    with get_db() as conn:
        cursor = conn.cursor()
        for ev in events_list:
            cursor.execute('''
                SELECT id FROM events 
                WHERE timestamp = ? AND door_id = ? AND event_type = ? AND card_id = ? AND pin = ?
            ''', (ev['timestamp'], ev.get('door_id', 0), ev.get('event_type', 0), ev.get('card_id', ''), ev.get('pin', '')))
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO events (timestamp, door_id, card_id, pin, event_type)
                    VALUES (?, ?, ?, ?, ?)
                ''', (ev['timestamp'], ev.get('door_id', 0), ev.get('card_id', ''), ev.get('pin', ''), ev.get('event_type', 0)))
        conn.commit()

def save_users(users_list):
    with get_db() as conn:
        cursor = conn.cursor()
        # Full sync: clear users if they've been deleted on device
        cursor.execute('DELETE FROM users')
        for u in users_list:
            if "error" in u:
                continue
            cursor.execute('''
                INSERT INTO users (pin, card, password, group_id, start_time, end_time, super_authorize)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                u.get('pin', ''),
                u.get('card', ''),
                u.get('password', ''),
                str(u.get('group', '')),
                u.get('start_time', ''),
                u.get('end_time', ''),
                u.get('super_authorize', False)
            ))
        conn.commit()

def save_hardware(hw_dict, doors_list):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("REPLACE INTO hardware (key, value) VALUES (?, ?)", ("state", json.dumps({
            "hw": hw_dict,
            "doors": doors_list
        })))
        conn.commit()

def get_latest_events(limit=50):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]

def get_users():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.*, MAX(e.timestamp) as last_used
            FROM users u
            LEFT JOIN events e ON (u.pin = e.pin OR (u.card != '' AND u.card = e.card_id))
            GROUP BY u.pin
        ''')
        return [dict(row) for row in cursor.fetchall()]

def get_hardware():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM hardware WHERE key = 'state'")
        row = cursor.fetchone()
        return json.loads(row['value']) if row else {"hw": {}, "doors": []}
