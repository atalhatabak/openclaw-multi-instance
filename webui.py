from __future__ import annotations

import html
import json
import os
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from flask import Flask, Response, flash, redirect, render_template_string, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("OPENCLAW_DB_PATH", BASE_DIR / "openclaw_instances.db"))
DEPLOY_SCRIPT = Path(os.environ.get("OPENCLAW_DEPLOY_SCRIPT", BASE_DIR / "deploy_openclaw.sh"))
DELETE_SCRIPT = Path(os.environ.get("OPENCLAW_DELETE_SCRIPT", BASE_DIR / "delete_openclaw.sh"))
DOCKER_COMPOSE_FILE = Path(os.environ.get("OPENCLAW_COMPOSE_FILE", BASE_DIR / "docker-compose.yml"))
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "change-me-in-production")

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL UNIQUE,
    project_name TEXT NOT NULL UNIQUE,
    volume_name TEXT NOT NULL UNIQUE,
    gateway_port INTEGER NOT NULL UNIQUE,
    bridge_port INTEGER NOT NULL UNIQUE,
    version TEXT NOT NULL,
    channel_choice TEXT NOT NULL DEFAULT 'telegram',
    channel_bot_token TEXT,
    allow_from TEXT,
    token TEXT NOT NULL,
    openrouter_token TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_instances_domain ON instances(domain);
CREATE INDEX IF NOT EXISTS idx_instances_gateway_port ON instances(gateway_port);
CREATE INDEX IF NOT EXISTS idx_instances_bridge_port ON instances(bridge_port);
"""


PAGE_TEMPLATE = """
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenClaw Admin</title>
  <style>
    :root {
      --bg: #0b1020;
      --panel: #131a2f;
      --panel-2: #0f1528;
      --text: #e8ecf7;
      --muted: #9fb0d1;
      --line: #273355;
      --primary: #6ea8fe;
      --danger: #ff6b6b;
      --warn: #ffd166;
      --success: #7bd88f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: linear-gradient(180deg, #0a0f1d 0%, #10172b 100%);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    }
    .wrap {
      width: min(1280px, calc(100% - 32px));
      margin: 24px auto 48px;
    }
    .hero {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 24px;
    }
    .hero h1 { margin: 0; font-size: 28px; }
    .hero p { margin: 6px 0 0; color: var(--muted); }
    .grid {
      display: grid;
      grid-template-columns: 420px 1fr;
      gap: 20px;
    }
    .card {
      background: rgba(19, 26, 47, 0.95);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 18px 50px rgba(0, 0, 0, 0.2);
      overflow: hidden;
    }
    .card .head {
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,0.02);
    }
    .card .head h2, .card .head h3 { margin: 0; font-size: 18px; }
    .card .body { padding: 18px; }
    label {
      display: block;
      margin-bottom: 14px;
      font-size: 13px;
      color: var(--muted);
    }
    input, select, textarea {
      width: 100%;
      margin-top: 6px;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px 14px;
      font-size: 14px;
      color: var(--text);
      background: var(--panel-2);
      outline: none;
    }
    input:focus, select:focus, textarea:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(110, 168, 254, 0.15);
    }
    .btn-row { display: flex; gap: 10px; flex-wrap: wrap; }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      text-decoration: none;
      cursor: pointer;
      border: 0;
      border-radius: 12px;
      padding: 11px 14px;
      font-weight: 600;
      font-size: 14px;
      color: white;
      background: #3454d1;
    }
    .btn.secondary { background: #2a365d; }
    .btn.warn { background: #8b6b18; }
    .btn.danger { background: #932f3b; }
    .btn.success { background: #1c7c54; }
    .btn.ghost {
      background: transparent;
      border: 1px solid var(--line);
      color: var(--text);
    }
    .instances {
      display: grid;
      gap: 14px;
    }
    .instance {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(15, 21, 40, 0.85);
      padding: 16px;
    }
    .instance-top {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
      margin-bottom: 12px;
    }
    .instance h3 {
      margin: 0 0 4px;
      font-size: 18px;
    }
    .muted { color: var(--muted); }
    .meta {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .meta .kv {
      background: rgba(255,255,255,0.03);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
    }
    .kv .k {
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 4px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.04);
    }
    .details {
      margin-top: 10px;
      border-top: 1px dashed var(--line);
      padding-top: 12px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .details pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: rgba(255,255,255,0.03);
      border: 1px solid var(--line);
      padding: 12px;
      border-radius: 12px;
      margin: 0;
      color: #d8e2f7;
      max-height: 240px;
      overflow: auto;
    }
    .flash-wrap { display: grid; gap: 10px; margin-bottom: 18px; }
    .flash {
      border-radius: 14px;
      padding: 12px 14px;
      border: 1px solid var(--line);
    }
    .flash.success { background: rgba(28,124,84,0.2); border-color: rgba(123,216,143,0.25); }
    .flash.error { background: rgba(147,47,59,0.22); border-color: rgba(255,107,107,0.25); }
    .flash.info { background: rgba(52,84,209,0.18); border-color: rgba(110,168,254,0.25); }
    .small { font-size: 12px; }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 10px;
    }
    .toolbar form { display: inline-flex; }
    .note {
      margin-top: 12px;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.5;
    }
    @media (max-width: 1000px) {
      .grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 700px) {
      .meta, .details { grid-template-columns: 1fr; }
      .instance-top { flex-direction: column; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>
        <h1>OpenClaw Admin UI</h1>
        <p>Yeni instance oluştur, mevcutları görüntüle, başlat/durdur/sil işlemlerini tek sayfadan yönet.</p>
      </div>
      <div class="badge">{{ instances|length }} instance</div>
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        <div class="flash-wrap">
          {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}

    <div class="grid">
      <div class="card">
        <div class="head"><h2>Yeni Instance Oluştur</h2></div>
        <div class="body">
          <form method="post" action="{{ url_for('create_instance') }}">
            <label>Domain
              <input type="text" name="domain" placeholder="bot1.example.com" required>
            </label>
            <label>Telegram Bot Token
              <input type="text" name="telegram_bot_token" placeholder="123456:ABCDEF" required>
            </label>
            <label>Telegram Allow From
              <input type="text" name="telegram_allow_from" placeholder="905551112233 veya 455921257" required>
            </label>
            <label>OpenRouter API Key
              <input type="password" name="openrouter_api_key" placeholder="or-v1-..." required>
            </label>
            <label>Gateway Token
              <input type="text" name="gateway_token" placeholder="Boş bırakılırsa otomatik üretilir">
            </label>
            <label>Version
              <input type="text" name="version" value="latest">
            </label>
            <label>Gateway Bind
              <select name="gateway_bind">
                <option value="lan" selected>lan</option>
                <option value="local">local</option>
              </select>
            </label>
            <div class="btn-row">
              <button class="btn success" type="submit">Oluştur</button>
            </div>
            <div class="note">
              Bu form deploy scriptini çalıştırır. Script başarılı olursa kayıt veritabanında görünür. Domain yönlendirmesi için DNS ve reverse proxy tarafının ayrıca hazır olması gerekir.
            </div>
          </form>
        </div>
      </div>

      <div class="card">
        <div class="head"><h2>Instance Listesi</h2></div>
        <div class="body">
          <div class="instances">
            {% if not instances %}
              <div class="instance">
                <div class="muted">Henüz kayıt yok.</div>
              </div>
            {% endif %}

            {% for item in instances %}
              <div class="instance">
                <div class="instance-top">
                  <div>
                    <h3>{{ item['domain'] }}</h3>
                    <div class="muted">{{ item['project_name'] }}</div>
                  </div>
                  <div class="badge">{{ item.get('container_state', 'unknown') }}</div>
                </div>

                <div class="meta">
                  <div class="kv"><span class="k">Gateway Port</span>{{ item['gateway_port'] }}</div>
                  <div class="kv"><span class="k">Bridge Port</span>{{ item['bridge_port'] }}</div>
                  <div class="kv"><span class="k">Volume</span>{{ item['volume_name'] }}</div>
                  <div class="kv"><span class="k">Version</span>{{ item['version'] }}</div>
                  <div class="kv"><span class="k">Channel</span>{{ item['channel_choice'] }}</div>
                  <div class="kv"><span class="k">Created</span>{{ item['created_at'] }}</div>
                </div>

                <div class="toolbar">
                  <a class="btn ghost" href="{{ url_for('go_domain', instance_id=item['id']) }}" target="_blank">Domain'e Git</a>
                  <a class="btn ghost" href="http://127.0.0.1:{{ item['gateway_port'] }}/#token={{ item['token'] }}" target="_blank">Gateway UI</a>

                  <form method="post" action="{{ url_for('start_instance', instance_id=item['id']) }}">
                    <button class="btn secondary" type="submit">Start</button>
                  </form>

                  <form method="post" action="{{ url_for('stop_instance', instance_id=item['id']) }}">
                    <button class="btn warn" type="submit">Stop</button>
                  </form>

                  <form method="post" action="{{ url_for('update_instance', instance_id=item['id']) }}">
                    <button class="btn ghost" type="submit">Güncelle</button>
                  </form>

                  <form method="post" action="{{ url_for('delete_instance', instance_id=item['id']) }}" onsubmit="return confirm('Bu instance silinsin mi? Container, network, volume ve DB kaydı kaldırılacak.');">
                    <button class="btn danger" type="submit">Sil</button>
                  </form>
                </div>

                <details class="details-toggle">
                  <summary style="cursor:pointer; color: var(--muted); margin-top: 14px;">Ayrıntıları göster</summary>
                  <div class="details">
                    <pre>{{ item['details_json'] }}</pre>
                    <pre>{{ item['docker_info'] }}</pre>
                  </div>
                </details>
              </div>
            {% endfor %}
          </div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class AppError(RuntimeError):
    pass


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def run_cmd(cmd: list[str], *, env: Optional[dict[str, str]] = None, check: bool = True) -> CommandResult:
    proc = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    result = CommandResult(command=cmd, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    if check and not result.ok:
        joined = " ".join(cmd)
        raise AppError(
            f"Komut başarısız: {joined}\n\nSTDOUT:\n{result.stdout or '-'}\n\nSTDERR:\n{result.stderr or '-'}"
        )
    return result


def fetch_instances() -> list[dict[str, Any]]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                id, domain, project_name, volume_name,
                gateway_port, bridge_port, version,
                channel_choice, channel_bot_token,
                allow_from, token, openrouter_token,
                created_at
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
        row = conn.execute(
            """
            SELECT
                id, domain, project_name, volume_name,
                gateway_port, bridge_port, version,
                channel_choice, channel_bot_token,
                allow_from, token, openrouter_token,
                created_at
            FROM instances
            WHERE id = ?
            """,
            (instance_id,),
        ).fetchone()
    if row is None:
        raise AppError("Instance bulunamadı.")
    return dict(row)


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def compose_base_cmd(project_name: str) -> list[str]:
    return ["docker", "compose", "-p", project_name, "-f", str(DOCKER_COMPOSE_FILE)]


def get_project_status(project_name: str) -> str:
    try:
        result = run_cmd(compose_base_cmd(project_name) + ["ps", "--format", "json"], check=False)
        if not result.ok:
            return "unknown"
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return "stopped"
        payloads = []
        for line in lines:
            try:
                payloads.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not payloads:
            return "unknown"
        states = {str(p.get("State", "unknown")).lower() for p in payloads}
        if "running" in states:
            return "running"
        return ", ".join(sorted(states))
    except Exception:
        return "unknown"


def inspect_project_text(project_name: str) -> str:
    try:
        result = run_cmd(compose_base_cmd(project_name) + ["ps"], check=False)
        text = (result.stdout or result.stderr or "No docker output").strip()
        return text[:4000]
    except Exception as exc:
        return f"Docker info alınamadı: {exc}"


def create_instance_from_form(form: dict[str, str]) -> str:
    if not DEPLOY_SCRIPT.exists():
        raise AppError(f"Deploy script bulunamadı: {DEPLOY_SCRIPT}")

    cmd = [
        "bash",
        str(DEPLOY_SCRIPT),
        "--domain", form["domain"].strip(),
        "--telegram-bot-token", form["telegram_bot_token"].strip(),
        "--telegram-allow-from", form["telegram_allow_from"].strip(),
        "--openrouter-api-key", form["openrouter_api_key"].strip(),
        "--version", form.get("version", "latest").strip() or "latest",
        "--gateway-bind", form.get("gateway_bind", "lan").strip() or "lan",
    ]

    gateway_token = form.get("gateway_token", "").strip()
    if gateway_token:
        cmd.extend(["--gateway-token", gateway_token])

    result = run_cmd(cmd)
    return result.stdout or "Instance oluşturuldu."


def delete_instance_resources(instance: dict[str, Any]) -> str:
    project_name = instance["project_name"]
    volume_name = instance["volume_name"]

    compose_result = run_cmd(compose_base_cmd(project_name) + ["down", "-v", "--remove-orphans"], check=False)
    network_result = run_cmd(["docker", "network", "prune", "-f"], check=False)
    volume_result = run_cmd(["docker", "volume", "rm", "-f", volume_name], check=False)

    with get_conn() as conn:
        conn.execute("DELETE FROM instances WHERE id = ?", (instance["id"],))
        conn.commit()

    return "\n\n".join([
        f"docker compose down çıktı:\n{compose_result.stdout or compose_result.stderr or '-'}",
        f"docker network prune çıktı:\n{network_result.stdout or network_result.stderr or '-'}",
        f"docker volume rm çıktı:\n{volume_result.stdout or volume_result.stderr or '-'}",
    ])


def start_instance_resources(instance: dict[str, Any]) -> str:
    result = run_cmd(compose_base_cmd(instance["project_name"]) + ["up", "-d"])
    return result.stdout or "Instance başlatıldı."


def stop_instance_resources(instance: dict[str, Any]) -> str:
    result = run_cmd(compose_base_cmd(instance["project_name"]) + ["stop"])
    return result.stdout or "Instance durduruldu."


@app.get("/")
def index() -> str:
    instances = fetch_instances()
    return render_template_string(PAGE_TEMPLATE, instances=instances)


@app.post("/instances/create")
def create_instance() -> Response:
    try:
        output = create_instance_from_form(request.form)
        flash(f"Instance oluşturuldu. {compact_text(output)}", "success")
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(url_for("index"))


@app.post("/instances/<int:instance_id>/delete")
def delete_instance(instance_id: int) -> Response:
    try:
        instance = get_instance(instance_id)
        output = delete_instance_resources(instance)
        flash(f"Instance silindi. {compact_text(output)}", "success")
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(url_for("index"))


@app.post("/instances/<int:instance_id>/start")
def start_instance(instance_id: int) -> Response:
    try:
        instance = get_instance(instance_id)
        output = start_instance_resources(instance)
        flash(f"Start tamamlandı. {compact_text(output)}", "success")
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(url_for("index"))


@app.post("/instances/<int:instance_id>/stop")
def stop_instance(instance_id: int) -> Response:
    try:
        instance = get_instance(instance_id)
        output = stop_instance_resources(instance)
        flash(f"Stop tamamlandı. {compact_text(output)}", "success")
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(url_for("index"))


@app.post("/instances/<int:instance_id>/update")
def update_instance(instance_id: int) -> Response:
    _ = instance_id
    flash("Güncelleme scripti henüz eklenmedi. Buton hazır bırakıldı.", "info")
    return redirect(url_for("index"))


@app.get("/instances/<int:instance_id>/go")
def go_domain(instance_id: int) -> Response:
    instance = get_instance(instance_id)
    domain = instance["domain"].strip()
    target = domain if domain.startswith("http://") or domain.startswith("https://") else f"https://{domain}"
    return redirect(target, code=302)


def compact_text(text: str, limit: int = 300) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5050")), debug=True)
