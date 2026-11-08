// Dashboard: KPIs, outcome split, run history, outbox, vendor master.

const state = {
  range: "all",
  status: "all",
  q: new URLSearchParams(location.search).get("q") || "",
  runs: [],
};
let refreshTimer = null;
const openMessages = new Set();

const SPLIT_COLORS = {
  approved: "var(--green-solid)", pending: "var(--amber-solid)", rejected: "var(--red-solid)", other: "#b9bcd0",
};
const RANGE_TEXT ={ today: "Today", "7d": "Last 7 days", "30d": "Last 30 days", all: "All submissions" };

function currentView() {
  const h = location.hash.slice(1);
  return ["outbox", "vendors"].includes(h) ? h : "runs";
}

function inRange(run) {
  if (state.range === "all") return true;
  const t = new Date(run.created_at);
  const now = new Date();
  if (state.range === "today") {
    return t.toDateString() === now.toDateString();
  }
  const days = state.range === "7d" ? 7 : 30;
  return now - t <= days * 86400000;
}

function matchesSearch(run) {
  const q = state.q.toLowerCase().replace(/^#/, "");
  if (!q) return true;
  return (run.legal_name || "").toLowerCase().includes(q) || String(run.id) === q;
}

function pct(n, total) {
  return total ? Math.round((n / total) * 100) : 0;
}

function renderKpis(runs) {
  const count = s => runs.filter(r => r.status === s).length;
  const total = runs.length;
  const done = runs.filter(r => r.finished_at);
  const avg = done.length
    ? done.reduce((sum, r) => sum + (new Date(r.finished_at) - new Date(r.created_at)) / 1000, 0) / done.length
    : null;
  const cards = [
    { cls: "", ico: "layers", label: "Submissions", num: total, foot: RANGE_TEXT[state.range] },
    { cls: "approved", ico: "check", label: "Approved", num: count("approved"), foot: `${pct(count("approved"), total)}% of submissions` },
    { cls: "pending", ico: "clock", label: "Pending", num: count("pending"), foot: "Waiting on the vendor" },
    { cls: "rejected", ico: "x", label: "Rejected", num: count("rejected"), foot: `${pct(count("rejected"), total)}% of submissions` },
    { cls: "time", ico: "bolt", label: "Avg. processing time", num: avg == null ? "–" : `${avg.toFixed(1)}s`, foot: "Submit to email sent" },
  ];
  document.getElementById("kpis").innerHTML = cards.map(c => `
    <div class="kpi">
      <div class="kpi-top"><span class="kpi-ico ${c.cls}">${icon(c.ico)}</span></div>
      <div class="kpi-label">${c.label}</div>
      <div class="kpi-num">${c.num}</div>
      <div class="kpi-foot">${esc(c.foot)}</div>
    </div>`).join("");
}

function renderSplit(runs) {
  const total = runs.length;
  const parts = [
    ["approved", "Approved", runs.filter(r => r.status === "approved").length],
    ["pending", "Pending", runs.filter(r => r.status === "pending").length],
    ["rejected", "Rejected", runs.filter(r => r.status === "rejected").length],
  ];
  const other = total - parts.reduce((s, p) => s + p[2], 0);
  if (other > 0) parts.push(["other", "Running / error", other]);
  document.getElementById("split-sub").textContent = RANGE_TEXT[state.range];
  if (!total) {
    document.getElementById("split").innerHTML = '<div class="muted">No submissions in this period yet.</div>';
    return;
  }
  const approvalRate = pct(parts[0][2], total);
  document.getElementById("split").innerHTML = `
    <div class="split-total"><b>${approvalRate}%</b><span>approved straight through · ${total} submission${total > 1 ? "s" : ""}</span></div>
    <div class="bar">${parts.filter(p => p[2]).map(p =>
      `<div class="${p[0]}" style="width:${(p[2] / total) * 100}%" title="${p[1]}: ${p[2]}"></div>`).join("")}</div>
    <div class="legend">${parts.map(p => `
      <div><i style="background:${SPLIT_COLORS[p[0]]}"></i>
        ${p[1]} <em>${p[2]} · ${pct(p[2], total)}%</em></div>`).join("")}</div>`;
}

function renderRunsTable() {
  const inPeriod = state.runs.filter(inRange);
  const rows = inPeriod.filter(r => (state.status === "all" || r.status === state.status) && matchesSearch(r));
  const body = document.getElementById("runs");
  if (!rows.length) {
    const none = !state.runs.length;
    body.innerHTML = `<tr><td colspan="6"><div class="empty">
      <b>${none ? "No submissions yet" : "No runs match"}</b>
      ${none ? 'Load a demo sample on <a href="/">New submission</a> to see it here.' : "Try another filter or clear the search."}</div></td></tr>`;
    return;
  }
  body.innerHTML = rows.map(r => `
    <tr class="clickable" data-id="${r.id}">
      <td class="num"><a class="run-id" href="/run.html?id=${r.id}">#${r.id}</a></td>
      <td class="vendor"><b>${esc(r.legal_name || "(no name)")}</b>
        <span>${esc(COUNTRY_NAMES[r.country] || r.country || "")}${r.vendor_code ? ` · <span class="mono">${esc(r.vendor_code)}</span>` : ""}</span></td>
      <td class="hide-sm nowrap muted">${esc(fmtDateTime(r.created_at))}</td>
      <td>${pill(r.status)}</td>
      <td class="hide-sm"><div class="issue" title="${esc(r.top_issue || "")}">${esc(r.top_issue || "No issues")}</div></td>
      <td class="num hide-sm muted">${esc(fmtSeconds(r.created_at, r.finished_at))}</td>
    </tr>`).join("");
  body.querySelectorAll("tr.clickable").forEach(tr =>
    tr.addEventListener("click", () => { location.href = `/run.html?id=${tr.dataset.id}`; }));
}

function renderRunsView() {
  const inPeriod = state.runs.filter(inRange);
  renderKpis(inPeriod);
  renderSplit(inPeriod);
  renderRunsTable();
}

async function loadRuns() {
  const data = await api("/api/runs?status=all");
  state.runs = data.runs;
  renderRunsView();
  document.getElementById("updated").textContent = `Updated ${new Date().toLocaleTimeString()}`;
  const anyRunning = data.runs.some(r => r.status === "running");
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, anyRunning ? 1500 : 8000);
}

async function loadOutbox() {
  const data = await api("/api/messages");
  const body = document.getElementById("outbox");
  if (!data.messages.length) {
    body.innerHTML = '<tr><td colspan="6"><div class="empty"><b>No messages yet</b>Emails appear here after each run.</div></td></tr>';
    return;
  }
  const statusMap = { sent: ["approved", "Sent"], not_configured: ["info", "Draft only"], failed: ["pending", "Not sent"] };
  body.innerHTML = data.messages.map(m => {
    const [cls, text] = statusMap[m.status] || ["info", m.status];
    const open = openMessages.has(m.id);
    return `
      <tr class="clickable" data-msg="${m.id}">
        <td class="hide-sm nowrap muted">${esc(fmtDateTime(m.created_at))}</td>
        <td class="num"><a class="run-id" href="/run.html?id=${m.run_id}">#${m.run_id}</a></td>
        <td>${m.kind === "internal" ? '<span class="tag internal">Internal alert</span>' : '<span class="tag">Vendor</span>'}</td>
        <td class="hide-sm">${esc(m.to_addr || "")}</td>
        <td><b style="font-weight:600">${esc(m.subject)}</b></td>
        <td><span class="pill ${cls}">${esc(text)}</span></td>
      </tr>
      <tr ${open ? "" : "hidden"} data-body="${m.id}"><td colspan="6" style="border-top:0;padding-top:0"><pre>${esc(m.body)}</pre></td></tr>`;
  }).join("");
  body.querySelectorAll("tr[data-msg]").forEach(tr => tr.addEventListener("click", (e) => {
    if (e.target.tagName === "A") return;
    const id = Number(tr.dataset.msg);
    const row = body.querySelector(`tr[data-body="${id}"]`);
    row.hidden = !row.hidden;
    row.hidden ? openMessages.delete(id) : openMessages.add(id);
  }));
}

async function loadVendors() {
  const data = await api("/api/vendors");
  document.getElementById("vendors").innerHTML = data.vendors.map(v => `
    <tr>
      <td><span class="chip-code">${esc(v.code)}</span></td>
      <td class="vendor"><b>${esc(v.legal_name)}</b></td>
      <td class="hide-sm"><span class="flag">${esc(v.country)}</span></td>
      <td class="hide-sm mono">${esc(v.tax_id || "")}</td>
      <td class="mono">${esc(v.bank_account || "")} <span class="muted">${esc(v.bank_code || "")}</span></td>
      <td class="hide-sm">${v.source === "onboarded"
        ? `<span class="pill approved">Onboarded</span> <a href="/run.html?id=${v.run_id}">run #${v.run_id}</a>`
        : '<span class="pill skip">Existing</span>'}</td>
    </tr>`).join("");
  document.getElementById("blocked").innerHTML = data.blocked.map(b =>
    `<tr><td class="vendor"><b>${esc(b.name)}</b></td><td class="muted">${esc(b.reason)}</td></tr>`).join("");
}

async function refresh() {
  const view = currentView();
  try {
    if (view === "runs") await loadRuns();
    if (view === "outbox") await loadOutbox();
    if (view === "vendors") await loadVendors();
  } catch (e) {
    const el = document.getElementById("updated");
    if (el) el.textContent = `Could not refresh: ${e.message}`;
  }
}

function showView() {
  const view = currentView();
  ["runs", "outbox", "vendors"].forEach(v => { document.getElementById(`view-${v}`).hidden = v !== view; });
  document.title = `${{ runs: "Dashboard", outbox: "Outbox", vendors: "Vendor master" }[view]} - Vendor Onboarding`;
  refresh();
}

function bindSeg(id, key, attr) {
  const seg = document.getElementById(id);
  seg.querySelectorAll("button").forEach(btn => btn.addEventListener("click", () => {
    seg.querySelectorAll("button").forEach(b => b.classList.toggle("active", b === btn));
    state[key] = btn.dataset[attr];
    renderRunsView();
  }));
}
bindSeg("range", "range", "range");
bindSeg("status-filter", "status", "status");

// Top-bar search filters the runs table live.
window.onTopSearch = (q) => {
  state.q = q;
  if (currentView() !== "runs") { location.hash = ""; return; }
  renderRunsTable();
};

document.getElementById("reset-btn").addEventListener("click", async () => {
  if (!confirm("Delete all runs and messages, and restore the vendor master to its original 9 vendors?")) return;
  try {
    await api("/api/admin/reset", { method: "POST" });
    refresh();
  } catch (e) {
    alert(e.message);
  }
});

window.addEventListener("hashchange", showView);
loadSystemStatus();
showView();
