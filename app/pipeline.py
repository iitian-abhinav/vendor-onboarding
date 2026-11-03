"""
The onboarding process. One submission goes through six stages:

  1. Intake & completeness    - is everything there?
  2. Format validation        - is each value valid on its own? (formats + official checksums)
  3. Cross-field consistency  - do the values agree with each other and with the documents?
  4. Risk & duplicate check   - does anything clash with vendors we already pay, or the blocked list?
  5. Decision                 - fixed rules turn the findings into approved / pending / rejected
  6. Communicate              - email the vendor (and alert compliance if needed)

Every check produces a result:
  pass  - fine
  info  - worth knowing, does not affect the decision
  warn  - fixable by the vendor  -> makes the run PENDING
  fail  - hard stop              -> makes the run REJECTED
  skip  - could not run because an earlier input was missing

Decision rule (stage 5):  any fail -> REJECTED,  else any warn -> PENDING,  else APPROVED.
"""
import asyncio
import re
import traceback

from . import ai, config, db, emailer
from . import validators as v
from .names import heuristic_same, normalize, similarity, split_legal_form
from .reference_data import (BLOCKED_ENTITIES, REQUIRED_DOCUMENTS, REQUIRED_FIELDS_BY_COUNTRY,
                             REQUIRED_FIELDS_COMMON, TAX_DOCUMENT)

RANK = {"skip": 0, "pass": 0, "info": 0, "warn": 1, "fail": 2}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


def chk(cid, label, result, detail, action=None, internal=False, source="rule"):
    """One check. `action` is what we ask the vendor to do. `internal` hides it from the vendor."""
    return {"id": cid, "label": label, "result": result, "detail": detail,
            "action": action, "internal": internal, "source": source}


def stage_status(checks):
    worst = max((RANK[c["result"]] for c in checks), default=0)
    return {0: "pass", 1: "warn", 2: "fail"}[worst]


def clean_submission(raw: dict) -> dict:
    s = {k: (str(val).strip() if val is not None else "") for k, val in raw.items()}
    s["country"] = s.get("country", "").upper()
    for key in ("tax_id", "pan", "company_number"):
        s[key] = v.clean_id(s.get(key, ""))
    s["bank_code"] = s.get("bank_code", "").upper().replace(" ", "")
    s["bank_account_number"] = re.sub(r"[\s-]", "", s.get("bank_account_number", ""))
    s["contact_email"] = s.get("contact_email", "").lower()
    s["postal_code"] = s.get("postal_code", "").upper()
    return s


def _lc(label: str) -> str:
    """'Contact phone' -> 'contact phone', but keep 'GSTIN', 'IFSC code', 'Companies House number'."""
    first = label.split()[0]
    if first.isupper() or first in ("Companies",):
        return label
    return label[0].lower() + label[1:]


def doc_label(country, doc_type):
    for key, label in REQUIRED_DOCUMENTS.get(country, []):
        if key == doc_type:
            return label
    return doc_type.replace("_", " ").capitalize()


# ===========================================================================
# Stage 1 - Intake & completeness
# ===========================================================================

def stage_intake(s, docs):
    checks = []
    country = s.get("country")
    if country not in REQUIRED_DOCUMENTS:
        checks.append(chk("country_supported", "Country supported", "fail",
                          f"'{country or 'blank'}' is not a country this process onboards (India, US, UK).",
                          action="Vendor registration through this process is available for India, the "
                                 "United States and the United Kingdom only. Please contact our procurement team."))
        return checks
    checks.append(chk("country_supported", "Country supported", "pass", v.COUNTRY_NAMES[country]))

    required = REQUIRED_FIELDS_COMMON + REQUIRED_FIELDS_BY_COUNTRY.get(country, [])
    missing = [(k, label) for k, label in required if not s.get(k)]
    if not missing:
        checks.append(chk("required_fields", "Required fields", "pass",
                          f"All {len(required)} required fields are filled in."))
    for key, label in missing:
        if key == "tax_id":
            label = v.TAX_ID_LABELS[country]
        if key == "bank_code":
            label = v.BANK_CODE_LABELS[country]
        checks.append(chk(f"missing_{key}", f"{label}", "warn", "Not provided.",
                          action=f"Provide your {_lc(label)}."))

    by_type = {d["doc_type"]: d for d in docs}
    for doc_type, label in REQUIRED_DOCUMENTS[country]:
        d = by_type.get(doc_type)
        if not d:
            checks.append(chk(f"doc_{doc_type}", label, "warn", "Not attached.",
                              action=f"Attach your {_lc(label)} (PDF, JPG or PNG)."))
        elif d["size"] == 0:
            checks.append(chk(f"doc_{doc_type}", label, "warn", f"'{d['filename']}' is empty (0 bytes).",
                              action=f"Re-upload your {_lc(label)}; the file we received was empty."))
        elif d["size"] > config.MAX_UPLOAD_BYTES:
            checks.append(chk(f"doc_{doc_type}", label, "warn", f"'{d['filename']}' is larger than 5 MB.",
                              action=f"Upload your {_lc(label)} as a file under 5 MB."))
        elif d["detected_type"] not in ("PDF", "PNG", "JPEG"):
            checks.append(chk(f"doc_{doc_type}", label, "warn",
                              f"'{d['filename']}' is not a PDF or image (content does not match its extension).",
                              action=f"Upload your {_lc(label)} as a PDF, JPG or PNG."))
        else:
            checks.append(chk(f"doc_{doc_type}", label, "pass",
                              f"{d['filename']} ({max(1, round(d['size'] / 1024))} KB, {d['detected_type']})"))

    # Same file uploaded in two slots = the vendor attached the wrong document somewhere
    seen = {}
    for d in docs:
        if d["size"] and d["sha256"] in seen:
            first = seen[d["sha256"]]
            checks.append(chk(f"doc_duplicate_{d['doc_type']}", "Duplicate attachment", "warn",
                              f"The same file was uploaded as both '{doc_label(country, first)}' and "
                              f"'{doc_label(country, d['doc_type'])}'.",
                              action=f"Upload the correct {_lc(doc_label(country, d['doc_type']))}; "
                                     f"the file attached is the same as your {_lc(doc_label(country, first))}."))
        else:
            seen[d["sha256"]] = d["doc_type"]
    return checks


# ===========================================================================
# Stage 2 - Format validation
# ===========================================================================

def _skip(cid, label):
    return chk(cid, label, "skip", "Not provided (see Intake).")


def _tax_id_wrong_country(s, label):
    """If the tax ID matches ANOTHER country's format, that's an identity conflict, not a typo."""
    other_country, other_label = v.detect_tax_id_country(s["tax_id"])
    country = s["country"]
    if other_country and other_country != country:
        return chk("tax_id_format", label, "fail",
                   f"'{s['tax_id']}' is in {other_label} format, but the vendor declared "
                   f"{v.COUNTRY_NAMES[country]}.",
                   action=f"The tax ID you entered ({s['tax_id']}) is in {other_label} format, but your "
                          f"registration says {v.COUNTRY_NAMES[country]}. If you are registered in "
                          f"{v.COUNTRY_NAMES[country]}, please submit a new registration with your "
                          f"{v.TAX_ID_LABELS[country]}. If you are a {v.COUNTRY_NAMES[other_country]} "
                          f"entity, please register as a {v.COUNTRY_NAMES[other_country]} vendor.")
    return None


def stage_format(s):
    checks = []
    c = s["country"]
    tax_label = v.TAX_ID_LABELS[c]

    # ---- Tax ID ----
    if not s["tax_id"]:
        checks.append(_skip("tax_id_format", tax_label))
    elif c == "IN":
        g = s["tax_id"]
        if v.GSTIN_RE.match(g):
            if v.gstin_checksum_ok(g):
                checks.append(chk("tax_id_format", tax_label, "pass",
                                  f"{g}: valid format and check digit."))
            else:
                checks.append(chk("tax_id_format", tax_label, "warn",
                                  f"{g}: the last character should be '{v.gstin_check_char(g[:14])}'. "
                                  "Most likely a typo.",
                                  action=f"Re-check your GSTIN ({g}); its check digit is not valid."))
        elif v.PAN_RE.match(g):
            checks.append(chk("tax_id_format", tax_label, "warn",
                              f"{g} is a PAN, not a GSTIN.",
                              action="Enter your 15-character GSTIN in the tax ID field (you entered your PAN)."))
        else:
            checks.append(_tax_id_wrong_country(s, tax_label) or chk(
                "tax_id_format", tax_label, "warn", f"'{g}' is not a valid 15-character GSTIN.",
                action="Provide a valid 15-character GSTIN."))
    elif c == "US":
        e = s["tax_id"]
        if v.EIN_RE.match(e):
            if e[:2] in v.EIN_INVALID_PREFIXES:
                checks.append(chk("tax_id_format", tax_label, "warn",
                                  f"{e}: prefix {e[:2]} has never been issued by the IRS.",
                                  action=f"Re-check your EIN ({e}); the first two digits are not a valid prefix."))
            else:
                checks.append(chk("tax_id_format", tax_label, "pass", f"{e}: valid EIN format and prefix."))
        else:
            checks.append(_tax_id_wrong_country(s, tax_label) or chk(
                "tax_id_format", tax_label, "warn", f"'{e}' is not a valid EIN (format 12-3456789).",
                action="Provide your 9-digit EIN (format 12-3456789)."))
    elif c == "UK":
        t = s["tax_id"]
        if re.match(r"^[0-9]{9}$", t):
            t = "GB" + t
            s["tax_id"] = t
        if v.UK_VAT_RE.match(t):
            if v.uk_vat_checksum_ok(t):
                checks.append(chk("tax_id_format", tax_label, "pass", f"{t}: valid format and HMRC check digits."))
            else:
                checks.append(chk("tax_id_format", tax_label, "warn",
                                  f"{t}: fails the HMRC modulus-97 check. Most likely a typo.",
                                  action=f"Re-check your VAT number ({t}); its check digits are not valid."))
        else:
            checks.append(_tax_id_wrong_country(s, tax_label) or chk(
                "tax_id_format", tax_label, "warn", f"'{t}' is not a valid UK VAT number (GB + 9 digits).",
                action="Provide your VAT number in the format GB123456789."))

    # ---- Secondary IDs ----
    if c == "IN":
        if not s["pan"]:
            checks.append(_skip("pan_format", "PAN"))
        elif v.PAN_RE.match(s["pan"]):
            entity = v.PAN_ENTITY_TYPES.get(s["pan"][3], "Unknown")
            checks.append(chk("pan_format", "PAN", "pass", f"{s['pan']}: valid format (holder type: {entity})."))
        else:
            checks.append(chk("pan_format", "PAN", "warn", f"'{s['pan']}' is not a valid PAN (format ABCDE1234F).",
                              action="Provide a valid 10-character PAN."))
    if c == "UK":
        if not s["company_number"]:
            checks.append(_skip("company_number_format", "Companies House number"))
        elif v.UK_COMPANY_NO_RE.match(s["company_number"]):
            checks.append(chk("company_number_format", "Companies House number", "pass",
                              f"{s['company_number']}: valid format."))
        else:
            checks.append(chk("company_number_format", "Companies House number", "warn",
                              f"'{s['company_number']}' is not a valid Companies House number.",
                              action="Provide your 8-character Companies House registration number."))

    # ---- Bank code ----
    bc, bc_label = s["bank_code"], v.BANK_CODE_LABELS[c]
    if not bc:
        checks.append(_skip("bank_code_format", bc_label))
    elif c == "IN":
        if v.IFSC_RE.match(bc):
            checks.append(chk("bank_code_format", bc_label, "pass", f"{bc}: valid IFSC (bank {bc[:4]})."))
        else:
            checks.append(chk("bank_code_format", bc_label, "warn",
                              f"'{bc}' is not an IFSC code. Indian vendors must be paid into an Indian bank account.",
                              action="Provide the 11-character IFSC code of your Indian bank branch."))
    elif c == "US":
        if v.ABA_RE.match(bc) and v.aba_checksum_ok(bc):
            checks.append(chk("bank_code_format", bc_label, "pass", f"{bc}: valid ABA routing checksum."))
        else:
            checks.append(chk("bank_code_format", bc_label, "warn",
                              f"'{bc}' is not a valid 9-digit ABA routing number.",
                              action="Re-check your 9-digit ABA routing number."))
    elif c == "UK":
        if v.UK_SORT_CODE_RE.match(bc):
            digits = re.sub(r"\D", "", bc)
            s["bank_code"] = f"{digits[:2]}-{digits[2:4]}-{digits[4:]}"
            checks.append(chk("bank_code_format", bc_label, "pass", f"{s['bank_code']}: valid sort code format."))
        else:
            checks.append(chk("bank_code_format", bc_label, "warn", f"'{bc}' is not a valid sort code (12-34-56).",
                              action="Provide your 6-digit sort code (format 12-34-56)."))

    # ---- Account number ----
    acct = s["bank_account_number"]
    acct_re = {"IN": v.IN_ACCOUNT_RE, "US": v.US_ACCOUNT_RE, "UK": v.UK_ACCOUNT_RE}[c]
    acct_rule = {"IN": "9-18 digits", "US": "4-17 digits", "UK": "8 digits"}[c]
    if not acct:
        checks.append(_skip("account_format", "Bank account number"))
    elif acct_re.match(acct):
        checks.append(chk("account_format", "Bank account number", "pass", f"{len(acct)} digits ({acct_rule})."))
    else:
        checks.append(chk("account_format", "Bank account number", "warn",
                          f"'{acct}' does not look like a {v.COUNTRY_NAMES[c]} account number ({acct_rule}).",
                          action="Re-check your bank account number."))

    # ---- Address ----
    pc = s["postal_code"]
    pc_rule = {"IN": (v.IN_PIN_RE, "6-digit PIN code"), "US": (v.US_ZIP_RE, "ZIP code"),
               "UK": (v.UK_POSTCODE_RE, "UK postcode")}[c]
    if not pc:
        checks.append(_skip("postal_format", "Postal code"))
    elif pc_rule[0].match(pc):
        checks.append(chk("postal_format", "Postal code", "pass", f"{pc}: valid {pc_rule[1]}."))
    else:
        checks.append(chk("postal_format", "Postal code", "warn", f"'{pc}' is not a valid {pc_rule[1]}.",
                          action=f"Correct your postal code (expected a {pc_rule[1]})."))
    if c == "IN" and s.get("state"):
        known = {x.lower(): x for x in v.INDIAN_STATES}
        if s["state"].lower() in known:
            s["state"] = known[s["state"].lower()]
            checks.append(chk("state_format", "State", "pass", f"{s['state']} is a recognised Indian state/UT."))
        else:
            checks.append(chk("state_format", "State", "warn", f"'{s['state']}' is not a recognised Indian state.",
                              action="Correct the state in your address."))
    if c == "US" and s.get("state"):
        if s["state"].upper() in v.US_STATES:
            checks.append(chk("state_format", "State", "pass", f"{s['state'].upper()} is a valid US state code."))
        else:
            checks.append(chk("state_format", "State", "warn", f"'{s['state']}' is not a 2-letter US state code.",
                              action="Use the 2-letter state code in your address (e.g. CA)."))

    # ---- Contact ----
    if s["contact_email"]:
        if EMAIL_RE.match(s["contact_email"]):
            checks.append(chk("email_format", "Contact email", "pass", s["contact_email"]))
        else:
            checks.append(chk("email_format", "Contact email", "warn", f"'{s['contact_email']}' is not a valid email.",
                              action="Provide a valid contact email address."))
    if s["contact_phone"]:
        digits = re.sub(r"\D", "", s["contact_phone"])
        if 8 <= len(digits) <= 15:
            checks.append(chk("phone_format", "Contact phone", "pass", s["contact_phone"]))
        else:
            checks.append(chk("phone_format", "Contact phone", "warn", f"'{s['contact_phone']}' is not a valid phone number.",
                              action="Provide a valid contact phone number including country code."))
    return checks


# ===========================================================================
# Stage 3 - Cross-field consistency
# ===========================================================================

def _valid(prior, cid):
    return any(c["id"] == cid and c["result"] == "pass" for c in prior)


def _domain(value: str) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"^https?://", "", value).split("/")[0]
    return value[4:] if value.startswith("www.") else value


async def check_bank_name(s):
    """Does the bank account belong to the company? Rules first, AI for the unclear cases."""
    legal, holder = s["legal_name"], s["bank_account_holder"]
    label = "Bank account name vs company name"
    if not legal or not holder:
        return chk("bank_name_match", label, "skip", "Name missing (see Intake).")

    if normalize(legal) == normalize(holder):
        return chk("bank_name_match", label, "pass",
                   f"'{holder}' matches '{legal}' after standardising abbreviations (PVT/LTD).")

    _, form_a, fam_a = split_legal_form(normalize(legal))
    _, form_b, fam_b = split_legal_form(normalize(holder))
    action = (f"The bank account you provided is in the name '{holder}', which does not match your "
              f"registered name '{legal}'. Please provide a bank letter or cancelled cheque showing the "
              f"account is held by {legal}, or provide an account in the company's name.")
    if fam_a and fam_b and fam_a != fam_b:
        return chk("bank_name_match", label, "warn",
                   f"Different legal forms: company is '{form_a}', account holder is '{form_b}'.", action=action)

    try:
        verdict = await ai.judge_names(legal, holder)
        conf = f"{verdict['confidence']:.0%}"
        if verdict["same_entity"] and verdict["confidence"] >= 0.7:
            return chk("bank_name_match", label, "pass",
                       f"'{holder}' vs '{legal}': same entity ({conf} confidence). {verdict['reason']}",
                       source="ai")
        return chk("bank_name_match", label, "warn",
                   f"'{holder}' vs '{legal}': not the same entity ({conf} confidence). {verdict['reason']}",
                   action=action, source="ai")
    except ai.AIUnavailable as exc:
        if heuristic_same(legal, holder):
            return chk("bank_name_match", label, "pass",
                       f"'{holder}' vs '{legal}': every word matches or is an abbreviation. "
                       f"(AI unavailable: {exc})", source="fallback")
        return chk("bank_name_match", label, "warn",
                   f"'{holder}' does not match '{legal}'. (AI unavailable, strict rule applied: {exc})",
                   action=action, source="fallback")


def _pdf_text(doc):
    return (doc or {}).get("text") or ""


def check_tax_document(s, docs, prior):
    c = s["country"]
    doc_type = TAX_DOCUMENT[c]
    label = f"{doc_label(c, doc_type)} vs entered {v.TAX_ID_LABELS[c]}"
    doc = next((d for d in docs if d["doc_type"] == doc_type), None)
    if not doc or not s["tax_id"]:
        return chk("tax_doc_match", label, "skip", "Document or tax ID missing (see Intake).")
    text = _pdf_text(doc)
    if not text.strip():
        return chk("tax_doc_match", label, "info",
                   "No readable text (scanned image). Needs a quick manual look at the certificate.")
    flat = re.sub(r"[\s-]", "", text.upper())
    wanted = re.sub(r"[\s-]", "", s["tax_id"])
    if wanted in flat:
        return chk("tax_doc_match", label, "pass", f"The certificate shows {s['tax_id']}.")
    patterns = {"IN": r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", "US": r"[0-9]{2}-?[0-9]{7}",
                "UK": r"GB ?[0-9]{9}"}
    found = re.findall(patterns[c], text.upper())
    if found:
        shown = found[0].replace(" ", "")
        return chk("tax_doc_match", label, "warn",
                   f"The certificate shows {shown}, but {s['tax_id']} was entered.",
                   action=f"The {v.TAX_ID_LABELS[c]} on your {_lc(doc_label(c, doc_type))} ({shown}) does not "
                          f"match the one you entered ({s['tax_id']}). Please confirm the correct number.")
    return chk("tax_doc_match", label, "warn",
               f"No {v.TAX_ID_LABELS[c]} could be found in '{doc['filename']}'.",
               action=f"The {_lc(doc_label(c, doc_type))} you attached does not show your "
                      f"{v.TAX_ID_LABELS[c]}. Please attach the correct certificate.")


def check_bank_document(s, docs):
    doc = next((d for d in docs if d["doc_type"] == "bank_proof"), None)
    label = "Bank proof vs entered account number"
    if not doc or not s["bank_account_number"]:
        return chk("bank_doc_match", label, "skip", "Document or account number missing (see Intake).")
    text = _pdf_text(doc)
    if not text.strip():
        return chk("bank_doc_match", label, "info",
                   "No readable text (scanned image). Needs a quick manual look at the bank proof.")
    if s["bank_account_number"] in re.sub(r"[\s-]", "", text):
        return chk("bank_doc_match", label, "pass", f"The bank proof shows account {s['bank_account_number']}.")
    return chk("bank_doc_match", label, "warn",
               f"Account {s['bank_account_number']} does not appear on '{doc['filename']}'.",
               action="The bank proof you attached does not show the account number you entered. "
                      "Please attach proof for the same account.")


async def stage_consistency(s, docs, prior):
    checks = []
    c = s["country"]

    if c == "IN":
        gst_ok, pan_ok = _valid(prior, "tax_id_format"), _valid(prior, "pan_format")
        if gst_ok and pan_ok:
            embedded = s["tax_id"][2:12]
            if embedded == s["pan"]:
                checks.append(chk("gstin_pan_match", "PAN inside GSTIN", "pass",
                                  f"Characters 3-12 of the GSTIN ({embedded}) match the PAN."))
            else:
                checks.append(chk("gstin_pan_match", "PAN inside GSTIN", "fail",
                                  f"The GSTIN contains PAN {embedded}, but the PAN provided is {s['pan']}. "
                                  "They belong to two different taxpayers.",
                                  action=f"The GSTIN ({s['tax_id']}) and PAN ({s['pan']}) you provided belong to "
                                         f"different taxpayers. Please submit a new registration in which both "
                                         f"belong to {s['legal_name']}."))
        else:
            checks.append(chk("gstin_pan_match", "PAN inside GSTIN", "skip", "GSTIN or PAN not valid (see Format)."))

        if gst_ok and s.get("state"):
            code = s["tax_id"][:2]
            gst_state = v.GST_STATE_CODES.get(code, f"unknown state code {code}")
            if gst_state.lower() == s["state"].lower():
                checks.append(chk("gstin_state_match", "GSTIN state vs address", "pass",
                                  f"GSTIN state code {code} = {gst_state}, same as the address."))
            else:
                checks.append(chk("gstin_state_match", "GSTIN state vs address", "warn",
                                  f"GSTIN is registered in {gst_state} (code {code}) but the address is in {s['state']}.",
                                  action=f"Your GSTIN is registered in {gst_state}, but your address is in "
                                         f"{s['state']}. Please provide the GSTIN registered for {s['state']}, "
                                         f"or correct your address."))

        if pan_ok and s["legal_name"]:
            pan_type = s["pan"][3]
            _, form, _ = split_legal_form(normalize(s["legal_name"]))
            expected = {"Private Limited": "C", "Limited": "C", "LLP": "F"}.get(form)
            if expected and pan_type != expected:
                checks.append(chk("pan_entity_type", "PAN holder type vs company type", "warn",
                                  f"Name says '{form}' but the PAN belongs to a "
                                  f"{v.PAN_ENTITY_TYPES.get(pan_type, 'different entity type')} (4th letter '{pan_type}').",
                                  action="The PAN you provided does not belong to a company. Please provide the "
                                         "company's own PAN."))
            elif expected:
                checks.append(chk("pan_entity_type", "PAN holder type vs company type", "pass",
                                  f"4th letter '{pan_type}' = {v.PAN_ENTITY_TYPES[pan_type]}, matches '{form}'."))
            first = normalize(s["legal_name"])[:1]
            if first and expected:
                if first[0][0] == s["pan"][4]:
                    checks.append(chk("pan_name_letter", "PAN 5th letter vs company name", "pass",
                                      f"5th letter '{s['pan'][4]}' matches the first letter of the company name."))
                else:
                    checks.append(chk("pan_name_letter", "PAN 5th letter vs company name", "warn",
                                      f"A company PAN's 5th letter is the first letter of its name; expected "
                                      f"'{first[0][0]}', found '{s['pan'][4]}'.",
                                      action="Please confirm the PAN belongs to your company; it does not match "
                                             "your registered name."))

    checks.append(await check_bank_name(s))

    # Email domain vs website
    email_dom = s["contact_email"].split("@")[-1] if "@" in s["contact_email"] else ""
    site_dom = _domain(s.get("website", ""))
    if not email_dom:
        checks.append(chk("email_domain", "Email domain vs website", "skip", "No valid email."))
    elif email_dom in v.FREE_EMAIL_DOMAINS:
        checks.append(chk("email_domain", "Email domain vs website", "info",
                          f"Uses a free email provider ({email_dom}). Common for small vendors; noted for the reviewer."))
    elif not site_dom:
        checks.append(chk("email_domain", "Email domain vs website", "info", "No website given to compare with."))
    elif email_dom == site_dom or email_dom.endswith("." + site_dom) or site_dom.endswith("." + email_dom):
        checks.append(chk("email_domain", "Email domain vs website", "pass", f"Both use {site_dom}."))
    else:
        checks.append(chk("email_domain", "Email domain vs website", "warn",
                          f"Email is at {email_dom} but the website is {site_dom}.",
                          action=f"Please confirm that {s['contact_email']} is a company email address; its domain "
                                 f"differs from your website ({site_dom})."))

    # Phone country code vs country
    phone = s.get("contact_phone", "").replace(" ", "")
    prefix = v.PHONE_PREFIX[c]
    if phone.startswith("+"):
        if phone.startswith(prefix):
            checks.append(chk("phone_country", "Phone country code", "pass", f"{prefix} matches {v.COUNTRY_NAMES[c]}."))
        else:
            checks.append(chk("phone_country", "Phone country code", "info",
                              f"Phone number is not a {v.COUNTRY_NAMES[c]} number ({prefix}). Noted for the reviewer."))

    checks.append(check_tax_document(s, docs, prior))
    checks.append(check_bank_document(s, docs))
    return checks


# ===========================================================================
# Stage 4 - Risk & duplicate check
# ===========================================================================

def _code(x):
    return re.sub(r"[^A-Z0-9]", "", (x or "").upper())


def stage_risk(s):
    checks = []
    vendors = db.query("SELECT * FROM vendors")
    n = len(vendors)
    legal_norm = normalize(s["legal_name"])

    # Bank account already used by someone else?
    if s["bank_account_number"] and s["bank_code"]:
        hits = [x for x in vendors if x["bank_account"] == s["bank_account_number"]
                and _code(x["bank_code"]) == _code(s["bank_code"])]
        if not hits:
            checks.append(chk("bank_reuse", "Bank account already on file?", "pass",
                              f"Not used by any of the {n} vendors in the vendor master."))
        for h in hits:
            if normalize(h["legal_name"]) == legal_norm:
                checks.append(chk("bank_reuse", "Bank account already on file?", "fail",
                                  f"This vendor already exists as {h['code']} with the same bank account.",
                                  action=f"{s['legal_name']} is already registered with us (vendor code "
                                         f"{h['code']}). To change any details, please contact our procurement team."))
            else:
                checks.append(chk("bank_reuse", "Bank account already on file?", "fail",
                                  f"Account {s['bank_account_number']} ({s['bank_code']}) is already on file for "
                                  f"{h['code']} {h['legal_name']}. One bank account must not be shared by two "
                                  "vendors: possible payment-diversion fraud.",
                                  internal=True))
    else:
        checks.append(chk("bank_reuse", "Bank account already on file?", "skip", "Bank details missing."))

    # Tax ID already registered?
    ids = {x for x in (s["tax_id"], s.get("pan")) if x}
    if ids:
        hits = [x for x in vendors if (x["tax_id"] in ids) or (x["secondary_id"] and x["secondary_id"] in ids)]
        if not hits:
            checks.append(chk("tax_reuse", "Tax ID already registered?", "pass",
                              f"Not registered to any of the {n} existing vendors."))
        for h in hits:
            if normalize(h["legal_name"]) == legal_norm:
                checks.append(chk("tax_reuse", "Tax ID already registered?", "fail",
                                  f"Duplicate: already registered as {h['code']}.",
                                  action=f"{s['legal_name']} is already registered with us (vendor code "
                                         f"{h['code']}). To change any details, please contact our procurement team."))
            else:
                checks.append(chk("tax_reuse", "Tax ID already registered?", "fail",
                                  f"Tax ID belongs to existing vendor {h['code']} {h['legal_name']}.",
                                  internal=True))
    else:
        checks.append(chk("tax_reuse", "Tax ID already registered?", "skip", "No tax ID."))

    # Blocked / debarred list
    hit = None
    for name, reason in BLOCKED_ENTITIES:
        score = max(similarity(s["legal_name"], name), similarity(s["bank_account_holder"], name))
        if score >= 0.88:
            hit = (name, reason, score)
            break
    if hit:
        checks.append(chk("blocked_list", "Blocked / debarred list", "fail",
                          f"Matches '{hit[0]}' ({hit[2]:.0%} similar): {hit[1]}.", internal=True))
    else:
        checks.append(chk("blocked_list", "Blocked / debarred list", "pass",
                          f"No match against {len(BLOCKED_ENTITIES)} blocked entities (company and account holder)."))
    return checks


# ===========================================================================
# Stage 5 - Decision
# ===========================================================================

def stage_decision(all_checks):
    fails = [c for c in all_checks if c["result"] == "fail"]
    warns = [c for c in all_checks if c["result"] == "warn"]
    if fails:
        status = "rejected"
        reason = f"{len(fails)} hard failure(s). " + " ".join(c["detail"] for c in fails[:2])
    elif warns:
        status = "pending"
        reason = f"{len(warns)} item(s) the vendor needs to fix or provide."
    else:
        status = "approved"
        reason = "All checks passed."
    checks = [
        chk("rule", "Decision rule", "info",
            "Any hard failure = Rejected. Otherwise any item needing action = Pending. Otherwise Approved."),
        chk("fails", "Hard failures", "fail" if fails else "pass",
            "; ".join(c["label"] for c in fails) if fails else "None."),
        chk("warns", "Items needing vendor action", "warn" if warns else "pass",
            "; ".join(c["label"] for c in warns) if warns else "None."),
    ]
    return status, reason, fails, warns, checks


# ===========================================================================
# Stage 6 - Communicate
# ===========================================================================

SUBJECTS = {
    "approved": "Vendor registration approved: {name}",
    "pending": "Action needed to complete your vendor registration: {name}",
    "rejected": "Update on your vendor registration: {name}",
}


def _fallback_vendor_texts(status, internal_only, name):
    buyer = config.BUYER_COMPANY
    if status == "approved":
        opening = (f"Thank you for registering as a supplier to {buyer}. Your registration has been "
                   "approved and your details are now set up in our vendor records.")
        closing = "Please quote your vendor code on all invoices you send us."
    elif status == "pending":
        opening = ("Thank you for your vendor registration. We have reviewed your submission and need "
                   "the following before we can complete it.")
        closing = "Please reply to this email with the items above, quoting the reference number below."
    elif internal_only:
        opening = ("Thank you for your vendor registration. We are unable to proceed with this "
                   "submission at this time.")
        closing = "A member of our procurement team will contact you if anything further is needed."
    else:
        opening = ("Thank you for your vendor registration. We could not accept the submission in its "
                   "current form, for the reasons below.")
        closing = "You are welcome to submit a new registration once these points are resolved."
    return {"subject": SUBJECTS[status].format(name=name), "opening": opening, "closing": closing}


def _fallback_summary(status, fails, warns):
    lead = {"approved": "Approved: every check passed.",
            "pending": f"Pending: {len(warns)} item(s) need the vendor's action.",
            "rejected": f"Rejected: {len(fails)} hard failure(s)."}[status]
    key = (fails or warns)
    if key:
        lead += f" Main reason: {key[0]['label']}: {key[0]['detail']}"
    if any(c["internal"] for c in fails):
        lead += " Internal risk finding: compliance has been alerted; do not share details with the vendor."
    return lead


def _compose_body(contact, opening, items_title, items, closing, run_id):
    parts = [f"Dear {contact or 'Sir/Madam'},", "", opening]
    if items:
        parts += ["", items_title]
        if len(items) == 1:
            parts += [f"  {items[0]}"]
        else:
            parts += [f"  {i}. {item}" for i, item in enumerate(items, 1)]
    parts += ["", closing, "", f"Reference: VOB-{run_id:05d}", "", "Regards,",
              "Vendor Onboarding Team", config.BUYER_COMPANY]
    return "\n".join(parts)


async def stage_communicate(run_id, s, status, fails, warns, vendor_code):
    checks = []
    name = s.get("legal_name") or "your company"
    internal_fails = [c for c in fails if c["internal"]]
    internal_only = status == "rejected" and bool(internal_fails)

    # What the vendor is told: their action items, never internal findings
    if status == "approved":
        items_title, items = "Your details:", [f"Vendor code: {vendor_code}"]
    elif status == "pending":
        items_title = "What we need from you:"
        items = list(dict.fromkeys(c["action"] for c in warns if c["action"]))
    elif internal_only:
        items_title, items = "", []
    else:
        items_title = "Why we could not accept it:"
        items = list(dict.fromkeys(c["action"] or c["detail"] for c in fails if not c["internal"]))
        items += [c["action"] for c in warns if c["action"] and c["action"] not in items]

    vendor_context = {
        "buyer_company": config.BUYER_COMPANY, "vendor_name": name,
        "contact_name": s.get("contact_name"), "decision": status,
        "items_that_will_be_listed_below_your_opening": items,
        "note": ("Reasons are confidential: say only that we cannot proceed at this time."
                 if internal_only else ""),
    }
    reviewer_context = {
        "decision": status, "vendor": name,
        "hard_failures": [f"{c['label']}: {c['detail']}" for c in fails],
        "items_needing_vendor_action": [f"{c['label']}: {c['detail']}" for c in warns],
        "internal_risk_findings": [c["detail"] for c in internal_fails],
    }

    texts_task = ai.draft_vendor_texts(vendor_context)
    summary_task = ai.summarize_for_reviewer(reviewer_context)
    texts, summary = await asyncio.gather(texts_task, summary_task, return_exceptions=True)

    if isinstance(texts, Exception):
        err = texts_err(texts)
        texts = _fallback_vendor_texts(status, internal_only, name)
        written_by = "template"
        checks.append(chk("draft", "Vendor message drafted", "pass",
                          f"Written from template (AI unavailable: {err})", source="fallback"))
    else:
        written_by = f"ai:{config.GROQ_MODEL}"
        checks.append(chk("draft", "Vendor message drafted", "pass",
                          "Opening and closing written by AI; the list of items comes from the rules.",
                          source="ai"))
    if isinstance(summary, Exception):
        summary_text, summary_src = _fallback_summary(status, fails, warns), "template"
    else:
        summary_text, summary_src = summary, f"ai:{config.GROQ_MODEL}"
    db.update_run(run_id, reviewer_summary=summary_text, summary_source=summary_src)

    body = _compose_body(s.get("contact_name"), texts["opening"], items_title, items, texts["closing"], run_id)
    sent = await emailer.send(s.get("contact_email"), texts["subject"], body)
    db.add_message(run_id, "vendor", sent["to"], s.get("contact_email"), texts["subject"], sent["body"],
                   sent["status"], sent["provider"], sent["error"], written_by)
    checks.append(_send_check("email_vendor", "Email to vendor", sent))

    if internal_fails:
        alert_subject = f"[Risk alert] Vendor submission VOB-{run_id:05d} held: {name}"
        alert_body = "\n".join(
            [f"Vendor submission VOB-{run_id:05d} from {name} was rejected on internal risk findings:", ""]
            + [f"  - {c['label']}: {c['detail']}" for c in internal_fails]
            + ["", f"Contact on the submission: {s.get('contact_name')} <{s.get('contact_email')}>",
               "The vendor has been sent a neutral message without these details.",
               "", "Automated vendor onboarding"])
        sent_alert = await emailer.send(config.COMPLIANCE_EMAIL, alert_subject, alert_body)
        db.add_message(run_id, "internal", sent_alert["to"], config.COMPLIANCE_EMAIL, alert_subject,
                       sent_alert["body"], sent_alert["status"], sent_alert["provider"], sent_alert["error"], "rules")
        checks.append(_send_check("email_compliance", "Alert to compliance", sent_alert))
    return checks


def texts_err(exc):
    return str(exc)[:120] or type(exc).__name__


def _send_check(cid, label, sent):
    if sent["status"] == "sent":
        return chk(cid, label, "pass", f"Sent to {sent['to']} via {sent['provider']}.")
    if sent["status"] == "not_configured":
        return chk(cid, label, "info", "Email not configured: saved to the outbox as a draft.")
    return chk(cid, label, "warn", f"Not sent ({sent['error']}). Saved to the outbox.")


# ===========================================================================
# Runner
# ===========================================================================

async def _stage(run_id, idx, func, *args):
    db.start_stage(run_id, idx)
    if config.STAGE_DELAY:
        await asyncio.sleep(config.STAGE_DELAY)
    result = func(*args)
    if asyncio.iscoroutine(result):
        result = await result
    return result


def _skip_rest(run_id, from_idx, why):
    for idx in range(from_idx, 4):
        db.finish_stage(run_id, idx, "skip", [chk("skipped", "Stage skipped", "skip", why)])


async def run_pipeline(run_id: int, raw_submission: dict, docs: list):
    s = clean_submission(raw_submission)
    try:
        # 1. Intake
        intake = await _stage(run_id, 0, stage_intake, s, docs)
        db.finish_stage(run_id, 0, stage_status(intake), intake)
        all_checks = list(intake)

        if s["country"] in REQUIRED_DOCUMENTS:
            # 2. Format
            fmt = await _stage(run_id, 1, stage_format, s)
            db.finish_stage(run_id, 1, stage_status(fmt), fmt)
            all_checks += fmt
            # 3. Consistency
            cons = await _stage(run_id, 2, stage_consistency, s, docs, all_checks)
            db.finish_stage(run_id, 2, stage_status(cons), cons)
            all_checks += cons
            # 4. Risk
            risk = await _stage(run_id, 3, stage_risk, s)
            db.finish_stage(run_id, 3, stage_status(risk), risk)
            all_checks += risk
        else:
            _skip_rest(run_id, 1, "Country not supported, so country-specific checks cannot run.")

        # 5. Decision
        status, reason, fails, warns, dchecks = await _stage(run_id, 4, stage_decision, all_checks)
        vendor_code = None
        if status == "approved":
            vendor_code = db.next_vendor_code()
            db.execute(
                "INSERT INTO vendors (code, legal_name, country, tax_id, secondary_id, bank_account, bank_code, "
                "source, run_id, created_at) VALUES (?,?,?,?,?,?,?, 'onboarded', ?, ?)",
                (vendor_code, s["legal_name"], s["country"], s["tax_id"], s.get("pan") or s.get("company_number"),
                 s["bank_account_number"], s["bank_code"], run_id, db.now()))
            dchecks.append(chk("vendor_created", "Vendor master", "pass",
                               f"Added to the vendor master as {vendor_code}."))
        dchecks.append(chk("outcome", "Outcome", {"approved": "pass", "pending": "warn", "rejected": "fail"}[status],
                           status.upper()))
        top = (fails or warns or [None])[0]
        db.update_run(run_id, decision=status, decision_reason=reason, vendor_code=vendor_code,
                      issue_count=len(fails) + len(warns),
                      top_issue=(f"{top['label']}: {top['detail']}" if top else None))
        db.finish_stage(run_id, 4, {"approved": "pass", "pending": "warn", "rejected": "fail"}[status], dchecks)

        # 6. Communicate
        comm = await _stage(run_id, 5, stage_communicate, run_id, s, status, fails, warns, vendor_code)
        db.finish_stage(run_id, 5, stage_status(comm), comm)
        # The run only leaves "running" once everything, including emails, is done.
        db.update_run(run_id, status=status, finished_at=db.now())
    except Exception as exc:  # never leave a run stuck in "running"
        traceback.print_exc()
        running = db.query_one("SELECT idx FROM stages WHERE run_id=? AND status='running'", (run_id,))
        if running:
            db.finish_stage(run_id, running["idx"], "fail",
                            [chk("error", "Unexpected error", "fail", f"{type(exc).__name__}: {exc}")])
        db.update_run(run_id, status="error", finished_at=db.now(),
                      decision_reason=f"Process error: {type(exc).__name__}: {exc}")
