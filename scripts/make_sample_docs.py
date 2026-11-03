"""
Generates the specimen PDFs used by the demo samples.
Run once:  python scripts/make_sample_docs.py
(Only needs reportlab, which is not required to run the app itself.)
"""
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.samples import SAMPLES  # noqa: E402

OUT = ROOT / "static" / "samples"

# Documents can show something different from what the vendor typed.
# Northwind typed a US EIN, but its real GST certificate shows its GSTIN.
DOC_OVERRIDES = {
    ("edge_wrong_country_id", "gst_certificate"): {"tax_id": "29AABCN4410K1ZH"},
}

TITLES = {
    "gst_certificate": ("GST Registration Certificate", "Form GST REG-06"),
    "pan_card": ("Permanent Account Number (PAN)", "Copy of PAN card"),
    "bank_proof": ("Confirmation of Bank Account Details", "Bank letter"),
    "incorporation_certificate": ("Certificate of Incorporation", "Private limited company"),
    "vat_certificate": ("VAT Registration Certificate", "VAT4"),
    "w9_form": ("Request for Taxpayer Identification Number", "Form W-9"),
}


def rows_for(doc, f):
    if doc == "gst_certificate":
        return [("Registration Number (GSTIN)", f["tax_id"]), ("Legal Name", f["legal_name"]),
                ("Principal Place of Business", f"{f['address_line']}, {f['city']}, {f['state']} {f['postal_code']}"),
                ("Type of Registration", "Regular"), ("Date of Liability", "01/04/2021")]
    if doc == "pan_card":
        return [("Permanent Account Number", f["pan"]), ("Name", f["legal_name"].upper()),
                ("Date of Incorporation", "12/06/2014")]
    if doc == "bank_proof":
        code_label = {"IN": "IFSC", "UK": "Sort code", "US": "Routing number"}[f["country"]]
        return [("Bank", f["bank_name"]), ("Account holder", f["bank_account_holder"]),
                ("Account number", f["bank_account_number"]), (code_label, f["bank_code"]),
                ("Account type", "Current account")]
    if doc == "incorporation_certificate":
        return [("Company number", f["company_number"]), ("Company name", f["legal_name"]),
                ("Registered office", f"{f['address_line']}, {f['city']} {f['postal_code']}"),
                ("Incorporated on", "14 March 2018")]
    if doc == "vat_certificate":
        return [("VAT registration number", f["tax_id"]), ("Name", f["legal_name"]),
                ("Effective date of registration", "01 June 2018")]
    if doc == "w9_form":
        return [("Name", f["legal_name"]), ("Employer identification number", f["tax_id"])]
    return []


def make_pdf(path: Path, doc: str, fields: dict):
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    title, sub = TITLES[doc]
    c.setFont("Helvetica-Bold", 16)
    c.drawString(60, h - 80, title)
    c.setFont("Helvetica", 10)
    c.drawString(60, h - 98, sub)
    c.line(60, h - 110, w - 60, h - 110)
    y = h - 145
    for label, value in rows_for(doc, fields):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(60, y, label)
        c.setFont("Helvetica", 10)
        c.drawString(250, y, str(value))
        y -= 22
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(60, 60, "SPECIMEN - demo data for a case study. Not a real document.")
    c.save()


def main():
    for key, sample in SAMPLES.items():
        folder = OUT / key
        folder.mkdir(parents=True, exist_ok=True)
        for doc in sample["documents"]:
            fields = dict(sample["fields"])
            fields.update(DOC_OVERRIDES.get((key, doc), {}))
            make_pdf(folder / f"{doc}.pdf", doc, fields)
            print("wrote", folder / f"{doc}.pdf")


if __name__ == "__main__":
    main()
