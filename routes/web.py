from __future__ import annotations

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, session, url_for

import db
from models.container_model import get_assigned_container_for_user, list_containers
from models.user_model import get_user_by_id, list_users
from services.admin_service import delete_user_stack, start_container, stop_container
from services.command_service import AppError
from services.container_service import assign_container_to_user, provision_container_for_user
from services.device_service import approve_latest_device
from services.gateway_service import build_gateway_redirect_url
from services.user_service import (
    authenticate_user,
    create_user_from_form,
    mark_user_logged_in,
    rollback_user_creation,
    update_user_account_from_form,
)

web_bp = Blueprint("web", __name__)


@web_bp.before_app_request
def ensure_db_ready() -> None:
    db.init_db()


@web_bp.get("/")
def home() -> str:
    return render_template("login.html")


@web_bp.post("/register")
def register() -> Response:
    user = None
    try:
        user = create_user_from_form(request.form)
        container = provision_container_for_user(user)
        redirect_url = build_gateway_redirect_url(user, container)
        mark_user_logged_in(int(user["id"]), gateway_url=redirect_url)
        return build_launch_response(user, container, redirect_url)
    except Exception as exc:
        if user is not None:
            try:
                rollback_user_creation(int(user["id"]))
            except Exception:
                pass
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
        return build_launch_response(user, assignment.container, redirect_url)
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
    user = None
    try:
        user = create_user_from_form(request.form)
        container = provision_container_for_user(user)
        flash(
            f"Kullanıcı oluşturuldu: {user['username']} | container={container['container_name']} | port={container['port']}",
            "success",
        )
    except Exception as exc:
        if user is not None:
            try:
                rollback_user_creation(int(user["id"]))
            except Exception:
                pass
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
        return build_launch_response(user, assignment.container, redirect_url)
    except Exception as exc:
        flash(safe_user_error(exc), "error")
        return redirect(url_for("web.admin_dashboard"))


@web_bp.post("/admin/users/<int:user_id>/delete")
def delete_user(user_id: int) -> Response:
    try:
        delete_user_stack(user_id)
        flash("Kullanici, container ve volume silindi.", "success")
    except Exception as exc:
        flash(safe_user_error(exc), "error")
    return redirect(url_for("web.admin_dashboard"))


@web_bp.get("/me")
def profile_page() -> Response | str:
    user = get_current_user_or_redirect()
    if isinstance(user, Response):
        return user
    container = get_assigned_container_for_user(int(user["id"]))
    launch_gateway = request.args.get("launch") == "1"
    return render_template(
        "profile.html",
        user=user,
        container=container,
        gateway_url=session.get("gateway_url") or user.get("gateway_url"),
        launch_gateway=launch_gateway,
    )


@web_bp.post("/me/account")
def update_account() -> Response:
    user = get_current_user_or_redirect()
    if isinstance(user, Response):
        return user
    try:
        refreshed = update_user_account_from_form(user, request.form)
        flash("Hesap bilgileri guncellendi.", "success")
        return redirect(url_for("web.profile_page"))
    except Exception as exc:
        flash(safe_user_error(exc), "error")
        return redirect(url_for("web.profile_page"))


@web_bp.post("/me/devices/approve-latest")
def approve_latest_pairing() -> Response:
    user = get_current_user_or_redirect()
    if isinstance(user, Response):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    container = get_assigned_container_for_user(int(user["id"]))
    if container is None or not container.get("project_name"):
        return jsonify({"ok": True, "approved": False})
    try:
        approve_latest_device(str(container["project_name"]), instance_id=container.get("instance_id"))
    except Exception:
        # No pending device or CLI output should not disturb the user flow.
        return jsonify({"ok": True, "approved": False})
    return jsonify({"ok": True, "approved": True})


@web_bp.post("/admin/containers/<int:container_id>/start")
def start_container_action(container_id: int) -> Response:
    try:
        start_container(container_id)
        flash("Container baslatildi.", "success")
    except Exception as exc:
        flash(safe_user_error(exc), "error")
    return redirect(_redirect_back_default("web.admin_dashboard"))


@web_bp.post("/admin/containers/<int:container_id>/stop")
def stop_container_action(container_id: int) -> Response:
    try:
        stop_container(container_id)
        flash("Container durduruldu.", "success")
    except Exception as exc:
        flash(safe_user_error(exc), "error")
    return redirect(_redirect_back_default("web.admin_dashboard"))


@web_bp.get("/admin/containers")
def containers_page() -> str:
    containers = list_containers()
    return render_template("containers.html", containers=containers)


def safe_user_error(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return str(exc)
    return f"Islem basarisiz. Detaylar loglarda bulunabilir. ({type(exc).__name__})"


def build_launch_response(user: dict, container: dict, redirect_url: str) -> Response:
    session["user_id"] = int(user["id"])
    session["gateway_url"] = redirect_url
    return Response(
        render_template(
            "session_launch.html",
            gateway_url=redirect_url,
            profile_url=url_for("web.profile_page", launch=1),
            username=user["username"],
            container_name=container["container_name"],
        )
    )


def get_current_user_or_redirect() -> dict | Response:
    user_id = session.get("user_id")
    if not user_id:
        flash("Oturum bulunamadi. Lutfen tekrar giris yapin.", "error")
        return redirect(url_for("web.home"))
    user = get_user_by_id(int(user_id))
    if user is None:
        session.pop("user_id", None)
        session.pop("gateway_url", None)
        flash("Kullanici bulunamadi. Lutfen tekrar giris yapin.", "error")
        return redirect(url_for("web.home"))
    return user


def _redirect_back_default(endpoint: str) -> str:
    return request.referrer or url_for(endpoint)
