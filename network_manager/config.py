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
import threading
import sys
import os

# When running as PyInstaller exe, use exe directory for DB/config
_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()

# Configuration constants
DB_PATH = os.path.join(_BASE_DIR, "network_manager.db")
GNS3_DEFAULT_URL = "http://localhost:3080"
CONFIG_FILE = os.path.join(_BASE_DIR, "ancs_config.json")

# Thread lock — acquire before every cur.execute / conn.commit from any thread.
db_lock = threading.Lock()

# Stores any startup error so the GUI can surface it as a dialog.
_db_error: str | None = None

# ---------------------------------------------------------------------------
# Safe initialization — a locked / corrupt / missing DB must never crash the
# import chain and prevent the window from opening.
# ---------------------------------------------------------------------------

class _DummyCursor:
    """No-op cursor used when the real DB is unavailable."""
    def execute(self, *a, **kw): pass
    def fetchone(self): return None
    def fetchall(self): return []


class _DummyConn:
    """No-op connection used when the real DB is unavailable."""
    def commit(self): pass
    def execute(self, *a, **kw): pass
    def cursor(self): return _DummyCursor()


conn: sqlite3.Connection = _DummyConn()   # type: ignore[assignment]
cur:  sqlite3.Cursor     = _DummyCursor() # type: ignore[assignment]

try:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    # WAL mode lets readers and a single writer coexist without blocking each
    # other, which significantly reduces "database is locked" errors when
    # background threads write concurrently with the main UI thread.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    # -----------------------------------------------------------------------
    # Base tables used by the existing application (backwards compatible)
    # -----------------------------------------------------------------------

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
        device_id INTEGER NOT NULL,
        config_name TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT,
        FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE
    )
    """)

    def _add_column_if_not_exists(table: str, column_def: str) -> None:
        """
        Safely add a column to an existing SQLite table.

        SQLite does not support many ALTER TABLE operations, but adding a column
        is allowed. If the column already exists, we silently ignore the error
        so that schema upgrades are idempotent.

        Only call this with hard-coded (non-user-supplied) table and column names.
        """
        _ALLOWED_TABLES = {"devices", "configs", "users", "device_configs",
                           "ai_models", "tasks", "logs", "training_data",
                           "credentials", "api_keys"}
        if table not in _ALLOWED_TABLES:
            raise ValueError(f"_add_column_if_not_exists: unknown table '{table}'")
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise

    # -----------------------------------------------------------------------
    # Smoothly extend the existing devices table with richer metadata
    # -----------------------------------------------------------------------

    _add_column_if_not_exists("devices", "mac_address TEXT")
    _add_column_if_not_exists("devices", "device_type TEXT")
    _add_column_if_not_exists("devices", "os_version TEXT")
    _add_column_if_not_exists("devices", "status TEXT DEFAULT 'unknown'")
    _add_column_if_not_exists("devices", "location TEXT")
    _add_column_if_not_exists("devices", "last_seen TEXT")
    # SHA-256 hash of the last successfully deployed config — used by Deploy All
    # to detect whether the config changed since the last send.
    _add_column_if_not_exists("devices", "deployed_config_hash TEXT DEFAULT ''")
    # Vendor OS (cisco_ios, huawei_vrp, etc.) — used by multi-vendor abstraction layer
    _add_column_if_not_exists("devices", "vendor_id TEXT DEFAULT 'cisco_ios'")

    # -----------------------------------------------------------------------
    # New tables
    # -----------------------------------------------------------------------

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_name TEXT UNIQUE NOT NULL,
        host TEXT DEFAULT '',
        port TEXT DEFAULT '',
        username TEXT DEFAULT '',
        password TEXT DEFAULT '',
        enable_password TEXT DEFAULT '',
        protocol TEXT DEFAULT 'telnet',
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Dedicated table for API keys — keeps secrets out of the audit log.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key_name TEXT UNIQUE NOT NULL,
        key_value TEXT NOT NULL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Dedicated table for global configuration backups / snapshots
    cur.execute("""
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_name TEXT NOT NULL,
        config_text TEXT NOT NULL,
        project_id TEXT,
        is_blank INTEGER DEFAULT 0,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Indexes for performance on common lookups / filters
    cur.execute("CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_devices_ip ON devices(ip)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")

    conn.commit()

except sqlite3.Error as exc:
    _db_error = str(exc)
    # Leave conn/cur as the no-op stubs so the rest of the app can import
    # safely and the GUI can surface the error in a dialog.
