from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from db import get_conn
from services.log_service import build_log_path, write_log


BASE_DIR = Path(__file__).resolve().parents[1]


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    log_file_path: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class AppError(RuntimeError):
    pass


def run_cmd_logged(
    cmd: list[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
    check: bool = True,
    instance_id: Optional[int] = None,
    action_type: str = "actions",
) -> CommandResult:
    # Force UTF-8 with replacement so box-drawing and colored output from
    # docker / openclaw CLI do not crash decoding on Windows consoles.
    proc = subprocess.run(
        cmd,
        cwd=str(cwd or BASE_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    header = "\n".join(
        [
            f"timestamp_utc: {datetime.now(timezone.utc).isoformat()}",
            f"cwd: {str(cwd or BASE_DIR)}",
            f"action_type: {action_type}",
            f"instance_id: {instance_id if instance_id is not None else ''}",
            f"command: {' '.join(cmd)}",
        ]
    )
    log_path = build_log_path(action_type, instance_id=instance_id)
    write_log(log_path, header=header, stdout=stdout, stderr=stderr)

    status = "success" if proc.returncode == 0 else "error"
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO operation_logs (instance_id, action_type, log_file_path, status)
                VALUES (?, ?, ?, ?)
                """,
                (instance_id, action_type, str(log_path), status),
            )
            conn.commit()
    except Exception:
        # Logging must never break the main flow.
        pass

    result = CommandResult(
        command=cmd,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        log_file_path=str(log_path),
    )

    if check and not result.ok:
        joined = " ".join(cmd)
        raise AppError(
            f"Komut başarısız: {joined}\nLog: {result.log_file_path}"
        )
    return result

