from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

# ============================================================
# Config
# ============================================================
ROOT_DIR = Path(os.environ.get("OPENCLAW_ROOT_DIR", Path.cwd())).resolve()
CREATE_SCRIPT = os.environ.get("OPENCLAW_CREATE_SCRIPT", str(ROOT_DIR / "create_instance.sh"))
DEFAULT_COMPOSE_FILE = ROOT_DIR / "docker-compose.yml"

# İstersen özel script'lere bağlayabilirsin.
# Yoksa panel varsayılan docker compose komutlarını kullanır.
CUSTOM_UPDATE_SCRIPT = os.environ.get("OPENCLAW_UPDATE_SCRIPT", "")
CUSTOM_DELETE_SCRIPT = os.environ.get("OPENCLAW_DELETE_SCRIPT", "")

# Basit erişim koruması için opsiyonel token.
# Çalıştırırken OPENCLAW_PANEL_TOKEN=supersecret python app.py diyebilirsin.
PANEL_TOKEN = os.environ.get("OPENCLAW_PANEL_TOKEN", "")

INDEX_HTML = r"""
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>OpenClaw Instance Panel</title>
  <style>
    :root {
      --bg: #0b1020;
      --panel: #121933;
      --panel-2: #182247;
      --muted: #8ea0c9;
      --text: #edf2ff;
      --ok: #1fc77e;
      --warn: #ffb020;
      --danger: #ff5d5d;
      --blue: #5b8cff;
      --border: rgba(255,255,255,0.09);
      --shadow: 0 10px 30px rgba(0,0,0,0.28);
      --radius: 18px;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      background: linear-gradient(180deg, #09101f 0%, #0d1530 100%);
      color: var(--text);
    }

    .wrap {
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
    }

    .header {
      display: flex;
      gap: 16px;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }

    .title h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.1;
    }

    .title p {
      margin: 6px 0 0;
      color: var(--muted);
    }

    .toolbar {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    .panel {
      background: rgba(18,25,51,0.9);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }

    .create-box {
      padding: 18px;
      display: grid;
      grid-template-columns: 1.4fr 1fr auto auto;
      gap: 12px;
      align-items: end;
      margin-bottom: 18px;
    }

    .field label {
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 14px;
    }

    .field input {
      width: 100%;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: #0d1430;
      color: var(--text);
      outline: none;
    }

    .button {
      border: 0;
      border-radius: 12px;
      padding: 12px 16px;
      font-weight: 700;
      cursor: pointer;
      transition: transform .08s ease, opacity .2s ease;
      color: white;
    }
    .button:hover { opacity: .94; }
    .button:active { transform: translateY(1px); }
    .button.primary { background: var(--blue); }
    .button.secondary { background: #24325f; }
    .button.success { background: var(--ok); color: #062313; }
    .button.warn { background: var(--warn); color: #241700; }
    .button.danger { background: var(--danger); }
    .button.ghost {
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text);
    }
    .button:disabled {
      cursor: not-allowed;
      opacity: .55;
    }

    .status-row {
      margin: 14px 0 18px;
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      padding: 7px 12px;
      font-size: 13px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.03);
      color: var(--muted);
    }

    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
    }
    .dot.ok { background: var(--ok); }
    .dot.warn { background: var(--warn); }
    .dot.danger { background: var(--danger); }
    .dot.muted { background: #6b7692; }

    .table-wrap {
      overflow-x: auto;
      border-radius: var(--radius);
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 1100px;
    }

    th, td {
      text-align: left;
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }

    th {
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
      background: rgba(255,255,255,0.02);
    }

    tr:hover td { background: rgba(255,255,255,0.02); }

    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }

    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .log-box {
      margin-top: 18px;
      padding: 18px;
    }

    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #09101f;
      border-radius: 14px;
      padding: 16px;
      border: 1px solid var(--border);
      min-height: 140px;
      max-height: 420px;
      overflow: auto;
      color: #dbe6ff;
    }

    .small {
      font-size: 12px;
      color: var(--muted);
    }

    .topline {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }

    @media (max-width: 920px) {
      .create-box {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <div class="title">
        <h1>OpenClaw Yönetim Paneli</h1>
        <p>Instance oluştur, başlat, durdur, güncelle ve gateway'e tek yerden git.</p>
      </div>
      <div class="toolbar">
        <button class="button ghost" onclick="loadInstances()">Yenile</button>
      </div>
    </div>

    <div class="panel create-box">
      <div class="field">
        <label>Yeni instance oluştur</label>
        <input id="instanceName" type="text" placeholder="Opsiyonel açıklama / label" />
      </div>
      <div class="field">
        <label>Panel token</label>
        <input id="panelToken" type="password" placeholder="Token varsa gir" />
      </div>
      <button class="button primary" onclick="createInstance()">Yeni Instance</button>
      <button class="button secondary" onclick="loadInstances()">Listeyi Tazele</button>
    </div>

    <div class="status-row" id="summaryRow"></div>

    <div class="panel table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Project</th>
            <th>Status</th>
            <th>Gateway</th>
            <th>Bridge</th>
            <th>Volume</th>
            <th>Env File</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="instanceTableBody">
          <tr><td colspan="8" class="small">Yükleniyor...</td></tr>
        </tbody>
      </table>
    </div>

    <div class="panel log-box">
      <div class="topline">
        <strong>İşlem çıktısı</strong>
        <span class="small">Son tetiklenen backend komutunun stdout/stderr çıktısı</span>
      </div>
      <pre id="logOutput">Hazır.</pre>
    </div>
  </div>

  <script>
    let busy = false;

    function getToken() {
      return document.getElementById('panelToken').value.trim();
    }

    function setLog(text) {
      document.getElementById('logOutput').textContent = text || 'Tamam.';
    }

    function authHeaders() {
      const token = getToken();
      const headers = { 'Content-Type': 'application/json' };
      if (token) headers['X-Panel-Token'] = token;
      return headers;
    }

    function badge(label, count, cls) {
      return `<span class="badge"><span class="dot ${cls}"></span>${label}: <strong>${count}</strong></span>`;
    }

    function renderSummary(items) {
      const total = items.length;
      const running = items.filter(x => x.running).length;
      const stopped = items.filter(x => !x.running).length;
      const row = document.getElementById('summaryRow');
      row.innerHTML = [
        badge('Toplam', total, 'muted'),
        badge('Çalışan', running, 'ok'),
        badge('Duran', stopped, stopped ? 'warn' : 'muted')
      ].join('');
    }

    function statusPill(item) {
      const dot = item.running ? 'ok' : (item.exists ? 'warn' : 'danger');
      const text = item.running ? 'Running' : (item.exists ? 'Stopped' : 'Missing');
      return `<span class="badge"><span class="dot ${dot}"></span>${text}</span>`;
    }

    function escapeHtml(value) {
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    }

    function actionButton(label, cls, onClick, disabled=false) {
      return `<button class="button ${cls}" ${disabled ? 'disabled' : ''} onclick="${onClick}">${label}</button>`;
    }

    function rowHtml(item) {
      const openGateway = item.gateway_url
        ? actionButton('Gateway', 'primary', `window.open('${item.gateway_url}', '_blank')`)
        : actionButton('Gateway', 'primary', '', true);

      return `
        <tr>
          <td><strong>${item.instance_number}</strong></td>
          <td>
            <div>${escapeHtml(item.project_name || '-')}</div>
            <div class="small mono">${escapeHtml(item.compose_project || '-')}</div>
          </td>
          <td>${statusPill(item)}</td>
          <td class="mono">${escapeHtml(item.gateway_port || '-')}</td>
          <td class="mono">${escapeHtml(item.bridge_port || '-')}</td>
          <td class="mono">${escapeHtml(item.volume_name || '-')}</td>
          <td class="mono">${escapeHtml(item.env_file || '-')}</td>
          <td>
            <div class="actions">
              ${item.running
                ? actionButton('Durdur', 'warn', `runAction(${item.instance_number}, 'stop')`)
                : actionButton('Başlat', 'success', `runAction(${item.instance_number}, 'start')`)}
              ${actionButton('Restart', 'secondary', `runAction(${item.instance_number}, 'restart')`)}
              ${actionButton('Güncelle', 'secondary', `runAction(${item.instance_number}, 'update')`)}
              ${openGateway}
              ${actionButton('Detay', 'ghost', `showDetails(${item.instance_number})`)}
            </div>
          </td>
        </tr>
      `;
    }

    async function loadInstances() {
      const tbody = document.getElementById('instanceTableBody');
      tbody.innerHTML = `<tr><td colspan="8" class="small">Yükleniyor...</td></tr>`;
      try {
        const res = await fetch('/api/instances', { headers: authHeaders() });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Liste alınamadı');

        const items = data.instances || [];
        renderSummary(items);

        if (!items.length) {
          tbody.innerHTML = `<tr><td colspan="8" class="small">Hiç instance bulunamadı.</td></tr>`;
          return;
        }

        tbody.innerHTML = items.map(rowHtml).join('');
        setLog('Liste güncellendi.');
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="8" class="small">Hata: ${escapeHtml(err.message)}</td></tr>`;
        setLog(`Hata: ${err.message}`);
      }
    }

    async function createInstance() {
      if (busy) return;
      busy = true;
      const label = document.getElementById('instanceName').value.trim();
      setLog('Yeni instance oluşturuluyor...');
      try {
        const res = await fetch('/api/instances', {
          method: 'POST',
          headers: authHeaders(),
          body: JSON.stringify({ label })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Oluşturma başarısız');
        setLog(data.output || 'Instance oluşturuldu.');
        await loadInstances();
      } catch (err) {
        setLog(`Hata: ${err.message}`);
      } finally {
        busy = false;
      }
    }

    async function runAction(instanceNumber, action) {
      if (busy) return;
      busy = true;
      setLog(`İşlem çalışıyor: ${action} / #${instanceNumber}`);
      try {
        const res = await fetch(`/api/instances/${instanceNumber}/${action}`, {
          method: 'POST',
          headers: authHeaders()
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'İşlem başarısız');
        setLog(data.output || `${action} tamamlandı.`);
        await loadInstances();
      } catch (err) {
        setLog(`Hata: ${err.message}`);
      } finally {
        busy = false;
      }
    }

    async function showDetails(instanceNumber) {
      try {
        const res = await fetch(`/api/instances/${instanceNumber}`, {
          headers: authHeaders()
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Detay alınamadı');
        setLog(JSON.stringify(data.instance, null, 2));
      } catch (err) {
        setLog(`Hata: ${err.message}`);
      }
    }

    loadInstances();
  </script>
</body>
</html>
"""


# ============================================================
# Helpers
# ============================================================
def require_token() -> tuple[bool, Any]:
    if not PANEL_TOKEN:
        return True, None
    provided = request.headers.get("X-Panel-Token", "")
    if provided != PANEL_TOKEN:
        return False, (jsonify({"error": "Unauthorized"}), 401)
    return True, None


def run_cmd(cmd: list[str], cwd: Path | None = None) -> dict[str, Any]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd or ROOT_DIR),
        text=True,
        capture_output=True,
    )
    output = (proc.stdout or "") + ("\n" if proc.stdout and proc.stderr else "") + (proc.stderr or "")
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "output": output.strip() or "(çıktı yok)",
        "cmd": shlex.join(cmd),
    }


def parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def env_files() -> list[Path]:
    files = []
    for p in ROOT_DIR.glob(".env.*"):
        suffix = p.name.split(".")[-1]
        if suffix.isdigit():
            files.append(p)
    return sorted(files, key=lambda p: int(p.name.split(".")[-1]))


def extract_instance_number(env_path: Path) -> int:
    return int(env_path.name.split(".")[-1])


def default_project_name(instance_number: int) -> str:
    return f"openclaw-instance-{instance_number}"


def compose_ps_state(project: str, env_file: Path) -> dict[str, Any]:
    if not DEFAULT_COMPOSE_FILE.exists():
        return {"exists": False, "running": False, "raw": "docker-compose.yml missing"}

    cmd = [
        "docker", "compose",
        "-p", project,
        "--env-file", str(env_file),
        "-f", str(DEFAULT_COMPOSE_FILE),
        "ps", "--format", "json",
    ]
    res = run_cmd(cmd)
    if not res["ok"]:
        return {"exists": True, "running": False, "raw": res["output"]}

    raw = res["output"].strip()
    if not raw or raw == "(çıktı yok)":
        return {"exists": True, "running": False, "raw": ""}

    lines = [line for line in raw.splitlines() if line.strip()]
    running = False
    parsed = []
    for line in lines:
        try:
            item = json.loads(line)
            parsed.append(item)
            state = str(item.get("State", "")).lower()
            if state == "running":
                running = True
        except json.JSONDecodeError:
            pass

    return {"exists": True, "running": running, "raw": raw, "services": parsed}


def instance_from_env(env_path: Path) -> dict[str, Any]:
    instance_number = extract_instance_number(env_path)
    env = parse_env_file(env_path)
    project = env.get("COMPOSE_PROJECT_NAME") or default_project_name(instance_number)
    ps = compose_ps_state(project, env_path)

    gateway_port = env.get("OPENCLAW_GATEWAY_PORT", "")
    gateway_token = env.get("OPENCLAW_GATEWAY_TOKEN", "")
    gateway_url = ""
    if gateway_port and gateway_token:
        gateway_url = f"http://127.0.0.1:{gateway_port}/#token={gateway_token}"

    return {
        "instance_number": instance_number,
        "project_name": project,
        "compose_project": project,
        "volume_name": env.get("OPENCLAW_HOME_VOLUME", f"openclaw-volume-{instance_number}"),
        "gateway_port": gateway_port,
        "bridge_port": env.get("OPENCLAW_BRIDGE_PORT", ""),
        "gateway_token": gateway_token,
        "gateway_url": gateway_url,
        "env_file": env_path.name,
        "exists": ps.get("exists", True),
        "running": ps.get("running", False),
        "ps_raw": ps.get("raw", ""),
        "services": ps.get("services", []),
    }


def get_instance(instance_number: int) -> dict[str, Any] | None:
    env_path = ROOT_DIR / f".env.{instance_number}"
    if not env_path.exists():
        return None
    return instance_from_env(env_path)


def compose_base_cmd(instance_number: int) -> list[str]:
    env_path = ROOT_DIR / f".env.{instance_number}"
    if not env_path.exists():
        raise FileNotFoundError(f"Env file not found: {env_path.name}")
    return [
        "docker", "compose",
        "-p", default_project_name(instance_number),
        "--env-file", str(env_path),
        "-f", str(DEFAULT_COMPOSE_FILE),
    ]


def run_instance_action(instance_number: int, action: str) -> dict[str, Any]:
    env_path = ROOT_DIR / f".env.{instance_number}"
    if not env_path.exists():
        return {"ok": False, "output": f".env.{instance_number} bulunamadı"}

    if action == "start":
        return run_cmd(compose_base_cmd(instance_number) + ["up", "-d"])
    if action == "stop":
        return run_cmd(compose_base_cmd(instance_number) + ["stop"])
    if action == "restart":
        return run_cmd(compose_base_cmd(instance_number) + ["restart"])
    if action == "update":
        if CUSTOM_UPDATE_SCRIPT:
            return run_cmd([CUSTOM_UPDATE_SCRIPT, str(instance_number)])
        # Varsayılan update: image çek, sonra ayağa kaldır.
        pull_res = run_cmd(compose_base_cmd(instance_number) + ["pull"])
        up_res = run_cmd(compose_base_cmd(instance_number) + ["up", "-d"])
        ok = pull_res["ok"] and up_res["ok"]
        return {
            "ok": ok,
            "code": 0 if ok else 1,
            "output": f"$ {pull_res['cmd']}\n{pull_res['output']}\n\n$ {up_res['cmd']}\n{up_res['output']}",
        }

    return {"ok": False, "output": f"Desteklenmeyen action: {action}"}


# ============================================================
# Routes
# ============================================================
@app.before_request
def _check_auth():
    allowed, response = require_token()
    if not allowed:
        return response
    return None


@app.get("/")
def index():
    return render_template_string(INDEX_HTML)


@app.get("/api/instances")
def list_instances():
    items = [instance_from_env(p) for p in env_files()]
    return jsonify({"instances": items, "root_dir": str(ROOT_DIR)})


@app.get("/api/instances/<int:instance_number>")
def instance_detail(instance_number: int):
    item = get_instance(instance_number)
    if not item:
        return jsonify({"error": "Instance bulunamadı"}), 404
    return jsonify({"instance": item})


@app.post("/api/instances")
def create_instance():
    if not Path(CREATE_SCRIPT).exists():
        return jsonify({"error": f"Create script bulunamadı: {CREATE_SCRIPT}"}), 404

    payload = request.get_json(silent=True) or {}
    label = str(payload.get("label", "")).strip()

    res = run_cmd([CREATE_SCRIPT], cwd=ROOT_DIR)
    latest = None
    items = [instance_from_env(p) for p in env_files()]
    if items:
        latest = max(items, key=lambda x: x["instance_number"])

    extra = f"\n\nLabel: {label}" if label else ""
    return jsonify({
        "ok": res["ok"],
        "output": res["output"] + extra,
        "instance": latest,
    }), (200 if res["ok"] else 500)


@app.post("/api/instances/<int:instance_number>/<action>")
def instance_action(instance_number: int, action: str):
    if action not in {"start", "stop", "restart", "update"}:
        return jsonify({"error": "Geçersiz action"}), 400
    res = run_instance_action(instance_number, action)
    return jsonify(res), (200 if res.get("ok") else 500)


@app.get("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    host = os.environ.get("OPENCLAW_PANEL_HOST", "0.0.0.0")
    port = int(os.environ.get("OPENCLAW_PANEL_PORT", "8080"))
    debug = os.environ.get("OPENCLAW_PANEL_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
