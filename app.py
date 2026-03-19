from __future__ import annotations

import os

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
