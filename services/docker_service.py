from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from services.command_service import run_cmd_logged


BASE_DIR = Path(__file__).resolve().parents[1]
DOCKER_COMPOSE_FILE = Path(
    __import__("os").environ.get("OPENCLAW_COMPOSE_FILE", BASE_DIR / "docker-compose.yml")
)


def compose_base_cmd(project_name: str, *, env_file: Optional[str] = None) -> list[str]:
    cmd = ["docker", "compose", "-p", project_name, "-f", str(DOCKER_COMPOSE_FILE)]
    if env_file:
        cmd.extend(["--env-file", env_file])
    return cmd


@contextmanager
def instance_env_file(instance: dict[str, Any]) -> Iterator[str]:
    lines = [
        f"OPENCLAW_HOME_VOLUME={instance['volume_name']}",
        f"OPENCLAW_GATEWAY_TOKEN={instance['token']}",
        f"OPENCLAW_GATEWAY_PORT={instance['gateway_port']}",
        f"OPENCLAW_BRIDGE_PORT={instance['bridge_port']}",
        f"OPENCLAW_GATEWAY_BIND={instance.get('gateway_bind') or 'lan'}",
        f"OPENCLAW_IMAGE={instance.get('image') or 'ghcr.io/openclaw/openclaw:latest'}",
        f"OPENROUTER_API_KEY={instance['openrouter_token']}",
    ]
    if instance.get("channel_bot_token") and instance.get("allow_from"):
        lines.extend(
            [
                f"TELEGRAM_BOT_TOKEN={instance['channel_bot_token']}",
                f"TELEGRAM_ALLOW_FROM={instance['allow_from']}",
            ]
        )

    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f"openclaw_{instance['id']}_",
        suffix=".env",
        dir=BASE_DIR,
        delete=False,
    )
    try:
        handle.write("\n".join(lines) + "\n")
        handle.flush()
        handle.close()
        yield handle.name
    finally:
        try:
            Path(handle.name).unlink(missing_ok=True)
        except Exception:
            pass


def gateway_container_name(project_name: str) -> str:
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


def compose_up(instance: dict[str, Any], *, instance_id: Optional[int] = None) -> str:
    with instance_env_file(instance) as env_file:
        result = run_cmd_logged(
            compose_base_cmd(str(instance["project_name"]), env_file=env_file) + ["up", "-d", "--remove-orphans"],
            instance_id=instance_id,
            action_type="start",
        )
    return result.stdout or "Instance başlatıldı."


def compose_stop(instance: dict[str, Any], *, instance_id: Optional[int] = None) -> str:
    with instance_env_file(instance) as env_file:
        result = run_cmd_logged(
            compose_base_cmd(str(instance["project_name"]), env_file=env_file) + ["stop"],
            instance_id=instance_id,
            action_type="stop",
        )
    return result.stdout or "Instance durduruldu."


def compose_down_and_remove_volume(instance: dict[str, Any], *, instance_id: Optional[int] = None) -> str:
    with instance_env_file(instance) as env_file:
        result = run_cmd_logged(
            compose_base_cmd(str(instance["project_name"]), env_file=env_file) + ["down", "-v", "--remove-orphans"],
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
