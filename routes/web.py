from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, session, url_for

import db
from models.container_model import get_assigned_container_for_user, list_containers
from models.user_model import get_user_by_id, list_users
from services.admin_service import (
    delete_user_stack,
    get_image_update_log_snapshot,
    rebuild_current_image,
    start_current_image_rebuild,
    start_container,
    stop_container,
    update_container_to_current_image,
)
from services.command_service import AppError
from services.container_service import assign_container_to_user, provision_container_for_user
from services.device_service import approve_latest_device
from services.gateway_service import build_gateway_redirect_url
from services.log_service import write_exception_log
from services.user_service import (
    authenticate_user,
    create_user_from_form,
    mark_user_logged_in,
    rollback_user_creation,
    update_user_account_from_form,
)
from services.version_service import get_current_image_state, image_refs_match, list_available_images, versions_match

web_bp = Blueprint("web", __name__)


@web_bp.before_app_request
def ensure_db_ready() -> None:
    db.init_db()


@web_bp.get("/")
def home() -> str:
    return render_template("home.html")


@web_bp.get("/login")
def login_page() -> str:
    return render_template("login.html")


@web_bp.get("/signin")
def signin_page() -> str:
    return render_template(
        "signin.html",
        current_image=get_current_image_state(),
        available_images=list_available_images(),
    )


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
        _log_web_exception("web-register-error", exc)
        if user is not None:
            try:
                rollback_user_creation(int(user["id"]))
            except Exception:
                pass
        flash(safe_user_error(exc), "error")
        return redirect(url_for("web.signin_page"))


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
        _log_web_exception("web-login-error", exc)
        flash(safe_user_error(exc), "error")
        return redirect(url_for("web.login_page"))


@web_bp.get("/admin")
def admin_dashboard() -> str:
    users = list_users()
    containers = list_containers()
    current_image = get_current_image_state()
    available_images = list_available_images()
    image_log_snapshot = get_image_update_log_snapshot()
    return render_template(
        "admin.html",
        users=users,
        containers=containers,
        current_image=current_image,
        available_images=available_images,
        image_log_snapshot=image_log_snapshot,
        stats={
            "user_count": len(users),
            "active_users": sum(1 for user in users if user.get("is_active")),
            "container_count": len(containers),
            "busy_containers": sum(1 for container in containers if container.get("assigned_user_id")),
            "current_image_version": current_image.version,
            "outdated_containers": sum(
                1
                for container in containers
                if container.get("id")
                and (
                    not versions_match(container.get("image_version"), current_image.version)
                    or not image_refs_match(container.get("image_ref"), current_image.image_ref)
                )
            ),
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
        _log_web_exception("web-admin-create-user-error", exc)
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
        _log_web_exception("web-launch-session-error", exc)
        flash(safe_user_error(exc), "error")
        return redirect(url_for("web.admin_dashboard"))


@web_bp.post("/admin/users/<int:user_id>/delete")
def delete_user(user_id: int) -> Response:
    try:
        delete_user_stack(user_id)
        flash("Kullanici, container ve volume silindi.", "success")
    except Exception as exc:
        _log_web_exception("web-delete-user-error", exc)
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
        _log_web_exception("web-update-account-error", exc)
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
        _log_web_exception("web-start-container-error", exc)
        flash(safe_user_error(exc), "error")
    return redirect(_redirect_back_default("web.admin_dashboard"))


@web_bp.post("/admin/image/update")
def update_image_action() -> Response:
    try:
        result = rebuild_current_image()
        flash(f"Image guncellendi. Ref: {result['image_ref']} | Version: {result['version']}", "success")
    except Exception as exc:
        _log_web_exception("web-image-update-error", exc)
        flash(safe_user_error(exc), "error")
    return redirect(url_for("web.admin_dashboard"))


@web_bp.post("/admin/image/update/start")
def start_image_update_action() -> Response:
    try:
        result = start_current_image_rebuild()
        return jsonify({"ok": True, **result})
    except Exception as exc:
        _log_web_exception("web-image-update-start-error", exc)
        return jsonify({"ok": False, "error": safe_user_error(exc)}), 500


@web_bp.get("/admin/image/logs")
def image_logs_api() -> Response:
    raw_log_id = (request.args.get("log_id") or "").strip()
    log_id = None
    if raw_log_id:
        try:
            log_id = int(raw_log_id)
        except ValueError:
            return jsonify({"ok": False, "error": "Gecersiz log_id"}), 400
    snapshot = get_image_update_log_snapshot(log_id=log_id)
    return jsonify({"ok": True, **snapshot})


@web_bp.post("/admin/containers/<int:container_id>/update")
def update_container_action(container_id: int) -> Response:
    try:
        result = update_container_to_current_image(container_id)
        if result["updated"]:
            flash(
                f"Container guncellendi. Version: {result['version']}",
                "success",
            )
        else:
            flash("Container zaten guncel.", "success")
    except Exception as exc:
        _log_web_exception("web-container-update-error", exc)
        flash(safe_user_error(exc), "error")
    return redirect(_redirect_back_default("web.admin_dashboard"))


@web_bp.post("/admin/containers/<int:container_id>/stop")
def stop_container_action(container_id: int) -> Response:
    try:
        stop_container(container_id)
        flash("Container durduruldu.", "success")
    except Exception as exc:
        _log_web_exception("web-stop-container-error", exc)
        flash(safe_user_error(exc), "error")
    return redirect(_redirect_back_default("web.admin_dashboard"))


@web_bp.get("/admin/containers")
def containers_page() -> str:
    containers = list_containers()
    return render_template(
        "containers.html",
        containers=containers,
        current_image=get_current_image_state(),
        available_images=list_available_images(),
    )


def safe_user_error(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return str(exc)
    return f"Islem basarisiz. Hata kaydi olusturuldu. ({type(exc).__name__})"


def _log_web_exception(action_type: str, exc: Exception) -> Path:
    return write_exception_log(
        action_type,
        exc,
        context={
            "method": request.method,
            "path": request.path,
            "remote_addr": request.headers.get("X-Forwarded-For") or request.remote_addr or "",
            "user_agent": request.user_agent.string if request.user_agent else "",
        },
    )


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
        return redirect(url_for("web.login_page"))
    user = get_user_by_id(int(user_id))
    if user is None:
        session.pop("user_id", None)
        session.pop("gateway_url", None)
        flash("Kullanici bulunamadi. Lutfen tekrar giris yapin.", "error")
        return redirect(url_for("web.login_page"))
    return user


def _redirect_back_default(endpoint: str) -> str:
    return request.referrer or url_for(endpoint)
