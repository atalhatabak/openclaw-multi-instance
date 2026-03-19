function qs(sel, el = document) { return el.querySelector(sel); }
function qsa(sel, el = document) { return Array.from(el.querySelectorAll(sel)); }

function normalize(s) {
  return (s || "").toString().toLowerCase().trim();
}

function setupSearch() {
  const input = qs("#searchInput");
  const list = qs("#instanceList");
  if (!input || !list) return;

  input.addEventListener("input", () => {
    const q = normalize(input.value);
    const cards = qsa(".instance", list);
    cards.forEach(card => {
      const hay = [
        card.dataset.domain,
        card.dataset.project,
        card.dataset.ports,
        card.dataset.status,
      ].map(normalize).join(" ");
      const show = !q || hay.includes(q);
      card.style.display = show ? "" : "none";
    });
  });
}

function setupDetailsToggle() {
  qsa("[data-toggle-details]").forEach(btn => {
    btn.addEventListener("click", () => {
      const card = btn.closest(".instance");
      const details = card && qs("[data-details]", card);
      if (!details) return;
      const expanded = btn.getAttribute("aria-expanded") === "true";
      details.classList.toggle("hidden");
      btn.setAttribute("aria-expanded", expanded ? "false" : "true");
      btn.textContent = expanded ? "Details" : "Hide Details";
    });
  });
}

async function apiGet(url) {
  const res = await fetch(url, { headers: { "Accept": "application/json" } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

async function apiPost(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function setupModal() {
  const modal = qs("#modal");
  const close = qs("#modalClose");
  if (!modal) return;
  const closeFn = () => modal.close();
  close && close.addEventListener("click", closeFn);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeFn();
  });
}

function openModal(title, html) {
  const modal = qs("#modal");
  const t = qs("#modalTitle");
  const b = qs("#modalBody");
  if (!modal || !t || !b) return;
  t.textContent = title;
  b.innerHTML = html;
  modal.showModal();
}

function escapeHtml(s) {
  return (s || "").toString()
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function buildTable(headers, rows) {
  const head = headers.map(h => `<th>${escapeHtml(h)}</th>`).join("");
  const body = rows.join("");
  return [
    `<div class="table-wrap">`,
    `<table class="table">`,
    `<thead><tr>${head}</tr></thead>`,
    `<tbody>${body}</tbody>`,
    `</table>`,
    `</div>`,
  ].join("");
}

async function showDevices(instanceId) {
  const data = await apiGet(`/api/instances/${instanceId}/devices`);
  const devices = data.devices || [];

  let html = "";
  html += `<div class="modal-stack">`;
  html += `<div id="devicesMessage" class="muted small"></div>`;
  const pending = devices.filter(d => (d.status || "").toLowerCase() === "pending");
  const paired = devices.filter(d => (d.status || "").toLowerCase() === "paired");

  if (!devices.length) {
    html += `<div class="muted">Henüz cihaz bulunamadı.</div>`;
  } else {
    html += `<div class="muted small">Bekleyen cihazları buradan onaylayabilirsin.</div>`;
    html += `<section class="surface-card"><div class="surface-card-body">`;
    html += `<h3 class="surface-title">Bekleyen cihazlar</h3>`;
    if (!pending.length) {
      html += `<div class="muted small">Bekleyen cihaz yok.</div>`;
    } else {
      const pendingRows = pending.map(d => [
        `<tr>`,
        `<td class="mono">${escapeHtml(d.device_id)}</td>`,
        `<td><button class="btn success smallbtn" data-approve="${escapeHtml(d.device_id)}">Onayla</button></td>`,
        `</tr>`,
      ].join(""));
      html += buildTable(["Request ID", "Action"], pendingRows);
    }
    html += `</div></section>`;

    html += `<section class="surface-card"><div class="surface-card-body">`;
    html += `<h3 class="surface-title">Eşleşmiş cihazlar</h3>`;
    if (!paired.length) {
      html += `<div class="muted small">Eşleşmiş cihaz bulunmuyor.</div>`;
    } else {
      const pairedRows = paired.map(d => [
        `<tr>`,
        `<td class="mono">${escapeHtml(d.device_id)}</td>`,
        `<td><span class="badge">Paired</span></td>`,
        `</tr>`,
      ].join(""));
      html += buildTable(["Device", "Status"], pairedRows);
    }
    html += `</div></section>`;
  }
  html += `</div>`;

  openModal(`Cihazlar (instance ${instanceId})`, html);

  qsa("[data-approve]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const deviceId = btn.dataset.approve;
      btn.disabled = true;
      try {
        await apiPost(`/api/instances/${instanceId}/devices/approve`, { device_id: deviceId });
        const row = btn.closest("tr");
        if (row) {
          row.remove();
        }
        const msg = qs("#devicesMessage");
        if (msg) {
          msg.textContent = "Cihaz onaylandı.";
        }
      } catch (e) {
        openModal(`Approve failed`, `<div class="flash error">${escapeHtml(e.message)}</div>`);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

async function showLogs(instanceId) {
  const data = await apiGet(`/api/instances/${instanceId}/logs`);
  const logs = data.logs || [];
  let html = "";
  if (!logs.length) {
    html = `<div class="muted">No logs yet for this instance.</div>`;
  } else {
    html += `<div class="modal-stack">`;
    html += `<div class="muted small">Latest 30 logs.</div>`;
    html += `<section class="surface-card"><div class="surface-card-body">`;
    const rows = logs.map(l => [
      `<tr>`,
      `<td>${escapeHtml(l.created_at || "")}</td>`,
      `<td>${escapeHtml(l.action_type || "")}</td>`,
      `<td><span class="badge">${escapeHtml(l.status || "")}</span></td>`,
      `<td><button class="btn ghost smallbtn" data-log-open="${l.id}">Open</button></td>`,
      `</tr>`,
    ].join(""));
    html += buildTable(["When", "Action", "Status", "Detail"], rows);
    html += `</div></section></div>`;
  }
  openModal(`Logs (instance ${instanceId})`, html);

  qsa("[data-log-open]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const logId = btn.dataset.logOpen;
      btn.disabled = true;
      try {
        const content = await apiGet(`/api/logs/${logId}`);
        openModal(`Log #${logId}`, `<pre>${escapeHtml(content.content || "")}</pre>`);
      } catch (e) {
        openModal(`Log load failed`, `<div class="flash error">${escapeHtml(e.message)}</div>`);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

function setupButtons() {
  qsa("[data-devices]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.devices;
      btn.disabled = true;
      try {
        await showDevices(id);
      } catch (e) {
        openModal("Devices failed", `<div class="flash error">${escapeHtml(e.message)}</div>`);
      } finally {
        btn.disabled = false;
      }
    });
  });

  qsa("[data-logs]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.logs;
      btn.disabled = true;
      try {
        await showLogs(id);
      } catch (e) {
        openModal("Logs failed", `<div class="flash error">${escapeHtml(e.message)}</div>`);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

function setupTheme() {
  const btn = qs("#themeToggle");
  const label = qs("#themeLabel");
  const body = document.body;
  if (!btn || !label || !body) return;

  const preferred = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  const saved = window.localStorage.getItem("openclaw-theme");
  const initial = saved || preferred || "dark";
  body.setAttribute("data-theme", initial);
  label.textContent = initial === "light" ? "Light" : "Dark";

  btn.addEventListener("click", () => {
    const current = body.getAttribute("data-theme") === "light" ? "light" : "dark";
    const next = current === "light" ? "dark" : "light";
    body.setAttribute("data-theme", next);
    window.localStorage.setItem("openclaw-theme", next);
    label.textContent = next === "light" ? "Light" : "Dark";
  });
}

async function setupVersion() {
  const badge = qs("#versionInline");
  if (!badge) return;
  try {
    const data = await apiGet("/api/version");
    const latest = data.image_version || data.default_version;
    if (!latest) return;
    badge.textContent = ` · OpenClaw ${latest}`;
  } catch (e) {
    // sessizce geç
  }
}

document.addEventListener("DOMContentLoaded", () => {
  setupSearch();
  setupDetailsToggle();
  setupModal();
  setupButtons();
  setupTheme();
  setupVersion();
});
