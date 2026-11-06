"""Shared helpers of the second Financelitics phase: HTTP, anonymised document fetch (HTML -> made-up names -> PDF;
PDF redacted in place), EDGAR filing lists, deal memos, credit files, EPA and World Bank ESG data."""
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

import requests

from avala.sink import safe

UA = os.environ.get("SEC_USER_AGENT") or "Financelitics research collector joseph@irtranscripts.com"
CAP = 60 * 2 ** 20
_ANON = {}
_REG = []


def session(sec=False):
    s = requests.Session()
    s.headers["User-Agent"] = UA if sec else "Financelitics research collector (github.com/Elsavado/earnings-sync)"
    return s


def get(s, url, tries=4, **kw):
    timeout = kw.pop("timeout", 120)
    for i in range(tries):
        try:
            r = s.get(url, timeout=timeout, **kw)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 404, 410):
                return None
        except requests.RequestException:
            pass
        time.sleep(5 * 2 ** i)
    return None


def tickers(s, st):
    if not st.get("tickers"):
        r = get(s, "https://www.sec.gov/files/company_tickers.json")
        st["tickers"] = {v["ticker"]: v["cik_str"] for v in r.json().values()} if r else {}
    return st["tickers"]


def _registrants(s):
    if not _REG:
        r = get(s, "https://www.sec.gov/files/company_tickers.json")
        t = r.json() if r else {}
        _REG.append([v["title"] for v in t.values()])
        _REG.append({v["ticker"]: v["title"] for v in t.values()})
    return _REG


def anon_for(st):
    """One anonymiser per state section; its name maps live in the section (so a name keeps its made-up name)."""
    key = id(st)
    if key not in _ANON:
        from howco.anon import Anon
        from howco.people import key_material
        names, ticks = _registrants(session(True))
        own = st.setdefault("names", {"people": {}, "companies": {}, "tickers": {}})
        a = Anon([], own.setdefault("people", {}), [], own.setdefault("companies", {}), key_material(),
                 names, names[:1500], ticks, [], own.setdefault("tickers", {}), ner=True)
        found = a.people_in
        a.people_in = lambda s, limit=400000: [(f, l) for f, l in found(s, limit) if _plausible(a, f, l)]
        _ANON[key] = a
    return _ANON[key]


STREET = {"drive", "street", "road", "avenue", "lane", "boulevard", "way", "place", "court", "plaza", "parkway",
          "suite", "square", "center", "centre", "floor", "tower", "park", "circle", "highway"}
GEO = set("""india china japan germany france italy spain canada mexico brazil israel ireland singapore korea taiwan
netherlands switzerland sweden norway denmark finland belgium austria australia zealand africa london paris tokyo
mumbai delhi bangalore beijing shanghai shenzhen hong kong dublin toronto vancouver sydney melbourne amsterdam zurich
geneva frankfurt munich berlin madrid milan stockholm boston chicago houston dallas austin denver seattle atlanta
miami phoenix york jersey delaware texas california florida massachusetts virginia carolina washington""".split())


def _plausible(a, f, l):
    """A person spaCy found: not a company word, a street, a place or a phrase of everyday words ('Amendment No')."""
    from wordfreq import zipf_frequency as z
    fl, ll = f.lower(), l.lower()
    co_words = a.co.single | {w for c in a.co.multi for w in c}
    if ll in STREET or fl in GEO or ll in GEO or fl in co_words or ll in co_words:
        return False
    if z(fl, "en") >= 4.3 and z(ll, "en") >= 4.3:
        return False
    return len(ll) > 2 and ll not in {"inc", "llc", "corp", "sub", "no", "co", "ltd", "plc"}


PAREN = re.compile(r"\(([^()]{1,160})\)")  # a parenthesis with defined terms: (the "Company" or "AspenTech")
QUOTED = re.compile(r'["“”]\s*([A-Z][A-Za-z0-9&.\'\- ]{1,40}?)\s*["“”]')
NAMED = re.compile(r"([A-Z][A-Za-z0-9&.'\- ]{1,60}?),?\s+(?:Inc|Incorporated|Corporation|Corp|Company|Co|LLC|L\.L\.C|Ltd|"
                   r"Limited|plc|PLC|L\.P|LP|N\.V|S\.A|AG|SE|Holdings?|Group|Partners|Bancorp|Trust)\b\.?")
ROLE = {"company", "parent", "merger sub", "buyer", "seller", "purchaser", "borrower", "lender", "lenders", "agent",
        "administrative agent", "issuer", "guarantor", "guarantors", "sponsor", "target", "acquiror", "holdings",
        "agreement", "merger", "offer", "board", "committee", "special committee", "we", "us", "our", "registrant",
        "bank", "trust", "fund", "adviser", "advisor", "investment adviser", "underwriters", "representatives"}


def learn_aliases(anon, text, filer=""):
    """Defined terms that stand for a company ('Aspen Technology, Inc. (\"AspenTech\")') and the filer's own short
    name get the company's made-up name, so short forms are replaced too."""
    from models.anonymize import core_tokens
    from wordfreq import zipf_frequency as z
    co = anon.co
    learned = []

    def force(core):
        co.seed.add(core)
        co._add(core, True)
        return co.pseudo(core)

    def alias(name, short):
        core = core_tokens(name)
        key = " ".join(core_tokens(short) or (short.lower(),))
        if not core or not key or key.lower() in ROLE:
            return
        made = force(core)
        learned.append((" ".join(core), made))
        if key in co.map or core == tuple(key.split()):
            return
        learned.append((key, made))
        co.map[key] = co.own[key] = made
        tup = tuple(key.split())
        co.seed.add(tup)
        co._add(tup, True)
        if len(tup) == 1:
            co.active.add(tup[0])
    text = re.sub(r"[\s​ ]+", " ", text[:3000000])
    for m in PAREN.finditer(text):
        terms = QUOTED.findall(m.group(1))
        if not terms:
            continue
        names = NAMED.findall(text[max(0, m.start() - 250):m.start()])
        if names:
            for t in terms:
                alias(names[-1], t.strip())
    core = core_tokens(filer) if filer else ()
    if core:
        learned.append((" ".join(core), force(core)))  # the filer's own name, even of everyday words ('Columbia Care')
        if len(core) > 1 and z(core[0], "en") < 4.0 and len(core[0]) >= 4:
            alias(filer, core[0].capitalize())
    return learned


def last_pass(text, learned):
    """Capitalised mentions of the deal parties' names and defined terms that the general pass left (possessives,
    names split by markup): replaced with their made-up names."""
    for key, made in sorted(set(learned), key=lambda x: -len(x[0])):
        words = key.split()
        if not words or (len(words) == 1 and len(key) < 4):
            continue
        rx = re.compile(r"(?<![A-Za-z])" + r"(?:\s|&nbsp;|&#160;|<[^>]{0,80}>)+".join(map(re.escape, words)) + r"(?![a-z])",
                        re.I)
        text = rx.sub(lambda m: made if m.group(0)[0].isupper() else m.group(0), text)
    return text


def to_pdf(p):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return p
    try:
        filt = "pdf:writer_web_pdf_Export" if p.lower().endswith(("htm", "html")) else "pdf"
        subprocess.run([soffice, "--headless", "--norestore", "--convert-to", filt, "--outdir", os.path.dirname(p), p],
                       capture_output=True, timeout=600)
    except (subprocess.TimeoutExpired, OSError):
        return p
    pdf = os.path.splitext(p)[0] + ".pdf"
    if os.path.exists(pdf) and os.path.getsize(pdf):
        os.remove(p)
        return pdf
    return p


def _download(s, url, cap=CAP):
    try:
        with s.get(url, stream=True, timeout=180) as r:
            if r.status_code != 200:
                return None
            buf = bytearray()
            for chunk in r.iter_content(1 << 20):
                buf += chunk
                if len(buf) > cap:
                    return None
            return bytes(buf) or None
    except requests.RequestException:
        return None


def fetch_anon(s, sink, anon, url, rel, filer=""):
    """Downloads one document, writes its made-up-name version as PDF at rel (+ .pdf). False when skipped."""
    ext = url.rsplit(".", 1)[-1].lower()
    if ext not in ("htm", "html", "txt", "pdf"):
        return False
    time.sleep(0.12)  # SEC fair access: at most 10 requests a second
    body = _download(s, url)
    if not body:
        return False
    tmp = tempfile.mkdtemp(prefix="fl_")
    try:
        src = os.path.join(tmp, f"src.{ext}")
        open(src, "wb").write(body)
        anon.start()
        if ext == "pdf":
            dst = sink.path(f"{rel}.pdf")
            ok, _ = anon.pdf(src, dst)
            if not ok:
                return False
            sink.wrote(dst)
            return True
        raw = body.decode("utf-8", "replace") if _utf8(body) else body.decode("cp1252", "replace")
        if ext == "txt":
            raw = "<html><body><pre>" + raw.replace("&", "&amp;").replace("<", "&lt;") + "</pre></body></html>"
        raw = re.sub(r"<img\b[^>]*>", "", raw, flags=re.I)  # logos and signatures stay out
        plain = html.unescape(re.sub(r"<[^>]+>", " ", raw)).replace(" ", " ")
        learned = learn_aliases(anon, plain, filer)
        people = anon.prelearn(plain[:400000])
        out = last_pass(anon.text(raw, people), learned)
        dst = sink.path(f"{rel}.htm")
        open(dst, "w", encoding="utf-8").write(out)
        sink.wrote(to_pdf(dst))
        return True
    except Exception:  # one bad document never stops a source
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _utf8(b):
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def all_filings(s, cik, forms, since="2008-01-01"):
    """(form, date, accession, primary document, company) of a company, recent and older pages."""
    time.sleep(0.12)
    r = get(s, f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
    if not r:
        return []
    d = r.json()
    company = d.get("name") or "Company"
    pages = [d["filings"]["recent"]]
    for f in d["filings"].get("files", []):
        time.sleep(0.12)
        x = get(s, f"https://data.sec.gov/submissions/{f['name']}")
        if x:
            pages.append(x.json())
    out = []
    for p in pages:
        for form, date, acc, doc in zip(p["form"], p["filingDate"], p["accessionNumber"], p["primaryDocument"]):
            if form in forms and date >= since and doc:
                out.append((form, date, acc, doc, company))
    return sorted(out, key=lambda x: x[1])


# ---------------------------------------------------------------- deal memo

TYPE = {"DEFM14A": "Merger (shareholder vote)", "PREM14A": "Merger (preliminary proxy)", "DEFM14C": "Merger (written consent)",
        "S-4": "Stock-for-stock merger / exchange offer", "SC TO-T": "Third-party tender offer",
        "SC 14D9": "Tender offer (target recommendation)", "SC 13E3": "Going-private transaction"}
WORKSTREAMS = ["Valuation and fairness review", "Financing and commitment terms", "Regulatory and antitrust approvals",
               "Shareholder vote / tender conditions", "Employee and management arrangements",
               "Termination fees and deal protection", "Integration planning"]


def deal_memo(sink, rel, room):
    from docx import Document
    docs = sorted(room["docs"])
    doc = Document()
    doc.add_heading(f"Deal memo: {room['name']}", 0)
    forms = sorted({d[3] for d in docs})
    doc.add_paragraph(f"Transaction type: {'; '.join(TYPE.get(f, f) for f in forms)}")
    doc.add_paragraph(f"First filing: {docs[0][0]}    Latest filing: {docs[-1][0]}    Documents in the room: {len(docs)}")
    doc.add_heading("Timeline", 1)
    t = doc.add_table(rows=1, cols=4)
    for c, h in zip(t.rows[0].cells, ("Date", "Filing", "Document", "Room section")):
        c.text = h
    for date, kind, label, form, typ in docs[:200]:
        r = t.add_row().cells
        r[0].text, r[1].text, r[2].text, r[3].text = date, form, label, kind
    banker = [d for d in docs if d[1] == "banker"]
    doc.add_heading("Banker deliverables and their sources", 1)
    if banker:
        for date, _k, label, form, typ in banker:
            doc.add_paragraph(f"{label}: from the {form} filed {date}, exhibit {typ}", style="List Bullet")
    else:
        doc.add_paragraph("No banker materials were filed as exhibits; see the fairness opinion summary in the proxy.")
    fin = [d for d in docs if d[1] == "financing"]
    doc.add_heading("Financing", 1)
    doc.add_paragraph(f"{len(fin)} commitment letter(s) / term sheet(s) in section 04." if fin else
                      "No financing commitments filed.")
    doc.add_heading("Diligence workstreams", 1)
    for w in WORKSTREAMS:
        doc.add_paragraph(w, style="List Bullet")
    p = sink.path(rel)
    doc.save(p)
    sink.wrote(p)


# ---------------------------------------------------------------- credit file

CONCEPTS = {  # row: candidate XBRL concepts
    "Revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "Operating income": ["OperatingIncomeLoss"],
    "Depreciation & amortisation": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                                    "DepreciationAmortizationAndAccretionNet"],
    "Interest expense": ["InterestExpense", "InterestExpenseDebt", "InterestExpenseNonoperating"],
    "Long-term debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "Current debt": ["LongTermDebtCurrent", "DebtCurrent"],
    "Cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "Net income": ["NetIncomeLoss"],
    "Operating cash flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "Capital expenditure": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}


def _annual(facts, names):
    for n in names:
        units = (facts.get(n) or {}).get("units", {}).get("USD")
        if not units:
            continue
        out = {}
        for u in units:
            if u.get("form") == "10-K" and u.get("fp") == "FY" and u.get("fy") and (u.get("frame") or "").startswith("CY"):
                out[int(u["frame"][2:6])] = u["val"]
        if out:
            return out
    return {}


def credit_file(s, sink, anon, cik, name, folder):
    """Credit model (financials, leverage, coverage, covenant tests as formulas) and credit memo of one borrower."""
    from docx import Document
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter as L
    time.sleep(0.12)
    r = get(s, f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", timeout=180)
    if not r:
        return 0
    facts = (r.json().get("facts") or {}).get("us-gaap", {})
    data = {row: _annual(facts, c) for row, c in CONCEPTS.items()}
    years = sorted({y for v in data.values() for y in v})[-8:]
    if len(years) < 2 or not data["Operating income"]:
        return 0
    wb = Workbook()
    ws = wb.active
    ws.title = "Financials"
    ws.append(["USD", *years])
    rows = {}
    for row in CONCEPTS:
        ws.append([row, *[data[row].get(y) for y in years]])
        rows[row] = ws.max_row
    last = L(len(years) + 1)
    m = wb.create_sheet("Credit metrics")
    m.append(["Metric", *years])
    f = {}

    def add(label, fn):
        m.append([label, *[fn(L(i + 2)) for i in range(len(years))]])
        f[label] = m.max_row

    add("EBITDA", lambda c: f"=Financials!{c}{rows['Operating income']}+N(Financials!{c}{rows['Depreciation & amortisation']})")
    add("Total debt", lambda c: f"=N(Financials!{c}{rows['Long-term debt']})+N(Financials!{c}{rows['Current debt']})")
    add("Net debt", lambda c: f"={c}{f['Total debt']}-N(Financials!{c}{rows['Cash']})")
    add("Leverage (debt / EBITDA)", lambda c: f"=IFERROR({c}{f['Total debt']}/{c}{f['EBITDA']},\"n/a\")")
    add("Net leverage", lambda c: f"=IFERROR({c}{f['Net debt']}/{c}{f['EBITDA']},\"n/a\")")
    add("Interest coverage (EBITDA / interest)", lambda c: f"=IFERROR({c}{f['EBITDA']}/Financials!{c}{rows['Interest expense']},\"n/a\")")
    add("Free cash flow", lambda c: f"=N(Financials!{c}{rows['Operating cash flow']})-N(Financials!{c}{rows['Capital expenditure']})")
    add("FCF / debt", lambda c: f"=IFERROR({c}{f['Free cash flow']}/{c}{f['Total debt']},\"n/a\")")
    cv = wb.create_sheet("Covenants")
    cv.append(["Test", "Threshold", "Latest", "Status", "Headroom"])
    cv.append(["Maximum leverage", 4.5, f"='Credit metrics'!{last}{f['Leverage (debt / EBITDA)']}",
               "=IF(ISNUMBER(C2),IF(C2<=B2,\"PASS\",\"BREACH\"),\"n/a\")", "=IFERROR(1-C2/B2,\"n/a\")"])
    cv.append(["Minimum interest coverage", 3.0, f"='Credit metrics'!{last}{f['Interest coverage (EBITDA / interest)']}",
               "=IF(ISNUMBER(C3),IF(C3>=B3,\"PASS\",\"BREACH\"),\"n/a\")", "=IFERROR(C3/B3-1,\"n/a\")"])
    p = sink.path(f"{folder}/Credit model.xlsx")
    wb.save(p)
    sink.wrote(p)
    y = years[-1]
    oi, da = data["Operating income"].get(y), data["Depreciation & amortisation"].get(y) or 0
    debt = (data["Long-term debt"].get(y) or 0) + (data["Current debt"].get(y) or 0)
    intr = data["Interest expense"].get(y)
    ebitda = (oi or 0) + da
    lev = debt / ebitda if ebitda > 0 else None
    cov = ebitda / intr if intr else None
    rating = ("Strong" if lev is not None and lev < 2 else "Satisfactory" if lev is not None and lev < 3.5 else
              "Watch" if lev is not None and lev < 5 else "Substandard")
    doc = Document()
    doc.add_heading(f"Credit memo: {name}", 0)
    doc.add_paragraph(f"Fiscal year {y}. EBITDA {ebitda:,.0f}; total debt {debt:,.0f}; leverage "
                      f"{lev:.2f}x" if lev is not None else f"Fiscal year {y}. EBITDA not positive: leverage not meaningful.")
    if cov is not None:
        doc.add_paragraph(f"Interest coverage {cov:.2f}x.")
    doc.add_paragraph(f"Internal risk rating: {rating}.")
    doc.add_heading("Covenant position", 1)
    doc.add_paragraph("Tested against a maximum leverage of 4.50x and minimum interest coverage of 3.00x (see the "
                      "Covenants sheet of the credit model; the thresholds are inputs).")
    doc.add_heading("Documents", 1)
    doc.add_paragraph("Credit agreements, amendments, term sheets and commitment letters are filed in this folder by date.")
    p = sink.path(f"{folder}/Credit memo.docx")
    doc.save(p)
    sink.wrote(p)
    return 2


# ---------------------------------------------------------------- EPA GHGRP and World Bank ESG

def ghgrp(s, sink, anon, st, folder):
    """Facility emissions by year (2010 on): made-up facility and parent names, no addresses or coordinates."""
    from openpyxl import Workbook
    done = set(st.setdefault("ghg", []))
    n = 0
    for y in range(2010, dt.date.today().year - 1):
        if str(y) in done or sink.full():
            continue
        fac, em = [], []
        for start in range(0, 20000, 5000):
            r = get(s, f"https://data.epa.gov/efservice/pub_dim_facility/year/=/{y}/rows/{start}:{start + 4999}/json",
                    timeout=300)
            rows = r.json() if r else []
            fac += rows
            if len(rows) < 5000:
                break
        for start in range(0, 400000, 10000):
            r = get(s, f"https://data.epa.gov/efservice/pub_facts_sector_ghg_emission/year/=/{y}/rows/{start}:{start + 9999}/json",
                    timeout=300)
            rows = r.json() if r else []
            em += rows
            if len(rows) < 10000:
                break
        if not fac or not em:
            continue
        rs = get(s, "https://data.epa.gov/efservice/pub_dim_sector/json")
        sec = {x["sector_id"]: x["sector_name"] for x in (rs.json() if rs else [])}
        label, count = {}, {}
        wb = Workbook()
        ws = wb.active
        ws.title = "Facilities"
        ws.append(["Facility", "Parent company (made-up)", "State", "NAICS", "Industry types", "Total CO2e (t)"])
        for i, x in enumerate(fac):
            parent = (x.get("parent_company") or "").split("(")[0].split(";")[0].strip() or "Independent operator"
            pa = safe(anon.text(parent.title() if parent.isupper() else parent), 70)
            count[pa] = count.get(pa, 0) + 1
            label[x["facility_id"]] = f"{pa} facility {count[pa]}"
            ws.append([label[x["facility_id"]], pa, x.get("state"), x.get("naics_code"), x.get("reported_industry_types"),
                       f"=SUMIF(Emissions!A:A,A{i + 2},Emissions!D:D)"])
        es = wb.create_sheet("Emissions")
        es.append(["Facility", "Sector", "Gas id", "CO2e (t)"])
        for x in em:
            if x["facility_id"] in label:
                es.append([label[x["facility_id"]], sec.get(x.get("sector_id"), x.get("sector_id")), x.get("gas_id"),
                           x.get("co2e_emission")])
        p = sink.path(f"{folder}/Facility emissions {y}.xlsx")
        wb.save(p)
        sink.wrote(p)
        done.add(str(y))
        st["ghg"] = sorted(done)
        n += 1
    return n


def worldbank_esg(s, sink, st, folder):
    """Country ESG indicators (World Bank source 75), one workbook per indicator (countries x years); yearly refresh."""
    from openpyxl import Workbook
    if st.get("wb") and st["wb"] > (dt.date.today() - dt.timedelta(days=180)).isoformat():
        return 0
    r = get(s, "https://api.worldbank.org/v2/sources/75/indicators", params={"format": "json", "per_page": 500})
    inds = (r.json()[1] if r and len(r.json()) > 1 else []) or []
    n = 0
    for ind in inds:
        if sink.full():
            return n
        d = get(s, f"https://api.worldbank.org/v2/country/all/indicator/{ind['id']}",
                params={"source": 75, "format": "json", "per_page": 20000}, timeout=300)
        rows = (d.json()[1] if d and len(d.json()) > 1 else []) or []
        if not rows:
            continue
        table = {}
        years = set()
        for x in rows:
            if x.get("value") is None:
                continue
            table.setdefault(x["country"]["value"], {})[x["date"]] = x["value"]
            years.add(x["date"])
        years = sorted(years)
        wb = Workbook()
        ws = wb.active
        ws.title = "Data"
        ws.append(["Country", *years])
        for c in sorted(table):
            ws.append([c, *[table[c].get(y) for y in years]])
        nt = wb.create_sheet("Definition")
        nt.append(["Indicator", ind["name"]])
        nt.append(["Definition", (ind.get("sourceNote") or "")[:30000]])
        p = sink.path(f"{folder}/{safe(ind['name'], 90)}.xlsx")
        wb.save(p)
        sink.wrote(p)
        n += 1
    st["wb"] = dt.date.today().isoformat()
    return n


EN_WORDS = frozenset("the and of to for our we with is are this that from by which have has will was were be its "
                     "their these been more also than such other into".split())


def is_english(text, sample=40000):
    """True when the text reads as English (user 2026-11-06: English versions only). Share of common English
    function words among the words of the first pages; other languages score near zero. No text (scans) = False."""
    words = re.findall(r"[a-zA-Z]+", text[:sample].lower())
    if len(words) < 150:
        return False
    return sum(w in EN_WORDS for w in words) / len(words) >= 0.08


ESG_TEXT = re.compile(r"sustainab|greenhouse|emission|scope [123]|climate|esg|carbon|decarboni|net[- ]zero|"
                      r"renewable|biodiversity|human rights|diversity|tcfd|gri|sasb|stakeholder", re.I)


def is_esg(text, sample=60000):
    """The report itself is about sustainability: ESG words come up again and again (not a thesis, contract or fund
    report that only has 'esg' or 'csr' in its web address)."""
    return len(ESG_TEXT.findall(text[:sample])) >= 15


def save_pdf_anon(sink, anon, body, rel, company="", esg=False):
    """A PDF already in memory (web archive): company aliases learned from its text, then redacted in place."""
    tmp = tempfile.mkdtemp(prefix="fl_")
    try:
        import pymupdf
        src = os.path.join(tmp, "src.pdf")
        open(src, "wb").write(body)
        try:
            doc = pymupdf.open(src)
            if doc.needs_pass or doc.page_count > 600:
                return False
            text = "".join(p.get_text() for p in doc)[:3000000]
            doc.close()
        except Exception:  # damaged PDF
            return False
        if not is_english(text) or (esg and not is_esg(text)):
            return False
        anon.start()
        learn_aliases(anon, text, company)
        dst = sink.path(f"{rel}.pdf")
        ok, _ = anon.pdf(src, dst)
        if ok:
            sink.wrote(dst)
        return ok
    except Exception:
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
