from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.command_service import run_cmd_logged
from services.docker_service import gateway_container_name


@dataclass
class VersionInfo:
    default_version: str
    image_version: Optional[str]


def get_openclaw_version(default_version: str) -> VersionInfo:
    """
    Detect the latest OpenClaw image version from the upstream image.
    """
    try:
        result = run_cmd_logged(
            ["docker", "run", "--rm", "ghcr.io/openclaw/openclaw", "openclaw", "--version"],
            check=False,
            action_type="version",
        )
        line = (result.stdout or result.stderr or "").strip().splitlines()[0].strip() if (result.stdout or result.stderr) else ""
        ver = line or None
    except Exception:
        ver = None
    return VersionInfo(default_version=default_version, image_version=ver)


def get_instance_version(project_name: str, default_version: str) -> str:
    """
    Detect the running instance's OpenClaw version by exec'ing into its gateway container.
    """
    container = gateway_container_name(project_name)
    try:
        result = run_cmd_logged(
            ["docker", "exec", "-i", container, "openclaw", "--version"],
            check=False,
            action_type="version",
        )
        if result.stdout or result.stderr:
            line = (result.stdout or result.stderr).strip().splitlines()[0].strip()
            if line:
                return line
    except Exception:
        pass
    return default_version

