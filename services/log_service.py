from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


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

