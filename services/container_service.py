from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from models import allocation_model, container_model
from services.command_service import run_cmd_logged
from services.user_service import mark_user_volume_prepared

DEFAULT_CONTAINER_HOST = os.environ.get("OPENCLAW_GATEWAY_HOST", "mebs.claw")
CONTAINER_NAME_PREFIX = os.environ.get("OPENCLAW_DYNAMIC_CONTAINER_PREFIX", "openclaw-dynamic")
CONTAINER_PORT_BASE = int(os.environ.get("OPENCLAW_CONTAINER_PORT_BASE", "20000"))
CONTAINER_PORT_STEP = int(os.environ.get("OPENCLAW_CONTAINER_PORT_STEP", "1"))


@dataclass
class ContainerAssignment:
    container: dict[str, Any]
    source: str
    volume_ready: bool


def ensure_user_volume(user: dict[str, Any]) -> bool:
    volume_name = str(user["volume_name"])
    try:
        inspect_result = run_cmd_logged(
            ["docker", "volume", "inspect", volume_name],
            check=False,
            action_type="volume-prepare",
        )
    except Exception:
        return False
    if inspect_result.ok:
        mark_user_volume_prepared(int(user["id"]))
        return True

    try:
        create_result = run_cmd_logged(
            ["docker", "volume", "create", volume_name],
            check=False,
            action_type="volume-prepare",
        )
    except Exception:
        return False
    if create_result.ok:
        mark_user_volume_prepared(int(user["id"]))
        return True
    return False


def assign_container_to_user(user: dict[str, Any]) -> ContainerAssignment:
    volume_ready = ensure_user_volume(user)
    existing = container_model.get_assigned_container_for_user(int(user["id"]))
    if existing and existing.get("status") in container_model.USABLE_CONTAINER_STATUSES:
        container_model.touch_container(int(existing["id"]), status="assigned")
        refreshed = container_model.get_container_by_id(int(existing["id"])) or existing
        return ContainerAssignment(container=refreshed, source="existing", volume_ready=volume_ready)

    container_model.release_containers_for_user(int(user["id"]))
    allocation_model.release_active_allocations(user_id=int(user["id"]))

    reusable = container_model.find_reusable_container()
    if reusable is not None:
        prepared = _assign_existing_container(reusable, user)
        return ContainerAssignment(container=prepared, source="reused", volume_ready=volume_ready)

    created = _provision_new_container(user)
    return ContainerAssignment(container=created, source="provisioned", volume_ready=volume_ready)


def _assign_existing_container(container: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    status = _ensure_container_running(container)
    container_model.assign_container(
        int(container["id"]),
        user_id=int(user["id"]),
        volume_name=str(user["volume_name"]),
        status=status,
    )
    allocation_model.release_active_allocations(container_id=int(container["id"]))
    allocation_model.create_allocation(
        user_id=int(user["id"]),
        container_id=int(container["id"]),
        volume_name=str(user["volume_name"]),
    )
    return container_model.get_container_by_id(int(container["id"])) or container


def _provision_new_container(user: dict[str, Any]) -> dict[str, Any]:
    port = container_model.next_container_port(
        base_port=CONTAINER_PORT_BASE,
        step=CONTAINER_PORT_STEP,
    )
    container = container_model.create_container(
        container_name=f"{CONTAINER_NAME_PREFIX}-{port}",
        host=DEFAULT_CONTAINER_HOST,
        port=port,
        status="starting",
        assigned_user_id=int(user["id"]),
        assigned_volume_name=str(user["volume_name"]),
    )
    _provision_container_placeholder(container, user)
    container_model.touch_container(int(container["id"]), status="assigned")
    allocation_model.create_allocation(
        user_id=int(user["id"]),
        container_id=int(container["id"]),
        volume_name=str(user["volume_name"]),
    )
    return container_model.get_container_by_id(int(container["id"])) or container


def _ensure_container_running(container: dict[str, Any]) -> str:
    status = str(container.get("status") or "available")
    if status == "stopped":
        _start_container_placeholder(container)
        return "assigned"
    if status in {"available", "running", "assigned", "starting"}:
        return "assigned"
    return "starting"


def _start_container_placeholder(container: dict[str, Any]) -> None:
    container_model.touch_container(int(container["id"]), status="starting")
    container_model.touch_container(int(container["id"]), status="running")


def _provision_container_placeholder(container: dict[str, Any], user: dict[str, Any]) -> None:
    _ = (container, user)
    container_model.touch_container(int(container["id"]), status="running")
