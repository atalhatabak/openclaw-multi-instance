from __future__ import annotations

import os
from typing import Any


GATEWAY_PUBLIC_BASE = os.environ.get("OPENCLAW_GATEWAY_PUBLIC_BASE", "https://mebs.claw/")


def build_gateway_redirect_url(user: dict[str, Any], container: dict[str, Any]) -> str:
    base = GATEWAY_PUBLIC_BASE.rstrip("/") + "/"
    port = int(container["port"])
    gateway_token = str(container.get("gateway_token") or user["gateway_token"])
    return f"{base}?url={port}#token={gateway_token}"
