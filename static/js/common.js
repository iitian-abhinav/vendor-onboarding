// Shared helpers used by every page.

const STATUS_TEXT = {
  approved: "Approved", pending: "Pending", rejected: "Rejected",
  running: "Running", error: "Error", waiting: "Waiting",
  pass: "Pass", warn: "Action", fail: "Fail", info: "Info", skip: "Skipped",
};

function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function label(status, extra) {
  return `<span class="label ${esc(status)} ${extra || ""}">${esc(STATUS_TEXT[status] || status)}</span>`;
}

function fmtDateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
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

// Fill the system status in the top bar (AI + email).
async function loadSystemStatus() {
  const el = document.getElementById("sys-status");
  if (!el) return null;
  try {
    const cfg = await api("/api/config");
    const ai = cfg.status.ai, mail = cfg.status.email;
    const model = ai.model.split("/").pop();
    el.innerHTML =
      `<span title="${ai.configured ? "Groq model: " + esc(ai.model) : "No GROQ_API_KEY: rule-based fallback is used"}">` +
      `<span class="dot ${ai.configured ? "on" : "off"}"></span>AI: ${ai.configured ? esc(model) : "fallback only"}</span>` +
      `<span title="${mail.redirect_to ? (mail.redirect_mode === "all" ? "All emails" : "Emails to the sample vendors' made-up addresses") + " are redirected to " + esc(mail.redirect_to) : ""}">` +
      `<span class="dot ${mail.configured ? "on" : "off"}"></span>Email: ${mail.configured ? esc(mail.provider.toUpperCase()) : "drafts only"}` +
      `${mail.redirect_to ? (mail.redirect_mode === "all" ? " (all redirected)" : " (demo redirect)") : ""}</span>`;
    return cfg;
  } catch (e) {
    el.textContent = "Server unreachable";
    return null;
  }
}
