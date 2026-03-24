from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("OPENCLAW_DB_PATH", BASE_DIR / "openclaw_instances.db"))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL UNIQUE,
    project_name TEXT NOT NULL UNIQUE,
    volume_name TEXT NOT NULL UNIQUE,
    gateway_port INTEGER NOT NULL UNIQUE,
    bridge_port INTEGER NOT NULL UNIQUE,
    version TEXT NOT NULL,
    gateway_bind TEXT NOT NULL DEFAULT 'lan',
    channel_choice TEXT NOT NULL DEFAULT 'telegram',
    channel_bot_token TEXT,
    allow_from TEXT,
    token TEXT NOT NULL,
    openrouter_token TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_instances_domain ON instances(domain);
CREATE INDEX IF NOT EXISTS idx_instances_gateway_port ON instances(gateway_port);
CREATE INDEX IF NOT EXISTS idx_instances_bridge_port ON instances(bridge_port);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    openrouter_api_key TEXT NOT NULL,
    openrouter_api_key2 TEXT,
    volume_name TEXT NOT NULL UNIQUE,
    gateway_token TEXT NOT NULL UNIQUE,
    gateway_url TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    volume_prepared_at DATETIME,
    last_login_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);

CREATE TABLE IF NOT EXISTS containers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER,
    project_name TEXT,
    container_name TEXT NOT NULL UNIQUE,
    docker_container_id TEXT,
    host TEXT NOT NULL DEFAULT 'mebs.claw',
    port INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'available',
    assigned_user_id INTEGER,
    assigned_volume_name TEXT,
    gateway_token TEXT,
    last_heartbeat_at DATETIME,
    last_used_at DATETIME,
    started_at DATETIME,
    stopped_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(instance_id) REFERENCES instances(id),
    FOREIGN KEY(assigned_user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_containers_status ON containers(status);
CREATE INDEX IF NOT EXISTS idx_containers_assigned_user ON containers(assigned_user_id);

CREATE TABLE IF NOT EXISTS container_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    container_id INTEGER NOT NULL,
    volume_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    released_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(container_id) REFERENCES containers(id)
);

CREATE INDEX IF NOT EXISTS idx_allocations_user_id ON container_allocations(user_id);
CREATE INDEX IF NOT EXISTS idx_allocations_container_id ON container_allocations(container_id);
CREATE INDEX IF NOT EXISTS idx_allocations_status ON container_allocations(status);

CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER,
    action_type TEXT NOT NULL,
    log_file_path TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(instance_id) REFERENCES instances(id)
);

CREATE INDEX IF NOT EXISTS idx_logs_instance_id ON operation_logs(instance_id);
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON operation_logs(created_at);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate(conn)
        conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    # Keep migrations additive/compatible (SQLite doesn't support altering constraints easily).
    if not _column_exists(conn, "instances", "domain_short"):
        conn.execute("ALTER TABLE instances ADD COLUMN domain_short TEXT")
    if not _column_exists(conn, "instances", "image"):
        conn.execute("ALTER TABLE instances ADD COLUMN image TEXT")
    if not _column_exists(conn, "instances", "current_image_id"):
        conn.execute("ALTER TABLE instances ADD COLUMN current_image_id TEXT")
    if not _column_exists(conn, "instances", "last_update_check_at"):
        conn.execute("ALTER TABLE instances ADD COLUMN last_update_check_at DATETIME")
    if not _column_exists(conn, "instances", "gateway_bind"):
        conn.execute("ALTER TABLE instances ADD COLUMN gateway_bind TEXT NOT NULL DEFAULT 'lan'")

    if _table_exists(conn, "users"):
        if not _column_exists(conn, "users", "openrouter_api_key2"):
            conn.execute("ALTER TABLE users ADD COLUMN openrouter_api_key2 TEXT")
        if not _column_exists(conn, "users", "gateway_url"):
            conn.execute("ALTER TABLE users ADD COLUMN gateway_url TEXT")
        if not _column_exists(conn, "users", "is_active"):
            conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        if not _column_exists(conn, "users", "volume_prepared_at"):
            conn.execute("ALTER TABLE users ADD COLUMN volume_prepared_at DATETIME")
        if not _column_exists(conn, "users", "last_login_at"):
            conn.execute("ALTER TABLE users ADD COLUMN last_login_at DATETIME")
        if not _column_exists(conn, "users", "updated_at"):
            conn.execute("ALTER TABLE users ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP")

    if _table_exists(conn, "containers"):
        if not _column_exists(conn, "containers", "instance_id"):
            conn.execute("ALTER TABLE containers ADD COLUMN instance_id INTEGER")
        if not _column_exists(conn, "containers", "project_name"):
            conn.execute("ALTER TABLE containers ADD COLUMN project_name TEXT")
        if not _column_exists(conn, "containers", "docker_container_id"):
            conn.execute("ALTER TABLE containers ADD COLUMN docker_container_id TEXT")
        if not _column_exists(conn, "containers", "assigned_user_id"):
            conn.execute("ALTER TABLE containers ADD COLUMN assigned_user_id INTEGER")
        if not _column_exists(conn, "containers", "assigned_volume_name"):
            conn.execute("ALTER TABLE containers ADD COLUMN assigned_volume_name TEXT")
        if not _column_exists(conn, "containers", "gateway_token"):
            conn.execute("ALTER TABLE containers ADD COLUMN gateway_token TEXT")
        if not _column_exists(conn, "containers", "last_heartbeat_at"):
            conn.execute("ALTER TABLE containers ADD COLUMN last_heartbeat_at DATETIME")
        if not _column_exists(conn, "containers", "last_used_at"):
            conn.execute("ALTER TABLE containers ADD COLUMN last_used_at DATETIME")
        if not _column_exists(conn, "containers", "started_at"):
            conn.execute("ALTER TABLE containers ADD COLUMN started_at DATETIME")
        if not _column_exists(conn, "containers", "stopped_at"):
            conn.execute("ALTER TABLE containers ADD COLUMN stopped_at DATETIME")
        if not _column_exists(conn, "containers", "updated_at"):
            conn.execute("ALTER TABLE containers ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP")

    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
        CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
        CREATE INDEX IF NOT EXISTS idx_containers_status ON containers(status);
        CREATE INDEX IF NOT EXISTS idx_containers_assigned_user ON containers(assigned_user_id);
        CREATE INDEX IF NOT EXISTS idx_allocations_user_id ON container_allocations(user_id);
        CREATE INDEX IF NOT EXISTS idx_allocations_container_id ON container_allocations(container_id);
        CREATE INDEX IF NOT EXISTS idx_allocations_status ON container_allocations(status);
        """
    )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    return dict(row) if row is not None else None
