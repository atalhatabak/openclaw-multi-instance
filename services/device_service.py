from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from services.command_service import AppError, run_cmd_logged
from services.docker_service import gateway_container_name


@dataclass
class Device:
    request_id: str
    device_id: str
    status: str
    timestamp_ms: int | None
    raw: str


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
                request_id=req_id,
                device_id=req_id,
                status="pending",
                timestamp_ms=_safe_int(entry.get("ts")),
                raw=json.dumps(entry, ensure_ascii=False),
            )
        )

    for entry in payload.get("paired") or []:
        dev_id = _safe_str(entry.get("deviceId"))
        if not dev_id:
            continue
        devices.append(
            Device(
                request_id="",
                device_id=dev_id,
                status="paired",
                timestamp_ms=_safe_int(entry.get("approvedAtMs") or entry.get("createdAtMs")),
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
    devices, _ = list_devices(project_name, instance_id=instance_id)
    pending_requests = [device for device in devices if device.status == "pending" and device.request_id]
    if not pending_requests:
        raise AppError("Bekleyen cihaz istegi bulunamadi.")

    selected_request = max(
        pending_requests,
        key=lambda device: device.timestamp_ms if device.timestamp_ms is not None else -1,
    )
    out = approve_device(project_name, selected_request.request_id, instance_id=instance_id)
    return out or f"Approved pending request: {selected_request.request_id}"
