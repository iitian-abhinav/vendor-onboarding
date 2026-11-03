"""
Format validators for tax IDs, bank codes and addresses.

Every function here is deterministic: same input, same answer.
Where an official checksum exists (GSTIN, ABA routing, UK VAT) we verify it,
so a typo in one digit is caught, not just a wrong length.
"""
import re

# ---------------------------------------------------------------------------
# India
# ---------------------------------------------------------------------------

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
IN_PIN_RE = re.compile(r"^[1-9][0-9]{5}$")
IN_ACCOUNT_RE = re.compile(r"^[0-9]{9,18}$")

# GST state codes (first two digits of a GSTIN)
GST_STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh",
}
INDIAN_STATES = sorted(set(GST_STATE_CODES.values()))

# 4th character of a PAN tells you what kind of entity holds it
PAN_ENTITY_TYPES = {
    "C": "Company", "P": "Individual", "H": "Hindu Undivided Family",
    "F": "Firm / LLP", "A": "Association of Persons", "T": "Trust",
    "B": "Body of Individuals", "L": "Local Authority",
    "J": "Artificial Juridical Person", "G": "Government",
}

_GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_char(first14: str) -> str:
    """Compute the 15th (checksum) character of a GSTIN."""
    total = 0
    for i, ch in enumerate(first14):
        value = _GST_CHARS.index(ch)
        factor = 1 if i % 2 == 0 else 2
        product = value * factor
        total += product // 36 + product % 36
    return _GST_CHARS[(36 - total % 36) % 36]


def gstin_checksum_ok(gstin: str) -> bool:
    return gstin_check_char(gstin[:14]) == gstin[14]


# ---------------------------------------------------------------------------
# United States
# ---------------------------------------------------------------------------

EIN_RE = re.compile(r"^[0-9]{2}-?[0-9]{7}$")
# Prefixes the IRS has never issued
EIN_INVALID_PREFIXES = {"00", "07", "08", "09", "17", "18", "19", "28", "29",
                        "49", "69", "70", "78", "79", "89", "96", "97"}
ABA_RE = re.compile(r"^[0-9]{9}$")
US_ZIP_RE = re.compile(r"^[0-9]{5}(-[0-9]{4})?$")
US_ACCOUNT_RE = re.compile(r"^[0-9]{4,17}$")
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}


def aba_checksum_ok(routing: str) -> bool:
    d = [int(c) for c in routing]
    total = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])
    return total % 10 == 0


# ---------------------------------------------------------------------------
# United Kingdom
# ---------------------------------------------------------------------------

UK_VAT_RE = re.compile(r"^GB[0-9]{9}$")
UK_COMPANY_NO_RE = re.compile(r"^([0-9]{8}|(SC|NI|OC|SO|NC)[0-9]{6})$")
UK_SORT_CODE_RE = re.compile(r"^[0-9]{2}-?[0-9]{2}-?[0-9]{2}$")
UK_ACCOUNT_RE = re.compile(r"^[0-9]{8}$")
UK_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][A-Z]{2}$")


def uk_vat_checksum_ok(vat: str) -> bool:
    """HMRC modulus-97 check (accepts both the old and the '9755' scheme)."""
    digits = vat[2:]
    weights = [8, 7, 6, 5, 4, 3, 2]
    total = sum(int(digits[i]) * weights[i] for i in range(7)) + int(digits[7:9])
    return total % 97 == 0 or (total + 55) % 97 == 0


# ---------------------------------------------------------------------------
# Helpers used by the pipeline
# ---------------------------------------------------------------------------

def clean_id(value: str) -> str:
    """Upper-case and strip spaces so ' 33aabcs 1429k1z5 ' still validates."""
    return re.sub(r"\s+", "", (value or "")).upper()


def detect_tax_id_country(tax_id: str):
    """
    Look at a tax ID on its own and guess which country's format it follows.
    Used to explain *why* a tax ID is wrong (e.g. 'this is a US EIN').
    """
    t = clean_id(tax_id)
    if GSTIN_RE.match(t):
        return "IN", "Indian GSTIN"
    if PAN_RE.match(t):
        return "IN", "Indian PAN"
    if EIN_RE.match(t):
        return "US", "US EIN"
    if UK_VAT_RE.match(t):
        return "UK", "UK VAT number"
    return None, None


COUNTRY_NAMES = {"IN": "India", "US": "United States", "UK": "United Kingdom"}

TAX_ID_LABELS = {"IN": "GSTIN", "US": "EIN", "UK": "VAT number"}
BANK_CODE_LABELS = {"IN": "IFSC code", "US": "ABA routing number", "UK": "sort code"}

FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com",
    "rediffmail.com", "live.com", "icloud.com", "aol.com", "proton.me",
    "protonmail.com", "zoho.com",
}

PHONE_PREFIX = {"IN": "+91", "US": "+1", "UK": "+44"}
