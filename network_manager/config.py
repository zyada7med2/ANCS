"""
Configuration constants and database initialization
"""
import sqlite3

# Configuration constants
DB_PATH = "network_manager.db"
GNS3_DEFAULT_URL = "http://localhost:3080"

# Database initialization
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

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
conn.commit()

