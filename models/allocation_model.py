from __future__ import annotations

from typing import Any

from db import get_conn


def create_allocation(*, user_id: int, container_id: int, volume_name: str, status: str = "active") -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO container_allocations (user_id, container_id, volume_name, status)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, container_id, volume_name, status),
        )
        conn.commit()


def release_active_allocations(*, user_id: int | None = None, container_id: int | None = None) -> None:
    if user_id is None and container_id is None:
        return

    clauses: list[str] = ["status = 'active'"]
    params: list[Any] = []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if container_id is not None:
        clauses.append("container_id = ?")
        params.append(container_id)

    where_sql = " AND ".join(clauses)
    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE container_allocations
            SET
                status = 'released',
                released_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE {where_sql}
            """,
            params,
        )
        conn.commit()
