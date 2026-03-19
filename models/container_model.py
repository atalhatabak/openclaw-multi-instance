from __future__ import annotations

from typing import Any

from db import get_conn, row_to_dict, rows_to_dicts


USABLE_CONTAINER_STATUSES = ("assigned", "running", "starting")
REUSABLE_CONTAINER_STATUSES = ("available", "stopped", "running")


def list_containers() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                c.*,
                u.username AS assigned_username
            FROM containers c
            LEFT JOIN users u ON u.id = c.assigned_user_id
            ORDER BY c.created_at DESC, c.id DESC
            """
        ).fetchall()
    return rows_to_dicts(rows)


def get_container_by_id(container_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM containers WHERE id = ?", (container_id,)).fetchone()
    return row_to_dict(row)


def get_assigned_container_for_user(user_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM containers
            WHERE assigned_user_id = ?
            ORDER BY
                CASE WHEN status IN ('assigned', 'running', 'starting') THEN 0 ELSE 1 END,
                updated_at DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    return row_to_dict(row)


def find_reusable_container() -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM containers
            WHERE assigned_user_id IS NULL
              AND status IN ('available', 'stopped', 'running')
            ORDER BY
                CASE status
                    WHEN 'running' THEN 0
                    WHEN 'available' THEN 1
                    WHEN 'stopped' THEN 2
                    ELSE 9
                END,
                COALESCE(last_used_at, created_at) ASC,
                id ASC
            LIMIT 1
            """
        ).fetchone()
    return row_to_dict(row)


def release_containers_for_user(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE containers
            SET
                assigned_user_id = NULL,
                assigned_volume_name = NULL,
                status = CASE
                    WHEN status = 'error' THEN 'error'
                    ELSE 'available'
                END,
                updated_at = CURRENT_TIMESTAMP,
                last_used_at = CURRENT_TIMESTAMP,
                stopped_at = CASE
                    WHEN status = 'error' THEN stopped_at
                    ELSE stopped_at
                END
            WHERE assigned_user_id = ?
            """,
            (user_id,),
        )
        conn.commit()


def assign_container(container_id: int, *, user_id: int, volume_name: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE containers
            SET
                assigned_user_id = ?,
                assigned_volume_name = ?,
                status = ?,
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                stopped_at = NULL,
                last_heartbeat_at = CURRENT_TIMESTAMP,
                last_used_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (user_id, volume_name, status, container_id),
        )
        conn.commit()


def touch_container(container_id: int, *, status: str | None = None) -> None:
    updates = ["last_heartbeat_at = CURRENT_TIMESTAMP", "last_used_at = CURRENT_TIMESTAMP", "updated_at = CURRENT_TIMESTAMP"]
    params: list[Any] = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
        if status == "stopped":
            updates.append("stopped_at = CURRENT_TIMESTAMP")
        elif status in {"assigned", "running", "starting"}:
            updates.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
            updates.append("stopped_at = NULL")
    params.append(container_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE containers SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()


def create_container(
    *,
    container_name: str,
    host: str,
    port: int,
    status: str,
    assigned_user_id: int | None = None,
    assigned_volume_name: str | None = None,
) -> dict[str, Any]:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO containers (
                container_name,
                host,
                port,
                status,
                assigned_user_id,
                assigned_volume_name,
                started_at,
                last_heartbeat_at,
                last_used_at
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                container_name,
                host,
                port,
                status,
                assigned_user_id,
                assigned_volume_name,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM containers WHERE id = ?", (cursor.lastrowid,)).fetchone()
    if row is None:
        raise RuntimeError("Container kaydı okunamadı.")
    return dict(row)


def next_container_port(*, base_port: int, step: int) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(port) AS max_port FROM containers").fetchone()
    max_port = row["max_port"] if row is not None else None
    if max_port is None:
        return base_port
    return int(max_port) + step
