#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import db
from db import get_conn
from models import container_model, instance_model, operation_log_model
from services.docker_service import gateway_container_name
from services.version_service import get_current_image_state, normalize_version


DEFAULT_CONTAINER_HOST = os.environ.get("OPENCLAW_GATEWAY_HOST", "mebs.claw")


def _json_print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _inspect_container(container_name: str) -> tuple[str | None, str | None]:
    try:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{.Id}}|{{.State.Status}}", container_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None, None

    if proc.returncode != 0:
        return None, None

    payload = (proc.stdout or "").strip()
    if not payload:
        return None, None
    if "|" not in payload:
        return payload, None
    docker_container_id, raw_status = payload.split("|", 1)
    return docker_container_id.strip() or None, raw_status.strip() or None


def _map_docker_status(raw_status: str | None) -> str:
    normalized = (raw_status or "").strip().lower()
    if normalized == "running":
        return "running"
    if normalized in {"created", "restarting"}:
        return "starting"
    if normalized in {"exited", "dead", "paused"}:
        return "stopped"
    return "error"


def _resolve_container_status(raw_status: str | None, *, assigned_user_id: int | None) -> str:
    mapped = _map_docker_status(raw_status)
    if assigned_user_id is not None and mapped == "running":
        return "assigned"
    return mapped


def cmd_record_log(args: argparse.Namespace) -> None:
    db.init_db()
    entry = operation_log_model.create_operation_log(
        action_type=args.action_type,
        log_file_path=args.log_file_path,
        status=args.status,
        instance_id=args.instance_id,
    )
    _json_print({"status": "ok", "operation_log": entry})


def cmd_sync_instance_container(args: argparse.Namespace) -> None:
    db.init_db()

    instance = instance_model.get_instance_by_id(args.instance_id)
    if instance is None:
        raise SystemExit(f"Instance not found: {args.instance_id}")

    current_image = get_current_image_state()
    image_ref = str(instance.get("image") or current_image.image_ref).strip()
    image_version = normalize_version(instance.get("version"), fallback=current_image.version)
    project_name = str(instance["project_name"])
    container_name = gateway_container_name(project_name)
    docker_container_id, raw_status = _inspect_container(container_name)

    existing = container_model.get_container_by_instance_id(args.instance_id)
    assigned_user_id = int(existing["assigned_user_id"]) if existing and existing.get("assigned_user_id") else None
    next_status = _resolve_container_status(raw_status, assigned_user_id=assigned_user_id)

    if existing is None:
        container = container_model.create_container(
            instance_id=int(instance["id"]),
            project_name=project_name,
            container_name=container_name,
            docker_container_id=docker_container_id,
            image_ref=image_ref,
            image_version=image_version,
            host=DEFAULT_CONTAINER_HOST,
            port=int(instance["gateway_port"]),
            status=next_status,
            assigned_user_id=None,
            assigned_volume_name=str(instance["volume_name"]),
            gateway_token=str(instance["token"]),
        )
        _json_print({"status": "ok", "container": container, "created": True})
        return

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE containers
            SET
                instance_id = ?,
                project_name = ?,
                container_name = ?,
                host = ?,
                port = ?,
                gateway_token = ?,
                assigned_volume_name = COALESCE(assigned_volume_name, ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(instance["id"]),
                project_name,
                container_name,
                DEFAULT_CONTAINER_HOST,
                int(instance["gateway_port"]),
                str(instance["token"]),
                str(instance["volume_name"]),
                int(existing["id"]),
            ),
        )
        conn.commit()

    container_model.update_container_runtime(
        int(existing["id"]),
        status=next_status,
        docker_container_id=docker_container_id,
        image_ref=image_ref,
        image_version=image_version,
    )
    refreshed = container_model.get_container_by_id(int(existing["id"])) or existing
    _json_print({"status": "ok", "container": refreshed, "created": False})


def cmd_purge_instance_records(args: argparse.Namespace) -> None:
    db.init_db()

    with get_conn() as conn:
        container_rows = conn.execute(
            "SELECT id FROM containers WHERE instance_id = ?",
            (args.instance_id,),
        ).fetchall()
        for row in container_rows:
            conn.execute("DELETE FROM container_allocations WHERE container_id = ?", (int(row["id"]),))
        conn.execute("DELETE FROM containers WHERE instance_id = ?", (args.instance_id,))
        conn.execute("DELETE FROM operation_logs WHERE instance_id = ?", (args.instance_id,))
        conn.execute("DELETE FROM instances WHERE id = ?", (args.instance_id,))
        conn.commit()

    _json_print({"status": "ok", "instance_id": args.instance_id, "purged": True})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync manual deploy/update operations into the web app database tables."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record-log", help="Insert a manual operation log row.")
    record.add_argument("--action-type", required=True)
    record.add_argument("--log-file-path", required=True)
    record.add_argument("--status", required=True, choices=("running", "success", "error"))
    record.add_argument("--instance-id", type=int)
    record.set_defaults(func=cmd_record_log)

    sync = sub.add_parser("sync-instance-container", help="Create or refresh the container row for an instance.")
    sync.add_argument("--instance-id", required=True, type=int)
    sync.set_defaults(func=cmd_sync_instance_container)

    purge = sub.add_parser("purge-instance-records", help="Remove instance/container/log rows for a failed manual deploy.")
    purge.add_argument("--instance-id", required=True, type=int)
    purge.set_defaults(func=cmd_purge_instance_records)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
