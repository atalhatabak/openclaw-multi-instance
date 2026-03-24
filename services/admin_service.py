from __future__ import annotations

from typing import Any

from models import container_model, instance_model, user_model
from services.command_service import AppError
from services.container_service import ensure_container_started
from services.docker_service import compose_down_and_remove_volume, compose_stop, compose_up, docker_volume_rm


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
    instance_id = container.get("instance_id")
    if not instance_id:
        raise AppError("Container instance kaydi eksik.")
    instance = instance_model.get_instance_by_id(int(instance_id))
    if instance is None:
        raise AppError("Instance bulunamadi.")
    compose_up(instance, instance_id=int(instance["id"]))
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
