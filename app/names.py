"""
Company-name helpers used by the bank-name check and the blocked-list check.
"""
import re
from difflib import SequenceMatcher

TOKEN_MAP = {
    "PVT": "PRIVATE", "PVT.": "PRIVATE", "PRIV": "PRIVATE",
    "LTD": "LIMITED", "LTD.": "LIMITED", "LIMITTED": "LIMITED",
    "CO": "COMPANY", "CORP": "CORPORATION", "INC": "INCORPORATED",
    "&": "AND",
}

# Legal-form families. Names in different families cannot be the same entity.
LEGAL_FORMS = [
    (("PRIVATE", "LIMITED"), "Private Limited", "limited"),
    (("LIMITED",), "Limited", "limited"),
    (("PLC",), "PLC", "limited"),
    (("LLP",), "LLP", "llp"),
    (("LLC",), "LLC", "us_corp"),
    (("INCORPORATED",), "Inc.", "us_corp"),
    (("CORPORATION",), "Corporation", "us_corp"),
]


def normalize(name: str) -> list:
    text = (name or "").upper().replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    tokens = [TOKEN_MAP.get(t, t) for t in text.split()]
    if tokens[:2] == ["M", "S"]:          # "M/S Sri Lakshmi ..." prefix used in India
        tokens = tokens[2:]
    if tokens[:1] == ["THE"]:
        tokens = tokens[1:]
    return tokens


def split_legal_form(tokens: list):
    """Returns (core tokens, legal form label or None, family or None)."""
    for suffix, label, family in LEGAL_FORMS:
        n = len(suffix)
        if len(tokens) > n and tuple(tokens[-n:]) == suffix:
            return tokens[:-n], label, family
    return tokens, None, None


def _is_subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def _token_abbrev(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 2 and short[0] == long[0] and _is_subsequence(short, long)


def heuristic_same(name_a: str, name_b: str) -> bool:
    """Deterministic fallback: same number of words and each word equal or an abbreviation."""
    core_a, _, fam_a = split_legal_form(normalize(name_a))
    core_b, _, fam_b = split_legal_form(normalize(name_b))
    if fam_a and fam_b and fam_a != fam_b:
        return False
    if len(core_a) != len(core_b) or not core_a:
        return False
    return all(_token_abbrev(x, y) for x, y in zip(core_a, core_b))


def similarity(name_a: str, name_b: str) -> float:
    core_a = " ".join(split_legal_form(normalize(name_a))[0])
    core_b = " ".join(split_legal_form(normalize(name_b))[0])
    if not core_a or not core_b:
        return 0.0
    return SequenceMatcher(None, core_a, core_b).ratio()
