function qs(selector, root = document) {
  return root.querySelector(selector);
}

function qsa(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

function normalize(value) {
  return (value || "").toString().toLowerCase().trim();
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
  setupDashboardPreopen();
  setupUserSearch();
  setupProfileAutomation();
});
