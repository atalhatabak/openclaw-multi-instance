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

    conn.executescript(
        """
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
    )


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    return dict(row) if row is not None else None

