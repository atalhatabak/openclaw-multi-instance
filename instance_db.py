#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
from typing import Any, Dict, Optional

DEFAULT_DB_PATH = os.environ.get("OPENCLAW_DB_PATH", "./openclaw_instances.db")

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

SELECT_FIELDS = """
id,
domain,
project_name,
volume_name,
gateway_port,
bridge_port,
version,
channel_choice,
channel_bot_token,
allow_from,
token,
openrouter_token,
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


def init_db(db_path: str) -> None:
    conn = get_conn(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
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
                project_name,
                volume_name,
                gateway_port,
                bridge_port,
                version,
                channel_choice,
                channel_bot_token,
                allow_from,
                token,
                openrouter_token
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                args.domain,
                args.project_name,
                args.volume_name,
                args.gateway_port,
                args.bridge_port,
                args.version,
                args.channel_choice,
                args.channel_bot_token,
                args.allow_from,
                args.token,
                args.openrouter_token,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenClaw instance database manager")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite db path")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add")
    p.add_argument("--domain", required=True)
    p.add_argument("--project-name", dest="project_name", required=True)
    p.add_argument("--volume-name", dest="volume_name", required=True)
    p.add_argument("--gateway-port", dest="gateway_port", required=True, type=int)
    p.add_argument("--bridge-port", dest="bridge_port", required=True, type=int)
    p.add_argument("--version", required=True)
    p.add_argument("--channel-choice", dest="channel_choice", default="telegram")
    p.add_argument("--channel-bot-token", dest="channel_bot_token", default="")
    p.add_argument("--allow-from", dest="allow_from", default="")
    p.add_argument("--token", required=True)
    p.add_argument("--openrouter-token", dest="openrouter_token", required=True)
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

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    init_db(args.db)
    args.func(args)


if __name__ == "__main__":
    main()