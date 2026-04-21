from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DEFAULT_ENV_BASE_FILE = Path(__file__).resolve().parent / "env.base"


def resolve_env_base_file(argv: list[str]) -> Path:
    env_file = os.environ.get("OPENCLAW_ENV_BASE_FILE")
    if env_file:
        return Path(env_file)

    for index, arg in enumerate(argv):
        if arg == "--env-file" and index + 1 < len(argv):
            return Path(argv[index + 1])
        if arg.startswith("--env-file="):
            return Path(arg.split("=", 1)[1])

    return DEFAULT_ENV_BASE_FILE


ENV_BASE_FILE = resolve_env_base_file(sys.argv[1:])


def load_env_base(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            os.environ.setdefault(key, value)


load_env_base(ENV_BASE_FILE)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the OpenClaw multi-instance web application.")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"), help="Bind host")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5050")), help="Bind port")
    parser.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        default=os.environ.get("FLASK_DEBUG", "1") not in {"0", "false", "False"},
        help="Run Flask in debug mode",
    )
    parser.add_argument("--no-debug", dest="debug", action="store_false", help="Disable Flask debug mode")
    parser.add_argument(
        "--env-file",
        default=str(ENV_BASE_FILE),
        help="Environment file loaded before app startup",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)
