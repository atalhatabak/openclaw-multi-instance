from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from db import get_conn, row_to_dict
from models import allocation_model, container_model
from services.command_service import AppError, run_cmd_logged
from services.user_service import mark_user_volume_prepared, sync_user_provisioning
from services.version_service import get_current_image_state, normalize_version, resolve_image_state

DEFAULT_CONTAINER_HOST = os.environ.get("OPENCLAW_GATEWAY_HOST", "mebs.claw")
DEPLOY_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "deploy_openclaw.sh"
GATEWAY_READY_HOST = os.environ.get("OPENCLAW_GATEWAY_READY_HOST", "127.0.0.1")
GATEWAY_READY_TIMEOUT_SECONDS = float(os.environ.get("OPENCLAW_GATEWAY_READY_TIMEOUT_SECONDS", "45"))
GATEWAY_READY_POLL_INTERVAL_SECONDS = float(os.environ.get("OPENCLAW_GATEWAY_READY_POLL_INTERVAL_SECONDS", "1"))
GATEWAY_READY_ENDPOINTS = ("/readyz", "/ready", "/healthz", "/health")


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
    volume_ready = bool(user.get("volume_prepared_at"))
    existing = container_model.get_assigned_container_for_user(int(user["id"]))
    if existing is None:
        created = provision_container_for_user(user)
        return ContainerAssignment(container=created, source="provisioned", volume_ready=True)

    prepared = ensure_container_started(existing)
    allocation_model.release_active_allocations(user_id=int(user["id"]))
    allocation_model.create_allocation(
        user_id=int(user["id"]),
        container_id=int(prepared["id"]),
        volume_name=str(prepared.get("assigned_volume_name") or user["volume_name"]),
    )
    return ContainerAssignment(container=prepared, source="existing", volume_ready=volume_ready or True)


def provision_container_for_user(user: dict[str, Any]) -> dict[str, Any]:
    existing = container_model.get_assigned_container_for_user(int(user["id"]))
    if existing is not None:
        return ensure_container_started(existing)

    instance = _get_instance_by_token(str(user["gateway_token"]))
    deploy_result = None
    if instance is None:
        selected_image = _resolve_user_preferred_image(user)
        deploy_result = run_cmd_logged(
            [
                "bash",
                str(DEPLOY_SCRIPT_PATH),
                "--openrouter-api-key",
                str(user["openrouter_api_key"]),
                "--gateway-token",
                str(user["gateway_token"]),
                "--version",
                selected_image.version,
                "--image-ref",
                selected_image.image_ref,
            ],
            env={**os.environ, "OPENCLAW_SKIP_SELF_LOG": "1"},
            check=True,
            action_type="deploy-user-container",
        )
        instance = _get_instance_by_token(str(user["gateway_token"]))
    if instance is None:
        raise AppError(
            f"Deploy tamamlandi ama instance DB kaydi bulunamadi. Log: {deploy_result.log_file_path if deploy_result else '-'}"
        )

    return _register_container_from_instance(user, instance)


def _register_container_from_instance(user: dict[str, Any], instance: dict[str, Any]) -> dict[str, Any]:
    container_name = _gateway_container_name(str(instance["project_name"]))
    docker_container_id = _inspect_container_id(container_name)
    status = _map_docker_status(_inspect_container_status(container_name))
    image_ref, image_version = _resolve_instance_image_state(instance)

    sync_user_provisioning(
        int(user["id"]),
        volume_name=str(instance["volume_name"]),
        gateway_token=str(instance["token"]),
    )

    existing_for_instance = _get_container_by_instance_id(int(instance["id"]))
    if existing_for_instance is not None:
        container_model.assign_container(
            int(existing_for_instance["id"]),
            user_id=int(user["id"]),
            volume_name=str(instance["volume_name"]),
            status="assigned" if status == "running" else status,
        )
        container_model.update_container_runtime(
            int(existing_for_instance["id"]),
            status="assigned" if status == "running" else status,
            docker_container_id=docker_container_id,
            image_ref=image_ref,
            image_version=image_version,
        )
        allocation_model.release_active_allocations(user_id=int(user["id"]))
        allocation_model.create_allocation(
            user_id=int(user["id"]),
            container_id=int(existing_for_instance["id"]),
            volume_name=str(instance["volume_name"]),
        )
        refreshed = container_model.get_container_by_id(int(existing_for_instance["id"]))
        if refreshed is None:
            raise AppError("Container kaydi okunamadi.")
        return refreshed

    container = container_model.create_container(
        instance_id=int(instance["id"]),
        project_name=str(instance["project_name"]),
        container_name=container_name,
        docker_container_id=docker_container_id,
        image_ref=image_ref,
        image_version=image_version,
        host=DEFAULT_CONTAINER_HOST,
        port=int(instance["gateway_port"]),
        status=status,
        assigned_user_id=int(user["id"]),
        assigned_volume_name=str(instance["volume_name"]),
        gateway_token=str(instance["token"]),
    )
    allocation_model.release_active_allocations(user_id=int(user["id"]))
    allocation_model.create_allocation(
        user_id=int(user["id"]),
        container_id=int(container["id"]),
        volume_name=str(instance["volume_name"]),
    )
    return container_model.get_container_by_id(int(container["id"])) or container


def ensure_container_started(container: dict[str, Any]) -> dict[str, Any]:
    container = _sync_container_image_state(container)
    container_id = int(container["id"])
    container_name = str(container["container_name"])
    raw_status = _inspect_container_status(container_name)
    db_status = _map_docker_status(raw_status)

    if raw_status != "running":
        container_model.update_container_runtime(container_id, status="starting")
        start_result = run_cmd_logged(
            ["docker", "start", container_name],
            check=False,
            action_type="docker-start-user-container",
        )
        if not start_result.ok:
            container_model.update_container_runtime(container_id, status="error")
            raise AppError(
                f"Container start edilemedi: {container_name}\nLog: {start_result.log_file_path}"
            )
        raw_status = _inspect_container_status(container_name)
        db_status = _map_docker_status(raw_status)

    docker_container_id = _inspect_container_id(container_name)
    if db_status == "running":
        container_model.update_container_runtime(
            container_id,
            status="starting",
            docker_container_id=docker_container_id,
        )
        try:
            _wait_for_gateway_ready(container_name, int(container["port"]))
        except AppError:
            container_model.update_container_runtime(container_id, status="error")
            raise

    final_status = "assigned" if db_status == "running" else db_status
    container_model.update_container_runtime(
        container_id,
        status=final_status,
        docker_container_id=docker_container_id,
    )
    refreshed = container_model.get_container_by_id(container_id)
    if refreshed is None:
        raise AppError("Container kaydi okunamadi.")
    return refreshed


def update_container_gateway_token(user: dict[str, Any], gateway_token: str) -> dict[str, Any]:
    container = container_model.get_assigned_container_for_user(int(user["id"]))
    if container is None:
        raise AppError("Kullaniciya atanmis container bulunamadi.")

    prepared = ensure_container_started(container)
    container_name = str(prepared["container_name"])

    mode_result = _run_openclaw_cli(
        container_name,
        [
            ["openclaw", "config", "set", "gateway.auth.mode", "token"],
            ["/usr/local/bin/openclaw", "config", "set", "gateway.auth.mode", "token"],
        ],
        action_type="gateway-config",
    )
    if not mode_result.ok:
        raise AppError(
            f"Gateway auth mode guncellenemedi: {container_name}\nLog: {mode_result.log_file_path}"
        )

    token_result = _run_openclaw_cli(
        container_name,
        [
            ["openclaw", "config", "set", "gateway.auth.token", gateway_token],
            ["/usr/local/bin/openclaw", "config", "set", "gateway.auth.token", gateway_token],
        ],
        action_type="gateway-config",
    )
    if not token_result.ok:
        raise AppError(
            f"Gateway token guncellenemedi: {container_name}\nLog: {token_result.log_file_path}"
        )

    sync_user_provisioning(
        int(user["id"]),
        volume_name=str(prepared.get("assigned_volume_name") or user["volume_name"]),
        gateway_token=gateway_token,
    )
    container_model.update_container_gateway_token(int(prepared["id"]), gateway_token)
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE instances
            SET token = ?
            WHERE id = ?
            """,
            (gateway_token, int(prepared["instance_id"])),
        )
        conn.commit()

    refreshed = container_model.get_container_by_id(int(prepared["id"]))
    if refreshed is None:
        raise AppError("Container kaydi okunamadi.")
    return refreshed

def _get_instance_by_token(token: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM instances
            WHERE token = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (token,),
        ).fetchone()
    return row_to_dict(row)


def _get_instance_by_id(instance_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM instances
            WHERE id = ?
            """,
            (instance_id,),
        ).fetchone()
    return row_to_dict(row)


def _get_container_by_instance_id(instance_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM containers
            WHERE instance_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (instance_id,),
        ).fetchone()
    return row_to_dict(row)


def _resolve_instance_image_state(instance: dict[str, Any]) -> tuple[str, str]:
    current_image = get_current_image_state()
    image_ref = str(instance.get("image") or current_image.image_ref).strip()
    image_version = normalize_version(instance.get("version"), fallback=current_image.version)
    return image_ref, image_version


def _resolve_user_preferred_image(user: dict[str, Any]):
    preferred_image_ref = str(user.get("preferred_image_ref") or "").strip()
    preferred_image_version = normalize_version(user.get("preferred_image_version"))
    if preferred_image_ref:
        return resolve_image_state(
            preferred_image_ref,
            fallback_version=preferred_image_version,
            allow_unmanaged=True,
        )
    return get_current_image_state()


def _sync_container_image_state(container: dict[str, Any]) -> dict[str, Any]:
    instance_id = container.get("instance_id")
    if not instance_id:
        return container
    instance = _get_instance_by_id(int(instance_id))
    if instance is None:
        return container
    image_ref, image_version = _resolve_instance_image_state(instance)
    current_ref = str(container.get("image_ref") or "").strip()
    current_version = normalize_version(container.get("image_version"))
    if current_ref == image_ref and current_version == image_version:
        return container
    container_model.update_container_runtime(
        int(container["id"]),
        image_ref=image_ref,
        image_version=image_version,
    )
    refreshed = container_model.get_container_by_id(int(container["id"]))
    return refreshed or container


def _inspect_container_status(container_name: str) -> str:
    result = run_cmd_logged(
        ["docker", "inspect", "-f", "{{.State.Status}}", container_name],
        check=False,
        action_type="docker-inspect-user-container",
    )
    if not result.ok:
        raise AppError(
            f"Container bulunamadi veya inspect basarisiz: {container_name}\nLog: {result.log_file_path}"
        )
    return (result.stdout or "").strip()


def _inspect_container_id(container_name: str) -> str | None:
    result = run_cmd_logged(
        ["docker", "inspect", "-f", "{{.Id}}", container_name],
        check=False,
        action_type="docker-inspect-user-container",
    )
    if not result.ok:
        return None
    value = (result.stdout or "").strip()
    return value or None


def _map_docker_status(status: str) -> str:
    normalized = (status or "").strip().lower()
    if normalized == "running":
        return "running"
    if normalized in {"exited", "dead"}:
        return "stopped"
    if normalized in {"created", "restarting"}:
        return "starting"
    if normalized == "paused":
        return "stopped"
    return "error"


def _gateway_container_name(project_name: str) -> str:
    return f"{project_name}-openclaw-gateway-1"


def _run_openclaw_cli(container_name: str, candidates: list[list[str]], *, action_type: str) -> Any:
    last_result = None
    for args in candidates:
        result = run_cmd_logged(
            ["docker", "exec", "-i", container_name] + args,
            check=False,
            action_type=action_type,
        )
        last_result = result
        if result.ok:
            return result
    return last_result


def _wait_for_gateway_ready(container_name: str, port: int) -> None:
    deadline = time.monotonic() + GATEWAY_READY_TIMEOUT_SECONDS
    last_error = "Gateway readiness endpointi cevap vermedi."

    while time.monotonic() < deadline:
        for endpoint in GATEWAY_READY_ENDPOINTS:
            url = f"http://{GATEWAY_READY_HOST}:{port}{endpoint}"
            try:
                with request.urlopen(url, timeout=2) as response:
                    if 200 <= response.status < 300:
                        return
                    last_error = f"{endpoint} HTTP {response.status}"
            except error.HTTPError as exc:
                last_error = f"{endpoint} HTTP {exc.code}"
            except Exception as exc:
                last_error = f"{endpoint} {type(exc).__name__}: {exc}"
        time.sleep(GATEWAY_READY_POLL_INTERVAL_SECONDS)

    raise AppError(
        "Container baslatildi ancak gateway hazir olmadi: "
        f"{container_name} ({GATEWAY_READY_HOST}:{port})\nSon durum: {last_error}"
    )
