from __future__ import annotations

import os
from pathlib import Path

ENV_BASE_FILE = Path(os.environ.get("OPENCLAW_ENV_BASE_FILE", Path(__file__).resolve().parent / "env.base"))


def load_env_base() -> None:
    if not ENV_BASE_FILE.is_file():
        return
    for raw_line in ENV_BASE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            os.environ.setdefault(key, value)


load_env_base()
if "OPENCLAW_GATEWAY_PUBLIC_BASE" not in os.environ and os.environ.get("DOMAIN"):
    os.environ["OPENCLAW_GATEWAY_PUBLIC_BASE"] = f"https://{os.environ['DOMAIN'].strip('/')}/"
if "OPENCLAW_GATEWAY_HOST" not in os.environ and os.environ.get("DOMAIN"):
    os.environ["OPENCLAW_GATEWAY_HOST"] = os.environ["DOMAIN"]

from flask import Flask

import db
from routes import web_bp

SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "change-me-in-production")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY
    db.init_db()
    app.register_blueprint(web_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5050")), debug=True)
