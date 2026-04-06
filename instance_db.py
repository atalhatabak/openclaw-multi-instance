#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
from typing import Any, Dict, Optional

DEFAULT_DB_PATH = os.environ.get("OPENCLAW_DB_PATH", "./openclaw_instances.db")
DEFAULT_CURRENT_IMAGE_REF = os.environ.get("OPENCLAW_IMAGE", "xenv1-openclaw:latest")
DEFAULT_CURRENT_IMAGE_VERSION = os.environ.get("OPENCLAW_CURRENT_IMAGE_VERSION", "2026.4.3")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL UNIQUE,
    domain_short TEXT,
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
    image TEXT,
    current_image_id TEXT,
    last_update_check_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_instances_domain ON instances(domain);
CREATE INDEX IF NOT EXISTS idx_instances_gateway_port ON instances(gateway_port);
CREATE INDEX IF NOT EXISTS idx_instances_bridge_port ON instances(bridge_port);

CREATE TABLE IF NOT EXISTS system_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_image_ref TEXT NOT NULL,
    current_image_version TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER,
    action_type TEXT NOT NULL,
    log_file_path TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logs_instance_id ON operation_logs(instance_id);
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON operation_logs(created_at);
"""

SELECT_FIELDS = """
id,
domain,
domain_short,
project_name,
volume_name,
gateway_port,
bridge_port,
version,
gateway_bind,
channel_choice,
channel_bot_token,
allow_from,
token,
openrouter_token,
image,
current_image_id,
last_update_check_at,
created_at
"""


def fail(message: str, code: int = 1) -> None:
    print(json.dumps({"status": "error", "message": message}, ensure_ascii=False), file=sys.stderr)
    sys.exit(code)


def ok(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def init_db(db_path: str) -> None:
    conn = get_conn(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
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
        conn.execute(
            """
            INSERT OR IGNORE INTO system_settings (id, current_image_ref, current_image_version)
            VALUES (1, ?, ?)
            """,
            (DEFAULT_CURRENT_IMAGE_REF, DEFAULT_CURRENT_IMAGE_VERSION),
        )
        conn.execute(
            """
            UPDATE system_settings
            SET
                current_image_ref = ?,
                current_image_version = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
              AND (
                current_image_ref IS NULL OR trim(current_image_ref) = ''
                OR current_image_version IS NULL OR trim(current_image_version) = ''
                OR lower(trim(current_image_version)) = 'latest'
              )
            """,
            (DEFAULT_CURRENT_IMAGE_REF, DEFAULT_CURRENT_IMAGE_VERSION),
        )
        conn.execute(
            """
            UPDATE instances
            SET version = ?
            WHERE version IS NULL
               OR trim(version) = ''
               OR lower(trim(version)) = 'latest'
            """,
            (DEFAULT_CURRENT_IMAGE_VERSION,),
        )
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def get_instance(conn: sqlite3.Connection, instance_id: Optional[int], domain: Optional[str]):
    if instance_id is not None:
        return conn.execute(
            f"SELECT {SELECT_FIELDS} FROM instances WHERE id = ?",
            (instance_id,),
        ).fetchone()

    if domain:
        return conn.execute(
            f"SELECT {SELECT_FIELDS} FROM instances WHERE domain = ?",
            (domain,),
        ).fetchone()

    return None


def cmd_init(args: argparse.Namespace) -> None:
    init_db(args.db)
    ok({"status": "ok", "message": "database initialized", "db": args.db})


def cmd_add(args: argparse.Namespace) -> None:
    conn = get_conn(args.db)
    try:
        cur = conn.execute(
            """
            INSERT INTO instances (
                domain,
                domain_short,
                project_name,
                volume_name,
                gateway_port,
                bridge_port,
                version,
                gateway_bind,
                channel_choice,
                channel_bot_token,
                allow_from,
                token,
                openrouter_token,
                image
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                args.domain,
                args.domain_short,
                args.project_name,
                args.volume_name,
                args.gateway_port,
                args.bridge_port,
                args.version,
                args.gateway_bind,
                args.channel_choice,
                args.channel_bot_token,
                args.allow_from,
                args.token,
                args.openrouter_token,
                args.image,
            ),
        )
        conn.commit()

        row = conn.execute(
            f"SELECT {SELECT_FIELDS} FROM instances WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()

        ok({"status": "ok", "instance": row_to_dict(row)})
    except sqlite3.IntegrityError as exc:
        fail(f"integrity error: {exc}")
    finally:
        conn.close()


def cmd_list(args: argparse.Namespace) -> None:
    conn = get_conn(args.db)
    try:
        rows = conn.execute(
            f"SELECT {SELECT_FIELDS} FROM instances ORDER BY id ASC"
        ).fetchall()

        ok({
            "status": "ok",
            "count": len(rows),
            "instances": [row_to_dict(r) for r in rows]
        })
    finally:
        conn.close()


def cmd_get(args: argparse.Namespace) -> None:
    conn = get_conn(args.db)
    try:
        row = get_instance(conn, args.id, args.domain)
        if row is None:
            fail("instance not found", 2)
        ok({"status": "ok", "instance": row_to_dict(row)})
    finally:
        conn.close()


def cmd_delete(args: argparse.Namespace) -> None:
    conn = get_conn(args.db)
    try:
        row = get_instance(conn, args.id, args.domain)
        if row is None:
            fail("instance not found", 2)

        conn.execute("DELETE FROM instances WHERE id = ?", (row["id"],))
        conn.commit()

        ok({"status": "ok", "deleted": row_to_dict(row)})
    finally:
        conn.close()


def cmd_available_port(args: argparse.Namespace) -> None:
    conn = get_conn(args.db)
    try:
        row = conn.execute(
            """
            SELECT
                MAX(gateway_port) AS max_gateway_port,
                MAX(bridge_port) AS max_bridge_port
            FROM instances
            """
        ).fetchone()

        max_gateway = row["max_gateway_port"]
        max_bridge = row["max_bridge_port"]

        next_gateway = args.base_gateway if max_gateway is None else max_gateway + args.step
        next_bridge = (args.base_gateway + 1) if max_bridge is None else max_bridge + args.step

        ok({
            "status": "ok",
            "gateway_port": next_gateway,
            "bridge_port": next_bridge
        })
    finally:
        conn.close()


def cmd_update_runtime(args: argparse.Namespace) -> None:
    conn = get_conn(args.db)
    try:
        row = get_instance(conn, args.id, None)
        if row is None:
            fail("instance not found", 2)

        conn.execute(
            """
            UPDATE instances
            SET version = ?, image = ?, last_update_check_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (args.version, args.image, args.id),
        )
        conn.commit()

        updated = get_instance(conn, args.id, None)
        ok({"status": "ok", "instance": row_to_dict(updated)})
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenClaw instance database manager")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite db path")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add")
    p.add_argument("--domain", required=True)
    p.add_argument("--domain-short", dest="domain_short", default="")
    p.add_argument("--project-name", dest="project_name", required=True)
    p.add_argument("--volume-name", dest="volume_name", required=True)
    p.add_argument("--gateway-port", dest="gateway_port", required=True, type=int)
    p.add_argument("--bridge-port", dest="bridge_port", required=True, type=int)
    p.add_argument("--version", required=True)
    p.add_argument("--gateway-bind", dest="gateway_bind", default="lan")
    p.add_argument("--channel-choice", dest="channel_choice", default="telegram")
    p.add_argument("--channel-bot-token", dest="channel_bot_token", default="")
    p.add_argument("--allow-from", dest="allow_from", default="")
    p.add_argument("--token", required=True)
    p.add_argument("--openrouter-token", dest="openrouter_token", required=True)
    p.add_argument("--image", default="")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("get")
    p.add_argument("--id", type=int)
    p.add_argument("--domain")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("delete")
    p.add_argument("--id", type=int)
    p.add_argument("--domain")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("available_port")
    p.add_argument("--base-gateway", type=int, default=20000)
    p.add_argument("--step", type=int, default=2)
    p.set_defaults(func=cmd_available_port)

    p = sub.add_parser("update_runtime")
    p.add_argument("--id", required=True, type=int)
    p.add_argument("--version", required=True)
    p.add_argument("--image", required=True)
    p.set_defaults(func=cmd_update_runtime)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    init_db(args.db)
    args.func(args)


if __name__ == "__main__":
    main()
