from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
NGINX_OUT_DIR = Path(os.environ.get("OPENCLAW_NGINX_OUT_DIR", BASE_DIR / "generated" / "nginx"))
BASE_DOMAIN = os.environ.get("OPENCLAW_BASE_DOMAIN", "mebsclaw.com").strip()


@dataclass(frozen=True)
class DomainResolution:
    domain_short: str
    domain_full: str


def resolve_domain(input_value: str) -> DomainResolution:
    raw = (input_value or "").strip().lower().rstrip(".")
    if not raw:
        raise ValueError("Domain/subdomain is required.")

    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*", raw):
        raise ValueError("Invalid domain/subdomain format.")

    if "." in raw:
        return DomainResolution(domain_short=raw.split(".")[0], domain_full=raw)
    return DomainResolution(domain_short=raw, domain_full=f"{raw}.{BASE_DOMAIN}")


def _safe_server_name(domain_full: str) -> str:
    normalized = domain_full.strip().lower().rstrip(".")
    if not normalized:
        raise ValueError("Invalid domain format.")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*", normalized):
        raise ValueError("Invalid domain format.")
    return normalized


def generate_vhost_config(*, domain_full: str, gateway_port: int) -> Path:
    server_name = _safe_server_name(domain_full)
    NGINX_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = NGINX_OUT_DIR / f"{server_name}.conf"
    content = f"""server {{
    listen 80;
    server_name {server_name};

    location / {{
        proxy_pass http://127.0.0.1:{gateway_port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""
    out_path.write_text(content, encoding="utf-8")
    return out_path
