"""
The AI does two narrow jobs. It never makes the approve / pending / reject decision.

  1. judge_names()  - are two company names the same legal entity?
                      ("SRI LAKSHMI ENGG WORKS PVT LTD" vs "Sri Lakshmi Engineering Works Private Limited")
  2. draft_vendor_texts() / summarize_for_reviewer()
                    - write the opening/closing of the vendor email, and a plain-English
                      summary for the procurement reviewer. The list of items the vendor
                      must fix always comes from the rules, never from the AI.

Every call has a deterministic fallback, so if Groq is slow, down, or the key is
missing, the process still finishes with the same decision.
"""
import json
import re

import httpx

from . import config

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class AIUnavailable(Exception):
    pass


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


async def _chat_json(system: str, user: str) -> dict:
    if not config.ai_configured():
        raise AIUnavailable("GROQ_API_KEY is not set")
    payload = {
        "model": config.GROQ_MODEL,
        "temperature": 0.1,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {config.GROQ_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=config.GROQ_TIMEOUT) as client:
            resp = await client.post(GROQ_URL, json=payload, headers=headers)
            if resp.status_code == 400:
                # Some models reject JSON mode; retry once without it.
                payload.pop("response_format", None)
                resp = await client.post(GROQ_URL, json=payload, headers=headers)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return _parse_json(content)
    except AIUnavailable:
        raise
    except Exception as exc:  # network, HTTP, bad JSON - all treated the same
        raise AIUnavailable(f"{type(exc).__name__}: {str(exc)[:160]}") from exc


# --------------------------------------------------------------------------
# 1. Name matching
# --------------------------------------------------------------------------

NAME_SYSTEM = """You check vendor onboarding data for an accounts-payable team.
Decide whether two names refer to the SAME legal entity.
Treat as the same: abbreviations (ENGG = Engineering, PVT = Private, LTD = Limited, CO = Company,
INDS = Industries), punctuation, word order of legal suffixes, upper/lower case, a missing "M/S".
Treat as DIFFERENT: a different trading name or business (e.g. "Kaveri Traders" vs
"Kaveri Agro Foods Private Limited"), a person's name instead of the company, a different legal
form (LLP vs Private Limited), or any extra/missing distinctive word.
When unsure, answer false.
Reply with JSON only: {"same_entity": true|false, "confidence": 0.0-1.0, "reason": "<one short sentence>"}"""


async def judge_names(legal_name: str, account_holder: str) -> dict:
    user = f'Legal company name: "{legal_name}"\nBank account holder name: "{account_holder}"'
    data = await _chat_json(NAME_SYSTEM, user)
    same = bool(data.get("same_entity"))
    try:
        conf = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    return {"same_entity": same, "confidence": max(0.0, min(conf, 1.0)),
            "reason": str(data.get("reason", "")).strip()[:300]}


# --------------------------------------------------------------------------
# 2. Writing the message and the reviewer summary
# --------------------------------------------------------------------------

VENDOR_SYSTEM = """You write short, professional emails from a procurement team's vendor onboarding desk
to a vendor who has submitted a registration.
Rules:
- The exact list of items (actions or reasons) is inserted between your opening and closing
  automatically. Do NOT list, repeat, add or invent any requirements yourself.
- Do not speculate about reasons that are not given to you.
- No promises about timelines or payments. No placeholders like [Name]. Plain text, no markdown.
- Do not start the opening with a greeting; "Dear <name>," is added automatically.
- Do not sign off; the signature is added automatically.
- "opening": 1-3 sentences. "closing": 1-2 sentences.
Reply with JSON only: {"subject": "...", "opening": "...", "closing": "..."}"""

REVIEWER_SYSTEM = """You summarise an automated vendor onboarding run for an internal procurement reviewer.
Write 2-3 plain-English sentences: the decision, the single most important reason, and what (if
anything) the reviewer should do next. Use only the findings given. No markdown.
Reply with JSON only: {"summary": "..."}"""


def _require(data: dict, keys) -> dict:
    out = {}
    for key in keys:
        value = str(data.get(key, "")).strip()
        if not value:
            raise AIUnavailable(f"AI response missing '{key}'")
        out[key] = value
    return out


async def draft_vendor_texts(context: dict) -> dict:
    """context contains only vendor-safe information."""
    data = await _chat_json(VENDOR_SYSTEM, json.dumps(context, indent=2))
    out = _require(data, ("subject", "opening", "closing"))
    out["subject"] = out["subject"][:150]
    return out


async def summarize_for_reviewer(context: dict) -> str:
    data = await _chat_json(REVIEWER_SYSTEM, json.dumps(context, indent=2))
    return _require(data, ("summary",))["summary"][:800]
