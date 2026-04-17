from __future__ import annotations

import os
import subprocess
import sys
import threading
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
    image_refs_match,
    image_exists,
    normalize_version,
    plan_next_image_build,
    prune_managed_images,
    set_current_image_state,
    versions_match,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
CLONE_PATCH_BUILD_SCRIPT = ROOT_DIR / "clone_patch_build.sh"
UPDATE_OPENCLAW_SCRIPT = ROOT_DIR / "update_openclaw.sh"
IMAGE_UPDATE_RUNNER_SCRIPT = ROOT_DIR / "scripts" / "run_image_update_job.py"
IMAGE_UPDATE_ACTION = "image-update"
_IMAGE_UPDATE_START_LOCK = threading.Lock()


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
    build_plan = plan_next_image_build()
    env = os.environ.copy()
    env["OPENCLAW_IMAGE"] = build_plan.image_ref
    result = run_cmd_logged(
        ["bash", str(CLONE_PATCH_BUILD_SCRIPT)],
        env=env,
        check=True,
        action_type="image-update",
    )
    if not image_exists(build_plan.image_ref):
        raise AppError(
            "Build tamamlandi ancak hedef image yerelde bulunamadi: "
            f"{build_plan.image_ref}. env.base icindeki OPENCLAW_IMAGE degeri override ediyor olabilir. "
            f"Log: {result.log_file_path}"
        )
    next_version = detect_image_version(build_plan.image_ref) or build_plan.requested_version
    updated_image = set_current_image_state(
        image_ref=build_plan.image_ref,
        version=next_version,
        version_source=build_plan.version_source,
    )
    prune_managed_images(retain=3, protected_refs={updated_image.image_ref})
    return {
        "image_ref": updated_image.image_ref,
        "version": updated_image.version,
        "log_file_path": result.log_file_path,
    }


def start_current_image_rebuild() -> dict[str, Any]:
    with _IMAGE_UPDATE_START_LOCK:
        running_job = _get_running_image_update_job()
        if running_job is not None:
            return {
                "started": False,
                "already_running": True,
                "log_id": int(running_job["id"]),
                "log_file_path": str(running_job["log_file_path"]),
            }

        build_plan = plan_next_image_build()
        env = os.environ.copy()
        env["OPENCLAW_IMAGE"] = build_plan.image_ref

        log_path = build_log_path(IMAGE_UPDATE_ACTION)
        pid_path = _image_update_pid_path(log_path)
        operation_log = operation_log_model.create_operation_log(
            action_type=IMAGE_UPDATE_ACTION,
            log_file_path=str(log_path),
            status="running",
        )
        try:
            _safe_unlink(pid_path)
            write_live_log_header(
                log_path,
                header="\n".join(
                    [
                        f"timestamp_utc: {datetime.now(timezone.utc).isoformat()}",
                        f"cwd: {ROOT_DIR}",
                        f"action_type: {IMAGE_UPDATE_ACTION}",
                        f"log_id: {operation_log['id']}",
                        f"command: bash {CLONE_PATCH_BUILD_SCRIPT}",
                        f"image_ref: {build_plan.image_ref}",
                        f"requested_version: {build_plan.requested_version}",
                        f"tag_version: {build_plan.tag_version}",
                        f"version_source: {build_plan.version_source}",
                        f"runner: {IMAGE_UPDATE_RUNNER_SCRIPT}",
                    ]
                ),
            )
        except Exception as exc:
            operation_log_model.update_operation_log_status(int(operation_log["id"]), status="error")
            raise AppError(f"Image log dosyasi hazirlanamadi. Log: {log_path}") from exc

        try:
            runner = subprocess.Popen(
                [
                    sys.executable,
                    str(IMAGE_UPDATE_RUNNER_SCRIPT),
                    "--log-id",
                    str(operation_log["id"]),
                    "--log-path",
                    str(log_path),
                    "--image-ref",
                    build_plan.image_ref,
                    "--target-version",
                    build_plan.requested_version,
                    "--version-source",
                    build_plan.version_source,
                    "--pid-path",
                    str(pid_path),
                ],
                cwd=str(ROOT_DIR),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            pid_path.write_text(f"{runner.pid}\n", encoding="ascii")
        except Exception as exc:
            append_log_text(log_path, f"Build runner baslatilamadi: {exc}\n")
            operation_log_model.update_operation_log_status(int(operation_log["id"]), status="error")
            _safe_unlink(pid_path)
            raise AppError(f"Image build baslatilamadi. Log: {log_path}") from exc

        return {
            "started": True,
            "already_running": False,
            "log_id": int(operation_log["id"]),
            "log_file_path": str(log_path),
        }


def list_recent_image_update_logs(*, limit: int = 8) -> list[dict[str, Any]]:
    running_job = _get_running_image_update_job()
    logs = operation_log_model.list_operation_logs(action_type=IMAGE_UPDATE_ACTION, limit=limit)
    running_log_id = int(running_job["id"]) if running_job is not None else None
    for entry in logs:
        entry["is_running"] = running_log_id == int(entry["id"])
    return logs


def get_image_update_log_snapshot(*, log_id: int | None = None, line_limit: int = 320) -> dict[str, Any]:
    running_job = _get_running_image_update_job()
    recent_logs = list_recent_image_update_logs()
    selected_log = None

    if log_id is not None:
        selected_log = operation_log_model.get_operation_log_by_id(log_id)

    if selected_log is None and running_job is not None:
        selected_log = operation_log_model.get_operation_log_by_id(int(running_job["id"]))

    if selected_log is None and recent_logs:
        selected_log = recent_logs[0]

    selected_log_payload = None
    content = ""
    truncated = False
    log_path = ""
    log_size_bytes = 0
    last_updated_at = ""

    if selected_log is not None:
        selected_id = int(selected_log["id"])
        resolved = resolve_managed_log_path(str(selected_log["log_file_path"]))
        tail = read_log_tail(resolved, max_lines=line_limit) if resolved is not None else None
        content = tail.content if tail is not None else ""
        truncated = bool(tail.truncated) if tail is not None else False
        log_size_bytes = int(tail.size_bytes) if tail is not None else 0
        log_path = str(resolved or selected_log["log_file_path"])
        if resolved is not None and resolved.exists():
            last_updated_at = datetime.fromtimestamp(
                resolved.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat()
        selected_log_payload = {
            **selected_log,
            "is_running": running_job is not None and int(running_job["id"]) == selected_id,
        }

    return {
        "selected_log": selected_log_payload,
        "recent_logs": recent_logs,
        "content": content,
        "truncated": truncated,
        "log_path": log_path,
        "log_size_bytes": log_size_bytes,
        "last_updated_at": last_updated_at,
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
    container_image_ref = str(container.get("image_ref") or instance.get("image") or "").strip()
    if versions_match(container_version, current_image.version) and image_refs_match(
        container_image_ref,
        current_image.image_ref,
    ):
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


def _get_running_image_update_job() -> dict[str, Any] | None:
    candidate_logs = operation_log_model.list_operation_logs(action_type=IMAGE_UPDATE_ACTION, limit=24)
    for entry in candidate_logs:
        if str(entry.get("status") or "") != "running":
            continue
        if _is_image_update_job_alive(entry):
            return entry
        _mark_image_update_job_stale(entry)
    return None


def _image_update_pid_path(log_path: Path) -> Path:
    return log_path.with_suffix(f"{log_path.suffix}.pid")


def _is_image_update_job_alive(entry: dict[str, Any]) -> bool:
    resolved = resolve_managed_log_path(str(entry["log_file_path"]))
    if resolved is None:
        return False
    pid = _read_pid_file(_image_update_pid_path(resolved))
    return pid is not None and _process_is_alive(pid)


def _mark_image_update_job_stale(entry: dict[str, Any]) -> None:
    log_id = int(entry["id"])
    resolved = resolve_managed_log_path(str(entry["log_file_path"]))
    if resolved is not None and resolved.exists():
        append_log_text(
            resolved,
            "\n---- RESULT ----\nCanli image update beklenmedik sekilde durdu. "
            "Web prosesi yeniden baslamis veya worker kapanmis olabilir.\n",
        )
    operation_log_model.update_operation_log_status(log_id, status="error")
    if resolved is not None:
        _safe_unlink(_image_update_pid_path(resolved))


def _read_pid_file(pid_path: Path) -> int | None:
    try:
        raw = pid_path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
