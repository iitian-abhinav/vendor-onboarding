// Live run view. Receives the full run over server-sent events and re-renders.

const runId = new URLSearchParams(location.search).get("id");
const userToggled = {};   // stage idx -> collapsed? (only once the user clicks)

const STAGE_SUB = {
  intake: "Required fields and documents",
  format: "Each value valid on its own",
  consistency: "Values agree with each other and the documents",
  risk: "Vendor master and blocked list",
  decision: "Rules turn findings into an outcome",
  communicate: "Vendor email and internal alerts",
};

const FIELD_LABELS = [
  ["legal_name", "Legal name"], ["country", "Country"], ["address_line", "Address"], ["city", "City"],
  ["state", "State / county"], ["postal_code", "Postal code"], ["website", "Website"],
  ["contact_name", "Contact"], ["contact_email", "Email"], ["contact_phone", "Phone"],
  ["tax_id", "Tax ID"], ["pan", "PAN"], ["company_number", "Company number"],
  ["bank_account_holder", "Account holder"], ["bank_account_number", "Account number"],
  ["bank_code", "Bank code"], ["bank_name", "Bank"],
];
const MONO_FIELDS = new Set(["tax_id", "pan", "company_number", "bank_account_number", "bank_code"]);

const DOC_NAMES = {
  gst_certificate: "GST certificate", pan_card: "PAN card", bank_proof: "Bank proof",
  w9_form: "Form W-9", incorporation_certificate: "Certificate of incorporation", vat_certificate: "VAT certificate",
};

const MSG_STATUS = {
  sent: ["approved", "Sent"], not_configured: ["info", "Draft only"], failed: ["pending", "Not sent"],
};

const OUTCOME_ICON = { approved: "check", pending: "clock", rejected: "x", error: "alert" };

function sourceTag(src) {
  if (src === "ai") return ` <span class="tag ai">${icon("sparkle")}AI</span>`;
  if (src === "fallback") return ' <span class="tag fallback">Rule fallback</span>';
  return "";
}

function nodeInner(status, idx) {
  if (status === "running") return '<span class="spinner"></span>';
  if (status === "pass") return icon("check");
  if (status === "warn") return icon("bang");
  if (status === "fail") return icon("x");
  if (status === "skip") return icon("minus");
  return idx + 1;
}

function renderStages(run) {
  const done = run.stages.filter(s => !["waiting", "running"].includes(s.status)).length;
  document.getElementById("progress-bar").style.width = `${Math.round(done / run.stages.length * 100)}%`;
  document.getElementById("stage-counter").textContent =
    done === run.stages.length ? `All ${done} stages complete` : `${done} of ${run.stages.length} stages complete`;

  document.getElementById("stages").innerHTML = run.stages.map(s => {
    const status = s.status;
    const finished = !["waiting", "running"].includes(status);
    // Stages that passed cleanly start folded (click to open); anything needing attention stays open.
    const collapsed = s.idx in userToggled ? userToggled[s.idx] : (status === "pass" || status === "skip");
    const counts = s.checks.filter(c => c.result !== "skip").length;
    let right = "";
    if (status === "waiting") right = pill("waiting");
    else if (status === "running") right = pill("running");
    else right = pill(status);
    let body = "";
    if (s.checks.length) {
      body = `<div class="step-body"><div class="checks">${s.checks.map(c => `
        <div class="check">
          <div>${pill(c.result)}</div>
          <div class="lbl">${esc(c.label)}</div>
          <div class="det">${esc(c.detail)}${sourceTag(c.source)}${c.internal ? ' <span class="tag internal">Internal only</span>' : ""}
            ${c.action && !c.internal && (c.result === "warn" || c.result === "fail")
              ? `<div class="ask">Asked of vendor: ${esc(c.action)}</div>` : ""}
          </div>
        </div>`).join("")}</div></div>`;
    } else if (status === "running") {
      body = '<div class="waiting-text"><span class="spinner"></span>Running checks…</div>';
    }
    return `
      <div class="step s-${esc(status)} ${finished ? "done" : ""} ${collapsed ? "collapsed" : ""}" data-idx="${s.idx}">
        <div class="node">${nodeInner(status, s.idx)}</div>
        <div class="step-head">
          <div>
            <div class="step-title">${esc(s.name)}</div>
            <div class="step-sub">${esc(STAGE_SUB[s.key] || "")}</div>
          </div>
          <div class="step-meta">
            ${finished && counts ? `<span class="step-count">${counts} check${counts > 1 ? "s" : ""}</span>` : ""}
            <span class="step-time">${fmtSeconds(s.started_at, s.finished_at)}</span>
            ${right}
            ${s.checks.length ? `<span class="chev">${icon("chevron")}</span>` : ""}
          </div>
        </div>
        ${body}
      </div>`;
  }).join("");

  document.querySelectorAll(".step-head").forEach(head => {
    head.addEventListener("click", () => {
      const el = head.parentElement;
      const collapsed = !el.classList.contains("collapsed");
      userToggled[el.dataset.idx] = collapsed;
      el.classList.toggle("collapsed", collapsed);
    });
  });
}

function renderDecision(run) {
  const box = document.getElementById("decision");
  const outcome = run.status === "error" ? "error" : run.decision;
  if (!outcome) {
    box.innerHTML = `
      <div class="outcome">
        <div class="o-icon"><span class="spinner"></span></div>
        <div><div class="o-label">In progress</div><div class="o-word">Checking…</div>
        <div class="o-reason">The decision appears as soon as stage 5 finishes.</div></div>
      </div><div style="height:24px"></div>`;
    return;
  }
  const summarySrc = run.summary_source && run.summary_source.startsWith("ai:")
    ? `<span class="tag ai">${icon("sparkle")}AI</span> ${esc(run.summary_source.slice(3).split("/").pop())}`
    : '<span class="tag">Template</span>';
  box.innerHTML = `
    <div class="outcome ${esc(outcome)}">
      <div class="o-icon">${icon(OUTCOME_ICON[outcome] || "info")}</div>
      <div>
        <div class="o-label">Outcome</div>
        <div class="o-word">${esc(STATUS_TEXT[outcome] || outcome)}</div>
        <div class="o-reason">${esc(run.decision_reason || "")}</div>
        ${run.vendor_code ? `<div style="margin-top:10px">Vendor code <span class="chip-code">${esc(run.vendor_code)}</span></div>` : ""}
      </div>
    </div>
    ${run.reviewer_summary ? `
      <div class="summary">
        <div class="label-line">Reviewer summary ${summarySrc}</div>
        <p>${esc(run.reviewer_summary)}</p>
      </div>` : '<div style="height:24px"></div>'}`;
}

function renderMessages(run) {
  const box = document.getElementById("messages");
  document.getElementById("msg-count").textContent = run.messages.length
    ? `${run.messages.length} message${run.messages.length > 1 ? "s" : ""} for this run`
    : "Emails drafted and sent for this run";
  if (!run.messages.length) {
    box.innerHTML = `<div class="muted small">${run.decision ? "No messages." : "The email is drafted after the decision."}</div>`;
    return;
  }
  box.innerHTML = run.messages.map(m => {
    const [cls, text] = MSG_STATUS[m.status] || ["info", m.status];
    const internal = m.kind === "internal";
    const redirected = m.intended_to && m.to_addr && m.intended_to !== m.to_addr;
    const writer = (m.written_by || "").startsWith("ai:") ? `<span class="tag ai">${icon("sparkle")}AI-assisted</span>`
      : `<span class="tag">${esc(m.written_by === "rules" ? "Rules" : "Template")}</span>`;
    return `
      <div class="mail">
        <div class="mail-head">
          <div class="mail-av ${internal ? "alert" : ""}">${internal ? icon("alert") : "VO"}</div>
          <div class="mail-meta">
            <div class="from">${internal ? "Internal alert · compliance" : "Vendor Onboarding → vendor"}
              <span class="pill ${cls}">${esc(text)}</span> ${writer}</div>
            <div class="to">To ${esc(m.to_addr || "(none)")}${redirected ? ` · intended for ${esc(m.intended_to)}` : ""}</div>
          </div>
        </div>
        <div class="mail-subject">${esc(m.subject)}</div>
        <pre class="mail-body">${esc(m.body)}</pre>
        ${m.error && m.status !== "not_configured" ? `<div class="mail-error">${esc(m.error)}</div>` : ""}
      </div>`;
  }).join("");
}

function renderSubmission(run) {
  const s = run.submission;
  document.getElementById("submission").innerHTML = `<table class="kv">${
    FIELD_LABELS.filter(([k]) => s[k]).map(([k, l]) => {
      const v = k === "country" ? (COUNTRY_NAMES[s[k]] || s[k]) : s[k];
      return `<tr><th>${l}</th><td class="${MONO_FIELDS.has(k) ? "mono" : ""}">${esc(v)}</td></tr>`;
    }).join("")
  }</table>`;
  const docs = run.documents;
  document.getElementById("documents").innerHTML = docs.length ? docs.map(d => `
    <a class="file" href="/api/runs/${run.id}/documents/${d.id}" target="_blank" rel="noopener">
      <span class="file-ico ${d.detected_type === "PDF" ? "" : "img"}">${esc(d.detected_type === "UNKNOWN" ? "?" : d.detected_type)}</span>
      <span><b>${esc(DOC_NAMES[d.doc_type] || d.doc_type.replace(/_/g, " "))}</b>
      <span>${esc(d.filename)} · ${Math.max(1, Math.round(d.size / 1024))} KB</span></span>
    </a>`).join("") : '<div class="empty">No documents attached.</div>';
}

function render(run) {
  document.title = `Run #${run.id} - Vendor Onboarding`;
  document.getElementById("crumb").textContent = `Run #${run.id}`;
  document.getElementById("title").textContent = run.legal_name || "(no company name)";
  const parts = [`Run #${run.id}`, COUNTRY_NAMES[run.country] || run.country, `submitted ${fmtDateTime(run.created_at)}`];
  if (run.finished_at) parts.push(`processed in ${fmtSeconds(run.created_at, run.finished_at)}`);
  document.getElementById("meta").textContent = parts.filter(Boolean).join(" · ");
  document.getElementById("head-status").innerHTML = pill(run.status, "lg");
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
    document.getElementById("page-notice").innerHTML =
      `<div class="notice error" style="margin:0 0 24px">${icon("alert")}<div>${esc(e.message)}</div></div>`;
    return;
  }
  if (!window.EventSource) return poll();
  const source = new EventSource(`/api/runs/${runId}/events`);
  source.onmessage = (e) => render(JSON.parse(e.data));
  source.addEventListener("done", () => source.close());
  source.onerror = () => { source.close(); poll(); };
})();