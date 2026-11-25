"""Spreadsheets and presentations for shintiru:hassan.

  python office/build_office.py spreadsheets   -> out/Spreadsheets/*.xlsx  (live formulas, finance and construction models)
  python office/build_office.py presentations  -> out/Presentations/*.pptx (construction decks, 5+ slides each)

Real data: the Slovak treasury 2025 invoice register (CC BY 4.0), natural persons anonymised to "Redacted Name".
Everything else is fictional. Counts come from env vars so the workflow controls the size.
"""
import csv
import io
import os
import random
import sys
import urllib.request
from datetime import date, timedelta

OUT = os.environ.get("OUT", "out")
N_SHEETS = int(os.environ.get("N_SHEETS", "16730"))
N_DECKS = int(os.environ.get("N_DECKS", "5000"))
REAL_SHARE_DECKS = float(os.environ.get("REAL_SHARE_DECKS", "0.15"))
SK_URL = "https://opendata.mfsr.sk/en/opendata/download/faktury-sp-obdobie-od-1-1-2025/1"
REDACTED = "Redacted Name"
random.seed(20261124)

PROJECT_TYPES = ["Office block", "Warehouse", "Road resurfacing", "School extension", "Hospital wing",
                 "Residential tower", "Bridge repair", "Data centre fit-out", "Retail fit-out", "Water treatment plant"]
TRADES = ["Structural steel", "Concrete", "Electrical", "Mechanical (HVAC)", "Plumbing", "Roofing", "Glazing",
          "Earthworks", "Interior finishes", "Fire protection", "Lifts", "Landscaping"]
SUFFIX = ["Group", "Construction", "Builders", "Civil", "Projects", "Engineering", "Holdings", "Works"]
PLACES = ["Northgate", "Cedar", "Summit", "Harbor", "Ironwood", "Bluepeak", "Redstone", "Lakeshore", "Pinecrest",
          "Westfield", "Granite", "Silverline", "Maple", "Crescent", "Atlas", "Meridian", "Beacon", "Foundry"]


def fictional_company():
    return f"{random.choice(PLACES)} {random.choice(SUFFIX)}"


def load_real_rows():
    raw = urllib.request.urlopen(urllib.request.Request(SK_URL, headers={"User-Agent": "dataset-builder/1.0"}), timeout=300).read().decode("utf-8", "replace")
    rows = list(csv.reader(io.StringIO(raw), delimiter=";"))
    header, body = rows[0], [r for r in rows[1:] if len(r) == len(rows[0])]
    fo = header.index("DodavatelPriznakFO")
    for r in body:
        if r[fo].strip().lower() in ("1", "true"):
            for col in ("DodavatelNazov", "ObjednavatelNazov"):
                r[header.index(col)] = REDACTED
            for col in ("DodavatelICO", "ObjednavatelICO"):
                r[header.index(col)] = ""
    return header, body


def build_spreadsheets():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    folder = os.path.join(OUT, "Spreadsheets")
    os.makedirs(folder, exist_ok=True)
    header, real = load_real_rows()
    made = 0
    # real-data workbooks first: the register split into workbooks of 100 rows, with live totals
    for k in range(0, len(real), 100):
        wb = Workbook()
        ws = wb.active
        ws.title = "Invoices"
        ws.append(header)
        for r in real[k:k + 100]:
            ws.append(r)
        ws.freeze_panes = "A2"
        for c in range(1, len(header) + 1):
            ws.cell(row=1, column=c).font = Font(bold=True)
        n = min(100, len(real) - k)
        last = n + 1
        wb.create_sheet("Totals")
        t = wb["Totals"]
        t["A1"], t["B1"] = "Real Slovak treasury 2025 register: rows", f"=COUNTA(Invoices!A2:A{last})"
        t["A2"], t["B2"] = "Sum of FakturaPlnenieHodnota (EUR column as reported)", f"=SUMPRODUCT(--(Invoices!{get_column_letter(REAL_HEADER.index('FakturaPlnenieHodnota')+1)}2:{get_column_letter(REAL_HEADER.index('FakturaPlnenieHodnota')+1)}{last}))"
        path = os.path.join(folder, f"real_slovak_register_{k // 100 + 1:04d}.xlsx")
        wb.save(path)
        made += 1
    # generated finance and construction models, each with inputs, a monthly schedule and live formulas
    base = date(2024, 1, 1)
    while made < N_SHEETS:
        i = made
        wb = Workbook()
        inputs = wb.active
        inputs.title = "Inputs"
        kind = random.choice(["project_budget", "cash_forecast", "loan_schedule", "job_cost", "payroll"])
        company = fictional_company()
        inputs["A1"] = f"{kind.replace('_', ' ').title()} model: {company}"
        inputs["A1"].font = Font(bold=True, size=13)
        months = random.randint(12, 36)
        rate = round(random.uniform(0.04, 0.12), 4)
        principal = random.randint(200, 9000) * 1000
        inputs["A3"], inputs["B3"] = "Currency", random.choice(["USD", "EUR", "GBP"])
        inputs["A4"], inputs["B4"] = "Start month", (base + timedelta(days=30 * random.randint(0, 20))).strftime("%Y-%m")
        inputs["A5"], inputs["B5"] = "Months", months
        inputs["A6"], inputs["B6"] = "Annual rate", rate
        inputs["A7"], inputs["B7"] = "Principal / budget", principal
        inputs["A8"], inputs["B8"] = "Contingency %", round(random.uniform(0.03, 0.15), 3)
        inputs["A9"], inputs["B9"] = "Tax rate", round(random.uniform(0.15, 0.27), 3)
        inputs["A10"], inputs["B10"] = "Project type", random.choice(PROJECT_TYPES)
        for r in range(3, 11):
            inputs.cell(row=r, column=1).font = Font(bold=True)
        inputs.column_dimensions["A"].width = 26
        inputs.column_dimensions["B"].width = 22
        sched = wb.create_sheet("Schedule")
        heads = ["Month", "Opening", "Interest", "Payment", "Principal", "Closing", "Tax", "Net cash"]
        sched.append(heads)
        for c in range(1, len(heads) + 1):
            sched.cell(row=1, column=c).font = Font(bold=True)
            sched.cell(row=1, column=c).fill = PatternFill("solid", fgColor="DDEBF7")
        pay = f"=PMT(Inputs!$B$6/12,Inputs!$B$5,-Inputs!$B$7)"
        for m in range(1, months + 1):
            row = m + 1
            sched.cell(row=row, column=1, value=m)
            sched.cell(row=row, column=2, value="=Inputs!$B$7" if m == 1 else f"=F{row-1}")
            sched.cell(row=row, column=3, value=f"=B{row}*Inputs!$B$6/12")
            sched.cell(row=row, column=4, value=pay)
            sched.cell(row=row, column=5, value=f"=D{row}-C{row}")
            sched.cell(row=row, column=6, value=f"=B{row}-E{row}")
            sched.cell(row=row, column=7, value=f"=C{row}*Inputs!$B$9")
            sched.cell(row=row, column=8, value=f"=D{row}-G{row}")
        end = months + 1
        sched.cell(row=end + 2, column=1, value="Total").font = Font(bold=True)
        for col in "CDEG":
            sched[f"{col}{end+2}"] = f"=SUM({col}2:{col}{end})"
        sched.freeze_panes = "A2"
        for c in range(1, 9):
            sched.column_dimensions[get_column_letter(c)].width = 16
        summ = wb.create_sheet("Summary")
        summ["A1"], summ["B1"] = "Total interest", f"=Schedule!C{end+2}"
        summ["A2"], summ["B2"] = "Total payments", f"=Schedule!D{end+2}"
        summ["A3"], summ["B3"] = "Contingency amount", "=Inputs!B7*Inputs!B8"
        summ["A4"], summ["B4"] = "Total tax", f"=Schedule!G{end+2}"
        summ["A5"], summ["B5"] = "Net cash after tax", f"=Schedule!H{end+2}"
        summ.column_dimensions["A"].width = 26
        summ.column_dimensions["B"].width = 20
        path = os.path.join(folder, f"{kind}_{i:05d}.xlsx")
        wb.save(path)
        made += 1
    return {"workbooks": made, "real_register_workbooks": (len(real) + 99) // 100, "rows_real": len(real)}


def build_presentations():
    from pptx import Presentation
    from pptx.util import Inches, Pt
    folder = os.path.join(OUT, "Presentations")
    os.makedirs(folder, exist_ok=True)
    real = []
    if REAL_SHARE_DECKS > 0:
        header, body = load_real_rows()
        real = body
        globals()["REAL_HEADER"] = header
    made = 0
    real_made = 0
    for i in range(N_DECKS):
        use_real = real and random.random() < REAL_SHARE_DECKS
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
        project = random.choice(PROJECT_TYPES)
        company = fictional_company()
        slides_n = random.randint(5, 9)
        title_layout = prs.slide_layouts[0]
        s = prs.slides.add_slide(title_layout)
        s.shapes.title.text = f"{project}: construction programme review"
        s.placeholders[1].text = f"{company}\nPrepared {date(2024, 1, 1) + timedelta(days=random.randint(0, 900)):%B %Y}"
        if use_real:
            real_made += 1
            bullet_layout = prs.slide_layouts[1]
            for k in range(slides_n - 1):
                sl = prs.slides.add_slide(bullet_layout)
                sl.shapes.title.text = f"Register extract {k + 1}: invoices in the 2025 treasury register"
                tf = sl.placeholders[1].text_frame
                tf.clear()
                for r in random.sample(real, 9):
                    p = tf.add_paragraph()
                    p.text = f"{r[REAL_HEADER.index('DodavatelNazov')][:60]} | {r[REAL_HEADER.index('FakturaPlnenieHodnota')]} {r[REAL_HEADER.index('FakturaMena')]} | {r[REAL_HEADER.index('FakturaDatumDorucenia')][:10]}"
                    p.font.size = Pt(16)
        else:
            for k in range(slides_n - 1):
                sl = prs.slides.add_slide(prs.slide_layouts[1])
                topic = random.choice(TRADES)
                sl.shapes.title.text = f"{topic}: {random.choice(['progress', 'cost', 'risks', 'schedule', 'procurement', 'quality', 'safety', 'subcontractors'])} for {project.lower()}"
                tf = sl.placeholders[1].text_frame
                tf.clear()
                for _ in range(random.randint(6, 9)):
                    p = tf.add_paragraph()
                    p.text = (f"{random.choice(['Week', 'Phase', 'Package'])} {random.randint(1, 52)}: "
                              f"{random.choice(['delivered', 'delayed', 'on track', 'at risk'])} — "
                              f"{random.randint(2, 96)}k budget, {random.randint(1, 30)} days float")
                    p.font.size = Pt(16)
        path = os.path.join(folder, f"deck_{i:05d}.pptx")
        prs.save(path)
        made += 1
    return {"decks": made, "decks_from_real_register": real_made}


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "spreadsheets":
        print(build_spreadsheets())
    elif what == "presentations":
        print(build_presentations())
    else:
        raise SystemExit("usage: spreadsheets | presentations")
