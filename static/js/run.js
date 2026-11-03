// Live run view. Receives the full run over server-sent events and re-renders.

const runId = new URLSearchParams(location.search).get("id");
const toggled = {};          // stage idx -> true if the user collapsed/expanded it manually
const collapsedState = {};   // stage idx -> collapsed?

const STAGE_SUB = {
  intake: "required fields and documents",
  format: "each value valid on its own",
  consistency: "values agree with each other and the documents",
  risk: "vendor master and blocked list",
  decision: "rules turn findings into an outcome",
  communicate: "vendor email and internal alerts",
};

const FIELD_LABELS = [
  ["legal_name", "Legal name"], ["country", "Country"], ["address_line", "Address"], ["city", "City"],
  ["state", "State / county"], ["postal_code", "Postal code"], ["website", "Website"],
  ["contact_name", "Contact"], ["contact_email", "Email"], ["contact_phone", "Phone"],
  ["tax_id", "Tax ID"], ["pan", "PAN"], ["company_number", "Company number"],
  ["bank_account_holder", "Account holder"], ["bank_account_number", "Account number"],
  ["bank_code", "Bank code"], ["bank_name", "Bank"],
];

const COUNTRY_NAMES = { IN: "India", US: "United States", UK: "United Kingdom" };
const DOC_NAMES = {
  gst_certificate: "GST certificate", pan_card: "PAN card", bank_proof: "Bank proof",
  w9_form: "Form W-9", incorporation_certificate: "Incorporation cert.", vat_certificate: "VAT certificate",
};

const MSG_STATUS = {
  sent: ["pass", "Sent"], not_configured: ["info", "Draft only"], failed: ["warn", "Not sent"],
};

function sourceTag(src) {
  if (src === "ai") return ' <span class="tag ai">AI</span>';
  if (src === "fallback") return ' <span class="tag fallback">Rule fallback</span>';
  return "";
}

function renderStages(run) {
  const done = run.stages.filter(s => !["waiting", "running"].includes(s.status)).length;
  document.getElementById("progress-bar").style.width = `${Math.round(done / run.stages.length * 100)}%`;
  document.getElementById("stage-counter").textContent = `${done} of ${run.stages.length} stages complete`;

  document.getElementById("stages").innerHTML = run.stages.map(s => {
    const collapsed = toggled[s.idx] ? collapsedState[s.idx] : false;
    const status = s.status;
    let right = "";
    if (status === "running") right = '<span class="spinner"></span>';
    else if (status === "waiting") right = label("waiting");
    else right = label(status === "skip" ? "skip" : status);
    const numInner = status === "pass" ? "&#10003;" : status === "fail" ? "&#10005;" : status === "warn" ? "!" : s.idx + 1;
    const body = s.checks.length ? `
      <div class="stage-body">
        <table class="checks"><tbody>
          ${s.checks.map(c => `
            <tr>
              <td class="res">${label(c.result)}</td>
              <td class="lbl">${esc(c.label)}</td>
              <td>${esc(c.detail)}${sourceTag(c.source)}${c.internal ? ' <span class="tag internal">Internal only</span>' : ""}
                ${c.action && !c.internal && (c.result === "warn" || c.result === "fail")
                  ? `<div class="meta small muted">Asked of vendor: ${esc(c.action)}</div>` : ""}
              </td>
            </tr>`).join("")}
        </tbody></table>
      </div>` : (status === "running" ? '<div class="stage-body small muted">Running checks…</div>' : "");
    return `
      <div class="stage s-${esc(status)} ${collapsed ? "collapsed" : ""}" data-idx="${s.idx}">
        <div class="stage-head">
          <div class="stage-num">${numInner}</div>
          <div class="stage-name">${esc(s.name)}<span class="sub">${esc(STAGE_SUB[s.key] || "")}</span></div>
          <div class="stage-time">${fmtSeconds(s.started_at, s.finished_at)}</div>
          <div>${right}</div>
        </div>
        ${body}
      </div>`;
  }).join("");

  document.querySelectorAll(".stage-head").forEach(head => {
    head.addEventListener("click", () => {
      const el = head.parentElement;
      const idx = el.dataset.idx;
      toggled[idx] = true;
      collapsedState[idx] = !el.classList.contains("collapsed");
      el.classList.toggle("collapsed");
    });
  });
}

function renderDecision(run) {
  const box = document.getElementById("decision");
  const outcome = run.status === "error" ? "error" : run.decision;
  if (!outcome) {
    box.innerHTML = '<span class="spinner"></span> <span class="muted">Waiting for the checks to finish…</span>';
    return;
  }
  const summarySrc = run.summary_source && run.summary_source.startsWith("ai:")
    ? `<span class="tag ai">AI</span> ${esc(run.summary_source.slice(3))}` : '<span class="tag">Template</span>';
  box.innerHTML = `
    <div class="decision-box ${esc(outcome)}">
      <div class="big">${esc(STATUS_TEXT[outcome] || outcome)}</div>
      <div>${esc(run.decision_reason || "")}</div>
      ${run.vendor_code ? `<div style="margin-top:6px">Vendor code: <strong class="mono">${esc(run.vendor_code)}</strong></div>` : ""}
    </div>
    ${run.reviewer_summary ? `
      <div style="margin-top:12px">
        <div class="small muted" style="margin-bottom:4px">Reviewer summary &middot; ${summarySrc}</div>
        <div>${esc(run.reviewer_summary)}</div>
      </div>` : ""}`;
}

function renderMessages(run) {
  const box = document.getElementById("messages");
  document.getElementById("msg-count").textContent = run.messages.length ? `${run.messages.length}` : "";
  if (!run.messages.length) {
    box.innerHTML = `<span class="muted">${run.status === "running" ? "Nothing sent yet." : "No messages."}</span>`;
    return;
  }
  box.innerHTML = run.messages.map(m => {
    const [cls, text] = MSG_STATUS[m.status] || ["info", m.status];
    const redirected = m.intended_to && m.to_addr && m.intended_to !== m.to_addr;
    const writer = (m.written_by || "").startsWith("ai:") ? '<span class="tag ai">AI-assisted</span>'
      : `<span class="tag">${esc(m.written_by === "rules" ? "Rules" : "Template")}</span>`;
    return `
      <div class="email">
        <div class="email-head">
          <div><strong>${m.kind === "internal" ? "Internal alert" : "To vendor"}</strong>
            &nbsp;<span class="label ${cls}">${esc(text)}</span> ${writer}</div>
          <div>To: ${esc(m.to_addr || "(none)")}${redirected ? ` <span class="muted">(intended for ${esc(m.intended_to)})</span>` : ""}</div>
          <div>Subject: ${esc(m.subject)}</div>
          ${m.error && m.status !== "not_configured" ? `<div style="color:#b3261e">${esc(m.error)}</div>` : ""}
        </div>
        <pre>${esc(m.body)}</pre>
      </div>`;
  }).join("");
}

function renderSubmission(run) {
  const s = run.submission;
  document.getElementById("submission").innerHTML = `<table class="kv">${
    FIELD_LABELS.filter(([k]) => s[k]).map(([k, l]) =>
      `<tr><th>${l}</th><td>${esc(k === "country" ? (COUNTRY_NAMES[s[k]] || s[k]) : s[k])}</td></tr>`).join("")
  }</table>`;
  const docs = run.documents;
  document.getElementById("documents").innerHTML = docs.length ? `
    <table class="table"><thead><tr><th>Type</th><th>File</th><th class="num">Size</th></tr></thead><tbody>
      ${docs.map(d => `<tr>
        <td>${esc(DOC_NAMES[d.doc_type] || d.doc_type.replace(/_/g, " "))}</td>
        <td><a href="/api/runs/${run.id}/documents/${d.id}" target="_blank">${esc(d.filename)}</a>
          <span class="muted small">${esc(d.detected_type)}</span></td>
        <td class="num">${Math.max(1, Math.round(d.size / 1024))} KB</td></tr>`).join("")}
    </tbody></table>` : '<div class="empty">No documents attached.</div>';
}

function render(run) {
  document.title = `Run #${run.id} - Vendor Onboarding`;
  document.getElementById("crumb").textContent = `#${run.id}`;
  document.getElementById("title").textContent = run.legal_name || "(no company name)";
  const parts = [`Run #${run.id}`, run.country, `submitted ${fmtDateTime(run.created_at)}`];
  if (run.finished_at) parts.push(`processed in ${fmtSeconds(run.created_at, run.finished_at)}`);
  document.getElementById("meta").textContent = parts.filter(Boolean).join(" · ");
  document.getElementById("head-status").innerHTML = label(run.status, "lg");
  renderStages(run);
  renderDecision(run);
  renderMessages(run);
  renderSubmission(run);
}

async function poll() {
  const run = await api(`/api/runs/${runId}`);
  render(run);
  if (run.status === "running") setTimeout(poll, 1000);
}

(async function init() {
  loadSystemStatus();
  if (!runId) {
    document.getElementById("title").textContent = "No run selected";
    return;
  }
  try {
    const run = await api(`/api/runs/${runId}`);
    render(run);
    if (run.status !== "running") return;
  } catch (e) {
    document.getElementById("title").textContent = "Run not found";
    document.getElementById("page-notice").innerHTML = `<div class="notice error">${esc(e.message)}</div>`;
    return;
  }
  if (!window.EventSource) return poll();
  const source = new EventSource(`/api/runs/${runId}/events`);
  source.onmessage = (e) => render(JSON.parse(e.data));
  source.addEventListener("done", () => source.close());
  source.onerror = () => { source.close(); poll(); };
})();
