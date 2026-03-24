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

document.addEventListener("DOMContentLoaded", () => {
  setupThemeToggle();
  setupDashboardPreopen();
  setupUserSearch();
  setupProfileAutomation();
});
