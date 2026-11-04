"""Financelitics, second phase (user 2026-11-04, "massively"): IPOs, ESG, deal data rooms and memos, credit agreements
with their term sheets and credit files (models + memos), quarterly portfolio reporting over many cycles, banker
deliverables with their source filings, wealth-management client records (holdings, statements, advisor notes, KYC;
generated, de-identified), fund holdings, benchmarks, pricing and ESG data.

EVERYTHING IS ANONYMISED (user 2026-11-04): every company, person and ticker gets one made-up name, the same in every
file (howco.anon: HTML/text rewritten before the PDF is made, PDFs redacted in place, identifiers such as CIK, CUSIP,
ISIN and LEI never written). Folder and file names use the made-up names. Logs print counts only.

Item budget: the Research Collections shared drive holds at most 400,000 items, so documents are grouped (one data
room per deal, one credit file per borrower, one statement book per client) and every source has an item cap."""
import datetime as dt
import gzip
import io
import json
import os
import random
import re
import time
import zipfile

from avala.sink import safe

from . import common as C

IPO = "07 IPOs & Prospectuses"
ESG = "08 ESG Reports & Data"
DEALS = "09 Deal Data Rooms & Memos"
CREDIT = "10 Credit Agreements, Term Sheets & Credit Files"
PREP = "11 Quarterly Portfolio Reporting"
WEALTH = "12 Wealth Management Client Records (De-identified)"
FUNDS = "13 Fund Holdings, Benchmarks, Pricing & ESG"

CAPS = {"ipos": 30000, "deals": 45000, "credit": 40000, "portfolio": 25000, "funds": 30000, "esg": 15000,
        "wealth": 25000}
ARCH = "https://www.sec.gov/Archives/edgar"


LANE = os.environ.get("FL_LANE", "")  # two parallel jobs per heavy source: 'even' and 'odd' years


def _mine(y):
    return not LANE or (y % 2 == 0) == (LANE == "even")


def _count(st, key, n=1):
    st["items"] = st.get("items", 0) + n
    return st["items"] < CAPS[key]


def _quarters(st, key, first=2001):
    """Quarters newest first, resumable: (year, q) not yet done."""
    done = set(st.setdefault(key, []))
    today = dt.date.today()
    y, q = today.year, (today.month - 1) // 3 + 1
    while y >= first:
        if f"{y}Q{q}" not in done and _mine(y):
            yield y, q
        q -= 1
        if q == 0:
            y, q = y - 1, 4


def form_index(s, y, q):
    """EDGAR full index of one quarter: [(form, company, cik, date, path)]."""
    r = C.get(s, f"{ARCH}/full-index/{y}/QTR{q}/form.idx", timeout=300)
    out = []
    if not r:
        return out
    for line in r.text.splitlines():
        m = re.match(r"^(\S.*?)\s{2,}(.+?)\s{2,}(\d+)\s{2,}(\d{4}-\d{2}-\d{2})\s{2,}(\S+)\s*$", line)
        if m:
            out.append(m.groups())
    return out


ROW = re.compile(r"<tr[^>]*>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>\s*<a href=\"([^\"]+)\"[^>]*>"
                 r"([^<]+)</a>.*?</td>\s*<td[^>]*>([^<]*)</td>", re.S | re.I)


def filing_docs(s, path):
    """Documents of one filing from its index page: [(description, url, name, type)]."""
    acc = path.rsplit("/", 1)[-1].replace(".txt", "")
    folder = path.rsplit("/", 1)[0] + "/" + acc.replace("-", "")
    time.sleep(0.12)
    r = C.get(s, f"https://www.sec.gov/Archives/{folder}/{acc}-index.htm")
    if not r:
        return []
    out = []
    for _seq, desc, href, name, typ in ROW.findall(r.text):
        if href.startswith("/Archives/") and not name.lower().endswith((".jpg", ".gif", ".png", ".xsd", ".css", ".js")):
            out.append((re.sub(r"<[^>]+>", "", desc).strip(), "https://www.sec.gov" + href, name.strip(),
                        typ.strip().upper()))
    return out


def _nm(anon, company):
    """Made-up company name for folders (the legal suffix stays)."""
    company = re.sub(r"\s*/[A-Z]{2}/?\s*$", "", company).strip()
    return safe(anon.text(company.title() if company.isupper() else company), 60)


# ---------------------------------------------------------------- 07 IPOs

def ipos(sink, st):
    """Initial registration statements (S-1, F-1) and final IPO prospectuses (424B4), with underwriting agreements,
    filed by company and year, newest first back to 2001."""
    s = C.session(True)
    anon = C.anon_for(st)
    n = 0
    for y, q in _quarters(st, "ipo_q"):
        if sink.full() or st.get("items", 0) >= CAPS["ipos"]:
            break
        rows = [r for r in form_index(s, y, q) if r[0] in ("S-1", "F-1", "424B4")]
        pos = st.setdefault("ipo_pos", {}).get(f"{y}Q{q}", 0)
        for i in range(pos, len(rows)):
            form, company, cik, date, path = rows[i]
            if sink.full():
                st["ipo_pos"][f"{y}Q{q}"] = i
                return n
            folder = f"{IPO}/{y}/{_nm(anon, company)}"
            for desc, url, name, typ in filing_docs(s, path):
                kind = None
                if typ == form or typ.startswith(form):
                    kind = {"S-1": "Registration statement (S-1)", "F-1": "Registration statement (F-1)",
                            "424B4": "Final prospectus (424B4)"}[form]
                elif typ.startswith("EX-1"):
                    kind = "Underwriting agreement"
                if kind and C.fetch_anon(s, sink, anon, url, f"{folder}/{date} {kind}", filer=company):
                    n += 1
                    if not _count(st, "ipos"):
                        return n
            st["ipo_pos"][f"{y}Q{q}"] = i + 1
        st["ipo_q"].append(f"{y}Q{q}")
    return n


# ---------------------------------------------------------------- 09 deal data rooms (with banker deliverables)

DEAL_FORMS = ("DEFM14A", "PREM14A", "S-4", "SC TO-T", "SC 14D9", "SC 13E3", "DEFM14C")
ROOM = {"agreement": "01 Merger Agreement", "proxy": "02 Proxy, Prospectus & Offer Documents",
        "banker": "03 Banker Deliverables (fairness opinions & board materials)",
        "financing": "04 Financing Commitments & Term Sheets", "offer": "05 Tender Offer Documents",
        "announce": "06 Announcements & Communications"}


def _deal_kind(form, desc, typ):
    d = f"{desc} {typ}".lower()
    if typ == form or typ.startswith(form):
        return "proxy"
    if typ.startswith("EX-2") or "merger agreement" in d or "agreement and plan of" in d:
        return "agreement"
    if re.search(r"\(c\)|fairness|opinion of|discussion materials|presentation to|board of directors materials|"
                 r"valuation analysis|financial analysis", d):
        return "banker"
    if re.search(r"\(b\)|commitment letter|term sheet|summary of terms|debt financing|equity commitment", d):
        return "financing"
    if re.search(r"\(a\)\(1\)|offer to purchase|letter of transmittal", d):
        return "offer"
    if re.search(r"\(a\)\(5\)|press release|ex-99", d):
        return "announce"
    return None


def deals(sink, st):
    """One data room per target: merger agreement, proxy / prospectus / offer documents, banker fairness opinions and
    board books (with the filing they came from), financing commitments and term sheets, tender offer documents and
    announcements, plus a deal memo (timeline, parties, document index, sources)."""
    s = C.session(True)
    anon = C.anon_for(st)
    rooms = st.setdefault("rooms", {})
    n = 0
    for y, q in _quarters(st, "deal_q"):
        if sink.full() or st.get("items", 0) >= CAPS["deals"]:
            break
        rows = [r for r in form_index(s, y, q) if r[0] in DEAL_FORMS]
        pos = st.setdefault("deal_pos", {}).get(f"{y}Q{q}", 0)
        for i in range(pos, len(rows)):
            form, company, cik, date, path = rows[i]
            if sink.full():
                st["deal_pos"][f"{y}Q{q}"] = i
                return n
            target = _nm(anon, company)
            room = rooms.setdefault(cik, {"name": target, "docs": []})
            base = f"{DEALS}/{room['name']} data room"
            got = 0
            for desc, url, name, typ in filing_docs(s, path):
                kind = _deal_kind(form, desc, typ)
                if not kind:
                    continue
                label = safe(anon.text(desc) or typ, 60) if kind != "proxy" else form
                rel = f"{base}/{ROOM[kind]}/{date} {label}"
                if C.fetch_anon(s, sink, anon, url, rel, filer=company):
                    room["docs"].append([date, kind, label, form, typ])
                    got += 1
                    n += 1
                    if not _count(st, "deals"):
                        break
            if got:
                C.deal_memo(sink, f"{base}/00 Deal memo.docx", room)
                _count(st, "deals")
            room["docs"] = room["docs"][-300:]
            st["deal_pos"][f"{y}Q{q}"] = i + 1
        st["deal_q"].append(f"{y}Q{q}")
    return n


# ---------------------------------------------------------------- 10 credit agreements, term sheets, credit files

CREDIT_Q = [('"credit agreement"', "Credit agreement"), ('"term loan"', "Term loan agreement"),
            ('"term sheet"', "Term sheet"), ('"commitment letter"', "Commitment letter"),
            ('"summary of terms"', "Term sheet"), ('"note purchase agreement"', "Note purchase agreement"),
            ('"amendment to credit agreement"', "Credit agreement amendment")]


def credit(sink, st):
    """Credit agreements, amendments, term sheets and commitment letters (EDGAR exhibits, 2001 on), filed per borrower
    with a credit model (XBRL financials, leverage, coverage and covenant tests as live formulas) and a credit memo."""
    s = C.session(True)
    anon = C.anon_for(st)
    pos = st.setdefault("efts", {})
    files = st.setdefault("files", {})
    n = 0
    years = [y for y in range(dt.date.today().year, 2000, -1) if _mine(y)]
    for y in years:
        for q, label in CREDIT_Q:
            key = f"{y}|{q}"
            start = pos.get(key, 0)
            while start is not None and start < 9900 and not sink.full():
                if st.get("items", 0) >= CAPS["credit"]:
                    return n
                time.sleep(0.25)
                r = C.get(s, "https://efts.sec.gov/LATEST/search-index", params={
                    "q": q, "forms": "8-K,10-Q,10-K,S-1,S-4", "startdt": f"{y}-01-01", "enddt": f"{y}-12-31",
                    "from": start})
                hits = r.json().get("hits", {}).get("hits", []) if r else []
                if not hits:
                    start = None
                    break
                start += len(hits)
                for h in hits:
                    src = h["_source"]
                    typ = (src.get("file_type") or "").upper()
                    if not typ.startswith("EX-10") and not typ.startswith("EX-99"):
                        continue
                    acc, fname = h["_id"].split(":", 1)
                    cik = (src.get("ciks") or ["0"])[0].lstrip("0") or "0"
                    company = re.sub(r"\s*\(.*", "", (src.get("display_names") or ["Borrower"])[0])
                    f = files.setdefault(cik, {"name": _nm(anon, company), "docs": 0})
                    rel = f"{CREDIT}/{f['name']}/{src.get('file_date', '')} {label} ({typ})"
                    url = f"{ARCH}/data/{cik}/{acc.replace('-', '')}/{fname}"
                    if C.fetch_anon(s, sink, anon, url, rel, filer=company):
                        n += 1
                        f["docs"] += 1
                        if f["docs"] == 1:  # first document of a borrower: its credit model and memo
                            n += C.credit_file(s, sink, anon, cik, f["name"], f"{CREDIT}/{f['name']}")
                        if not _count(st, "credit"):
                            return n
                    if sink.full():
                        break
            pos[key] = start
    return n


# ---------------------------------------------------------------- 11 quarterly portfolio reporting

BDCS = ["ARCC", "OBDC", "FSK", "BXSL", "MAIN", "GBDC", "HTGC", "PSEC", "TSLX", "OCSL", "GSBD", "NMFC", "MFIC",
        "CGBD", "BBDC", "SLRC", "TCPC", "CSWC", "TRIN", "FDUS", "GAIN", "GLAD", "PFLT", "PNNT", "CCAP", "SAR", "WHF",
        "HRZN", "TPVG", "OFS", "MRCC", "PTMN", "OXSQ", "LRFC", "GECC", "RAND", "ICMB", "SCM", "BCSF", "CION", "NCDL",
        "MSDL", "PSBD", "OBDE", "KBDC", "TCPC", "SSSS", "PFX", "HCAP", "FCRD"]


def portfolio(sink, st):
    """Quarterly portfolio reports over many cycles: business development companies' 10-Q / 10-K reports (schedule
    of investments, portfolio quality, non-accruals, NAV bridge), 2008 on, per manager and year."""
    s = C.session(True)
    anon = C.anon_for(st)
    tick = C.tickers(s, st)
    done = set(st.setdefault("acc", []))
    n = 0
    for t in BDCS:
        cik = tick.get(t)
        if not cik or sink.full() or st.get("items", 0) >= CAPS["portfolio"]:
            continue
        for form, date, acc, doc, company in C.all_filings(s, cik, ("10-Q", "10-K"), since="2008-01-01"):
            if acc in done or sink.full():
                continue
            name = _nm(anon, company)
            q = f"Q{(int(date[5:7]) - 1) // 3 + 1}"
            url = f"{ARCH}/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
            kind = "Annual portfolio report (10-K)" if form == "10-K" else "Quarterly portfolio report (10-Q)"
            if C.fetch_anon(s, sink, anon, url, f"{PREP}/{name}/{date[:4]}/{date} {q} {kind}", filer=company):
                n += 1
                if not _count(st, "portfolio"):
                    break
            done.add(acc)
            st["acc"] = sorted(done)
    return n


# ---------------------------------------------------------------- 13 fund holdings, benchmarks, pricing, ESG

def _x(el, path):
    from xml.etree import ElementTree as ET  # noqa: F401
    node = el
    for p in path.split("/"):
        if node is None:
            return ""
        node = next((c for c in node if c.tag.rsplit("}", 1)[-1] == p), None)
    return (node.text or "").strip() if node is not None and node.text else ""


def funds(sink, st):
    """Monthly portfolio holdings of registered funds (Form N-PORT, 2019 on): one workbook per fund and period with
    the fund summary (net assets, flows, monthly returns), holdings by asset class, issuer type and country, and the
    fair-value level used for pricing. Funds whose name says ESG / sustainable / climate are filed apart.
    Fund and issuer names are made up; CUSIP, ISIN, LEI and other identifiers are never written."""
    from xml.etree import ElementTree as ET
    from openpyxl import Workbook
    s = C.session(True)
    anon = C.anon_for(st)
    n = 0
    for y, q in _quarters(st, "nport_q", first=2019):
        if sink.full() or st.get("items", 0) >= CAPS["funds"]:
            break
        rows = [r for r in form_index(s, y, q) if r[0] == "NPORT-P"]
        random.Random(f"{y}{q}").shuffle(rows)  # spread over fund families
        pos = st.setdefault("nport_pos", {}).get(f"{y}Q{q}", 0)
        take = rows[:2500]  # per quarter: keeps the item budget spread over the years
        for i in range(pos, len(take)):
            form, company, cik, date, path = take[i]
            if sink.full():
                st["nport_pos"][f"{y}Q{q}"] = i
                return n
            acc = path.rsplit("/", 1)[-1].replace(".txt", "")
            time.sleep(0.12)
            r = C.get(s, f"https://www.sec.gov/Archives/{path.rsplit('/', 1)[0]}/{acc.replace('-', '')}/primary_doc.xml")
            if not r:
                continue
            try:
                root = ET.fromstring(r.content)
            except ET.ParseError:
                continue
            fd = next((c for c in root.iter() if c.tag.endswith("formData")), None)
            if fd is None:
                continue
            gen = next((c for c in fd if c.tag.endswith("genInfo")), None)
            fin = next((c for c in fd if c.tag.endswith("fundInfo")), None)
            fam = _nm(anon, company)
            series = safe(anon.text(_x(gen, "seriesName") or company), 70)
            period = _x(gen, "repPdDate") or date
            esg = bool(re.search(r"\b(esg|sustainab|climate|green|impact|clean energy|low carbon|social)\b",
                                 _x(gen, "seriesName"), re.I))
            wb = Workbook()
            ws = wb.active
            ws.title = "Fund summary"
            ws.append(["Fund family", fam])
            ws.append(["Fund", series])
            ws.append(["Reporting period end", period])
            for label, p in (("Total assets", "totAssets"), ("Total liabilities", "totLiabs"), ("Net assets", "netAssets")):
                v = _x(fin, p)
                ws.append([label, float(v) if re.match(r"^-?\d+(\.\d+)?$", v or "") else v])
            ws.append(["Net assets check (assets - liabilities)", "=B4-B5"])
            ws.append([])
            ws.append(["Monthly total return (%)", "Month 1", "Month 2", "Month 3"])
            ret = next((c for c in fin.iter() if c.tag.endswith("monthlyTotReturn")), None) if fin is not None else None
            if ret is not None:
                ws.append(["Fund", *[float(ret.attrib.get(k, "0") or 0) for k in ("rtn1", "rtn2", "rtn3")]])
                ws.append(["Quarter (compounded)", "=((1+B10/100)*(1+C10/100)*(1+D10/100)-1)*100"])
            hs = wb.create_sheet("Holdings")
            hs.append(["Issuer (made-up name)", "Asset class", "Issuer type", "Country", "Currency", "Value (USD)",
                       "% of net assets", "Fair value level"])
            inv = next((c for c in fd if c.tag.endswith("invstOrSecs")), None)
            rows_n = 0
            for sec in (inv if inv is not None else []):
                name = _x(sec, "name") or _x(sec, "title")
                vals = [anon.text(name)[:120], _x(sec, "assetCat"), _x(sec, "issuerCat"), _x(sec, "invCountry"),
                        _x(sec, "curCd")]
                for p in ("valUSD", "pctVal"):
                    v = _x(sec, p)
                    vals.append(float(v) if re.match(r"^-?\d+(\.\d+)?(E-?\d+)?$", v or "", re.I) else v)
                vals.append(_x(sec, "fairValLevel"))
                hs.append(vals)
                rows_n += 1
            if rows_n:
                hs.append(["Total", "", "", "", "", f"=SUM(F2:F{rows_n + 1})", f"=SUM(G2:G{rows_n + 1})", ""])
            kind = "ESG & Sustainable Funds" if esg else "All Funds"
            p = sink.path(f"{FUNDS}/Fund Holdings (monthly portfolio reports)/{kind}/{period[:4]}/{fam}/"
                          f"{series} {period}.xlsx")
            wb.save(p)
            sink.wrote(p)
            n += 1
            if not _count(st, "funds"):
                return n
            st["nport_pos"][f"{y}Q{q}"] = i + 1
        st["nport_q"].append(f"{y}Q{q}")
    return n


# ---------------------------------------------------------------- 08 ESG

ESG_Q = ['"sustainability report"', '"ESG report"', '"climate-related financial disclosures"', '"TCFD"',
         '"greenhouse gas emissions" "scope 3"', '"corporate responsibility report"', '"human capital"']


def esg(sink, st):
    """ESG material: company sustainability, climate (TCFD) and corporate-responsibility reports filed with the SEC,
    facility greenhouse-gas emissions by parent company and year (EPA GHGRP), and country ESG indicators (World Bank
    sovereign ESG data). Company and facility names are made up; countries stay."""
    s = C.session(True)
    anon = C.anon_for(st)
    n = 0
    # 1. company reports (EDGAR full-text search: exhibits that are the reports themselves)
    pos = st.setdefault("efts", {})
    for y in range(dt.date.today().year, 2009, -1):
        for q in ESG_Q:
            key = f"{y}|{q}"
            start = pos.get(key, 0)
            while start is not None and start < 3000 and not sink.full() and st.get("items", 0) < CAPS["esg"]:
                time.sleep(0.25)
                r = C.get(s, "https://efts.sec.gov/LATEST/search-index", params={
                    "q": q, "forms": "8-K,10-K,DEF 14A,ARS", "startdt": f"{y}-01-01", "enddt": f"{y}-12-31",
                    "from": start})
                hits = r.json().get("hits", {}).get("hits", []) if r else []
                if not hits:
                    start = None
                    break
                start += len(hits)
                for h in hits:
                    src = h["_source"]
                    typ = (src.get("file_type") or "").upper()
                    if not (typ.startswith("EX-99") or typ in ("DEF 14A", "ARS")):
                        continue
                    acc, fname = h["_id"].split(":", 1)
                    cik = (src.get("ciks") or ["0"])[0].lstrip("0") or "0"
                    company = re.sub(r"\s*\(.*", "", (src.get("display_names") or ["Company"])[0])
                    kind = "Proxy statement (ESG & governance)" if typ == "DEF 14A" else "Sustainability & climate report"
                    rel = f"{ESG}/Company ESG Reports/{y}/{_nm(anon, company)}/{src.get('file_date', '')} {kind}"
                    if C.fetch_anon(s, sink, anon, f"{ARCH}/data/{cik}/{acc.replace('-', '')}/{fname}", rel, filer=company):
                        n += 1
                        _count(st, "esg")
            pos[key] = start
    # 2. EPA greenhouse gas reporting program: facility emissions per year, parent companies made up
    n += C.ghgrp(s, sink, anon, st, f"{ESG}/Facility Greenhouse Gas Emissions (EPA GHGRP)")
    # 3. World Bank sovereign ESG indicators
    n += C.worldbank_esg(s, sink, st, f"{ESG}/Country ESG Indicators (World Bank)")
    return n


# ---------------------------------------------------------------- 12 wealth management client records (generated)

def wealth(sink, st, per_run=400):
    """Client records of a wealth-management practice, generated and de-identified: client profile, KYC file (identity
    checks with masked numbers, risk profile, source of wealth, screening), quarterly holdings workbook with live
    formulas, a statement book (one monthly statement per page, several years) and advisor meeting notes."""
    from . import wealthgen
    n = 0
    k = st.get("next", 0)
    while k < CAPS["wealth"] // 5 and n < per_run * 5 and not sink.full():
        n += wealthgen.client(sink, WEALTH, k)
        k += 1
        st["next"] = k
    st["items"] = k * 5
    return n


SOURCES = {"ipos": ipos, "deals": deals, "credit": credit, "portfolio": portfolio, "funds": funds, "esg": esg,
           "wealth": wealth}


# ---------------------------------------------------------------- 08 ESG: company websites worldwide (Common Crawl)

CC = "https://data.commoncrawl.org"
CRAWLS = ["CC-MAIN-2025-30", "CC-MAIN-2025-26", "CC-MAIN-2025-21", "CC-MAIN-2025-18", "CC-MAIN-2025-13",
          "CC-MAIN-2025-08", "CC-MAIN-2025-05", "CC-MAIN-2024-51", "CC-MAIN-2024-46", "CC-MAIN-2024-42",
          "CC-MAIN-2024-38", "CC-MAIN-2024-33", "CC-MAIN-2024-30", "CC-MAIN-2024-26", "CC-MAIN-2024-22",
          "CC-MAIN-2024-18", "CC-MAIN-2024-10", "CC-MAIN-2023-50", "CC-MAIN-2023-40", "CC-MAIN-2023-23"]
# report words in the PDF's address, in the main languages companies publish in (lower case)
ESG_URL = (r"sustainab|esg[-_ ]?(report|disclosure|factbook|data)|csr[-_ ]?report|corporate[-_ ]?responsibility|"
           r"responsibility[-_ ]?report|impact[-_ ]?report|climate[-_ ]?(report|disclosure|transition)|tcfd|tnfd|"
           r"integrated[-_ ]?(annual[-_ ]?)?report|non[-_ ]?financial|carbon[-_ ]?(disclosure|report)|"
           r"nachhaltigkeit|durabilit|duurzaamheid|sostenibilit|sustentabilidad|sustentabilidade|sostenibilidad|"
           r"hallbarhet|baerekraft|baeredygtighed|kestavyys|vastuullisuus|zrownowazon|udrzitelnost|fenntarthat|"
           r"surdurulebilirlik|csr|esg")
PUBLIC = re.compile(r"\.(gov|edu|mil|int)$|\.(gov|gc|ac|edu|govt|gob|gouv|go)\.[a-z]{2}$|\.nhs\.uk$|\.europa\.eu$|"
                    r"\.un\.org$|worldbank\.org$|oecd\.org$", re.I)  # public bodies are the Asset Library's
SECOND = {"co", "com", "net", "org", "ac", "gov", "ne", "or", "go"}


def _company_label(host):
    parts = host.lower().removeprefix("www.").split(".")
    if len(parts) >= 3 and parts[-2] in SECOND:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


def _cc_part(s, path, cache="cache/cc-esg.parquet"):
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    os.makedirs("cache", exist_ok=True)
    with s.get(f"{CC}/{path}", stream=True, timeout=1200) as r:
        r.raise_for_status()
        with open(cache, "wb") as f:
            for chunk in r.iter_content(8 << 20):
                f.write(chunk)
    try:
        t = pq.read_table(cache, columns=["url", "url_host_name", "url_path", "content_languages",
                                          "warc_filename", "warc_record_offset", "warc_record_length",
                                          "content_truncated"],
                          filters=[("content_mime_detected", "=", "application/pdf"), ("fetch_status", "=", 200)])
    finally:
        os.remove(cache)
    t = t.filter(pc.match_substring_regex(pc.utf8_lower(t["url_path"]), ESG_URL))
    return [r for r in t.to_pylist() if not r.get("content_truncated") and not PUBLIC.search(r["url_host_name"] or "")]


def _warc_body(s, row):
    import zlib
    off, ln = int(row["warc_record_offset"]), int(row["warc_record_length"])
    r = C.get(s, f"{CC}/{row['warc_filename']}", headers={"Range": f"bytes={off}-{off + ln - 1}"}, tries=3)
    if r is None or len(r.content) != ln:
        return None
    try:
        rec = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(r.content)
    except zlib.error:
        return None
    parts = rec.split(b"\r\n\r\n", 2)
    return parts[2] if len(parts) == 3 and parts[2][:5] == b"%PDF-" else None


def esgweb(sink, st):
    """Sustainability, ESG, climate (TCFD), CSR and integrated reports that companies publish on their own websites,
    worldwide and in every language, out of the Common Crawl web archive (public bodies left out). One folder per
    company under its made-up name; the report text is anonymised (company, people and ticker names made up)."""
    import hashlib
    s = C.session()
    anon = C.anon_for(st)
    pos = st.setdefault("cc", {"crawl": 0, "part": 0})
    seen = set(st.setdefault("seen", []))
    comp = st.setdefault("companies", {})
    n = 0
    while pos["crawl"] < len(CRAWLS) and not sink.full() and st.get("items", 0) < CAPS["esgweb"]:
        crawl = CRAWLS[pos["crawl"]]
        r = C.get(s, f"{CC}/crawl-data/{crawl}/cc-index-table.paths.gz", timeout=300)
        parts = [p for p in gzip.decompress(r.content).decode().split() if "subset=warc/" in p] if r else []
        random.Random(crawl).shuffle(parts)
        parts = [p for i, p in enumerate(parts) if _mine(i)]
        if pos["part"] >= len(parts):
            pos["crawl"], pos["part"] = pos["crawl"] + 1, 0
            continue
        try:
            rows = _cc_part(s, parts[pos["part"]])
        except Exception as exc:  # noqa: BLE001
            print(f"esgweb: index part skipped ({type(exc).__name__})")
            rows = []
        pos["part"] += 1
        for row in rows:
            if sink.full() or st.get("items", 0) >= CAPS["esgweb"]:
                break
            key = hashlib.sha1(row["url"].split("?")[0].lower().encode()).hexdigest()[:16]
            if key in seen:
                continue
            seen.add(key)
            body = _warc_body(s, row)
            if not body or len(body) > C.CAP:
                continue
            dig = hashlib.sha1(body).hexdigest()[:16]
            if dig in seen:
                continue
            seen.add(dig)
            label = _company_label(row["url_host_name"])
            if label not in comp:
                comp[label] = safe(anon.co.pseudo((label,)), 60)
            year = (re.findall(r"(?<!\d)(20[0-3]\d)(?!\d)", row["url"]) or ["undated"])[-1]
            lang = (row.get("content_languages") or "").split(",")[0] or "xx"
            kind = ("Climate report" if re.search(r"climate|tcfd|tnfd|carbon", row["url"], re.I) else
                    "Integrated report" if re.search(r"integrated", row["url"], re.I) else
                    "CSR report" if re.search(r"csr|responsib", row["url"], re.I) else "Sustainability report")
            rel = f"{ESG}/Company Sustainability Reports (worldwide)/{comp[label]}/{year} {kind} ({lang}) {dig[:6]}"
            if C.save_pdf_anon(sink, anon, body, rel, label):
                n += 1
                _count(st, "esgweb")
        st["seen"] = sorted(seen)[-400000:]
        sink.state.save()
    return n


SOURCES["esgweb"] = esgweb
CAPS["esgweb"] = 40000
