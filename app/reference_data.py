"""
Reference data the process checks against.

In a real company these would come from the ERP / procurement system:
  - SEED_VENDORS: vendors that are already approved and being paid
  - BLOCKED_ENTITIES: internal debarred / sanctioned list
  - REQUIRED_DOCUMENTS: what each country's onboarding policy asks for
"""

REQUIRED_DOCUMENTS = {
    "IN": [
        ("gst_certificate", "GST registration certificate"),
        ("pan_card", "PAN card copy"),
        ("bank_proof", "Cancelled cheque or bank letter"),
    ],
    "US": [
        ("w9_form", "IRS Form W-9"),
        ("bank_proof", "Bank letter or voided cheque"),
    ],
    "UK": [
        ("incorporation_certificate", "Certificate of incorporation"),
        ("vat_certificate", "VAT registration certificate"),
        ("bank_proof", "Bank letter"),
    ],
}

# Which uploaded document should contain the tax ID (used for a text check)
TAX_DOCUMENT = {"IN": "gst_certificate", "US": "w9_form", "UK": "vat_certificate"}

REQUIRED_FIELDS_COMMON = [
    ("legal_name", "Legal company name"),
    ("country", "Country"),
    ("address_line", "Registered address"),
    ("city", "City"),
    ("postal_code", "Postal code"),
    ("contact_name", "Contact person"),
    ("contact_email", "Contact email"),
    ("contact_phone", "Contact phone number"),
    ("tax_id", "Tax ID"),
    ("bank_account_holder", "Bank account holder name"),
    ("bank_account_number", "Bank account number"),
    ("bank_code", "Bank code"),
]
REQUIRED_FIELDS_BY_COUNTRY = {
    "IN": [("state", "State"), ("pan", "PAN")],
    "US": [("state", "State")],
    "UK": [("company_number", "Companies House number")],
}

SEED_VENDORS = [
    # code, legal name, country, tax id, secondary id, bank account, bank code
    ("V-1001", "Meenakshi Packaging Private Limited", "IN", "33AABCM5521Q1ZB", "AABCM5521Q", "50200012345678", "HDFC0000123"),
    ("V-1002", "Bharat Bearings Private Limited", "IN", "27AABCB9012F1Z0", "AABCB9012F", "912010045678123", "UTIB0000456"),
    ("V-1003", "Anand Electricals Private Limited", "IN", "29AABCA3310R1ZJ", "AABCA3310R", "001205012345", "ICIC0000012"),
    ("V-1004", "Deccan Logistics Private Limited", "IN", "07AABCD6634J1ZL", "AABCD6634J", "30112233445", "SBIN0001234"),
    ("V-1005", "Tirupur Textiles Private Limited", "IN", "33AABCT4410H1ZT", "AABCT4410H", "7711002233", "IDIB000T013"),
    ("V-1006", "Pioneer Tools Inc.", "US", "46-1234567", "", "4455667788", "121000358"),
    ("V-1007", "Harbor Industrial Supply LLC", "US", "84-2233445", "", "123456789012", "026009593"),
    ("V-1008", "Thames Precision Engineering Ltd", "UK", "GB987654353", "08123456", "55779911", "20-00-00"),
    ("V-1009", "Cotswold Office Supplies Ltd", "UK", "GB123456782", "09876543", "11223344", "40-11-62"),
]

BLOCKED_ENTITIES = [
    ("Shadowline Exports Private Limited", "Debarred after 2025 invoice fraud investigation"),
    ("Globex Trading FZE", "On sanctions screening list"),
    ("Northstar Metals Ltd", "Debarred: falsified quality certificates"),
]
