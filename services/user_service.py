from __future__ import annotations

import secrets
import sqlite3
import re
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from models import user_model
from services.command_service import AppError

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,62}[a-z0-9]$")


def normalize_username(username: str) -> str:
    cleaned = (username or "").strip().lower()
    if not cleaned:
        raise AppError("Username zorunludur.")
    if not USERNAME_PATTERN.fullmatch(cleaned):
        raise AppError("Username sadece kucuk harf, rakam, nokta, alt cizgi ve tire icerebilir.")
    return cleaned


def build_volume_name(username: str) -> str:
    return f"{normalize_username(username)}-volume"


def generate_gateway_token() -> str:
    return secrets.token_urlsafe(24)


def create_user_from_form(form: dict[str, str]) -> dict[str, Any]:
    username = normalize_username(form.get("username") or "")
    password = (form.get("password") or "").strip()
    openrouter_api_key = (form.get("openrouter_api_key") or "").strip()
    openrouter_api_key2 = (form.get("openrouter_api_key2") or "").strip() or None

    if not password:
        raise AppError("Password zorunludur.")
    if not openrouter_api_key:
        raise AppError("OpenRouter API Key zorunludur.")
    if user_model.is_username_taken(username):
        raise AppError("Bu username zaten kayıtlı.")

    try:
        return user_model.create_user(
            username=username,
            password_hash=generate_password_hash(password),
            openrouter_api_key=openrouter_api_key,
            openrouter_api_key2=openrouter_api_key2,
            volume_name=build_volume_name(username),
            gateway_token=generate_gateway_token(),
        )
    except sqlite3.IntegrityError as exc:
        if user_model.is_unique_violation(exc):
            raise AppError("Kullanıcı oluşturulamadı: benzersiz alan çakıştı.") from exc
        raise


def rollback_user_creation(user_id: int) -> None:
    user_model.delete_user_with_related_rows(user_id)


def update_user_account_from_form(user: dict[str, Any], form: dict[str, str]) -> dict[str, Any]:
    password = (form.get("password") or "").strip()
    openrouter_api_key = (form.get("openrouter_api_key") or "").strip()
    openrouter_api_key2 = (form.get("openrouter_api_key2") or "").strip()

    password_hash = generate_password_hash(password) if password else None
    primary_key = openrouter_api_key or None
    secondary_key = openrouter_api_key2 or None

    if password_hash is None and primary_key is None and secondary_key is None:
        raise AppError("Guncellenecek en az bir alan girin.")

    user_model.update_user_account(
        int(user["id"]),
        password_hash=password_hash,
        openrouter_api_key=primary_key,
        openrouter_api_key2=secondary_key,
    )
    refreshed = user_model.get_user_by_id(int(user["id"]))
    if refreshed is None:
        raise AppError("Kullanici kaydi okunamadi.")
    return refreshed


def authenticate_user(username: str, password: str) -> dict[str, Any]:
    user = user_model.get_user_by_username(normalize_username(username))
    if user is None or not user.get("is_active"):
        raise AppError("Kullanıcı bulunamadı veya pasif.")
    if not check_password_hash(user["password_hash"], password or ""):
        raise AppError("Username veya password hatalı.")
    return user


def mark_user_logged_in(user_id: int, *, gateway_url: str | None = None) -> None:
    user_model.update_user_runtime(user_id, gateway_url=gateway_url, last_login=True)


def mark_user_volume_prepared(user_id: int) -> None:
    user_model.update_user_runtime(user_id, volume_prepared=True)


def sync_user_provisioning(user_id: int, *, volume_name: str, gateway_token: str) -> None:
    user_model.update_user_provisioning(
        user_id,
        volume_name=volume_name,
        gateway_token=gateway_token,
    )
    user_model.update_user_runtime(user_id, volume_prepared=True)
