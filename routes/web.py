from __future__ import annotations

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

import db
from models.container_model import list_containers
from models.user_model import get_user_by_id, list_users
from services.command_service import AppError
from services.container_service import assign_container_to_user, provision_container_for_user
from services.gateway_service import build_gateway_redirect_url
from services.user_service import authenticate_user, create_user_from_form, mark_user_logged_in

web_bp = Blueprint("web", __name__)


@web_bp.before_app_request
def ensure_db_ready() -> None:
    db.init_db()


@web_bp.get("/")
def home() -> str:
    return render_template("login.html")


@web_bp.post("/register")
def register() -> Response:
    try:
        user = create_user_from_form(request.form)
        container = provision_container_for_user(user)
        redirect_url = build_gateway_redirect_url(user, container)
        mark_user_logged_in(int(user["id"]), gateway_url=redirect_url)
        return redirect(redirect_url, code=302)
    except Exception as exc:
        flash(safe_user_error(exc), "error")
        return redirect(url_for("web.home"))


@web_bp.post("/login")
def login() -> Response:
    try:
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = authenticate_user(username, password)
        assignment = assign_container_to_user(user)
        redirect_url = build_gateway_redirect_url(user, assignment.container)
        mark_user_logged_in(int(user["id"]), gateway_url=redirect_url)
        return redirect(redirect_url, code=302)
    except Exception as exc:
        flash(safe_user_error(exc), "error")
        return redirect(url_for("web.home"))


@web_bp.get("/admin")
def admin_dashboard() -> str:
    users = list_users()
    containers = list_containers()
    return render_template(
        "admin.html",
        users=users,
        containers=containers,
        stats={
            "user_count": len(users),
            "active_users": sum(1 for user in users if user.get("is_active")),
            "container_count": len(containers),
            "busy_containers": sum(1 for container in containers if container.get("assigned_user_id")),
        },
    )


@web_bp.post("/admin/users")
def create_user() -> Response:
    try:
        user = create_user_from_form(request.form)
        container = provision_container_for_user(user)
        flash(
            f"Kullanıcı oluşturuldu: {user['username']} | container={container['container_name']} | port={container['port']}",
            "success",
        )
    except Exception as exc:
        flash(safe_user_error(exc), "error")
    return redirect(url_for("web.admin_dashboard"))


@web_bp.post("/admin/users/<int:user_id>/launch")
def launch_user_session(user_id: int) -> Response:
    try:
        user = get_user_by_id(user_id)
        if user is None:
            raise AppError("Kullanıcı bulunamadı.")
        assignment = assign_container_to_user(user)
        redirect_url = build_gateway_redirect_url(user, assignment.container)
        mark_user_logged_in(int(user["id"]), gateway_url=redirect_url)
        return redirect(redirect_url, code=302)
    except Exception as exc:
        flash(safe_user_error(exc), "error")
        return redirect(url_for("web.admin_dashboard"))


@web_bp.get("/admin/containers")
def containers_page() -> str:
    containers = list_containers()
    return render_template("containers.html", containers=containers)


def safe_user_error(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return str(exc)
    return f"Islem basarisiz. Detaylar loglarda bulunabilir. ({type(exc).__name__})"
