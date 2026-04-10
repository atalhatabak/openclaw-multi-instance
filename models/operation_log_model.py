from __future__ import annotations

from typing import Any

from db import get_conn, row_to_dict, rows_to_dicts


def create_operation_log(
    *,
    action_type: str,
    log_file_path: str,
    status: str,
    instance_id: int | None = None,
) -> dict[str, Any]:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO operation_logs (instance_id, action_type, log_file_path, status)
            VALUES (?, ?, ?, ?)
            """,
            (instance_id, action_type, log_file_path, status),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM operation_logs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    payload = row_to_dict(row)
    if payload is None:
        raise RuntimeError("Operation log kaydi okunamadi.")
    return payload


def get_operation_log_by_id(log_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM operation_logs WHERE id = ?", (log_id,)).fetchone()
    return row_to_dict(row)


def update_operation_log_status(log_id: int, *, status: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE operation_logs
            SET status = ?
            WHERE id = ?
            """,
            (status, log_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM operation_logs WHERE id = ?", (log_id,)).fetchone()
    return row_to_dict(row)


def list_operation_logs(*, action_type: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
    sql = "SELECT * FROM operation_logs"
    params: list[Any] = []
    if action_type:
        sql += " WHERE action_type = ?"
        params.append(action_type)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(max(1, limit))
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return rows_to_dicts(rows)
