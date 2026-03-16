from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from services.command_service import run_cmd_logged


BASE_DIR = Path(__file__).resolve().parents[1]
DOCKER_COMPOSE_FILE = Path(
    __import__("os").environ.get("OPENCLAW_COMPOSE_FILE", BASE_DIR / "docker-compose.yml")
)


def compose_base_cmd(project_name: str) -> list[str]:
    return ["docker", "compose", "-p", project_name, "-f", str(DOCKER_COMPOSE_FILE)]


def gateway_container_name(project_name: str) -> str:
    # Default docker compose container naming scheme:
    # {project_name}-{service_name}-1
    return f"{project_name}-openclaw-gateway-1"


def get_project_status(project_name: str) -> str:
    try:
        result = run_cmd_logged(
            compose_base_cmd(project_name) + ["ps", "--format", "json"],
            check=False,
            action_type="actions",
        )
        if not result.ok:
            return "unknown"
        lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        if not lines:
            return "stopped"
        payloads: list[dict[str, Any]] = []
        for line in lines:
            try:
                payloads.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not payloads:
            return "unknown"
        states = {str(p.get("State", "unknown")).lower() for p in payloads}
        if "running" in states:
            return "running"
        return ", ".join(sorted(states))
    except Exception:
        return "unknown"


def inspect_project_text(project_name: str, *, limit: int = 4000) -> str:
    try:
        result = run_cmd_logged(
            compose_base_cmd(project_name) + ["ps"],
            check=False,
            action_type="actions",
        )
        text = (result.stdout or result.stderr or "No docker output").strip()
        return text[:limit]
    except Exception as exc:
        return f"Docker info alınamadı: {exc}"


def compose_up(project_name: str, *, instance_id: Optional[int] = None) -> str:
    result = run_cmd_logged(
        compose_base_cmd(project_name) + ["up", "-d"],
        instance_id=instance_id,
        action_type="start",
    )
    return result.stdout or "Instance başlatıldı."


def compose_stop(project_name: str, *, instance_id: Optional[int] = None) -> str:
    result = run_cmd_logged(
        compose_base_cmd(project_name) + ["stop"],
        instance_id=instance_id,
        action_type="stop",
    )
    return result.stdout or "Instance durduruldu."


def compose_down_and_remove_volume(project_name: str, *, instance_id: Optional[int] = None) -> str:
    result = run_cmd_logged(
        compose_base_cmd(project_name) + ["down", "-v", "--remove-orphans"],
        check=False,
        instance_id=instance_id,
        action_type="delete",
    )
    return result.stdout or result.stderr or ""


def docker_volume_rm(volume_name: str, *, instance_id: Optional[int] = None) -> str:
    result = run_cmd_logged(
        ["docker", "volume", "rm", "-f", volume_name],
        check=False,
        instance_id=instance_id,
        action_type="delete",
    )
    return result.stdout or result.stderr or ""


def docker_network_prune(*, instance_id: Optional[int] = None) -> str:
    result = run_cmd_logged(
        ["docker", "network", "prune", "-f"],
        check=False,
        instance_id=instance_id,
        action_type="delete",
    )
    return result.stdout or result.stderr or ""


def exec_openclaw_cli(project_name: str, args: list[str], *, instance_id: Optional[int] = None) -> str:
    # On Windows Docker Desktop, using `docker exec` with the concrete container
    # name matches the manual flow more reliably than `docker compose exec`.
    container = gateway_container_name(project_name)
    cmd = ["docker", "exec", "-i", container] + args
    result = run_cmd_logged(cmd, check=False, instance_id=instance_id, action_type="devices")
    if result.ok:
        return result.stdout.strip()
    return (result.stdout or result.stderr or "").strip()

