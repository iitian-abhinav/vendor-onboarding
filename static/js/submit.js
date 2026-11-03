// New submission page: dynamic form per country, demo samples, submit.

let CONFIG = null;
const form = document.getElementById("form");
const countrySel = document.getElementById("country");

const POSTAL_LABEL = { IN: "PIN code", US: "ZIP code", UK: "Postcode" };
const STATE_LABEL = { IN: "State", US: "State (2-letter)", UK: "County" };

function countryInfo(code) {
  return CONFIG.countries.find(c => c.code === code);
}

function setLabel(id, text, required) {
  document.getElementById(id).innerHTML = esc(text) + (required ? ' <span class="req">*</span>' : "");
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

  const list = document.getElementById("state-list");
  list.innerHTML = code === "IN" ? CONFIG.indian_states.map(s => `<option value="${esc(s)}">`).join("") : "";

  const rows = document.getElementById("doc-rows");
  if (!info) {
    rows.innerHTML = '<tr><td class="muted">Select a country to see which documents are required.</td></tr>';
    return;
  }
  rows.innerHTML = info.documents.map(d => `
    <tr>
      <td class="doc-name">${esc(d.label)} <span class="req">*</span></td>
      <td><input type="file" name="doc_${esc(d.type)}" accept=".pdf,.jpg,.jpeg,.png"></td>
    </tr>`).join("");
}

function renderSamples() {
  const box = document.getElementById("samples");
  box.innerHTML = CONFIG.samples.map(s => `
    <div class="sample" data-key="${esc(s.key)}">
      <div class="sample-top">
        <div class="sample-title">${esc(s.title)}</div>
        <button type="button" class="btn sm" data-load="${esc(s.key)}">Load</button>
      </div>
      <p>Expected: ${label(s.expected)}</p>
    </div>`).join("");
  box.querySelectorAll("[data-load]").forEach(btn =>
    btn.addEventListener("click", () => loadSample(btn.dataset.load)));
}

function showNotice(html, kind) {
  document.getElementById("form-notice").innerHTML = html ? `<div class="notice ${kind || ""}">${html}</div>` : "";
}

async function attachFile(input, url) {
  const res = await fetch(url);
  const blob = await res.blob();
  const name = url.split("/").pop();
  const file = new File([blob], name, { type: blob.type || "application/pdf" });
  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
}

async function loadSample(key) {
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
    showNotice(`<strong>Loaded:</strong> ${esc(sample.title)}. ${esc(sample.explain)}
      <div class="small muted" style="margin-top:4px">Expected outcome: ${label(sample.expected)}.
      The sample's email address is made up, so its outcome email goes to the demo inbox.
      Put your own address in the Email field to receive it yourself.</div>`);
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (e) {
    showNotice(`Could not load the sample: ${esc(e.message)}`, "error");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const btn = document.getElementById("submit-btn");
  const msg = document.getElementById("submit-msg");
  if (!countrySel.value) {
    showNotice("Please select a country first.", "warn");
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
  countrySel.innerHTML = '<option value="">Select…</option>' +
    CONFIG.countries.map(c => `<option value="${c.code}">${esc(c.name)}</option>`).join("");
  renderCountry();
  renderSamples();
})();
