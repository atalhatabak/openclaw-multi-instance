from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.command_service import run_cmd_logged
from services.docker_service import gateway_container_name

UPSTREAM_IMAGE = "ghcr.io/openclaw/openclaw"


@dataclass
class VersionInfo:
    default_version: str
    image_version: Optional[str]


def resolve_openclaw_image(version_or_image: Optional[str]) -> str:
    value = (version_or_image or "").strip()
    if not value:
        return f"{UPSTREAM_IMAGE}:latest"
    if "/" in value:
        return value
    return f"{UPSTREAM_IMAGE}:{value}"


def get_openclaw_version(default_version: str, *, image_ref: Optional[str] = None) -> VersionInfo:
    """
    Detect the OpenClaw version from the provided image, or fall back to upstream latest.
    """
    target_image = resolve_openclaw_image(image_ref)
    try:
        result = run_cmd_logged(
            ["docker", "run", "--rm", target_image, "openclaw", "--version"],
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
