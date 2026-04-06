from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from models import system_settings_model
from services.command_service import run_cmd_logged
from services.docker_service import gateway_container_name

DEFAULT_IMAGE_REF = os.environ.get("OPENCLAW_IMAGE", "xenv1-openclaw:latest")
DEFAULT_IMAGE_VERSION = os.environ.get("OPENCLAW_CURRENT_IMAGE_VERSION", "2026.4.3")
VERSION_PATTERN = re.compile(r"\b\d{4}\.\d+\.\d+(?:[-+._][A-Za-z0-9]+)*\b")


@dataclass
class ImageState:
    image_ref: str
    version: str


def normalize_version(raw: Optional[str], *, fallback: Optional[str] = None) -> str:
    value = (raw or "").strip()
    if not value:
        return (fallback or "").strip()
    match = VERSION_PATTERN.search(value)
    if match:
        return match.group(0)
    return value


def versions_match(left: Optional[str], right: Optional[str]) -> bool:
    return normalize_version(left) == normalize_version(right)


def get_current_image_state() -> ImageState:
    settings = system_settings_model.get_system_settings()
    return ImageState(
        image_ref=(settings.get("current_image_ref") or DEFAULT_IMAGE_REF).strip(),
        version=normalize_version(settings.get("current_image_version"), fallback=DEFAULT_IMAGE_VERSION),
    )


def set_current_image_state(*, image_ref: Optional[str] = None, version: Optional[str] = None) -> ImageState:
    current = get_current_image_state()
    updated = system_settings_model.update_current_image(
        image_ref=(image_ref or current.image_ref).strip(),
        image_version=normalize_version(version, fallback=current.version),
    )
    return ImageState(
        image_ref=str(updated["current_image_ref"]).strip(),
        version=normalize_version(updated["current_image_version"], fallback=DEFAULT_IMAGE_VERSION),
    )


def detect_image_version(image_ref: str) -> str | None:
    target_image = (image_ref or "").strip()
    if not target_image:
        return None
    try:
        result = run_cmd_logged(
            ["docker", "run", "--rm", target_image, "openclaw", "--version"],
            check=False,
            action_type="version",
        )
    except Exception:
        return None

    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return None
    return normalize_version(output)


def get_instance_version(project_name: str, default_version: str) -> str:
    container = gateway_container_name(project_name)
    try:
        result = run_cmd_logged(
            ["docker", "exec", "-i", container, "openclaw", "--version"],
            check=False,
            action_type="version",
        )
    except Exception:
        return normalize_version(default_version, fallback=DEFAULT_IMAGE_VERSION)

    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return normalize_version(default_version, fallback=DEFAULT_IMAGE_VERSION)
    return normalize_version(output, fallback=default_version)
