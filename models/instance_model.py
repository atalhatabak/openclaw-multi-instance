from __future__ import annotations

from typing import Any

from db import get_conn, row_to_dict


def get_instance_by_id(instance_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
    return row_to_dict(row)


def delete_instance(instance_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM operation_logs WHERE instance_id = ?", (instance_id,))
        conn.execute("DELETE FROM instances WHERE id = ?", (instance_id,))
        conn.commit()
