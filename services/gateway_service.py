from __future__ import annotations

import os
from typing import Any


GATEWAY_PUBLIC_BASE = os.environ.get("OPENCLAW_GATEWAY_PUBLIC_BASE", "https://mebs.claw/")
GATEWAY_WS_SCHEME = os.environ.get("OPENCLAW_GATEWAY_WS_SCHEME", "ws")


def build_gateway_redirect_url(user: dict[str, Any], container: dict[str, Any]) -> str:
    base = GATEWAY_PUBLIC_BASE.rstrip("/") + "/"
    ws_host = str(container.get("host") or "mebs.claw")
    port = int(container["port"])
    gateway_token = str(user["gateway_token"])
    token_value = f"{GATEWAY_WS_SCHEME}://{ws_host}:{port};{gateway_token}"
    return f"{base}?token={token_value}"
