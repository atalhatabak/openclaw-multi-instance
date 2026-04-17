from __future__ import annotations

import json
import os
import re
from typing import Optional
from urllib import error, request

LATEST_RELEASE_URL = "https://api.github.com/repos/openclaw/openclaw/releases/latest"
DEFAULT_STABLE_FALLBACK_VERSION = os.environ.get("OPENCLAW_STABLE_FALLBACK_VERSION", "2026.4.14")
VERSION_PATTERN = re.compile(r"\b\d{4}\.\d+\.\d+(?:[-+._][A-Za-z0-9]+)*\b")


def normalize_version(raw: Optional[str]) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    match = VERSION_PATTERN.search(value)
    if match:
        return match.group(0)
    stripped = value[1:] if value[:1].lower() == "v" else value
    match = VERSION_PATTERN.search(stripped)
    if match:
        return match.group(0)
    return value


def is_stable_version(raw: Optional[str]) -> bool:
    version = normalize_version(raw)
    if not version:
        return False
    lowered = version.lower()
    return not any(marker in lowered for marker in ("alpha", "beta", "rc", "preview", "pre"))


def get_target_stable_version(*, fallback: Optional[str] = None) -> str:
    env_override = normalize_version(os.environ.get("OPENCLAW_TARGET_VERSION") or os.environ.get("OPENCLAW_STABLE_VERSION"))
    if is_stable_version(env_override):
        return env_override

    latest_release = fetch_latest_stable_release_version()
    if latest_release:
        return latest_release

    normalized_fallback = normalize_version(fallback)
    if is_stable_version(normalized_fallback):
        return normalized_fallback

    return normalize_version(DEFAULT_STABLE_FALLBACK_VERSION)


def fetch_latest_stable_release_version() -> str | None:
    try:
        req = request.Request(
            LATEST_RELEASE_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "openclaw-multi-instance",
            },
        )
        with request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, error.URLError, json.JSONDecodeError):
        return None

    if payload.get("prerelease") or payload.get("draft"):
        return None

    version = normalize_version(str(payload.get("tag_name") or payload.get("name") or "").strip())
    if not is_stable_version(version):
        return None
    return version
