from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from models import container_model, instance_model, user_model
from services.command_service import AppError, run_cmd_logged
from services.container_service import ensure_container_started
from services.docker_service import compose_down_and_remove_volume, compose_stop, docker_volume_rm
from services.version_service import (
    detect_image_version,
    get_current_image_state,
    normalize_version,
    set_current_image_state,
    versions_match,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
CLONE_PATCH_BUILD_SCRIPT = ROOT_DIR / "clone_patch_build.sh"
UPDATE_OPENCLAW_SCRIPT = ROOT_DIR / "update_openclaw.sh"


def delete_user_stack(user_id: int) -> None:
    user = user_model.get_user_by_id(user_id)
    if user is None:
        raise AppError("Kullanici bulunamadi.")

    container = container_model.get_assigned_container_for_user(user_id)
    instance = None
    if container is not None and container.get("instance_id"):
        instance = instance_model.get_instance_by_id(int(container["instance_id"]))

    if instance is not None:
        compose_down_and_remove_volume(instance, instance_id=int(instance["id"]))
        docker_volume_rm(str(instance["volume_name"]), instance_id=int(instance["id"]))
    else:
        docker_volume_rm(str(user["volume_name"]), instance_id=None)

    if container is not None:
        container_model.delete_container(int(container["id"]))
    if instance is not None:
        instance_model.delete_instance(int(instance["id"]))
    user_model.delete_user_with_related_rows(user_id)


def start_container(container_id: int) -> dict[str, Any]:
    container = container_model.get_container_by_id(container_id)
    if container is None:
        raise AppError("Container bulunamadi.")
    return ensure_container_started(container)


def stop_container(container_id: int) -> dict[str, Any]:
    container = container_model.get_container_by_id(container_id)
    if container is None:
        raise AppError("Container bulunamadi.")
    instance_id = container.get("instance_id")
    if not instance_id:
        raise AppError("Container instance kaydi eksik.")
    instance = instance_model.get_instance_by_id(int(instance_id))
    if instance is None:
        raise AppError("Instance bulunamadi.")
    compose_stop(instance, instance_id=int(instance["id"]))
    container_model.update_container_runtime(container_id, status="stopped")
    refreshed = container_model.get_container_by_id(container_id)
    if refreshed is None:
        raise AppError("Container kaydi okunamadi.")
    return refreshed


def rebuild_current_image() -> dict[str, Any]:
    current_image = get_current_image_state()
    env = os.environ.copy()
    env["OPENCLAW_IMAGE"] = current_image.image_ref
    result = run_cmd_logged(
        ["bash", str(CLONE_PATCH_BUILD_SCRIPT)],
        env=env,
        check=True,
        action_type="image-update",
    )
    detected_version = detect_image_version(current_image.image_ref)
    if not detected_version:
        raise AppError(
            f"Image build tamamlandi ama version okunamadi. Log: {result.log_file_path}"
        )
    updated_image = set_current_image_state(
        image_ref=current_image.image_ref,
        version=detected_version,
    )
    return {
        "image_ref": updated_image.image_ref,
        "version": updated_image.version,
        "log_file_path": result.log_file_path,
    }


def update_container_to_current_image(container_id: int) -> dict[str, Any]:
    container = container_model.get_container_by_id(container_id)
    if container is None:
        raise AppError("Container bulunamadi.")

    instance_id = container.get("instance_id")
    if not instance_id:
        raise AppError("Container instance kaydi eksik.")

    instance = instance_model.get_instance_by_id(int(instance_id))
    if instance is None:
        raise AppError("Instance bulunamadi.")

    current_image = get_current_image_state()
    container_version = normalize_version(
        container.get("image_version"),
        fallback=instance.get("version") if instance.get("version") else "",
    )
    if versions_match(container_version, current_image.version):
        return {
            "updated": False,
            "container": container,
            "image_ref": current_image.image_ref,
            "version": current_image.version,
        }

    result = run_cmd_logged(
        [
            "bash",
            str(UPDATE_OPENCLAW_SCRIPT),
            "--instance-id",
            str(instance["id"]),
            "--version",
            current_image.version,
            "--image-ref",
            current_image.image_ref,
        ],
        check=True,
        instance_id=int(instance["id"]),
        action_type="container-update",
    )

    refreshed_instance = instance_model.get_instance_by_id(int(instance["id"])) or instance
    next_version = normalize_version(
        refreshed_instance.get("version"),
        fallback=current_image.version,
    )
    next_image_ref = str(refreshed_instance.get("image") or current_image.image_ref).strip()
    container_model.update_container_runtime(
        container_id,
        status="starting",
        image_ref=next_image_ref,
        image_version=next_version,
    )
    refreshed = container_model.get_container_by_id(container_id)
    if refreshed is None:
        raise AppError("Container kaydi okunamadi.")
    refreshed = ensure_container_started(refreshed)
    container_model.update_container_runtime(
        int(refreshed["id"]),
        image_ref=next_image_ref,
        image_version=next_version,
    )
    final_container = container_model.get_container_by_id(int(refreshed["id"]))
    if final_container is None:
        raise AppError("Container kaydi okunamadi.")
    return {
        "updated": True,
        "container": final_container,
        "image_ref": next_image_ref,
        "version": next_version,
        "log_file_path": result.log_file_path,
    }
