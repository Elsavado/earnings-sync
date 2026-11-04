"""Generated, de-identified wealth-management client records (no real person, account or firm). One client = 5 files:
profile & KYC file (PDF), investment policy statement & account agreement (PDF), holdings and performance workbook
(live formulas), statement book (one monthly statement per page, several years; PDF) and advisor meeting notes
(DOCX). Deterministic: client k always comes out the same."""
import datetime as dt
import math
import random

FIRST = ("Amara Bennett Caleb Dalia Elias Farrah Gideon Hana Idris Jolene Kian Lyra Mateo Nadia Orson Priya Quentin Rhea "
         "Silas Talia Ulric Vera Wesley Xenia Yusuf Zara Ansel Brielle Cyrus Delphine Emeric Freya Gareth Imogen Jasper "
         "Keira Leander Marisol Nikolai Odessa Phineas Rosalind Soren Thea Valentin Willa Ximena Yara Zeke Aurelia Beckett "
         "Celeste Dorian Esme Fabian Giselle Hollis Ines Jude Kaia Lucian Maren Nico Ophelia Pierce Rowan Saskia Tobias").split()
LAST = ("Ashdown Blackwood Carrow Davenport Ellery Fairbank Galloway Hartwell Ingram Jessop Kettering Langley Merriweather "
        "Northcott Oakhurst Pemberton Quayle Radcliffe Stanhope Thornbury Underhill Vance Whitlock Yardley Ainsworth "
        "Brightmore Calloway Dunmore Eastbrook Fenwick Glenister Holloway Ivesdale Jardine Kingsley Lockhart Montague "
        "Netherby Ormsby Prescott Ravensworth Sedgwick Trevelyan Upton Wainwright Wexley Ashcombe Bramley Cheshire Dalton").split()
CITIES = ["Ridgeport", "Lakemont", "Harbor Falls", "Cedar Vale", "Westbrook", "Stonehaven", "Maple Crossing",
          "Silver Bay", "Northfield", "Fairhaven", "Brookside", "Pine Hollow"]
FIRM = "Larkmoor Wealth Partners"  # made up
# made-up funds: (name, ticker, asset class, annual return, annual volatility, beta to equities)
FUNDS = [("Halvern US Total Market Index Fund", "HVTMX", "US equity", 0.085, 0.16, 1.0),
         ("Halvern International Developed Index Fund", "HVIDX", "International equity", 0.065, 0.17, 0.85),
         ("Corvane Emerging Markets Fund", "CVEMX", "Emerging markets equity", 0.07, 0.22, 0.9),
         ("Brightwater Dividend Growth Fund", "BWDGX", "US equity", 0.075, 0.14, 0.9),
         ("Sorrel Small Cap Value Fund", "SRSVX", "US small cap equity", 0.08, 0.21, 1.1),
         ("Ashgrove Core Bond Fund", "AGCBX", "Investment-grade bonds", 0.035, 0.05, 0.05),
         ("Ashgrove Short-Term Treasury Fund", "AGSTX", "Treasuries", 0.03, 0.02, -0.05),
         ("Pellion High Yield Credit Fund", "PLHYX", "High-yield credit", 0.055, 0.09, 0.45),
         ("Merrow Municipal Income Fund", "MRMIX", "Municipal bonds", 0.03, 0.045, 0.05),
         ("Tamsin Global Real Estate Fund", "TSGRX", "Real estate", 0.06, 0.19, 0.75),
         ("Quillon Sustainable Leaders Fund", "QSLDX", "ESG equity", 0.08, 0.16, 0.95),
         ("Fenmore Inflation-Protected Bond Fund", "FMIPX", "Inflation-linked bonds", 0.03, 0.06, 0.1),
         ("Varden Money Market Fund", "VDMXX", "Cash", 0.025, 0.003, 0.0)]
PROFILES = {"Conservative": [0.15, 0.05, 0, 0.05, 0, 0.3, 0.2, 0.05, 0.1, 0, 0, 0.05, 0.05],
            "Moderate": [0.25, 0.1, 0.05, 0.05, 0.05, 0.25, 0.05, 0.05, 0.05, 0.05, 0.05, 0, 0],
            "Growth": [0.35, 0.15, 0.08, 0.07, 0.08, 0.12, 0, 0.03, 0, 0.05, 0.07, 0, 0],
            "Aggressive": [0.4, 0.17, 0.12, 0.05, 0.12, 0.05, 0, 0, 0, 0.05, 0.04, 0, 0]}
NOTES = ["Reviewed allocation against the investment policy; drift within bands, no trades needed.",
         "Client asked about market volatility; walked through drawdown history of the model portfolio.",
         "Rebalanced back to target after equity rally; trimmed US equity, added to core bonds.",
         "Discussed tax-loss harvesting opportunities in the international sleeve.",
         "Updated beneficiary designations and confirmed estate documents are current.",
         "Client expects a bonus; agreed to add it as a lump-sum contribution next month.",
         "Talked through education savings for the children and a separate goal bucket.",
         "Risk questionnaire re-taken; score unchanged, profile confirmed.",
         "Client raised interest in sustainable investing; added the ESG equity fund at 5%.",
         "Planned retirement income: discussed withdrawal rate and cash buffer of 12 months.",
         "Annual fee review; explained the advisory fee schedule and fund expense ratios.",
         "Client relocated; updated address and tax residency on file and re-verified identity.",
         "Reviewed required minimum distribution schedule and charitable giving options.",
         "Market outlook call; no change to strategy, reaffirmed long-term horizon."]


def _person(rng):
    return rng.choice(FIRST), rng.choice(LAST)


def _months(rng):
    end = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    n = rng.randint(36, 72)
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append(dt.date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def _simulate(rng, months, weights, start_value, monthly_add):
    """Monthly prices and holdings: one market factor plus fund noise; contributions bought at target weights."""
    prices = [[10.0 + 40 * rng.random() for _ in FUNDS]]
    for _ in months[1:]:
        mkt = rng.gauss(0, 0.045)
        row = []
        for (name, tk, ac, mu, vol, beta), p in zip(FUNDS, prices[-1]):
            idio = math.sqrt(max(vol ** 2 / 12 - (beta * 0.045) ** 2, 1e-6))
            row.append(round(p * math.exp(mu / 12 + beta * mkt + rng.gauss(0, idio)), 4))
        prices.append(row)
    units = [start_value * w / p for w, p in zip(weights, prices[0])]
    hist = []
    for i, mth in enumerate(months):
        add = monthly_add if i else 0
        wd = 0
        if rng.random() < 0.04:
            wd = round(sum(u * p for u, p in zip(units, prices[i])) * rng.uniform(0.01, 0.05), 2)
        for j, (w, p) in enumerate(zip(weights, prices[i])):
            units[j] += (add - wd) * w / p
            units[j] = max(units[j], 0)
        if i and i % 12 == 0:  # yearly rebalance to target
            total = sum(u * p for u, p in zip(units, prices[i]))
            units = [total * w / p for w, p in zip(weights, prices[i])]
        hist.append((mth, list(units), prices[i], add, wd))
    return hist


def _pdf(path, pages):
    import pymupdf
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page(width=612, height=792)
        y = 50
        for size, text in lines:
            width = int(105 * 10 / size)
            for chunk in [text[i:i + width] for i in range(0, max(len(text), 1), width)]:
                if y > 760:
                    page = doc.new_page(width=612, height=792)
                    y = 50
                page.insert_text((48, y), chunk, fontsize=size, fontname="helv")
                y += size + 5
    doc.set_metadata({"title": "", "author": FIRM})
    doc.save(path, garbage=3, deflate=True)


def client(sink, root, k):
    from docx import Document
    from openpyxl import Workbook
    rng = random.Random(f"larkmoor-client-{k}")
    first, last = _person(rng)
    name = f"{first} {last}"
    cid = f"LWP-{100000 + k}"
    acct = f"****{rng.randint(1000, 9999)}"
    profile = rng.choice(list(PROFILES))
    weights = PROFILES[profile]
    advisor = " ".join(_person(rng))
    city = rng.choice(CITIES)
    age = rng.randint(28, 82)
    start = round(rng.lognormvariate(math.log(600000), 0.9), -3)
    monthly = round(start * rng.uniform(0, 0.004), -1)
    months = _months(rng)
    hist = _simulate(rng, months, weights, start, monthly)
    folder = f"{root}/{FIRM}/Clients {k // 1000 * 1000:05d}-{k // 1000 * 1000 + 999:05d}/{cid} {last}, {first}"
    occupation = rng.choice(["Physician", "Software engineer", "Business owner", "Attorney", "Retired teacher",
                             "Corporate executive", "Architect", "Pharmacist", "Retired engineer", "Consultant"])
    wealth_src = rng.choice(["Employment income and savings", "Sale of a private business", "Inheritance",
                             "Pension and retirement savings", "Real estate sale", "Equity compensation"])
    kyc = [[(16, f"{FIRM} - Client profile and KYC file"), (10, f"Client ID {cid}    Prepared {months[0]:%Y-%m-%d}"),
            (12, "1. Client"), (10, f"Name: {name}    Age band: {age // 10 * 10}s    City: {city}"),
            (10, f"Occupation: {occupation}    Tax ID: ***-**-{rng.randint(1000, 9999)} (masked)"),
            (12, "2. Identity verification"),
            (10, f"Government ID: verified ({rng.choice(['passport', 'driver licence'])}, number masked)"),
            (10, f"Address verification: utility statement, verified {months[0]:%Y-%m-%d}"),
            (12, "3. Source of wealth and funds"), (10, f"Source of wealth: {wealth_src}"),
            (10, f"Initial funding: {start:,.0f} USD by account transfer"),
            (12, "4. Screening"), (10, "Sanctions lists: no match.  PEP: no.  Adverse media: none found."),
            (12, "5. Suitability"), (10, f"Risk profile: {profile}.  Horizon: {rng.choice([7, 10, 15, 20])} years."),
            (10, f"Liquidity needs: {rng.choice(['low', 'moderate', 'annual withdrawals'])}.  Experience: "
                 f"{rng.choice(['limited', 'moderate', 'extensive'])}."),
            (12, "6. Review history"),
            *[(10, f"{m:%Y-%m-%d}: periodic KYC refresh completed by {advisor}") for m in months[::24]]]]
    _pdf(sink.path(f"{folder}/Client profile and KYC file.pdf"), kyc)
    sink.wrote(sink.path(f"{folder}/Client profile and KYC file.pdf"))
    ips = [[(16, f"{FIRM} - Investment policy statement and advisory agreement"),
            (10, f"Client: {name} ({cid})    Account {acct}    Effective {months[0]:%Y-%m-%d}"),
            (12, "Objectives"), (10, f"{profile} profile: long-term growth consistent with the stated risk tolerance."),
            (12, "Target allocation"),
            *[(10, f"{f[0]} ({f[1]}), {f[2]}: {w:.0%} (band +/-5%)") for f, w in zip(FUNDS, weights) if w],
            (12, "Rebalancing"), (10, "Annually, or when an asset class drifts outside its band."),
            (12, "Fees"), (10, f"Advisory fee {rng.choice([0.6, 0.75, 0.9, 1.0])}% a year, billed quarterly in arrears."),
            (12, "Signatures"), (10, f"Client: {name}    Advisor: {advisor}    (signed copies on file)")]]
    _pdf(sink.path(f"{folder}/Investment policy statement and agreement.pdf"), ips)
    sink.wrote(sink.path(f"{folder}/Investment policy statement and agreement.pdf"))
    pages, prev = [], start
    for mth, units, prices, add, wd in hist:
        vals = [u * p for u, p in zip(units, prices)]
        total = sum(vals)
        lines = [(14, f"{FIRM} - Monthly statement"), (10, f"{name}    Account {acct}    Period {mth:%B %Y}"),
                 (10, f"Beginning value {prev:,.2f}   Contributions {add:,.2f}   Withdrawals {wd:,.2f}   "
                      f"Change in value {total - prev - add + wd:,.2f}   Ending value {total:,.2f}"),
                 (11, "Holdings")]
        for f, u, p, v in zip(FUNDS, units, prices, vals):
            if v > 0.5:
                lines.append((9, f"{f[1]:6}  {f[0][:44]:44}  units {u:12,.3f}  price {p:9.4f}  value {v:14,.2f}  "
                                 f"{v / total:6.1%}"))
        pages.append(lines)
        prev = total
    _pdf(sink.path(f"{folder}/Statements {months[0]:%Y-%m} to {months[-1]:%Y-%m}.pdf"), pages)
    sink.wrote(sink.path(f"{folder}/Statements {months[0]:%Y-%m} to {months[-1]:%Y-%m}.pdf"))
    wb = Workbook()
    ws = wb.active
    ws.title = "Holdings (latest)"
    ws.append(["Ticker", "Fund", "Asset class", "Units", "Price", "Value", "Weight", "Target", "Drift"])
    mth, units, prices, _a, _w = hist[-1]
    n = len(FUNDS)
    for i, (f, u, p, w) in enumerate(zip(FUNDS, units, prices, weights)):
        r = i + 2
        ws.append([f[1], f[0], f[2], round(u, 4), p, f"=D{r}*E{r}", f"=F{r}/F{n + 2}", w, f"=G{r}-H{r}"])
    ws.append(["Total", "", "", "", "", f"=SUM(F2:F{n + 1})", f"=SUM(G2:G{n + 1})", f"=SUM(H2:H{n + 1})", ""])
    pf = wb.create_sheet("Monthly performance")
    pf.append(["Month", "Ending value", "Contributions", "Withdrawals", "Return"])
    for i, (m, u, p, add, wd) in enumerate(hist):
        r = i + 2
        pf.append([m.strftime("%Y-%m"), round(sum(a * b for a, b in zip(u, p)), 2), add, wd,
                   "" if i == 0 else f"=(B{r}-C{r}+D{r})/B{r - 1}-1"])
    pf.append(["Cumulative (time-weighted)", "", "", "", f"=PRODUCT(INDEX(1+E3:E{len(hist) + 1},0))-1"])
    wb.save(sink.path(f"{folder}/Holdings and performance.xlsx"))
    sink.wrote(sink.path(f"{folder}/Holdings and performance.xlsx"))
    doc = Document()
    doc.add_heading(f"Advisor notes: {name} ({cid})", 0)
    for m in months[::3]:
        doc.add_heading(f"{m:%Y-%m-%d} - meeting with {advisor}", 2)
        for t in rng.sample(NOTES, 2):
            doc.add_paragraph(t)
    doc.save(sink.path(f"{folder}/Advisor notes.docx"))
    sink.wrote(sink.path(f"{folder}/Advisor notes.docx"))
    return 5
