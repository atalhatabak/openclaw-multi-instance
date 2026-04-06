from __future__ import annotations

from typing import Any

from db import (
    DEFAULT_CURRENT_IMAGE_REF,
    DEFAULT_CURRENT_IMAGE_VERSION,
    get_conn,
    row_to_dict,
)


def get_system_settings() -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM system_settings WHERE id = 1").fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO system_settings (id, current_image_ref, current_image_version)
                VALUES (1, ?, ?)
                """,
                (DEFAULT_CURRENT_IMAGE_REF, DEFAULT_CURRENT_IMAGE_VERSION),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM system_settings WHERE id = 1").fetchone()
    payload = row_to_dict(row)
    if payload is None:
        raise RuntimeError("System settings kaydi okunamadi.")
    return payload


def update_current_image(*, image_ref: str | None = None, image_version: str | None = None) -> dict[str, Any]:
    updates = ["updated_at = CURRENT_TIMESTAMP"]
    params: list[Any] = []
    if image_ref is not None:
        updates.append("current_image_ref = ?")
        params.append(image_ref)
    if image_version is not None:
        updates.append("current_image_version = ?")
        params.append(image_version)
    params.append(1)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE system_settings SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM system_settings WHERE id = 1").fetchone()
    payload = row_to_dict(row)
    if payload is None:
        raise RuntimeError("System settings kaydi okunamadi.")
    return payload
