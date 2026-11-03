"""All settings come from environment variables (or a .env file)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


# Postgres connection string (hosted). Leave empty to use a local SQLite file.
DATABASE_URL = _get("DATABASE_URL")
DATA_DIR = Path(_get("DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = DATA_DIR / "onboarding.db"

# --- AI (Groq) -------------------------------------------------------------
GROQ_API_KEY = _get("GROQ_API_KEY")
GROQ_MODEL = _get("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_TIMEOUT = float(_get("GROQ_TIMEOUT", "20"))

# --- Email -----------------------------------------------------------------
# EMAIL_PROVIDER: "smtp" (Gmail etc., for local use), "brevo" (HTTPS API,
# works on hosts that block SMTP such as Render's free tier), or "none".
EMAIL_PROVIDER = _get("EMAIL_PROVIDER", "smtp").lower()
SMTP_HOST = _get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_get("SMTP_PORT", "587"))
SMTP_USER = _get("SMTP_USER")
SMTP_PASSWORD = _get("SMTP_PASSWORD").replace(" ", "")  # Gmail shows app passwords with spaces
BREVO_API_KEY = _get("BREVO_API_KEY")
EMAIL_FROM = _get("EMAIL_FROM", SMTP_USER)
EMAIL_FROM_NAME = _get("EMAIL_FROM_NAME", "Vendor Onboarding")

# Where internal risk alerts go (fraud / blocked-list hits)
COMPLIANCE_EMAIL = _get("COMPLIANCE_EMAIL", EMAIL_FROM)
# Demo safety. The sample vendors have made-up email addresses, so emails to them
# are delivered to DEMO_REDIRECT_TO instead (the intended recipient is written at the
# top). DEMO_REDIRECT_MODE: "samples" = only those made-up addresses (default; a real
# address typed into the form gets the real email), "all" = redirect every email.
DEMO_REDIRECT_TO = _get("DEMO_REDIRECT_TO")
DEMO_REDIRECT_MODE = _get("DEMO_REDIRECT_MODE", "samples").lower()

# --- Business --------------------------------------------------------------
BUYER_COMPANY = _get("BUYER_COMPANY", "Northgate Industries")

# Small pause between stages so a person can follow the live view.
# The checks themselves take milliseconds. Set to 0 to disable.
STAGE_DELAY = float(_get("STAGE_DELAY", "0.7"))

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def email_configured() -> bool:
    if EMAIL_PROVIDER == "smtp":
        return bool(SMTP_USER and SMTP_PASSWORD and EMAIL_FROM)
    if EMAIL_PROVIDER == "brevo":
        return bool(BREVO_API_KEY and EMAIL_FROM)
    return False


def ai_configured() -> bool:
    return bool(GROQ_API_KEY)
