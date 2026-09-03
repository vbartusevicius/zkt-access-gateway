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
        # Gateway-side enrichment: the device User table has no name field,
        # so cardholder names live here keyed by pin and never hit the device
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_names (
                pin TEXT PRIMARY KEY,
                name TEXT
            )
        ''')
        # Migrate: add event detail columns if coming from an older schema
        for column, ddl in (("entry_exit", "TEXT"), ("verify_mode", "TEXT")):
            cols = [r[1] for r in cursor.execute("PRAGMA table_info(events)")]
            if column not in cols:
                cursor.execute(f"ALTER TABLE events ADD COLUMN {column} {ddl}")

        # Remove duplicates before enforcing uniqueness (keeps earliest row)
        cursor.execute('''
            DELETE FROM events WHERE id NOT IN (
                SELECT MIN(id) FROM events
                GROUP BY timestamp, door_id, event_type, card_id, pin
            )
        ''')
        cursor.execute('DROP INDEX IF EXISTS idx_events_dedup')
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedup
            ON events (timestamp, door_id, event_type, card_id, pin)
        ''')
        conn.commit()

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()


MAX_EVENTS = 10000

def save_events(events_list):
    """Insert events atomically; the UNIQUE index on idx_events_dedup handles dedup."""
    rows = [
        (ev['timestamp'], ev.get('door_id', 0), ev.get('card_id', ''), ev.get('pin', ''),
         ev.get('event_type', 0), ev.get('entry_exit', ''), ev.get('verify_mode', ''))
        for ev in events_list
    ]
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.executemany('''
            INSERT OR IGNORE INTO events (timestamp, door_id, card_id, pin, event_type, entry_exit, verify_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', rows)
        cursor.execute('''
            DELETE FROM events WHERE id NOT IN (
                SELECT id FROM events ORDER BY timestamp DESC LIMIT ?
            )
        ''', (MAX_EVENTS,))
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

def save_user_name(pin, name):
    with get_db() as conn:
        cursor = conn.cursor()
        if name and str(name).strip():
            cursor.execute("REPLACE INTO user_names (pin, name) VALUES (?, ?)", (str(pin), str(name).strip()))
        else:
            cursor.execute("DELETE FROM user_names WHERE pin = ?", (str(pin),))
        conn.commit()

def get_events_name_join():
    """Shared JOIN fragment resolving event -> cardholder name by pin or card."""
    return """
        LEFT JOIN users u ON (e.pin != '' AND e.pin = u.pin)
                          OR (e.card_id != '' AND e.card_id = u.card)
        LEFT JOIN user_names un ON un.pin = u.pin
    """

def get_latest_event_timestamp():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(timestamp) as ts FROM events")
        row = cursor.fetchone()
        return row["ts"] if row and row["ts"] else ""

def get_latest_events(limit=50):
    return get_events_filtered({"limit": limit})

def get_events_filtered(filters):
    """Filterable event query. Supported filters: limit, door_id, event_type,
    q (card/pin substring), dt_from, dt_to (inclusive ISO bounds)."""
    where, params = ["1=1"], []
    if filters.get("door_id"):
        where.append("e.door_id = ?")
        params.append(int(filters["door_id"]))
    if filters.get("event_type") not in (None, ""):
        where.append("e.event_type = ?")
        params.append(int(filters["event_type"]))
    if filters.get("q"):
        where.append("(e.card_id LIKE ? OR e.pin LIKE ? OR un.name LIKE ?)")
        q = f"%{filters['q']}%"
        params.extend((q, q, q))
    if filters.get("dt_from"):
        where.append("e.timestamp >= ?")
        params.append(filters["dt_from"])
    if filters.get("dt_to"):
        where.append("e.timestamp <= ?")
        params.append(filters["dt_to"])
    limit = min(int(filters.get("limit") or 100), 1000)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT e.*, COALESCE(un.name, '') AS user_name FROM events e "
            f"{get_events_name_join()} "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY e.timestamp DESC LIMIT ?", (*params, limit)
        )
        return [dict(row) for row in cursor.fetchall()]

def get_users():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.*, MAX(e.timestamp) as last_used,
                   COALESCE((SELECT name FROM user_names WHERE pin = u.pin), '') AS name
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

def get_latest_event_per_door():
    """Retrieve the single most recent recorded event for each distinct door"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f'''
            SELECT e.*, COALESCE(un.name, '') AS user_name
            FROM events e
            {get_events_name_join()}
            WHERE e.id IN (
                SELECT MAX(id) FROM events GROUP BY door_id
            )
        ''')
        return [dict(row) for row in cursor.fetchall()]
