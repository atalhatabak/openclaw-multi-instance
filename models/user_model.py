from __future__ import annotations

import sqlite3
from typing import Any

from db import get_conn, row_to_dict, rows_to_dicts


def create_user(
    *,
    username: str,
    password_hash: str,
    openrouter_api_key: str,
    volume_name: str,
    gateway_token: str,
    openrouter_api_key2: str | None = None,
    gateway_url: str | None = None,
) -> dict[str, Any]:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (
                username,
                password_hash,
                openrouter_api_key,
                openrouter_api_key2,
                volume_name,
                gateway_token,
                gateway_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                password_hash,
                openrouter_api_key,
                openrouter_api_key2,
                volume_name,
                gateway_token,
                gateway_url,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    if row is None:
        raise RuntimeError("User kaydı okunamadı.")
    return dict(row)


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return row_to_dict(row)


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(username) = lower(?)",
            (username,),
        ).fetchone()
    return row_to_dict(row)


def list_users() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                u.*,
                c.id AS container_id,
                c.container_name,
                c.host AS container_host,
                c.port AS container_port,
                c.status AS container_status
            FROM users u
            LEFT JOIN containers c ON c.assigned_user_id = u.id
            ORDER BY u.created_at DESC, u.id DESC
            """
        ).fetchall()
    return rows_to_dicts(rows)


def update_user_runtime(
    user_id: int,
    *,
    gateway_url: str | None = None,
    volume_prepared: bool = False,
    last_login: bool = False,
) -> None:
    updates: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
    params: list[Any] = []
    if gateway_url is not None:
        updates.append("gateway_url = ?")
        params.append(gateway_url)
    if volume_prepared:
        updates.append("volume_prepared_at = CURRENT_TIMESTAMP")
    if last_login:
        updates.append("last_login_at = CURRENT_TIMESTAMP")
    params.append(user_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()


def update_user_provisioning(
    user_id: int,
    *,
    volume_name: str | None = None,
    gateway_token: str | None = None,
) -> None:
    updates: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
    params: list[Any] = []
    if volume_name is not None:
        updates.append("volume_name = ?")
        params.append(volume_name)
    if gateway_token is not None:
        updates.append("gateway_token = ?")
        params.append(gateway_token)
    params.append(user_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()


def update_user_account(
    user_id: int,
    *,
    password_hash: str | None = None,
    openrouter_api_key: str | None = None,
    openrouter_api_key2: str | None = None,
) -> None:
    updates: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
    params: list[Any] = []
    if password_hash is not None:
        updates.append("password_hash = ?")
        params.append(password_hash)
    if openrouter_api_key is not None:
        updates.append("openrouter_api_key = ?")
        params.append(openrouter_api_key)
    if openrouter_api_key2 is not None:
        updates.append("openrouter_api_key2 = ?")
        params.append(openrouter_api_key2)
    params.append(user_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()


def deactivate_user(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE users
            SET is_active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (user_id,),
        )
        conn.commit()


def delete_user_with_related_rows(user_id: int) -> None:
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
                last_used_at = CURRENT_TIMESTAMP
            WHERE assigned_user_id = ?
            """,
            (user_id,),
        )
        conn.execute("DELETE FROM container_allocations WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


def is_username_taken(username: str) -> bool:
    return get_user_by_username(username) is not None


def is_unique_violation(exc: Exception) -> bool:
    return isinstance(exc, sqlite3.IntegrityError) and "unique" in str(exc).lower()
