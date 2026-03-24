from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from services.command_service import AppError, run_cmd_logged
from services.docker_service import gateway_container_name


@dataclass
class Device:
    device_id: str
    status: str
    raw: str


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _run_openclaw_cli(project_name: str, candidates: list[list[str]], *, instance_id: Optional[int] = None) -> str:
    container = gateway_container_name(project_name)
    last_output = ""
    for args in candidates:
        result = run_cmd_logged(
            ["docker", "exec", "-i", container] + args,
            check=False,
            instance_id=instance_id,
            action_type="devices",
        )
        output = (result.stdout or result.stderr or "").strip()
        if result.ok:
            return output
        last_output = output
    raise AppError(last_output or "OpenClaw device command failed.")


def list_devices(project_name: str, *, instance_id: Optional[int] = None) -> tuple[list[Device], str]:
    candidates: list[list[str]] = [
        ["openclaw", "devices", "list", "--json"],
        ["/usr/local/bin/openclaw", "devices", "list", "--json"],
    ]
    raw_output = _run_openclaw_cli(project_name, candidates, instance_id=instance_id)
    if not raw_output:
        return [], ""

    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise AppError("Cihaz listesi JSON olarak parse edilemedi.") from exc

    devices: list[Device] = []

    for entry in payload.get("pending") or []:
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

    for entry in payload.get("paired") or []:
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

    return devices, raw_output


def approve_device(project_name: str, device_id: str, *, instance_id: Optional[int] = None) -> str:
    candidates: list[list[str]] = [
        ["openclaw", "devices", "approve", device_id],
        ["/usr/local/bin/openclaw", "devices", "approve", device_id],
    ]
    out = _run_openclaw_cli(project_name, candidates, instance_id=instance_id)
    return out or "Approve command executed."


def approve_latest_device(project_name: str, *, instance_id: Optional[int] = None) -> str:
    candidates: list[list[str]] = [
        ["openclaw", "devices", "approve", "--latest"],
        ["/usr/local/bin/openclaw", "devices", "approve", "--latest"],
    ]
    out = _run_openclaw_cli(project_name, candidates, instance_id=instance_id)
    return out or "Latest approve command executed."
