from __future__ import annotations

import os
import subprocess
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import container_model, instance_model, operation_log_model, user_model
from services.command_service import AppError, run_cmd_logged
from services.container_service import ensure_container_started
from services.docker_service import compose_down_and_remove_volume, compose_stop, docker_volume_rm
from services.log_service import (
    append_log_text,
    build_log_path,
    read_log_tail,
    resolve_managed_log_path,
    write_live_log_header,
)
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
IMAGE_UPDATE_ACTION = "image-update"


@dataclass
class ImageUpdateJob:
    log_id: int
    log_file_path: Path
    image_ref: str
    process: subprocess.Popen[str]


_IMAGE_UPDATE_LOCK = threading.Lock()
_IMAGE_UPDATE_JOB: ImageUpdateJob | None = None


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
    if _get_running_image_update_job() is not None:
        raise AppError("Image guncelleme zaten calisiyor. Canli log panelinden takip edebilirsin.")
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


def start_current_image_rebuild() -> dict[str, Any]:
    global _IMAGE_UPDATE_JOB
    with _IMAGE_UPDATE_LOCK:
        if _IMAGE_UPDATE_JOB is not None and _IMAGE_UPDATE_JOB.process.poll() is None:
            return {
                "started": False,
                "already_running": True,
                "log_id": _IMAGE_UPDATE_JOB.log_id,
                "log_file_path": str(_IMAGE_UPDATE_JOB.log_file_path),
            }
        _IMAGE_UPDATE_JOB = None

        current_image = get_current_image_state()
        env = os.environ.copy()
        env["OPENCLAW_IMAGE"] = current_image.image_ref

        log_path = build_log_path(IMAGE_UPDATE_ACTION)
        operation_log = operation_log_model.create_operation_log(
            action_type=IMAGE_UPDATE_ACTION,
            log_file_path=str(log_path),
            status="running",
        )
        try:
            write_live_log_header(
                log_path,
                header="\n".join(
                    [
                        f"timestamp_utc: {datetime.now(timezone.utc).isoformat()}",
                        f"cwd: {ROOT_DIR}",
                        f"action_type: {IMAGE_UPDATE_ACTION}",
                        f"log_id: {operation_log['id']}",
                        f"command: bash {CLONE_PATCH_BUILD_SCRIPT}",
                        f"image_ref: {current_image.image_ref}",
                    ]
                ),
            )
        except Exception as exc:
            operation_log_model.update_operation_log_status(int(operation_log["id"]), status="error")
            raise AppError(f"Image log dosyasi hazirlanamadi. Log: {log_path}") from exc

        try:
            process = subprocess.Popen(
                ["bash", str(CLONE_PATCH_BUILD_SCRIPT)],
                cwd=str(ROOT_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as exc:
            append_log_text(log_path, f"Build baslatilamadi: {exc}\n")
            operation_log_model.update_operation_log_status(int(operation_log["id"]), status="error")
            raise AppError(f"Image build baslatilamadi. Log: {log_path}") from exc

        job = ImageUpdateJob(
            log_id=int(operation_log["id"]),
            log_file_path=log_path,
            image_ref=current_image.image_ref,
            process=process,
        )
        _IMAGE_UPDATE_JOB = job

    threading.Thread(
        target=_monitor_image_update_job,
        args=(job,),
        daemon=True,
    ).start()

    return {
        "started": True,
        "already_running": False,
        "log_id": job.log_id,
        "log_file_path": str(job.log_file_path),
    }


def list_recent_image_update_logs(*, limit: int = 8) -> list[dict[str, Any]]:
    logs = operation_log_model.list_operation_logs(action_type=IMAGE_UPDATE_ACTION, limit=limit)
    running_job = _get_running_image_update_job()
    running_log_id = running_job.log_id if running_job is not None else None
    for entry in logs:
        entry["is_running"] = running_log_id == int(entry["id"])
    return logs


def get_image_update_log_snapshot(*, log_id: int | None = None, line_limit: int = 320) -> dict[str, Any]:
    recent_logs = list_recent_image_update_logs()
    selected_log = None

    if log_id is not None:
        selected_log = operation_log_model.get_operation_log_by_id(log_id)

    running_job = _get_running_image_update_job()
    if selected_log is None and running_job is not None:
        selected_log = operation_log_model.get_operation_log_by_id(running_job.log_id)

    if selected_log is None and recent_logs:
        selected_log = recent_logs[0]

    selected_log_payload = None
    content = ""
    truncated = False
    log_path = ""

    if selected_log is not None:
        selected_id = int(selected_log["id"])
        resolved = resolve_managed_log_path(str(selected_log["log_file_path"]))
        tail = read_log_tail(resolved, max_lines=line_limit) if resolved is not None else None
        content = tail.content if tail is not None else ""
        truncated = bool(tail.truncated) if tail is not None else False
        log_path = str(resolved or selected_log["log_file_path"])
        selected_log_payload = {
            **selected_log,
            "is_running": running_job is not None and running_job.log_id == selected_id,
        }

    return {
        "selected_log": selected_log_payload,
        "recent_logs": recent_logs,
        "content": content,
        "truncated": truncated,
        "log_path": log_path,
        "line_limit": line_limit,
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


def _get_running_image_update_job() -> ImageUpdateJob | None:
    with _IMAGE_UPDATE_LOCK:
        global _IMAGE_UPDATE_JOB
        if _IMAGE_UPDATE_JOB is None:
            return None
        if _IMAGE_UPDATE_JOB.process.poll() is not None:
            _IMAGE_UPDATE_JOB = None
            return None
        return _IMAGE_UPDATE_JOB


def _monitor_image_update_job(job: ImageUpdateJob) -> None:
    status = "error"
    try:
        if job.process.stdout is not None:
            with job.process.stdout:
                for chunk in iter(job.process.stdout.readline, ""):
                    append_log_text(job.log_file_path, chunk)

        returncode = job.process.wait()
        if returncode != 0:
            append_log_text(
                job.log_file_path,
                f"\n---- RESULT ----\nBuild basarisiz tamamlandi. Exit code: {returncode}\n",
            )
        else:
            detected_version = detect_image_version(job.image_ref)
            if not detected_version:
                append_log_text(
                    job.log_file_path,
                    "\n---- RESULT ----\nBuild tamamlandi ama version okunamadi.\n",
                )
            else:
                updated_image = set_current_image_state(
                    image_ref=job.image_ref,
                    version=detected_version,
                )
                status = "success"
                append_log_text(
                    job.log_file_path,
                    f"\n---- RESULT ----\nImage guncellendi. Version: {updated_image.version}\n",
                )
        operation_log_model.update_operation_log_status(job.log_id, status=status)
    except Exception:
        append_log_text(
            job.log_file_path,
            "\n---- INTERNAL ERROR ----\n"
            f"{traceback.format_exc()}\n",
        )
        operation_log_model.update_operation_log_status(job.log_id, status="error")
    finally:
        with _IMAGE_UPDATE_LOCK:
            global _IMAGE_UPDATE_JOB
            if _IMAGE_UPDATE_JOB is not None and _IMAGE_UPDATE_JOB.log_id == job.log_id:
                _IMAGE_UPDATE_JOB = None
