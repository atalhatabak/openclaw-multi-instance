from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from db import DEFAULT_CURRENT_IMAGE_REF, DEFAULT_CURRENT_IMAGE_VERSION, get_conn
from models import managed_image_model, system_settings_model
from services.command_service import AppError, run_cmd_logged
from services.docker_service import gateway_container_name
from services.openclaw_release_service import get_target_stable_version

DEFAULT_IMAGE_BASE = os.environ.get("OPENCLAW_IMAGE_BASE", "xen").strip() or "xen"
VERSION_PATTERN = re.compile(r"\b\d{4}\.\d+\.\d+(?:[-+._][A-Za-z0-9]+)*\b")
IMAGE_REF_VERSION_PATTERN = re.compile(r"-v(\d{4}\.\d+\.\d+(?:[-+._][A-Za-z0-9]+)*)$")
REPO_DIR = Path(__file__).resolve().parents[1] / "openclaw"


@dataclass
class ImageState:
    image_ref: str
    version: str


@dataclass
class PlannedImageBuild:
    image_ref: str
    requested_version: str
    tag_version: str
    version_source: str


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


def image_refs_match(left: Optional[str], right: Optional[str]) -> bool:
    left_candidates = set(_image_ref_candidates(left))
    right_candidates = set(_image_ref_candidates(right))
    if not left_candidates or not right_candidates:
        return False
    return bool(left_candidates & right_candidates)


def build_managed_image_ref(version: str) -> str:
    normalized = normalize_version(version)
    if not normalized:
        normalized = DEFAULT_CURRENT_IMAGE_VERSION
    return f"{DEFAULT_IMAGE_BASE}-v{normalized}"


def get_current_image_state() -> ImageState:
    settings = system_settings_model.get_system_settings()
    image_ref = (settings.get("current_image_ref") or DEFAULT_CURRENT_IMAGE_REF).strip()
    version = normalize_version(settings.get("current_image_version"), fallback=DEFAULT_CURRENT_IMAGE_VERSION)
    if not image_ref:
        image_ref = build_managed_image_ref(version)
    return ImageState(image_ref=image_ref, version=version)


def set_current_image_state(
    *,
    image_ref: Optional[str] = None,
    version: Optional[str] = None,
    version_source: str = "manual",
) -> ImageState:
    current = get_current_image_state()
    next_image_ref = (image_ref or current.image_ref).strip()
    next_version = normalize_version(version, fallback=current.version)
    updated = system_settings_model.update_current_image(
        image_ref=next_image_ref,
        image_version=next_version,
    )
    managed_image_model.upsert_managed_image(
        image_ref=next_image_ref,
        version=next_version,
        version_source=version_source,
    )
    return ImageState(
        image_ref=str(updated["current_image_ref"]).strip(),
        version=normalize_version(updated["current_image_version"], fallback=DEFAULT_CURRENT_IMAGE_VERSION),
    )


def detect_image_version(image_ref: str) -> str | None:
    resolved_image = resolve_local_image_ref(image_ref)
    if not resolved_image:
        return None
    try:
        result = run_cmd_logged(
            ["docker", "run", "--rm", resolved_image, "openclaw", "--version"],
            check=False,
            action_type="version",
        )
    except Exception:
        return None

    if not result.ok:
        return None

    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return None
    match = VERSION_PATTERN.search(output)
    if not match:
        return None
    return match.group(0)


def image_exists(image_ref: str) -> bool:
    return resolve_local_image_ref(image_ref) is not None


def resolve_local_image_ref(image_ref: str | None) -> str | None:
    for candidate in _image_ref_candidates(image_ref):
        try:
            proc = subprocess.run(
                ["docker", "image", "ls", "--format", "{{.ID}}", candidate],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return None
        if proc.returncode == 0 and (proc.stdout or "").strip():
            return candidate
    return None


def detect_repo_version(repo_dir: Path | None = None) -> str | None:
    package_json = (repo_dir or REPO_DIR) / "package.json"
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return normalize_version(str(payload.get("version") or "").strip())


def list_available_images(*, limit: int = 12) -> list[dict[str, Any]]:
    current = get_current_image_state()
    items = managed_image_model.list_managed_images(limit=limit)
    payload: list[dict[str, Any]] = []
    seen_refs: set[str] = set()

    for item in items:
        image_ref = str(item.get("image_ref") or "").strip()
        if not image_ref or image_ref in seen_refs:
            continue
        version = normalize_version(
            item.get("version"),
            fallback=_infer_version_from_image_ref(image_ref) or current.version,
        )
        payload.append(
            {
                **item,
                "image_ref": image_ref,
                "version": version,
                "is_current": image_ref == current.image_ref,
            }
        )
        seen_refs.add(image_ref)

    if current.image_ref not in seen_refs:
        payload.insert(
            0,
            {
                "id": None,
                "image_ref": current.image_ref,
                "version": current.version,
                "version_source": "system",
                "created_at": None,
                "updated_at": None,
                "is_current": True,
            },
        )
    else:
        current_index = next(
            (index for index, item in enumerate(payload) if item.get("image_ref") == current.image_ref),
            None,
        )
        if current_index not in (None, 0):
            payload.insert(0, payload.pop(current_index))

    return payload


def resolve_image_state(
    image_ref: str | None = None,
    *,
    fallback_version: str | None = None,
    allow_unmanaged: bool = False,
) -> ImageState:
    current = get_current_image_state()
    target_ref = (image_ref or "").strip()
    if not target_ref:
        return current
    if target_ref == current.image_ref:
        version = normalize_version(fallback_version, fallback=current.version)
        return ImageState(image_ref=target_ref, version=version)

    managed = managed_image_model.get_managed_image_by_ref(target_ref)
    if managed is not None:
        return ImageState(
            image_ref=target_ref,
            version=normalize_version(managed.get("version"), fallback=fallback_version or current.version),
        )

    if allow_unmanaged:
        inferred = _infer_version_from_image_ref(target_ref)
        if inferred:
            return ImageState(
                image_ref=target_ref,
                version=normalize_version(fallback_version, fallback=inferred),
            )

        detected = detect_image_version(target_ref)
        if detected:
            return ImageState(
                image_ref=target_ref,
                version=normalize_version(detected, fallback=fallback_version or current.version),
            )

    raise AppError("Secilen image bulunamadi veya kullanilabilir degil.")


def plan_next_image_build(now: datetime | None = None) -> PlannedImageBuild:
    target_version = get_target_stable_version(fallback=DEFAULT_CURRENT_IMAGE_VERSION)
    return PlannedImageBuild(
        image_ref=build_managed_image_ref(target_version),
        requested_version=target_version,
        tag_version=target_version,
        version_source="release-stable",
    )


def prune_managed_images(*, retain: int = 3, protected_refs: set[str] | None = None) -> dict[str, list[dict[str, str]]]:
    images = managed_image_model.list_managed_images()
    if len(images) <= retain:
        return {"removed": [], "skipped": []}

    protected = _list_protected_image_refs()
    if protected_refs:
        protected.update({ref for ref in protected_refs if ref})

    removed: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for item in reversed(images[retain:]):
        image_ref = str(item.get("image_ref") or "").strip()
        if not image_ref:
            continue
        if image_ref in protected:
            skipped.append({"image_ref": image_ref, "reason": "in use or pinned"})
            continue

        result = run_cmd_logged(
            ["docker", "image", "rm", image_ref],
            check=False,
            action_type="image-prune",
        )
        output = (result.stderr or result.stdout or "").strip()
        if result.ok or _image_missing_message(output):
            managed_image_model.delete_managed_image(image_ref)
            removed.append({"image_ref": image_ref, "reason": "removed"})
            continue

        skipped.append({"image_ref": image_ref, "reason": output or "docker image rm failed"})

    return {"removed": removed, "skipped": skipped}


def get_instance_version(project_name: str, default_version: str) -> str:
    container = gateway_container_name(project_name)
    try:
        result = run_cmd_logged(
            ["docker", "exec", "-i", container, "openclaw", "--version"],
            check=False,
            action_type="version",
        )
    except Exception:
        return normalize_version(default_version, fallback=DEFAULT_CURRENT_IMAGE_VERSION)

    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return normalize_version(default_version, fallback=DEFAULT_CURRENT_IMAGE_VERSION)
    return normalize_version(output, fallback=default_version)


def _infer_version_from_image_ref(image_ref: str) -> str | None:
    match = IMAGE_REF_VERSION_PATTERN.search((image_ref or "").strip())
    if match:
        return normalize_version(match.group(1))
    return None


def _image_ref_candidates(image_ref: str | None) -> list[str]:
    target_ref = (image_ref or "").strip()
    if not target_ref:
        return []
    candidates = [target_ref]
    if not _has_explicit_image_tag(target_ref):
        candidates.append(f"{target_ref}:latest")
    return candidates


def _has_explicit_image_tag(image_ref: str) -> bool:
    ref = (image_ref or "").strip()
    if not ref:
        return False
    if "@" in ref:
        return True
    return ":" in ref.rsplit("/", 1)[-1]


def _format_date_version(now: datetime) -> str:
    return f"{now.year}.{now.month}.{now.day}"


def _format_timestamp_version(now: datetime) -> str:
    return f"{now.year}.{now.month}.{now.day}-{now:%H%M%S}"


def _image_missing_message(output: str) -> bool:
    normalized = (output or "").lower()
    return "no such image" in normalized or "image not known" in normalized or "not found" in normalized


def _list_protected_image_refs() -> set[str]:
    refs: set[str] = set()
    current = get_current_image_state()
    if current.image_ref:
        refs.add(current.image_ref)

    with get_conn() as conn:
        for query in (
            "SELECT image AS image_ref FROM instances WHERE image IS NOT NULL AND trim(image) <> ''",
            "SELECT image_ref FROM containers WHERE image_ref IS NOT NULL AND trim(image_ref) <> ''",
            """
            SELECT preferred_image_ref AS image_ref
            FROM users
            WHERE preferred_image_ref IS NOT NULL AND trim(preferred_image_ref) <> ''
            """,
        ):
            for row in conn.execute(query).fetchall():
                image_ref = str(row["image_ref"] or "").strip()
                if image_ref:
                    refs.add(image_ref)
    return refs
