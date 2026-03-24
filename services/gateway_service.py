from __future__ import annotations

import os
from typing import Any


GATEWAY_PUBLIC_BASE = os.environ.get("OPENCLAW_GATEWAY_PUBLIC_BASE", "https://mebs.claw/")
GATEWAY_WS_SCHEME = os.environ.get("OPENCLAW_GATEWAY_WS_SCHEME", "ws")
GATEWAY_WS_HOST = os.environ.get("OPENCLAW_GATEWAY_WS_HOST", "127.0.0.1")


def build_gateway_redirect_url(user: dict[str, Any], container: dict[str, Any]) -> str:
    base = GATEWAY_PUBLIC_BASE.rstrip("/") + "/"
    port = int(container["port"])
    gateway_token = str(container.get("gateway_token") or user["gateway_token"])
    ws_url = f"{GATEWAY_WS_SCHEME}://{GATEWAY_WS_HOST}:{port}"
    return f"{base}?url={ws_url}#token={gateway_token}"
