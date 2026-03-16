from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from services.docker_service import exec_openclaw_cli


@dataclass
class Device:
    device_id: str  # requestId for pending, deviceId for paired
    status: str  # "pending" | "paired"
    raw: str


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def list_devices(project_name: str, *, instance_id: Optional[int] = None) -> tuple[list[Device], str]:
    """
    Use OpenClaw's JSON output for stable parsing.
    """
    candidates: list[list[str]] = [
        ["openclaw", "devices", "list", "--json"],
        ["/usr/local/bin/openclaw", "devices", "list", "--json"],
    ]
    last = ""
    payload: dict[str, Any] = {}
    for args in candidates:
        last = exec_openclaw_cli(project_name, args, instance_id=instance_id)
        if not last:
            continue
        try:
            payload = json.loads(last)
            break
        except json.JSONDecodeError:
            continue

    devices: list[Device] = []

    pending_list = payload.get("pending") or []
    for entry in pending_list:
        req_id = _safe_str(entry.get("requestId"))
        if not req_id:
            continue
        devices.append(
            Device(
                device_id=req_id,
                status="pending",
                raw=json.dumps(entry, ensure_ascii=False),
            )
        )

    paired_list = payload.get("paired") or []
    for entry in paired_list:
        dev_id = _safe_str(entry.get("deviceId"))
        if not dev_id:
            continue
        devices.append(
            Device(
                device_id=dev_id,
                status="paired",
                raw=json.dumps(entry, ensure_ascii=False),
            )
        )

    return devices, last or json.dumps(payload, ensure_ascii=False)


def approve_device(project_name: str, device_id: str, *, instance_id: Optional[int] = None) -> str:
    candidates: list[list[str]] = [
        ["openclaw", "devices", "approve", device_id],
        ["/usr/local/bin/openclaw", "devices", "approve", device_id],
    ]
    out = ""
    for args in candidates:
        out = exec_openclaw_cli(project_name, args, instance_id=instance_id)
        if out:
            break
    return out or "Approve command executed."

