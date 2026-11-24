"""Invoice pipeline for shintiru:hassan/Invoices.

Sources (public, see README sections in the workflow):
  1. Slovak National Treasury invoice register, 2025 (CC BY 4.0): real invoice records, CSV.
     Natural-person suppliers/buyers (FO flag = 1) are anonymised to "Redacted Name"; their
     registration numbers are blanked.
  2. Hugging Face feyninc/invoices-and-receipts: real invoices and receipts (images + labels).
  3. Hugging Face JohnTan38/sparrow-invoice-v1 (Apache-2.0): invoice PDFs.
  4. Generated invoices in Bill.com-style layout (fictional vendors/customers) to reach TOTAL_DOCS.

Writes everything under OUT (default ./out). Upload is done by the workflow with rclone.
"""
import csv
import hashlib
import io
import json
import os
import random
import re
import sys
import urllib.request
from datetime import date, timedelta

OUT = os.environ.get("OUT", "out")
TOTAL_DOCS = int(os.environ.get("TOTAL_DOCS", "4000"))
SEED = 20261124
random.seed(SEED)

ROOT = os.path.join(OUT, "Invoices")
DIR_SK = os.path.join(ROOT, "1 Slovak Treasury Register 2025")
DIR_HF = os.path.join(ROOT, "2 Real Invoices and Receipts (Hugging Face)")
DIR_SP = os.path.join(ROOT, "3 Sparrow Invoice PDFs")
DIR_GEN = os.path.join(ROOT, "4 Generated Invoices")
for d in (DIR_SK, DIR_HF, DIR_SP, DIR_GEN):
    os.makedirs(d, exist_ok=True)

REDACTED = "Redacted Name"
SK_URL = "https://opendata.mfsr.sk/en/opendata/download/faktury-sp-obdobie-od-1-1-2025/1"
HF_PARQUET = "https://huggingface.co/datasets/feyninc/invoices-and-receipts/resolve/main/data/train-00000-of-00001.parquet"
SP_API = "https://huggingface.co/api/datasets/JohnTan38/sparrow-invoice-v1"
SP_BASE = "https://huggingface.co/datasets/JohnTan38/sparrow-invoice-v1/resolve/main/"


def fetch(url, timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": "research-dataset-builder/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def part1_slovak():
    raw = fetch(SK_URL).decode("utf-8", errors="replace")
    rows = list(csv.reader(io.StringIO(raw), delimiter=";"))
    header, body = rows[0], rows[1:]
    fo = header.index("DodavatelPriznakFO")
    anonymised = 0
    cleaned = []
    for row in body:
        if len(row) != len(header):
            continue
        if row[fo] == "1":  # natural person
            for col in ("DodavatelNazov", "ObjednavatelNazov", "DodavatelICO", "ObjednavatelICO"):
                if col in header:
                    i = header.index(col)
                    if row[i]:
                        row[i] = REDACTED if col.endswith("Nazov") else ""
            anonymised += 1
        cleaned.append(row)
    path = os.path.join(DIR_SK, "slovak_invoice_register_2025.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(header)
        w.writerows(cleaned)
    return {"records": len(cleaned), "anonymised_natural_persons": anonymised, "file": path}


def part2_hf_feyninc():
    import pyarrow.parquet as pq
    data = fetch(HF_PARQUET, timeout=600)
    table = pq.read_table(io.BytesIO(data))
    cols = table.column_names
    n = 0
    labels_path = os.path.join(DIR_HF, "labels.jsonl")
    with open(labels_path, "w", encoding="utf-8") as lab:
        for i, rec in enumerate(table.to_pylist()):
            img = rec.get("image")
            payload = img.get("bytes") if isinstance(img, dict) else None
            if payload:
                ext = "png"
                if payload[:3] == b"\xff\xd8\xff":
                    ext = "jpg"
                with open(os.path.join(DIR_HF, f"{i:05d}.{ext}"), "wb") as fh:
                    fh.write(payload)
                n += 1
            meta = {k: v for k, v in rec.items() if k != "image"}
            lab.write(json.dumps(meta, ensure_ascii=False, default=str) + "\n")
    return {"documents": n, "columns": cols}


def part3_sparrow():
    listing = json.loads(fetch(SP_API).decode("utf-8"))
    pdfs = [s["rfilename"] for s in listing.get("siblings", []) if s["rfilename"].lower().endswith(".pdf")]
    n = 0
    for name in pdfs:
        data = fetch(SP_BASE + name)
        with open(os.path.join(DIR_SP, os.path.basename(name)), "wb") as fh:
            fh.write(data)
        n += 1
    return {"documents": n}


# ---- generated invoices -------------------------------------------------------------------
COMPANY_A = ["Northgate", "Cedar", "Summit", "Harbor", "Ironwood", "Bluepeak", "Redstone", "Lakeshore", "Pinecrest",
             "Westfield", "Granite", "Silverline", "Maple", "Crescent", "Atlas", "Meridian", "Beacon", "Foundry"]
COMPANY_B = ["Supply Co.", "Industrial Ltd.", "Services LLC", "Logistics Inc.", "Engineering GmbH", "Trading S.A.",
             "Partners LLP", "Materials Corp.", "Systems BV", "Consulting Pty", "Holdings plc", "Works Ltd."]
ITEMS = [("Structural steel beams", 1850.0), ("Ready-mix concrete (m3)", 135.0), ("Rebar, grade 500 (t)", 720.0),
         ("Site labour (hours)", 46.0), ("Plant hire, excavator (days)", 390.0), ("Scaffolding rental (weeks)", 210.0),
         ("Office supplies", 38.5), ("Software licence (seats)", 29.0), ("Freight, pallet", 64.0),
         ("Consulting, hourly", 125.0), ("Accounting services (month)", 880.0), ("Insurance premium (quarter)", 2400.0),
         ("Electrical cable (100 m)", 215.0), ("Paint, 20 L", 88.0), ("Safety helmets (box)", 142.0)]
CURRENCIES = [("USD", "$"), ("EUR", "€"), ("GBP", "£")]
TERMS = ["Net 15", "Net 30", "Net 45", "Due on receipt"]


def make_company(i):
    return f"{random.choice(COMPANY_A)} {random.choice(['Group', 'Works', 'Holdings', 'Solutions', 'Partners'])} {random.choice(COMPANY_B)}"


def generate_invoice_pdf(path, number, issue, vendor, customer, lines, currency, terms):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    c.setFillColor(colors.HexColor("#1f6fb2"))
    c.rect(0, h - 60, w, 60, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, h - 38, "INVOICE")
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 40, h - 30, f"Invoice no. {number}")
    c.drawRightString(w - 40, h - 44, f"Issue date {issue:%d %b %Y}   Terms {terms}")
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, h - 92, vendor)
    c.setFont("Helvetica", 9)
    c.drawString(40, h - 106, "Accounts payable, invoices@" + re.sub(r"[^a-z]", "", vendor.lower())[:18] + ".example")
    c.drawString(40, h - 120, f"Currency {currency[0]}")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(330, h - 92, "Bill to")
    c.setFont("Helvetica", 9)
    c.drawString(330, h - 106, customer)
    y = h - 170
    c.setFillColor(colors.HexColor("#e8eef6"))
    c.rect(40, y - 4, w - 80, 18, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    for x, t in ((44, "Description"), (330, "Qty"), (390, "Unit price"), (470, "Amount")):
        c.drawString(x, y, t)
    y -= 22
    c.setFont("Helvetica", 9)
    subtotal = 0.0
    for desc, qty, unit in lines:
        amt = round(qty * unit, 2)
        subtotal += amt
        c.drawString(44, y, desc[:52])
        c.drawRightString(360, y, f"{qty:g}")
        c.drawRightString(440, y, f"{currency[1]}{unit:,.2f}")
        c.drawRightString(w - 44, y, f"{currency[1]}{amt:,.2f}")
        y -= 16
    tax = round(subtotal * 0.2, 2)
    y -= 10
    for label, value in (("Subtotal", subtotal), ("VAT 20%", tax), ("Total due", subtotal + tax)):
        c.setFont("Helvetica-Bold" if label == "Total due" else "Helvetica", 9)
        c.drawString(360, y, label)
        c.drawRightString(w - 44, y, f"{currency[1]}{value:,.2f}")
        y -= 14
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.grey)
    c.drawString(40, 40, "Synthetic invoice: all vendors and customers are fictional. Generated for dataset use.")
    c.showPage()
    c.save()


def part4_generated(needed):
    base = date(2024, 1, 1)
    made = 0
    for i in range(needed):
        vendor = make_company(i)
        customer = make_company(i + 7919)
        issue = base + timedelta(days=random.randint(0, 900))
        currency = random.choice(CURRENCIES)
        terms = random.choice(TERMS)
        count = random.randint(2, 9)
        lines = []
        for desc, unit in random.sample(ITEMS, count):
            lines.append((desc, random.randint(1, 40), unit * random.uniform(0.9, 1.15)))
        number = f"INV-{issue.year}-{i:05d}"
        pdf = os.path.join(DIR_GEN, f"{i:05d}_{hashlib.sha1(number.encode()).hexdigest()[:6]}.pdf")
        generate_invoice_pdf(pdf, number, issue, vendor, customer, lines, currency, terms)
        made += 1
    return {"documents": made}


def count_docs():
    n = 0
    for dp, _, files in os.walk(ROOT):
        n += sum(1 for f in files if not f.endswith((".json", ".jsonl", ".csv")))
    return n


if __name__ == "__main__":
    report = {}
    which = sys.argv[1:] or ["slovak", "hf", "sparrow", "generated"]
    if "slovak" in which:
        report["slovak"] = part1_slovak()
    if "hf" in which:
        report["hf_feyninc"] = part2_hf_feyninc()
    if "sparrow" in which:
        report["sparrow"] = part3_sparrow()
    if "generated" in which:
        real = count_docs()
        need = max(0, TOTAL_DOCS - real)
        report["real_documents_before_generation"] = real
        report["generated_needed"] = need
        report["generated"] = part4_generated(need)
    report["total_documents"] = count_docs()
    with open(os.path.join(OUT, "invoices_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False, default=str)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
