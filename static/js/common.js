// Shared helpers + the app shell (sidebar and top bar) used by every page.

const STATUS_TEXT = {
  approved: "Approved", pending: "Pending", rejected: "Rejected",
  running: "Running", error: "Error", waiting: "Waiting",
  pass: "Pass", warn: "Action", fail: "Fail", info: "Info", skip: "Skipped",
};
const COUNTRY_NAMES = { IN: "India", US: "United States", UK: "United Kingdom" };

// Simple line icons (24x24, stroke).
const ICONS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m4 7 8 6 8-6"/>',
  building: '<path d="M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16"/><path d="M16 9h2a2 2 0 0 1 2 2v10"/><path d="M8 7h4M8 11h4M8 15h4M3 21h18"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  alert: '<path d="M12 8v5M12 16.5v.5"/><circle cx="12" cy="12" r="9"/>',
  bang: '<path d="M12 6v8M12 18v.5"/>',
  shield: '<path d="M12 3 5 6v5c0 4.5 3 8.5 7 10 4-1.5 7-5.5 7-10V6l-7-3Z"/><path d="m9 12 2 2 4-4"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z"/><path d="M14 3v5h5"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  back: '<path d="M15 6l-6 6 6 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/>',
  sparkle: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
  refresh: '<path d="M20 12a8 8 0 1 1-2.3-5.7L20 8.5"/><path d="M20 4v4.5h-4.5"/>',
  minus: '<path d="M6 12h12"/>',
  bolt: '<path d="M13 3 5 13.5h6L10 21l8-10.5h-6L13 3Z"/>',
};

function icon(name, cls) {
  return `<svg class="i ${cls || ""}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}

function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function pill(status, extra) {
  return `<span class="pill ${esc(status)} ${extra || ""}">${esc(STATUS_TEXT[status] || status)}</span>`;
}
// Older name kept so nothing breaks.
const label = pill;

function fmtDateTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function fmtSeconds(fromIso, toIso) {
  if (!fromIso || !toIso) return "";
  const s = (new Date(toIso) - new Date(fromIso)) / 1000;
  return s < 10 ? `${s.toFixed(1)}s` : `${Math.round(s)}s`;
}

async function api(path, options) {
  const res = await fetch(path, options);
  let body = null;
  try { body = await res.json(); } catch (e) { /* not json */ }
  if (!res.ok) {
    const msg = (body && (body.detail || body.error)) || `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return body;
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------

const NAV = [
  { group: "Workflow", items: [
    { key: "submit", label: "New submission", icon: "plus", href: "/" },
    { key: "runs", label: "Dashboard", icon: "grid", href: "/dashboard.html" },
  ] },
  { group: "Records", items: [
    { key: "outbox", label: "Outbox", icon: "mail", href: "/dashboard.html#outbox" },
    { key: "vendors", label: "Vendor master", icon: "building", href: "/dashboard.html#vendors" },
  ] },
];

function currentNavKey() {
  const page = document.body.dataset.page;
  if (page === "dashboard") {
    const h = location.hash.slice(1);
    return ["outbox", "vendors"].includes(h) ? h : "runs";
  }
  if (page === "run") return "runs";
  return "submit";
}

function renderNav() {
  const active = currentNavKey();
  document.getElementById("nav").innerHTML = NAV.map(g => `
    <div class="nav-label">${g.group}</div>
    ${g.items.map(it => `
      <a class="nav-item ${it.key === active ? "active" : ""}" href="${it.href}" data-key="${it.key}">
        ${icon(it.icon)}<span>${it.label}</span>
      </a>`).join("")}`).join("");
}

function renderShell() {
  const sidebar = document.getElementById("sidebar");
  sidebar.innerHTML = `
    <a class="brand" href="/">
      <span class="brand-mark">${icon("shield")}</span>
      <span><span class="brand-name">Vendor Onboarding</span><br><span class="brand-sub" id="buyer-name">Procurement</span></span>
    </a>
    <nav id="nav"></nav>
    <div class="sys-card">
      <h4>System</h4>
      <div id="sys-status"><div class="sys-row muted">Checking…</div></div>
    </div>`;
  renderNav();

  const topbar = document.getElementById("topbar");
  topbar.innerHTML = `
    <button class="btn icon ghost menu-btn" id="menu-btn" type="button" aria-label="Open menu">${icon("menu")}</button>
    <form class="search" id="top-search" role="search">
      ${icon("search")}
      <input type="search" id="top-q" placeholder="Search runs by vendor or #id" autocomplete="off">
      <kbd>/</kbd>
    </form>
    <div class="top-right">
      <div class="avatar">PT</div>
      <div class="who"><b>Procurement team</b><span id="top-buyer">Reviewer</span></div>
    </div>`;

  document.getElementById("menu-btn").addEventListener("click", () => document.body.classList.toggle("nav-open"));
  document.getElementById("scrim").addEventListener("click", () => document.body.classList.remove("nav-open"));
  window.addEventListener("hashchange", () => { renderNav(); document.body.classList.remove("nav-open"); });

  const q = document.getElementById("top-q");
  const params = new URLSearchParams(location.search);
  if (params.get("q")) q.value = params.get("q");
  document.getElementById("top-search").addEventListener("submit", (e) => {
    e.preventDefault();
    if (window.onTopSearch) return window.onTopSearch(q.value.trim());
    location.href = `/dashboard.html?q=${encodeURIComponent(q.value.trim())}`;
  });
  q.addEventListener("input", () => { if (window.onTopSearch) window.onTopSearch(q.value.trim()); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      e.preventDefault();
      q.focus();
    }
  });
}

// Fill the system card (AI, email, database). Returns the config.
async function loadSystemStatus() {
  const el = document.getElementById("sys-status");
  try {
    const cfg = await api("/api/config");
    const ai = cfg.status.ai, mail = cfg.status.email;
    const model = ai.model.split("/").pop();
    const mailVal = mail.configured
      ? `${mail.provider.toUpperCase()}${mail.redirect_to ? (mail.redirect_mode === "all" ? " · all redirected" : " · demo redirect") : ""}`
      : "Drafts only";
    el.innerHTML = `
      <div class="sys-row" title="${ai.configured ? "Groq model: " + esc(ai.model) : "No GROQ_API_KEY: rule-based fallback is used"}">
        <span class="dot ${ai.configured ? "on" : "off"}"></span><b>AI</b><span class="val">${ai.configured ? esc(model) : "Fallback only"}</span></div>
      <div class="sys-row" title="${mail.redirect_to ? "Sample vendor emails go to " + esc(mail.redirect_to) : ""}">
        <span class="dot ${mail.configured ? "on" : "off"}"></span><b>Email</b><span class="val">${esc(mailVal)}</span></div>
      <div class="sys-row">
        <span class="dot on"></span><b>Database</b><span class="val">${esc(cfg.status.database || "")}</span></div>`;
    const buyer = cfg.status.buyer || "Procurement";
    document.getElementById("buyer-name").textContent = buyer;
    document.getElementById("top-buyer").textContent = buyer;
    return cfg;
  } catch (e) {
    el.innerHTML = '<div class="sys-row"><span class="dot off"></span><b>Server unreachable</b></div>';
    return null;
  }
}

renderShell();
