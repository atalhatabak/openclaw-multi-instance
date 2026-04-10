from __future__ import annotations

import os
import re
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional


BASE_DIR = Path(__file__).resolve().parents[1]
LOG_ROOT = Path(os.environ.get("OPENCLAW_LOG_DIR", BASE_DIR / "logs"))


SECRET_PATTERNS = [
    # env-like KEY=VALUE
    re.compile(r"(?im)^(OPENROUTER_API_KEY|TELEGRAM_BOT_TOKEN|OPENCLAW_GATEWAY_TOKEN)\s*=\s*(.+?)\s*$"),
    # cli flags: --token value / --openrouter-api-key value / etc
    re.compile(r"(?i)(--openrouter-api-key|--telegram-bot-token|--gateway-token)\s+(\S+)"),
]


def _utc_ts_for_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_log_dir(action_type: str) -> Path:
    safe = re.sub(r"[^a-z0-9_-]+", "_", action_type.lower()).strip("_") or "actions"
    p = LOG_ROOT / safe
    p.mkdir(parents=True, exist_ok=True)
    return p


def build_log_path(action_type: str, *, instance_id: Optional[int] = None) -> Path:
    d = ensure_log_dir(action_type)
    ts = _utc_ts_for_filename()
    if instance_id is None:
        name = f"{ts}.log"
    else:
        name = f"{ts}_instance_{instance_id}.log"
    return d / name


def mask_secrets(text: str) -> str:
    if not text:
        return text
    out = text
    for pat in SECRET_PATTERNS:
        def repl(m: re.Match) -> str:
            if m.lastindex == 2:
                return f"{m.group(1)} ***"
            return f"{m.group(1)}=***"

        out = pat.sub(repl, out)
    return out


@dataclass
class LogWriteResult:
    path: Path


@dataclass
class LogTailResult:
    path: Path
    content: str
    exists: bool
    truncated: bool
    size_bytes: int


def write_log(path: Path, *, header: str, stdout: str, stderr: str) -> LogWriteResult:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            header.rstrip(),
            "",
            "---- STDOUT ----",
            (stdout or "").rstrip(),
            "",
            "---- STDERR ----",
            (stderr or "").rstrip(),
            "",
        ]
    )
    path.write_text(mask_secrets(content), encoding="utf-8", errors="replace")
    return LogWriteResult(path=path)


def write_live_log_header(path: Path, *, header: str) -> LogWriteResult:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            header.rstrip(),
            "",
            "---- LIVE OUTPUT ----",
            "",
        ]
    )
    path.write_text(mask_secrets(content), encoding="utf-8", errors="replace")
    return LogWriteResult(path=path)


def append_log_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(mask_secrets(text))
        handle.flush()


def resolve_managed_log_path(raw_path: str | Path) -> Path | None:
    candidate = Path(raw_path).expanduser()
    resolved = candidate.resolve(strict=False)
    root = LOG_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def read_log_tail(path: Path, *, max_lines: int = 320, max_bytes: int = 262144) -> LogTailResult:
    if not path.exists():
        return LogTailResult(
            path=path,
            content="",
            exists=False,
            truncated=False,
            size_bytes=0,
        )

    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size_bytes = handle.tell()
        start = max(0, size_bytes - max_bytes)
        handle.seek(start)
        payload = handle.read()

    truncated = start > 0
    text = payload.decode("utf-8", errors="replace")
    if truncated:
        first_break = text.find("\n")
        text = text[first_break + 1 :] if first_break >= 0 else ""

    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        truncated = True

    return LogTailResult(
        path=path,
        content="\n".join(lines),
        exists=True,
        truncated=truncated,
        size_bytes=size_bytes,
    )


def write_exception_log(
    action_type: str,
    exc: Exception,
    *,
    context: Optional[Mapping[str, object]] = None,
    instance_id: Optional[int] = None,
) -> Path:
    header_lines = [
        f"timestamp_utc: {datetime.now(timezone.utc).isoformat()}",
        f"action_type: {action_type}",
        f"instance_id: {instance_id if instance_id is not None else ''}",
        f"exception_type: {type(exc).__name__}",
        f"exception_message: {str(exc)}",
    ]
    if context:
        for key, value in context.items():
            header_lines.append(f"{key}: {value}")

    log_path = build_log_path(action_type, instance_id=instance_id)
    write_log(
        log_path,
        header="\n".join(header_lines),
        stdout="",
        stderr="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )
    return log_path
