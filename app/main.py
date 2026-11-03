"""
Web server: receives submissions, starts the pipeline, streams progress, serves the UI.

Run locally:  uvicorn app.main:app --reload
"""
import asyncio
import base64
import hashlib
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .pipeline import run_pipeline
from .reference_data import BLOCKED_ENTITIES, REQUIRED_DOCUMENTS
from .samples import SAMPLES
from .validators import BANK_CODE_LABELS, COUNTRY_NAMES, INDIAN_STATES, TAX_ID_LABELS

STATIC_DIR = config.BASE_DIR / "static"
FIELD_NAMES = ["legal_name", "country", "address_line", "city", "state", "postal_code", "website",
               "contact_name", "contact_email", "contact_phone", "tax_id", "pan", "company_number",
               "bank_account_holder", "bank_account_number", "bank_code", "bank_name"]
_tasks = set()


@asynccontextmanager
async def lifespan(_app):
    db.init()
    # A run left "running" by a restart can never finish; mark it.
    db.execute("UPDATE runs SET status='error', decision_reason='Server restarted during this run' "
               "WHERE status='running'")
    yield


app = FastAPI(title="Vendor Onboarding", lifespan=lifespan)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def detect_type(data: bytes) -> str:
    if data.startswith(b"%PDF"):
        return "PDF"
    if data.startswith(b"\x89PNG"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    return "UNKNOWN"


def pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:3])
    except Exception:
        return ""


def save_document(run_id: int, doc_type: str, filename: str, data: bytes) -> dict:
    """Stores the file in the database (so it survives restarts on hosts with no disk)."""
    safe_name = "".join(ch for ch in (filename or "upload") if ch.isalnum() or ch in "._- ")[:80] or "upload"
    kind = detect_type(data)
    sha = hashlib.sha256(data).hexdigest()
    # Oversized files are recorded (so the check can report them) but not stored.
    stored = data if len(data) <= config.MAX_UPLOAD_BYTES else b""
    db.add_document(run_id, doc_type, safe_name, len(data), kind, sha, stored)
    return {"doc_type": doc_type, "filename": safe_name, "size": len(data), "detected_type": kind,
            "sha256": sha, "text": pdf_text(data) if kind == "PDF" and stored else ""}


def start(run_id: int, submission: dict, docs: list):
    task = asyncio.create_task(run_pipeline(run_id, submission, docs))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

@app.get("/api/config")
def get_config():
    return {
        "countries": [{"code": c, "name": COUNTRY_NAMES[c], "tax_id_label": TAX_ID_LABELS[c],
                       "bank_code_label": BANK_CODE_LABELS[c],
                       "documents": [{"type": t, "label": l} for t, l in REQUIRED_DOCUMENTS[c]]}
                      for c in ("IN", "US", "UK")],
        "indian_states": INDIAN_STATES,
        "samples": [{"key": k, "title": s["title"], "expected": s["expected"], "explain": s["explain"]}
                    for k, s in SAMPLES.items()],
        "status": {
            "ai": {"configured": config.ai_configured(), "model": config.GROQ_MODEL},
            "email": {"configured": config.email_configured(), "provider": config.EMAIL_PROVIDER,
                      "redirect_to": config.DEMO_REDIRECT_TO or None,
                      "redirect_mode": config.DEMO_REDIRECT_MODE},
            "database": db.backend_name(),
            "buyer": config.BUYER_COMPANY,
        },
    }


@app.get("/api/samples/{key}")
def get_sample(key: str):
    sample = SAMPLES.get(key)
    if not sample:
        raise HTTPException(404, "Unknown sample")
    return {"key": key, **sample,
            "document_urls": {d: f"/samples/{key}/{d}.pdf" for d in sample["documents"]}}


@app.post("/api/runs")
async def create_run(request: Request):
    """
    Accepts either:
      - multipart/form-data from the web form (fields + files named doc_<type>)
      - application/json {fields..., "documents": [{"type", "filename", "content_base64"}]}
    """
    ctype = request.headers.get("content-type", "")
    files = []
    if ctype.startswith("application/json"):
        body = await request.json()
        submission = {k: str(body.get(k, "") or "") for k in FIELD_NAMES}
        for d in body.get("documents") or []:
            try:
                data = base64.b64decode(d.get("content_base64", ""), validate=True)
            except Exception:
                raise HTTPException(400, f"Document '{d.get('type')}' is not valid base64")
            files.append((d.get("type", "other"), d.get("filename", "document"), data))
    else:
        form = await request.form()
        submission = {k: str(form.get(k, "") or "") for k in FIELD_NAMES}
        for key, value in form.multi_items():
            if key.startswith("doc_") and hasattr(value, "read"):
                data = await value.read()
                if value.filename:
                    files.append((key[4:], value.filename, data))

    run_id = db.create_run(submission)
    docs = [save_document(run_id, t, name, data) for t, name, data in files]
    start(run_id, submission, docs)
    return {"run_id": run_id}


@app.get("/api/runs")
def list_runs(status: str = None, q: str = None):
    return {"runs": db.list_runs(status, q), "stats": db.stats()}


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: int, request: Request):
    """Server-sent events: pushes the full run every time it changes, until it finishes."""
    if not db.get_run(run_id):
        raise HTTPException(404, "Run not found")

    async def stream():
        last_seq = -1
        while True:
            if await request.is_disconnected():
                break
            row = db.query_one("SELECT updated_seq, status FROM runs WHERE id=?", (run_id,))
            if row and row["updated_seq"] != last_seq:
                last_seq = row["updated_seq"]
                yield f"data: {json.dumps(db.get_run(run_id))}\n\n"
            if row and row["status"] != "running":
                yield "event: done\ndata: {}\n\n"
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


MEDIA_TYPES = {"PDF": "application/pdf", "PNG": "image/png", "JPEG": "image/jpeg"}


@app.get("/api/runs/{run_id}/documents/{doc_id}")
def download_document(run_id: int, doc_id: int):
    doc = db.get_document(run_id, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.get("content"):
        return Response(bytes(doc["content"]),
                        media_type=MEDIA_TYPES.get(doc["detected_type"], "application/octet-stream"),
                        headers={"Content-Disposition": f'inline; filename="{doc["filename"]}"'})
    if doc.get("path") and Path(doc["path"]).exists():  # files saved by an earlier version
        return FileResponse(doc["path"], filename=doc["filename"])
    raise HTTPException(404, "File content not stored")


@app.get("/api/messages")
def list_messages():
    return {"messages": db.query(
        "SELECT m.*, r.legal_name FROM messages m LEFT JOIN runs r ON r.id = m.run_id ORDER BY m.id DESC LIMIT 200")}


@app.get("/api/vendors")
def list_vendors():
    return {"vendors": db.query("SELECT * FROM vendors ORDER BY code"),
            "blocked": [{"name": n, "reason": r} for n, r in BLOCKED_ENTITIES]}


@app.post("/api/admin/reset")
def reset():
    if any(not t.done() for t in _tasks):
        return JSONResponse({"error": "A run is in progress. Try again in a few seconds."}, status_code=409)
    db.reset_demo()
    return {"ok": True}


@app.get("/healthz")
def health():
    return {"ok": True}


# --------------------------------------------------------------------------
# UI (static files)
# --------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
