from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, url_for

import db
from db import get_conn
from services.command_service import AppError
from services.device_service import approve_device, list_devices
from services.docker_service import (
    compose_down_and_remove_volume,
    compose_stop,
    compose_up,
    docker_network_prune,
    docker_volume_rm,
    get_project_status,
    inspect_project_text,
)
from services.nginx_service import generate_vhost_config, resolve_domain
from services.version_service import get_openclaw_version
from services.command_service import run_cmd_logged

BASE_DIR = Path(__file__).resolve().parent
DEPLOY_SCRIPT = Path(os.environ.get("OPENCLAW_DEPLOY_SCRIPT", BASE_DIR / "deploy_openclaw.sh"))
UPDATE_SCRIPT = Path(os.environ.get("OPENCLAW_UPDATE_SCRIPT", BASE_DIR / "update_openclaw.sh"))
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "change-me-in-production")
# Default OpenClaw version for new instances (image version).
DEFAULT_OPENCLAW_VERSION = os.environ.get("OPENCLAW_DEFAULT_VERSION", "2026.3.2")


def _bash_script_path(script_path: Path) -> str:
    """
    On Windows, 'bash' may be provided by WSL (can't see C:\\ paths).
    Using a repo-relative path works for Git-Bash and for bash running in the same filesystem context.
    """
    try:
        rel = script_path.resolve().relative_to(BASE_DIR.resolve())
        return f"./{rel.as_posix()}"
    except Exception:
        return str(script_path)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY

    @app.get("/")
    def index() -> str:
        db.init_db()
        instances = fetch_instances()
        info = get_openclaw_version(DEFAULT_OPENCLAW_VERSION)
        latest = info.image_version or info.default_version
        return render_template("index.html", instances=instances, default_version=latest)

    @app.post("/instances/create")
    def create_instance() -> Response:
        try:
            msg = create_instance_from_form(request.form)
            flash(msg, "success")
        except Exception as exc:
            flash(safe_user_error(exc), "error")
        return redirect(url_for("index"))

    @app.post("/instances/<int:instance_id>/delete")
    def delete_instance(instance_id: int) -> Response:
        try:
            instance = get_instance(instance_id)
            output = delete_instance_resources(instance)
            flash(f"Instance silindi. {compact_text(output)}", "success")
        except Exception as exc:
            flash(safe_user_error(exc), "error")
        return redirect(url_for("index"))

    @app.post("/instances/<int:instance_id>/start")
    def start_instance(instance_id: int) -> Response:
        try:
            instance = get_instance(instance_id)
            output = compose_up(instance["project_name"], instance_id=instance_id)
            flash(f"Start tamamlandı. {compact_text(output)}", "success")
        except Exception as exc:
            flash(safe_user_error(exc), "error")
        return redirect(url_for("index"))

    @app.post("/instances/<int:instance_id>/stop")
    def stop_instance(instance_id: int) -> Response:
        try:
            instance = get_instance(instance_id)
            output = compose_stop(instance["project_name"], instance_id=instance_id)
            flash(f"Stop tamamlandı. {compact_text(output)}", "success")
        except Exception as exc:
            flash(safe_user_error(exc), "error")
        return redirect(url_for("index"))

    @app.post("/instances/<int:instance_id>/update")
    def update_instance(instance_id: int) -> Response:
        try:
            instance = get_instance(instance_id)
            if not UPDATE_SCRIPT.exists():
                raise AppError(f"Update script bulunamadı: {UPDATE_SCRIPT}")
            # update script reads DB and recreates in-place
            result = run_cmd_logged(
                ["bash", _bash_script_path(UPDATE_SCRIPT), "--instance-id", str(instance_id)],
                instance_id=instance_id,
                action_type="update",
                check=False,
            )
            if result.ok:
                # Refresh version from the updated image and persist it.
                info = get_openclaw_version(instance.get("version") or DEFAULT_OPENCLAW_VERSION)
                new_version = info.image_version or info.default_version
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE instances SET version = ?, last_update_check_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_version, instance_id),
                    )
                    conn.commit()
                flash(f"Güncelleme tamamlandı. {compact_text(result.stdout or '')}", "success")
            else:
                raise AppError(f"Güncelleme başarısız. Log: {result.log_file_path}")
        except Exception as exc:
            flash(safe_user_error(exc), "error")
        return redirect(url_for("index"))

    @app.get("/instances/<int:instance_id>/go")
    def go_domain(instance_id: int) -> Response:
        instance = get_instance(instance_id)
        domain = (instance["domain"] or "").strip()
        target = domain if domain.startswith("http://") or domain.startswith("https://") else f"https://{domain}"
        return redirect(target, code=302)

    @app.get("/api/instances/<int:instance_id>/devices")
    def api_devices(instance_id: int) -> Response:
        instance = get_instance(instance_id)
        devices, raw = list_devices(instance["project_name"], instance_id=instance_id)
        return jsonify(
            {
                "instance_id": instance_id,
                "devices": [d.__dict__ for d in devices],
                "raw": raw,
            }
        )

    @app.post("/api/instances/<int:instance_id>/devices/approve")
    def api_devices_approve(instance_id: int) -> Response:
        instance = get_instance(instance_id)
        data = request.get_json(silent=True) or {}
        device_id = str(data.get("device_id", "")).strip()
        if not device_id:
            return jsonify({"ok": False, "error": "device_id is required"}), 400
        out = approve_device(instance["project_name"], device_id, instance_id=instance_id)
        return jsonify({"ok": True, "output": out})

    @app.get("/api/instances/<int:instance_id>/logs")
    def api_instance_logs(instance_id: int) -> Response:
        db.init_db()
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, action_type, log_file_path, status, created_at
                FROM operation_logs
                WHERE instance_id = ?
                ORDER BY id DESC
                LIMIT 30
                """,
                (instance_id,),
            ).fetchall()
        return jsonify({"instance_id": instance_id, "logs": [dict(r) for r in rows]})

    @app.get("/api/logs/<int:log_id>")
    def api_log_content(log_id: int) -> Response:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id, log_file_path FROM operation_logs WHERE id = ?",
                (log_id,),
            ).fetchone()
        if row is None:
            return jsonify({"ok": False, "error": "log not found"}), 404
        path = Path(row["log_file_path"])
        # only allow reading logs under repo logs directory
        repo_logs = (BASE_DIR / "logs").resolve()
        try:
            resolved = path.resolve()
            if repo_logs not in resolved.parents and resolved != repo_logs:
                return jsonify({"ok": False, "error": "access denied"}), 403
        except Exception:
            return jsonify({"ok": False, "error": "invalid path"}), 400
        if not path.exists():
            return jsonify({"ok": False, "error": "file missing"}), 404
        text = path.read_text(encoding="utf-8", errors="replace")
        return jsonify({"ok": True, "content": text})

    @app.get("/api/version")
    def api_version() -> Response:
        info = get_openclaw_version(DEFAULT_OPENCLAW_VERSION)
        return jsonify(
            {
                "default_version": info.default_version,
                "image_version": info.image_version or info.default_version,
            }
        )

    return app


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def fetch_instances() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                id, domain, domain_short, project_name, volume_name,
                gateway_port, bridge_port, version,
                channel_choice, channel_bot_token,
                allow_from, token, openrouter_token,
                created_at, image, current_image_id, last_update_check_at
            FROM instances
            ORDER BY id DESC
            """
        ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["container_state"] = get_project_status(item["project_name"])
        safe = dict(item)
        safe["channel_bot_token"] = mask_secret(safe.get("channel_bot_token"))
        safe["openrouter_token"] = mask_secret(safe.get("openrouter_token"))
        safe["token"] = mask_secret(safe.get("token"))
        item["details_json"] = json.dumps(safe, ensure_ascii=False, indent=2)
        item["docker_info"] = inspect_project_text(item["project_name"])
        items.append(item)
    return items


def get_instance(instance_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
    if row is None:
        raise AppError("Instance bulunamadı.")
    return dict(row)


def create_instance_from_form(form: dict[str, str]) -> str:
    if not DEPLOY_SCRIPT.exists():
        raise AppError(f"Deploy script bulunamadı: {DEPLOY_SCRIPT}")

    core_domain = (form.get("domain") or "").strip()
    resolved = resolve_domain(core_domain)

    openrouter_api_key = (form.get("openrouter_api_key") or "").strip()
    if not openrouter_api_key:
        raise AppError("OpenRouter API Key zorunludur.")

    telegram_bot_token = (form.get("telegram_bot_token") or "").strip()
    telegram_allow_from = (form.get("telegram_allow_from") or "").strip()

    cmd = [
        "bash",
        _bash_script_path(DEPLOY_SCRIPT),
        "--domain",
        resolved.domain_full,
        "--openrouter-api-key",
        openrouter_api_key,
        "--gateway-bind",
        (form.get("gateway_bind") or "lan").strip() or "lan",
    ]

    gateway_token = (form.get("gateway_token") or "").strip()
    if gateway_token:
        cmd.extend(["--gateway-token", gateway_token])

    raw_version = (form.get("version") or "").strip()
    if raw_version:
        version = raw_version
    else:
        info = get_openclaw_version(DEFAULT_OPENCLAW_VERSION)
        version = info.image_version or info.default_version
    cmd.extend(["--version", version])

    # Telegram is now optional: only pass when both are provided.
    if telegram_bot_token and telegram_allow_from:
        cmd.extend(["--telegram-bot-token", telegram_bot_token, "--telegram-allow-from", telegram_allow_from])

    result = run_cmd_logged(cmd, action_type="deploy", check=True)

    # Best-effort: store domain_short + generate nginx config after success.
    with get_conn() as conn:
        conn.execute(
            "UPDATE instances SET domain_short = ? WHERE domain = ?",
            (resolved.domain_short, resolved.domain_full),
        )
        conn.commit()

        row = conn.execute("SELECT id, gateway_port FROM instances WHERE domain = ?", (resolved.domain_full,)).fetchone()
        if row is not None:
            generate_vhost_config(domain_full=resolved.domain_full, gateway_port=int(row["gateway_port"]))

    return "Instance oluşturuldu."


def delete_instance_resources(instance: dict[str, Any]) -> str:
    instance_id = int(instance["id"])
    project_name = instance["project_name"]
    volume_name = instance["volume_name"]

    compose_out = compose_down_and_remove_volume(project_name, instance_id=instance_id)
    net_out = docker_network_prune(instance_id=instance_id)
    vol_out = docker_volume_rm(volume_name, instance_id=instance_id)

    with get_conn() as conn:
        conn.execute("DELETE FROM instances WHERE id = ?", (instance_id,))
        conn.commit()

    return "\n\n".join(
        [
            f"docker compose down çıktı:\n{compose_out or '-'}",
            f"docker network prune çıktı:\n{net_out or '-'}",
            f"docker volume rm çıktı:\n{vol_out or '-'}",
        ]
    )


def compact_text(text: str, limit: int = 220) -> str:
    one_line = " ".join((text or "").split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


def safe_user_error(exc: Exception) -> str:
    # Keep sensitive output out of flash messages; logs contain details.
    if isinstance(exc, AppError):
        return str(exc)
    return f"İşlem başarısız. Detaylar loglara yazıldı. ({type(exc).__name__})"


app = create_app()


if __name__ == "__main__":
    db.init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5050")), debug=True)

