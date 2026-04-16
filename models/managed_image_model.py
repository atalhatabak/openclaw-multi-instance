from __future__ import annotations

from typing import Any

from db import get_conn, row_to_dict, rows_to_dicts


def list_managed_images(*, limit: int | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT *
        FROM managed_images
        ORDER BY datetime(created_at) DESC, id DESC
    """
    params: list[Any] = []
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return rows_to_dicts(rows)


def get_managed_image_by_ref(image_ref: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM managed_images
            WHERE image_ref = ?
            """,
            (image_ref,),
        ).fetchone()
    return row_to_dict(row)


def upsert_managed_image(*, image_ref: str, version: str, version_source: str = "manual") -> dict[str, Any]:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO managed_images (image_ref, version, version_source)
            VALUES (?, ?, ?)
            ON CONFLICT(image_ref) DO UPDATE SET
                version = excluded.version,
                version_source = excluded.version_source,
                updated_at = CURRENT_TIMESTAMP
            """,
            (image_ref, version, version_source),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT *
            FROM managed_images
            WHERE image_ref = ?
            """,
            (image_ref,),
        ).fetchone()
    payload = row_to_dict(row)
    if payload is None:
        raise RuntimeError("Managed image kaydi okunamadi.")
    return payload


def delete_managed_image(image_ref: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM managed_images WHERE image_ref = ?", (image_ref,))
        conn.commit()
