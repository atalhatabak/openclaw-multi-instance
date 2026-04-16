function qs(selector, root = document) {
  return root.querySelector(selector);
}

function qsa(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

function normalize(value) {
  return (value || "").toString().toLowerCase().trim();
}

function getSystemTheme() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function getPreferredTheme() {
  try {
    return localStorage.getItem("theme-preference") || getSystemTheme();
  } catch (err) {
    return getSystemTheme();
  }
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
}

function setupThemeToggle() {
  const toggle = qs("#themeToggle");
  if (!toggle) return;

  const label = qs(".theme-toggle-label", toggle);
  const mediaQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  const syncButton = (theme) => {
    const isDark = theme === "dark";
    toggle.setAttribute("aria-pressed", isDark ? "true" : "false");
    toggle.setAttribute("title", isDark ? "Light moda gec" : "Dark moda gec");
    if (label) {
      label.textContent = isDark ? "Light" : "Dark";
    }
  };

  const updateTheme = (theme, persist) => {
    applyTheme(theme);
    syncButton(theme);
    if (!persist) return;
    try {
      localStorage.setItem("theme-preference", theme);
    } catch (err) {
    }
  };

  updateTheme(getPreferredTheme(), false);

  toggle.addEventListener("click", () => {
    const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    updateTheme(nextTheme, true);
  });

  if (mediaQuery) {
    mediaQuery.addEventListener("change", (event) => {
      try {
        const storedTheme = localStorage.getItem("theme-preference");
        if (storedTheme) return;
      } catch (err) {
      }
      updateTheme(event.matches ? "dark" : "light", false);
    });
  }
}

function setupUserSearch() {
  const input = qs("#userSearch");
  const rows = qsa("[data-user-row]");
  if (!input || !rows.length) return;

  input.addEventListener("input", () => {
    const query = normalize(input.value);
    rows.forEach((row) => {
      const haystack = normalize(row.textContent);
      row.style.display = !query || haystack.includes(query) ? "" : "none";
    });
  });
}

function setupDashboardPreopen() {
  const forms = qsa("form[data-preopen-dashboard='1']");
  if (!forms.length) return;

  forms.forEach((form) => {
    form.addEventListener("submit", () => {
      try {
        const dashboardWindow = window.open("", "openclaw-dashboard");
        if (dashboardWindow && dashboardWindow.document) {
          dashboardWindow.document.title = "OpenClaw Dashboard";
          dashboardWindow.document.body.innerHTML = "<p style='font-family: sans-serif; padding: 24px;'>OpenClaw dashboard hazirlaniyor...</p>";
        }
      } catch (err) {
      }
    });
  });
}

async function postJson(url) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "X-Requested-With": "fetch",
    },
  });
  return response;
}

function setupProfileAutomation() {
  const shell = qs(".profile-shell");
  if (!shell) return;

  const approveUrl = shell.dataset.approveUrl;
  const approveButton = qs("#approveLatestButton", shell);
  const launchGateway = shell.dataset.launchGateway === "1";

  const approveLatest = async () => {
    if (!approveUrl) return;
    try {
      await postJson(approveUrl);
    } catch (err) {
    }
  };

  if (approveButton) {
    approveButton.addEventListener("click", () => {
      approveLatest();
    });
  }

  if (launchGateway) {
    if (window.history && window.history.replaceState) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }
    window.setTimeout(() => {
      approveLatest();
    }, 3000);
  }
}

async function getJson(url, options = {}) {
  const response = await fetch(url, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch (err) {
  }
  if (!response.ok || !payload || payload.ok === false) {
    const message = payload && payload.error ? payload.error : `Request failed: ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

function escapeHtml(value) {
  return (value || "")
    .toString()
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setupImageLogViewer() {
  const panel = qs("#imageLogPanel");
  const form = qs("[data-image-update-form='1']");
  if (!panel || !form) return;

  const storageKey = "image-log-panel-expanded";
  const logsUrl = panel.dataset.logsUrl;
  const startUrl = form.dataset.asyncUrl;
  const content = qs("#imageLogContent", panel);
  const refreshButton = qs("#imageLogRefreshButton", panel);
  const output = qs("#imageLogOutput", panel);
  const meta = qs("#imageLogMeta", panel);
  const statusBadge = qs("#imageLogStatusBadge", panel);
  const list = qs("#imageLogList", panel);
  const followToggle = qs("#imageLogFollowToggle", panel);
  const submitButton = qs("button[type='submit']", form);
  const toggleButton = qs("#imageLogToggleButton", panel);

  let selectedLogId = panel.dataset.selectedLogId || "";
  let pollHandle = null;
  let requestInFlight = false;
  let lastSnapshot = null;

  const persistExpanded = (isExpanded) => {
    try {
      localStorage.setItem(storageKey, isExpanded ? "1" : "0");
    } catch (err) {
    }
  };

  const setExpanded = (isExpanded, { persist = true } = {}) => {
    panel.dataset.expanded = isExpanded ? "1" : "0";
    panel.classList.toggle("is-collapsed", !isExpanded);
    if (toggleButton) {
      toggleButton.textContent = isExpanded ? "Loglari Kapat" : "Loglari Ac";
      toggleButton.setAttribute("aria-expanded", isExpanded ? "true" : "false");
    }
    if (content) {
      content.hidden = !isExpanded;
    }
    if (persist) {
      persistExpanded(isExpanded);
    }
  };

  const getInitialExpanded = () => {
    try {
      const stored = localStorage.getItem(storageKey);
      if (stored === "1") return true;
      if (stored === "0") return false;
    } catch (err) {
    }
    return false;
  };

  const updateSubmitButton = (snapshot = lastSnapshot) => {
    if (!submitButton) return;
    const isRunning = !!(snapshot && snapshot.selected_log && snapshot.selected_log.is_running);
    submitButton.disabled = isRunning || requestInFlight;
    submitButton.textContent = isRunning ? "Image Guncelleniyor" : "Image Guncelle";
  };

  const renderLogList = (logs, activeLogId) => {
    if (!list) return;
    if (!logs || !logs.length) {
      list.innerHTML = "<div class=\"image-log-empty muted\">Henuz image logu yok.</div>";
      return;
    }

    list.innerHTML = logs
      .map((log) => {
        const state = log.is_running ? "running" : (log.status || "idle");
        const classes = ["image-log-item"];
        if (`${log.id}` === `${activeLogId || ""}`) {
          classes.push("active");
        }
        return `
          <button class="${classes.join(" ")}" type="button" data-log-id="${escapeHtml(log.id)}">
            <strong>#${escapeHtml(log.id)}</strong>
            <span>${escapeHtml(state)}</span>
            <span>${escapeHtml(log.created_at || "")}</span>
          </button>
        `;
      })
      .join("");
  };

  const schedulePoll = (shouldPoll) => {
    if (pollHandle) {
      window.clearTimeout(pollHandle);
      pollHandle = null;
    }
    if (!shouldPoll) return;
    pollHandle = window.setTimeout(() => {
      fetchSnapshot().catch(() => {
        schedulePoll(true);
      });
    }, 2000);
  };

  const renderSnapshot = (snapshot) => {
    lastSnapshot = snapshot;
    const selectedLog = snapshot.selected_log;
    selectedLogId = selectedLog ? `${selectedLog.id}` : "";
    panel.dataset.selectedLogId = selectedLogId;

    renderLogList(snapshot.recent_logs || [], selectedLogId);

    if (statusBadge) {
      const state = selectedLog ? (selectedLog.is_running ? "running" : selectedLog.status || "idle") : "idle";
      statusBadge.textContent = state;
      statusBadge.classList.toggle("ok", state === "success");
      statusBadge.classList.toggle("warn", state !== "success");
    }

    if (meta) {
      if (!selectedLog) {
        meta.textContent = "Bir image update baslatildiginda log buraya akacak.";
      } else {
        const parts = [
          `log #${selectedLog.id}`,
          selectedLog.created_at || "",
          snapshot.log_path || "",
        ];
        if (selectedLog.is_running) {
          parts.push("canli takip aktif");
        }
        if (snapshot.truncated) {
          parts.push("tail mode aktif");
        }
        if (snapshot.last_updated_at) {
          parts.push(`son guncelleme ${snapshot.last_updated_at}`);
        }
        meta.textContent = parts.filter(Boolean).join(" | ");
      }
    }

    if (output) {
      output.textContent = snapshot.content || "Henuz image logu yok.";
      if (followToggle && followToggle.checked) {
        output.scrollTop = output.scrollHeight;
      }
    }

    updateSubmitButton(snapshot);
    schedulePoll(selectedLog && (selectedLog.is_running || selectedLog.status === "running"));
  };

  const fetchSnapshot = async (logId = selectedLogId) => {
    if (!logsUrl) return;
    const url = new URL(logsUrl, window.location.origin);
    if (logId) {
      url.searchParams.set("log_id", logId);
    }
    const snapshot = await getJson(url.toString());
    renderSnapshot(snapshot);
  };

  if (refreshButton) {
    refreshButton.addEventListener("click", () => {
      fetchSnapshot().catch(() => {
      });
    });
  }

  if (toggleButton) {
    toggleButton.addEventListener("click", () => {
      const isExpanded = panel.dataset.expanded === "1";
      setExpanded(!isExpanded);
    });
  }

  if (list) {
    list.addEventListener("click", (event) => {
      if (!(event.target instanceof Element)) return;
      const button = event.target.closest("[data-log-id]");
      if (!button) return;
      selectedLogId = button.dataset.logId || "";
      fetchSnapshot(selectedLogId).catch(() => {
      });
    });
  }

  form.addEventListener("submit", async (event) => {
    if (!startUrl) return;
    event.preventDefault();
    setExpanded(true);
    requestInFlight = true;
    updateSubmitButton(null);
    try {
      const payload = await getJson(startUrl, {
        method: "POST",
        headers: {
          "X-Requested-With": "fetch",
        },
      });
      selectedLogId = payload.log_id ? `${payload.log_id}` : selectedLogId;
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
      await fetchSnapshot(selectedLogId);
    } catch (err) {
      form.submit();
      return;
    } finally {
      requestInFlight = false;
      updateSubmitButton();
    }
  });

  setExpanded(getInitialExpanded(), { persist: false });
  fetchSnapshot(selectedLogId).catch(() => {
    updateSubmitButton();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupThemeToggle();
  setupDashboardPreopen();
  setupUserSearch();
  setupProfileAutomation();
  setupImageLogViewer();
});
