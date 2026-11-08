// New submission page: dynamic form per country, drop zones, demo samples, submit.

let CONFIG = null;
const form = document.getElementById("form");
const countrySel = document.getElementById("country");

const POSTAL_LABEL = { IN: "PIN code", US: "ZIP code", UK: "Postcode" };
const STATE_LABEL = { IN: "State", US: "State (2-letter)", UK: "County" };
const SAMPLE_ICON = { approved: "check", pending: "clock", rejected: "x" };

function countryInfo(code) {
  return CONFIG.countries.find(c => c.code === code);
}

function setLabel(id, text, required) {
  document.getElementById(id).innerHTML = esc(text) + (required ? ' <span class="req">*</span>' : "");
}

function fmtSize(bytes) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
}

function updateDrop(input) {
  const drop = input.closest(".drop");
  const status = drop.querySelector(".drop-status");
  const file = input.files && input.files[0];
  drop.classList.toggle("has-file", !!file);
  drop.querySelector(".drop-icon").innerHTML = icon(file ? "check" : "upload");
  status.textContent = file ? `${file.name} · ${fmtSize(file.size)}` : "Drop file or click to browse";
}

function renderCountry() {
  const code = countrySel.value;
  const info = countryInfo(code);
  document.getElementById("pan-field").style.display = code === "IN" ? "" : "none";
  document.getElementById("company-number-field").style.display = code === "UK" ? "" : "none";
  if (code !== "IN") form.pan.value = "";
  if (code !== "UK") form.company_number.value = "";

  setLabel("tax-label", info ? info.tax_id_label : "Tax ID", true);
  setLabel("bank-code-label", info ? info.bank_code_label : "Bank code", true);
  setLabel("postal-label", POSTAL_LABEL[code] || "Postal code", true);
  setLabel("state-label", STATE_LABEL[code] || "State", code === "IN" || code === "US");

  document.getElementById("state-list").innerHTML =
    code === "IN" ? CONFIG.indian_states.map(s => `<option value="${esc(s)}">`).join("") : "";

  const box = document.getElementById("doc-rows");
  if (!info) {
    box.innerHTML = '<div class="muted small">Select a country to see which documents are required.</div>';
    return;
  }
  box.innerHTML = info.documents.map(d => `
    <label class="drop">
      <input type="file" name="doc_${esc(d.type)}" accept=".pdf,.jpg,.jpeg,.png" aria-label="${esc(d.label)}">
      <span class="drop-icon">${icon("upload")}</span>
      <span class="drop-text"><b>${esc(d.label)} <span class="req">*</span></b><span class="drop-status">Drop file or click to browse</span></span>
    </label>`).join("");
  box.querySelectorAll(".drop").forEach(drop => {
    const input = drop.querySelector("input");
    input.addEventListener("change", () => updateDrop(input));
    ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, () => drop.classList.add("over")));
    ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, () => drop.classList.remove("over")));
  });
}

function renderSamples() {
  const groups = CONFIG.samples.map(s => {
    const [kind, ...rest] = s.title.split(":");
    return { ...s, kind: rest.length ? kind.trim() : "Sample", name: rest.length ? rest.join(":").trim() : s.title };
  });
  const box = document.getElementById("samples");
  box.innerHTML = groups.map(s => `
    <div class="sample">
      <span class="sample-ico ${esc(s.expected)}">${icon(SAMPLE_ICON[s.expected] || "info")}</span>
      <div class="sample-main">
        <div class="sample-kind">${esc(s.kind)}</div>
        <div class="sample-title">${esc(s.name.charAt(0).toUpperCase() + s.name.slice(1))}</div>
      </div>
      <button type="button" class="btn soft sm" data-load="${esc(s.key)}">Load</button>
    </div>`).join("");
  box.querySelectorAll("[data-load]").forEach(btn =>
    btn.addEventListener("click", () => loadSample(btn.dataset.load, btn)));
}

function showNotice(html, kind) {
  const ico = kind === "error" ? "alert" : kind === "warn" ? "alert" : "info";
  document.getElementById("form-notice").innerHTML =
    html ? `<div class="notice ${kind || ""}">${icon(ico)}<div>${html}</div></div>` : "";
}

async function attachFile(input, url) {
  const res = await fetch(url);
  const blob = await res.blob();
  const name = url.split("/").pop();
  const file = new File([blob], name, { type: blob.type || "application/pdf" });
  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
  updateDrop(input);
}

async function loadSample(key, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Loading…"; }
  try {
    const sample = await api(`/api/samples/${encodeURIComponent(key)}`);
    form.reset();
    for (const [name, value] of Object.entries(sample.fields)) {
      if (form.elements[name]) form.elements[name].value = value;
    }
    renderCountry();
    for (const [docType, url] of Object.entries(sample.document_urls)) {
      const input = form.querySelector(`input[name="doc_${docType}"]`);
      if (input) await attachFile(input, url);
    }
    showNotice("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (e) {
    showNotice(`Could not load the sample: ${esc(e.message)}`, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Load"; }
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const btn = document.getElementById("submit-btn");
  const msg = document.getElementById("submit-msg");
  if (!countrySel.value) {
    showNotice("Please select a country first.", "warn");
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  btn.disabled = true;
  msg.textContent = "Submitting…";
  try {
    const result = await api("/api/runs", { method: "POST", body: new FormData(form) });
    window.location.href = `/run.html?id=${result.run_id}`;
  } catch (e) {
    showNotice(`Submission failed: ${esc(e.message)}`, "error");
    btn.disabled = false;
    msg.textContent = "";
  }
});

document.getElementById("clear-btn").addEventListener("click", () => {
  form.reset();
  renderCountry();
  showNotice("");
});

countrySel.addEventListener("change", renderCountry);

(async function init() {
  CONFIG = await loadSystemStatus();
  if (!CONFIG) {
    showNotice("Cannot reach the server.", "error");
    return;
  }
  countrySel.innerHTML = '<option value="">Select country…</option>' +
    CONFIG.countries.map(c => `<option value="${c.code}">${esc(c.name)}</option>`).join("");
  renderCountry();
  renderSamples();
})();
