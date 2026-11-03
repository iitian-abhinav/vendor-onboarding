// Dashboard: stats, run history, outbox, vendor master.

let currentTab = "runs";
let refreshTimer = null;
const openMessages = new Set();

function renderStats(st) {
  const avg = st.avg_seconds == null ? "–" : `${st.avg_seconds}s`;
  document.getElementById("stats").innerHTML = `
    <div class="stat total"><div class="n">${st.total}</div><div class="t">Submissions</div></div>
    <div class="stat approved"><div class="n">${st.approved}</div><div class="t">Approved</div></div>
    <div class="stat pending"><div class="n">${st.pending}</div><div class="t">Pending</div></div>
    <div class="stat rejected"><div class="n">${st.rejected}</div><div class="t">Rejected</div></div>
    <div class="stat"><div class="n">${avg}</div><div class="t">Avg. processing time</div></div>`;
}

async function loadRuns() {
  const status = document.getElementById("filter-status").value;
  const q = document.getElementById("filter-q").value.trim();
  const params = new URLSearchParams({ status });
  if (q) params.set("q", q);
  const data = await api(`/api/runs?${params}`);
  renderStats(data.stats);
  const body = document.getElementById("runs");
  if (!data.runs.length) {
    body.innerHTML = `<tr><td colspan="7" class="empty">${status === "all" && !q
      ? 'No submissions yet. <a href="/">Create one</a> or load a demo sample.' : "No runs match the filter."}</td></tr>`;
  } else {
    body.innerHTML = data.runs.map(r => `
      <tr class="clickable" data-id="${r.id}">
        <td class="num"><a href="/run.html?id=${r.id}">#${r.id}</a></td>
        <td style="white-space:nowrap">${esc(fmtDateTime(r.created_at))}</td>
        <td>${esc(r.legal_name || "(no name)")}${r.vendor_code ? ` <span class="muted small mono nowrap">${esc(r.vendor_code)}</span>` : ""}</td>
        <td class="hide-sm">${esc(r.country || "")}</td>
        <td>${label(r.status)}</td>
        <td class="hide-sm"><div class="ellipsis" title="${esc(r.top_issue || "")}">${esc(r.top_issue || "–")}</div></td>
        <td class="num hide-sm">${esc(fmtSeconds(r.created_at, r.finished_at))}</td>
      </tr>`).join("");
    body.querySelectorAll("tr.clickable").forEach(tr =>
      tr.addEventListener("click", () => { location.href = `/run.html?id=${tr.dataset.id}`; }));
  }
  document.getElementById("updated").textContent = `Updated ${new Date().toLocaleTimeString()}`;
  const anyRunning = data.runs.some(r => r.status === "running");
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, anyRunning ? 1500 : 8000);
}

async function loadOutbox() {
  const data = await api("/api/messages");
  const body = document.getElementById("outbox");
  if (!data.messages.length) {
    body.innerHTML = '<tr><td colspan="6" class="empty">No messages yet.</td></tr>';
    return;
  }
  const statusMap = { sent: ["pass", "Sent"], not_configured: ["info", "Draft only"], failed: ["warn", "Not sent"] };
  body.innerHTML = data.messages.map(m => {
    const [cls, text] = statusMap[m.status] || ["info", m.status];
    const open = openMessages.has(m.id);
    return `
      <tr class="clickable" data-msg="${m.id}">
        <td style="white-space:nowrap">${esc(fmtDateTime(m.created_at))}</td>
        <td class="num"><a href="/run.html?id=${m.run_id}">#${m.run_id}</a></td>
        <td>${m.kind === "internal" ? '<span class="tag internal">Internal alert</span>' : "Vendor"}</td>
        <td>${esc(m.to_addr || "")}</td>
        <td>${esc(m.subject)}</td>
        <td><span class="label ${cls}">${esc(text)}</span></td>
      </tr>
      <tr ${open ? "" : "hidden"} data-body="${m.id}"><td colspan="6"><pre style="margin:0;white-space:pre-wrap">${esc(m.body)}</pre></td></tr>`;
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
      <td class="mono">${esc(v.code)}</td>
      <td>${esc(v.legal_name)}</td>
      <td>${esc(v.country)}</td>
      <td class="mono">${esc(v.tax_id || "")}</td>
      <td class="mono">${esc(v.bank_account || "")} <span class="muted">${esc(v.bank_code || "")}</span></td>
      <td>${v.source === "onboarded" ? `Onboarded (<a href="/run.html?id=${v.run_id}">run #${v.run_id}</a>)` : "Existing"}</td>
    </tr>`).join("");
  document.getElementById("blocked").innerHTML = data.blocked.map(b =>
    `<tr><td>${esc(b.name)}</td><td>${esc(b.reason)}</td></tr>`).join("");
}

async function refresh() {
  try {
    if (currentTab === "runs") await loadRuns();
    else {
      // keep stats fresh on every tab
      const data = await api("/api/runs?status=all");
      renderStats(data.stats);
      if (currentTab === "outbox") await loadOutbox();
      if (currentTab === "vendors") await loadVendors();
    }
  } catch (e) {
    document.getElementById("updated").textContent = `Could not refresh: ${e.message}`;
  }
}

document.querySelectorAll(".tabs button").forEach(btn => btn.addEventListener("click", () => {
  currentTab = btn.dataset.tab;
  document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("active", b === btn));
  ["runs", "outbox", "vendors"].forEach(t => { document.getElementById(`tab-${t}`).hidden = t !== currentTab; });
  history.replaceState(null, "", `#${currentTab}`);
  refresh();
}));

document.getElementById("filter-status").addEventListener("change", loadRuns);
let searchTimer = null;
document.getElementById("filter-q").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadRuns, 250);
});

document.getElementById("reset-btn").addEventListener("click", async () => {
  if (!confirm("Delete all runs and messages, and restore the vendor master to its original 9 vendors?")) return;
  try {
    await api("/api/admin/reset", { method: "POST" });
    refresh();
  } catch (e) {
    alert(e.message);
  }
});

loadSystemStatus();
const initial = location.hash.slice(1);
if (["outbox", "vendors"].includes(initial)) {
  document.querySelector(`.tabs button[data-tab="${initial}"]`).click();
} else {
  refresh();
}
