# Vendor Onboarding: from submission to approval

ASA case study, **PS-2 (Operations)**. A vendor submits their company, tax, bank and
contact details plus documents. The process checks it in six stages and returns
**Approved**, **Pending** or **Rejected**, with every check visible, then emails the
vendor exactly what is needed (and alerts compliance when something looks like fraud).

**Python (FastAPI + SQLite)** makes every decision. **Groq AI** helps with two narrow
jobs. **Plain HTML/CSS/JS** is the UI.

---

## Run it locally (about 5 minutes)

Needs Python 3.10 or newer.

```bash
cd vendor-onboarding
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # Windows: copy .env.example .env
# open .env and fill in GROQ_API_KEY, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM, DEMO_REDIRECT_TO

uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**.

The app works with an empty `.env`: AI falls back to rules and emails are saved as
drafts. The two dots in the top-right corner show what is switched on.

### Gmail app password
Your normal Gmail password will not work. Turn on 2-Step Verification in your Google
account, then create an **App password** (Google Account → Security → App passwords).
Put the 16 characters in `SMTP_PASSWORD`.

---

## The six stages

| # | Stage | What it checks |
|---|---|---|
| 1 | **Intake & completeness** | Required fields and documents for the country; files are real PDFs/images (checked by content, not extension); the same file isn't uploaded twice. |
| 2 | **Format validation** | Each value on its own, including official check digits: GSTIN checksum, ABA routing checksum, UK VAT modulus-97, EIN prefixes, PAN, IFSC, sort code, postcodes. Detects a tax ID from the *wrong country*. |
| 3 | **Cross-field consistency** | Values agree with each other and with the documents: PAN inside the GSTIN, GSTIN state vs address state, PAN entity type vs "Private Limited", bank account name vs company name (AI), email domain vs website, tax ID and account number actually appear in the uploaded certificate and bank proof. |
| 4 | **Risk & duplicate check** | Against the vendor master: bank account already used by another vendor, tax ID already registered, blocked/debarred list. |
| 5 | **Decision** | Fixed rule: **any hard failure → Rejected**, otherwise **anything needing vendor action → Pending**, otherwise **Approved** (vendor is added to the vendor master). |
| 6 | **Communicate** | Email to the vendor listing exactly what to fix. For fraud signals, the vendor gets a neutral message and compliance gets the details. |

Each check is one of: **pass**, **info** (noted, no effect), **action** (fixable → pending),
**fail** (hard stop → rejected), **skipped** (an earlier input was missing).

### Where the AI is used, and where it isn't
- **Bank name vs company name.** Clear matches and clear mismatches (e.g. "LLP" vs
  "Private Limited") are decided by rules. Only the unclear cases go to the AI
  ("SRI LAKSHMI ENGG WORKS PVT LTD" vs "Sri Lakshmi Engineering Works Private Limited").
- **Writing.** The AI writes the opening/closing of the email and a reviewer summary.
  **The list of what the vendor must fix always comes from the rules**, so the AI cannot
  invent or drop a requirement. Internal findings are never sent to the vendor-facing prompt.
- **The AI never decides** approved/pending/rejected.
- **Fallback.** If Groq is down or the key is missing, a strict rule (every word must match
  or be an abbreviation) and templates take over. The run still finishes, and the UI marks
  which checks used **AI** or **Rule fallback**.

---

## Demo samples (load them from the right-hand panel)

| Sample | Outcome | What it shows |
|---|---|---|
| Happy path: Indian vendor | Approved | Everything consistent. Abbreviated bank name accepted by the AI. |
| Happy path: UK vendor | Approved | Same process, UK rules. |
| **Edge 1:** bank account in a different name | Pending | "Kaveri Traders" vs "Kaveri Agro Foods Private Limited". Vendor asked for a bank letter. |
| **Edge 2:** GSTIN belongs to another company | Rejected | Every field valid on its own; only cross-referencing shows the PAN inside the GSTIN isn't theirs. |
| **Edge 3:** US tax ID on an Indian registration | Rejected | An identity conflict, not a typo. The uploaded certificate shows the real GSTIN, and the email tells them. |
| **Edge 4:** bank account already on file | Rejected | Payment-diversion pattern. Neutral email to the vendor; details to compliance only. |
| Extra: incomplete submission | Pending | Missing phone and bank proof; email lists exactly those two items. |

Running the happy path **twice** is a good live demo: the second run is rejected as a
duplicate, because the first one added the vendor to the vendor master.
**Dashboard → Vendor master → Reset demo data** restores the starting state.

The sample vendors have made-up email addresses, so their emails go to `DEMO_REDIRECT_TO` (your
inbox), with the intended recipient written at the top. If you type a real address into the
form, that address receives the email. Set `DEMO_REDIRECT_MODE=all` to redirect everything.

---

## Assumptions (made deliberately; the brief left these open)
- The form is filled in by the vendor; the procurement team sees the outcome.
- Countries: India, United States, United Kingdom. Anything else is rejected with a clear message.
- Typos (bad check digit) are **Pending**: the vendor can fix them. Identity conflicts
  (another country's tax ID, GSTIN and PAN from different taxpayers) are **Rejected**:
  the submission contradicts itself and a fresh one is needed.
- Free email domains (gmail.com) and foreign phone numbers are noted, not blocked: common for small vendors.
- Documents are read for text (to match the tax ID and account number). Scanned images
  can't be read, so they are flagged for a quick manual look instead of failing.
- The vendor master and blocked list are small fake datasets in `app/reference_data.py`.
- A short pause between stages (`STAGE_DELAY`) makes the live view easy to follow. The
  checks themselves take milliseconds.

## What I'd build next
Vendor resubmission linked to the original run · OCR for scanned documents · live
GSTIN/VAT lookups against government APIs · bank account verification (penny drop) ·
reviewer override with a reason, kept in the audit trail.

---

## API
- `POST /api/runs` with multipart form data (the web form), or JSON:
  `{ "legal_name": "...", "country": "IN", ..., "documents": [{"type": "gst_certificate", "filename": "gst.pdf", "content_base64": "..."}] }`
- `GET /api/runs/{id}`: full run, every check. `GET /api/runs/{id}/events`: live stream.
- `GET /api/runs`, `GET /api/messages`, `GET /api/vendors`, `POST /api/admin/reset`, `GET /healthz`

## Project layout
```
app/
  main.py            web server, uploads, live stream
  pipeline.py        the six stages and the decision rule
  validators.py      formats and checksums (GSTIN, PAN, IFSC, EIN, ABA, UK VAT...)
  names.py           company-name normalisation and abbreviation matching
  ai.py              Groq calls (name judgement, email text, reviewer summary)
  emailer.py         Gmail SMTP or Brevo API
  db.py              SQLite locally / Postgres hosted: runs, stages, documents, messages, vendors
  reference_data.py  required documents, vendor master, blocked list
  samples.py         demo submissions
static/              UI (index, run, dashboard) and sample PDFs
scripts/make_sample_docs.py   regenerates the sample PDFs
```

## Storage
- **Laptop:** leave `DATABASE_URL` empty. Everything goes into `data/onboarding.db` (SQLite).
- **Hosted:** set `DATABASE_URL` to a Postgres connection string (Neon's free tier).
  Render's free tier has no permanent disk, so this keeps run history and uploaded documents
  across restarts. Uploaded documents are stored in the database itself.

The code is the same either way (`app/db.py`). The top-bar status and `/api/config` show which is in use.

## Deploying on Render (free)

You need free accounts on GitHub, Neon, Brevo and Render.

1. **Neon:** create a project (region: AWS Asia Pacific, Singapore), click **Connect**, and
   copy the connection string. That is `DATABASE_URL`.
2. **Brevo:** add your Gmail address as a sender (Settings → Senders) and click the
   verification link. Then generate an API key (Settings → SMTP & API → API Keys).
   That is `BREVO_API_KEY`.
3. **GitHub:** push this folder to a new repository. `.env` is git-ignored; run `git status`
   to check it isn't listed before committing.
4. **Render:** New + → **Blueprint** → pick the repository. `render.yaml` sets everything up;
   fill in the secrets it asks for:
   `DATABASE_URL`, `GROQ_API_KEY`, `BREVO_API_KEY`, `EMAIL_FROM` (the verified sender),
   `DEMO_REDIRECT_TO` and `COMPLIANCE_EMAIL` (your Gmail).
5. **Check:** open the URL. The top bar should show AI and email in green. Run a sample, then
   **Manual Deploy → Restart service** and confirm the run is still on the dashboard.
6. **Keep it awake:** free services sleep after 15 minutes idle and take about a minute to wake.
   Add a free UptimeRobot HTTP monitor on `https://<your-app>.onrender.com/healthz` every 5 minutes.

Render's free tier blocks SMTP ports, which is why the hosted version sends email through
Brevo's HTTPS API instead of Gmail.
