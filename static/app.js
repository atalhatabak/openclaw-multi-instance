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

document.addEventListener("DOMContentLoaded", () => {
  setupUserSearch();
});
