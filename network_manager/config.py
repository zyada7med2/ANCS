"""
Configuration constants and database initialization.

This module is responsible for:
- Defining core configuration values.
- Initializing the SQLite database connection.
- Ensuring all required tables exist.

The original schema contained simple `devices` and `configs` tables which are
still supported for full backwards compatibility with the existing GUI.
On top of that, we extend the schema with richer tables for:
users, device_configs, ai_models, tasks, logs, and training_data.
"""

import sqlite3

# Configuration constants
DB_PATH = "network_manager.db"
GNS3_DEFAULT_URL = "http://localhost:3080"

# Database initialization
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

# ---------------------------------------------------------------------------
# Base tables used by the existing application (backwards compatible)
# ---------------------------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    type TEXT,
    ip TEXT,
    port TEXT,
    connection_type TEXT,
    added_from_gns3 INTEGER DEFAULT 0,
    project_id TEXT,
    node_id TEXT,
    created_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER,
    config_name TEXT,
    content TEXT,
    created_at TEXT
)
""")


def _add_column_if_not_exists(table: str, column_def: str) -> None:
    """
    Safely add a column to an existing SQLite table.

    SQLite does not support many ALTER TABLE operations, but adding a column
    is allowed. If the column already exists, we silently ignore the error
    so that schema upgrades are idempotent.
    """
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
    except sqlite3.OperationalError as exc:
        # "duplicate column name" indicates the column is already there.
        if "duplicate column name" not in str(exc).lower():
            raise


# ---------------------------------------------------------------------------
# Smoothly extend the existing devices table with richer metadata
# ---------------------------------------------------------------------------

_add_column_if_not_exists("devices", "mac_address TEXT")
_add_column_if_not_exists("devices", "device_type TEXT")  # more explicit alias of 'type'
_add_column_if_not_exists("devices", "os_version TEXT")
_add_column_if_not_exists("devices", "status TEXT DEFAULT 'unknown'")
_add_column_if_not_exists("devices", "location TEXT")
_add_column_if_not_exists("devices", "last_seen TEXT")


# ---------------------------------------------------------------------------
# New tables inspired by the extended schema (users, tasks, logs, AI, etc.)
# ---------------------------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT UNIQUE,
    role TEXT CHECK(role IN ('admin', 'engineer')) DEFAULT 'engineer',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS device_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER,
    config_text TEXT NOT NULL,
    applied_by INTEGER,
    is_auto_generated INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE,
    FOREIGN KEY(applied_by) REFERENCES users(id) ON DELETE SET NULL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS ai_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT,
    model_type TEXT,
    accuracy REAL,
    version TEXT,
    trained_at TEXT,
    file_path TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER,
    task_type TEXT,
    status TEXT DEFAULT 'pending',
    result TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    executed_by INTEGER,
    FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE,
    FOREIGN KEY(executed_by) REFERENCES users(id) ON DELETE SET NULL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT,
    device_id INTEGER,
    details TEXT,
    severity TEXT CHECK(severity IN ('info', 'warning', 'error')) DEFAULT 'info',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE SET NULL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS training_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER,
    feature_json TEXT,
    label TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE
)
""")


# Helpful indexes for performance on common lookups / filters
cur.execute("CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_devices_ip ON devices(ip)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs(created_at)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")

conn.commit()
