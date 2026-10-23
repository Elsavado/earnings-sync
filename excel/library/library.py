"""Arrange the IR Transcripts SFTP server as a finance library.

    python library.py plan  inventory.tsv  plan.json   # decide every file's place
    python library.py apply plan.json                  # move / delete on the server

inventory.tsv: "<size>\t<path>" per line (rclone lsf -R --format sp), directories end in "/".
Every file is classified by its folder and name into a section of the library. Exact duplicates
(same name and size) keep one copy. Leaf folders with more than BATCH files are split into
numbered batch folders. File names are never changed, except " (2)" for a same-name clash.
"""
import collections, json, os, posixpath, re, sys, threading, time

BATCH = 500
HERE = os.path.dirname(os.path.abspath(__file__))
TOPICS = {n: t for t, ns in json.load(open(os.path.join(HERE, "repo_topics.json"), encoding="utf-8")).items() for n in ns}

M, CF, DEALS = "01 Financial Models", "02 Company Filings", "04 Deals & Transactions"
EW, CM = f"{M}/Enterprise Wide Models", f"{M}/Corporate Models"
GIT = "11 Git Mirror"   # user, 2026-10-23: repositories live in the Git mirror
NB, HR, BK, ARC = "09 Jupyter Notebooks", "08 Payroll & HR", "07 Bookkeeping & Accounting", "99 Archive"
SECTIONS = ["01 Financial Models", "02 Company Filings", "03 Earnings Call Transcripts", DEALS, "05 Research",
            "06 Investor Relations", BK, HR, NB, "10 Design Assets", GIT, ARC]

ENTERPRISE = {
    "Valuation (DCF)": f"{EW}/Corporate & Industry Models/DCF Valuation",
    "Leveraged buyout": f"{EW}/Corporate & Industry Models/LBO",
    "Integrated financial plan": f"{EW}/Corporate & Industry Models/Integrated Financial Plans",
    "Budget & FP&A": f"{EW}/Corporate & Industry Models/Budget & FP&A",
    "Credit & liquidity": f"{EW}/Corporate & Industry Models/Credit & Liquidity",
    "Strategic 10-year plan": f"{EW}/Corporate & Industry Models/Strategic 10-Year Plans",
    "IR-enhanced operating model": f"{EW}/IR-Enhanced Operating Models",
    "Bank ALM & interest rate risk": f"{EW}/Bank Models/ALM & Interest Rate Risk",
    "Bank capital planning & stress test": f"{EW}/Bank Models/Capital Planning & Stress Testing",
    "Bank valuation": f"{EW}/Bank Models/Bank Valuation",
    "Integrated bank plan": f"{EW}/Bank Models/Integrated Bank Plans",
    "Strategic 10-year bank plan": f"{EW}/Bank Models/Strategic 10-Year Bank Plans",
    "Public investment project appraisal": f"{EW}/Government Models/Public Investment Appraisal",
    "Population projection & service planning": f"{EW}/Government Models/Population & Service Planning",
    "Macroeconomic framework": f"{EW}/Government Models/Macroeconomic Frameworks",
    "Fiscal & debt sustainability": f"{EW}/Government Models/Fiscal & Debt Sustainability",
}
UMBRELLAS = {"Corporate & Industry Models", "Bank Models", "Government Models"}
MODEL_NAMES = [
    ("three-statement model", f"{CM}/Three-Statement Models"),
    ("dcf valuation model", f"{CM}/DCF Valuation"),
    ("lbo model", f"{CM}/LBO"),
    ("operating & fp&a model", f"{CM}/Operating & FP&A"),
    ("industry-specific model", f"{CM}/Industry-Specific Models"),
]
FIN_DOCS = {
    "Earnings Call Transcripts": "03 Earnings Call Transcripts",
    "CIMs, QoE & Diligence Reports": f"{DEALS}/CIMs, QoE & Diligence Reports",
    "Term Sheets, LOIs & NDAs": f"{DEALS}/Term Sheets, LOIs & NDAs",
    "Investment & IC Memos": f"{DEALS}/Investment & IC Memos",
    "Contracts": f"{DEALS}/Contracts",
    "Equity Research & Investment Thesis": "05 Research/Equity Research & Investment Thesis",
    "Industry & Market Research": "05 Research/Industry & Market Research",
    "LP Updates & Investor Letters": "06 Investor Relations/LP Updates & Investor Letters",
    "Financial Transactions": f"{BK}/Financial Transactions",
    "Bookkeeping Records": f"{BK}/Bookkeeping Records",
    "Employee Payroll & Payments": f"{HR}/Payroll & Payments",
    "Jupyter Notebooks": f"{NB}/Finance & Analytics",
}
CONTRACT_KINDS = [("credit agreement", "Credit Agreements"), ("employment agreement", "Employment Agreements"),
                  ("services agreement", "Services Agreements"), ("lease agreement", "Lease Agreements"),
                  ("license agreement", "License Agreements"), ("purchase agreement", "Purchase Agreements"),
                  ("supply agreement", "Supply Agreements")]
FILING_KINDS = [("annual-report", "Annual Reports"), ("quarterly-report", "Quarterly Reports"),
                ("10-k", "Annual Reports"), ("10-q", "Quarterly Reports"),
                ("earnings-release", "Earnings Releases"), ("prospectus", "Prospectuses"),
                ("financial-supplement", "Financial Supplements"), ("exhibit", "Exhibits")]
CO = re.compile(r"CO-[0-9A-F]{6}_")


def label(name):
    """File name without its leading number: '123 - X.pdf' / '123 X.pdf' -> 'X.pdf'."""
    return re.sub(r"^\d+(?: -)? ", "", name)


def contract_dir(name):
    low = label(name).lower()
    for k, d in CONTRACT_KINDS:
        if low.startswith(k):
            return f"{DEALS}/Contracts/{d}"
    return f"{DEALS}/Contracts/Other Contracts"


def by_label(name):
    """Classify a financial document by its label (used for the loose root Folder N copies)."""
    low = label(name).lower()
    if low.startswith("earnings call transcript"):
        return "03 Earnings Call Transcripts"
    if "agreement" in low.split(" - ")[0] or low.startswith("contract"):
        return contract_dir(name)
    if re.match(r"(quality of earnings|due diligence|diligence|special committee|board presentation"
                r"|fairness|confidential information|cim\b)", low):
        return f"{DEALS}/CIMs, QoE & Diligence Reports"
    if re.match(r"(term sheet|letter of intent|non-disclosure|nda\b|loi\b)", low):
        return f"{DEALS}/Term Sheets, LOIs & NDAs"
    if "memo" in low.split(" - ")[0]:
        return f"{DEALS}/Investment & IC Memos"
    if re.match(r"(lp update|investor letter|shareholder letter|letter to)", low):
        return "06 Investor Relations/LP Updates & Investor Letters"
    if "research" in low.split(" - ")[0]:
        return "05 Research/Industry & Market Research"
    return None


def notebook_dir(name):
    m = re.match(r"research notebook - (.+)\.ipynb$", label(name), re.I)
    if m:
        return f"{NB}/STEM Research/{m.group(1).strip().capitalize()}"
    return f"{NB}/Finance & Analytics"


def spreadsheet_dir(name):
    low = label(name).lower()
    for k, d in MODEL_NAMES:
        if low.startswith(k):
            return d
    if CO.search(name) and "financial-statements" in low:
        return f"{CF}/Financial Statements (Excel)/" + ("Annual (10-K)" if "-10k" in low else "Quarterly (10-Q)")
    if CO.search(name):
        return f"{CF}/Financial Data Workbooks (Excel)"
    if "payroll" in low:
        return f"{HR}/Payroll Records"
    if "maruti, kelvin" in low:
        return f"{ARC}/Takeout Documents"
    if low.startswith("untitled"):
        return f"{ARC}/Miscellaneous"
    return f"{CM}/Other Models"


def docx_dir(name):
    low = name.lower()
    if CO.search(name):
        for k, d in FILING_KINDS:
            if k in low:
                return f"{CF}/{d}"
        return f"{CF}/Other Filings"
    if "employment agreement" in low:
        return f"{HR}/Employment Agreements"
    if "onboarding" in low:
        return f"{HR}/Onboarding Guides"
    if "maruti" in low:
        return f"{ARC}/Takeout Documents"
    return f"{ARC}/Miscellaneous"


KNOWN_BAD = {("12 - DCF Valuation - Computer Programming FY24 - AE1EB2.xlsx", 65536)}
BATCH_DIR = re.compile(r"\d{5}-\d{5}")
ENT_CODE = re.compile(r" - [0-9A-F]{6}(?: \(\d+\))?\.xls[xm]$")
OLD_GROUPS = {"Banking": "Bank Models", "Public Sector": "Government Models"}


def refile_model(coll, name):
    """Second-layout move: enterprise models (coded names) into Enterprise Wide Models, others into Corporate Models."""
    parts = coll.split("/")
    if parts[1:] == ["Other Models"]:
        return f"{CM}/Other Models"
    if len(parts) < 3 or parts[1] in ("Enterprise Wide Models", "Corporate Models"):
        return coll
    group, kind = parts[1], parts[2]
    if group in OLD_GROUPS:
        return f"{EW}/{OLD_GROUPS[group]}/{kind}"
    if kind == "IR Operating Models":
        return f"{EW}/IR-Enhanced Operating Models"
    if ENT_CODE.search(name):
        return f"{EW}/Corporate & Industry Models/{kind}"
    return f"{CM}/{kind}"


def classify(path):
    """Library folder for a server path, 'DELETE' for junk, None to leave it where it is."""
    parts = path.split("/")
    name, top = parts[-1], parts[0]
    ext = os.path.splitext(name)[1].lower()
    if top == "11 Software Repositories":   # renamed section
        return "/".join([GIT] + [p for p in parts[1:-1] if not BATCH_DIR.fullmatch(p)])
    if top in SECTIONS:                  # already arranged: re-file models, keep the rest in place
        coll = "/".join(p for p in parts[:-1] if not BATCH_DIR.fullmatch(p))
        if coll == f"{HR}/Onboarding Guides/Drive":
            return f"{HR}/Onboarding Guides"
        return refile_model(coll, name) if top == M else coll
    if top == "_speedtest" or ext == ".partial":
        return "DELETE"
    if top == "Repo Import" and len(parts) == 2:   # repository zips staged by sftp-export
        parts = parts[1:]
    if len(parts) == 1:                  # loose files at the root
        base = re.sub(r"\.zip$", "", re.sub(r"^(Elsavado|LittleGamesIncorporated) - ", "", name))
        if base in TOPICS:
            return f"{GIT}/{TOPICS[base]}"
        return f"{ARC}/Bundles & Exports"
    sub = parts[1] if len(parts) > 2 else ""
    if top == "Valuation (DCF)":
        if sub == "_zips":
            return None                  # being unpacked
        if sub.startswith("Folder ") and "(Models" in sub:
            return ENTERPRISE[top]
    elif top in ENTERPRISE:
        return ENTERPRISE[top]
    if top in UMBRELLAS and sub in ENTERPRISE:
        return ENTERPRISE[sub]
    if top == "Financial Documents" and sub in FIN_DOCS:
        return contract_dir(name) if sub == "Contracts" else FIN_DOCS[sub]
    if top.startswith("Folder ") and "(Documents" in top:
        return by_label(name) or f"{ARC}/Unsorted Documents"
    if top == "Figma Designs":
        return "10 Design Assets/Figma Designs"
    if top in ("Integro_Employment_Agreements",):
        return f"{HR}/Employment Agreements"
    if top == "IR_Transcripts_Onboarding_Guides":
        return f"{HR}/Onboarding Guides"
    if top == "Jupyter Notebooks (STEM)" or ext == ".ipynb":
        return notebook_dir(name)
    if top in ("My Drive", "Excel Models - private") or top.endswith(" - private") or name == "state.json.gz":
        return f"{ARC}/Admin"
    if ext in (".xlsx", ".xlsm", ".xls"):
        return spreadsheet_dir(name)
    if ext == ".docx":
        return f"{ARC}/Takeout Documents" if "Takeout" in parts[:-1] else docx_dir(name)
    return f"{ARC}/Unsorted"


def num_key(name):
    m = re.match(r"^(\d+)", name)
    return (int(m.group(1)) if m else 10**12, name.lower())


def plan(inv_path, out_path):
    files, dirs = [], []
    with open(inv_path, encoding="utf-8") as fh:
        for line in fh:
            size, path = line.rstrip("\n").split("\t", 1)
            (dirs if path.endswith("/") else files).append((path, int(size or 0)))
    seen, moves, deletes, kept, report = {}, [], [], collections.defaultdict(list), collections.Counter()
    # The Workspace copy of "Excel Models" (renumbered 25666-34689, "<n> <label>") repeats the
    # IR Transcripts Excel Models ("<n> - <label>"); drop a copy only when label AND size match.
    excel_models = set()
    for path, size in files:
        m = re.match(r"^\d+ - (.+)$", posixpath.basename(path))
        if path.startswith(M + "/") and m and not ENT_CODE.search(m.group(1)):
            excel_models.add((m.group(1), size))
    for path, size in sorted(files, key=lambda f: (classify(f[0]) or "~", f[0])):
        dest = classify(path)
        name = posixpath.basename(path)
        m = re.match(r"^(\d+) (?!- )(.+)$", name)
        if (dest and path.startswith(M + "/") and m and 25666 <= int(m.group(1)) <= 34689
                and (m.group(2), size) in excel_models):
            deletes.append(path); report["deleted (Workspace copy of an Excel Models file)"] += 1
            continue
        if (name, size) in KNOWN_BAD:
            deletes.append(path); report["deleted (truncated upload)"] += 1
            continue
        if dest is None:
            report["left in place"] += 1
            continue
        if dest == "DELETE":
            deletes.append(path); report["deleted (junk/partial)"] += 1
            continue
        key = (name, size)
        if key in seen:
            deletes.append(path); report["deleted (exact duplicate)"] += 1
            continue
        seen[key] = path
        fixed = re.sub(r" \(2\)(\.\w+)$", r"\1", name)
        if fixed != name and any(fixed == bad for bad, _ in KNOWN_BAD):
            name = fixed                 # the full copy takes the name of the truncated one
        kept[dest].append((name, size, path))
    for dest, items in kept.items():
        items.sort(key=lambda i: num_key(i[0]))
        names = collections.Counter()
        for i, (name, size, path) in enumerate(items):
            names[name.lower()] += 1
            if names[name.lower()] > 1:
                stem, ext = os.path.splitext(name)
                name = f"{stem} ({names[name.lower()]}){ext}"
                report["renamed (same name, different file)"] += 1
            folder = dest
            if len(items) > BATCH:
                lo = i // BATCH * BATCH + 1
                folder = f"{dest}/{lo:05d}-{min(lo + BATCH - 1, len(items)):05d}"
            target = f"{folder}/{name}"
            if target != path:
                moves.append((path, target))
            report[f"files in {dest.split('/')[0]}"] += 1
    leaves = {d: len(v) for d, v in sorted(kept.items())}
    json.dump({"moves": moves, "deletes": deletes, "dirs": [d for d, _ in dirs], "leaves": leaves,
               "report": dict(report)}, open(out_path, "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps(dict(sorted(report.items())), indent=1, ensure_ascii=False))
    print(f"moves {len(moves)}  deletes {len(deletes)}")
    for d, n in leaves.items():
        print(f"  {n:7d}  {d}")


# ---------------------------------------------------------------- apply (paramiko, many sessions)

def connect():
    import paramiko
    key = paramiko.PKey.from_path(os.environ["SFTP_KEY_FILE"])
    t = paramiko.Transport((os.environ["SFTP_HOST"], 22))
    t.connect(username=os.environ["SFTP_USER"], pkey=key)
    return paramiko.SFTPClient.from_transport(t)


def apply(plan_path, workers=24):
    p = json.load(open(plan_path, encoding="utf-8"))
    made, lock = set(), threading.Lock()
    stats = collections.Counter()
    errors = []

    def mkdirs(sftp, d):
        parts = d.strip("/").split("/")
        for i in range(1, len(parts) + 1):
            sub = "/" + "/".join(parts[:i])
            with lock:
                if sub in made:
                    continue
            try:
                sftp.mkdir(sub)
            except IOError:
                pass
            with lock:
                made.add(sub)

    def run(jobs, fn, label):
        q = list(jobs)
        idx = [0]

        def worker():
            sftp = connect()
            while True:
                with lock:
                    if idx[0] >= len(q):
                        break
                    job = q[idx[0]]; idx[0] += 1
                for attempt in range(4):
                    try:
                        fn(sftp, job); stats[label] += 1
                        break
                    except Exception as e:  # reconnect and retry
                        if attempt == 3:
                            with lock:
                                errors.append((label, job, repr(e)))
                        else:
                            time.sleep(2 * (attempt + 1))
                            try:
                                sftp = connect()
                            except Exception:
                                pass
            sftp.close()

        ts = [threading.Thread(target=worker) for _ in range(workers)]
        [t.start() for t in ts]
        while any(t.is_alive() for t in ts):
            time.sleep(30)
            print(f"{label}: {stats[label]}/{len(q)}  errors {len(errors)}", flush=True)
        [t.join() for t in ts]

    def move(sftp, job):
        src, dst = job
        mkdirs(sftp, posixpath.dirname("/" + dst))
        sftp.rename("/" + src, "/" + dst)

    def delete(sftp, path):
        sftp.remove("/" + path)

    run(p["moves"], move, "moved")
    run(p["deletes"], delete, "deleted")
    # remove folders left empty, deepest first
    sftp = connect()
    for d in sorted(p["dirs"], key=lambda d: d.count("/"), reverse=True):
        if d.split("/")[0] in SECTIONS or d.startswith("Valuation (DCF)/_zips"):
            continue
        try:
            sftp.rmdir("/" + d.rstrip("/")); stats["empty folders removed"] += 1
        except IOError:
            pass
    print(json.dumps(dict(stats), indent=1))
    json.dump(errors, open("errors.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"errors: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    if sys.argv[1] == "plan":
        plan(sys.argv[2], sys.argv[3])
    else:
        sys.exit(apply(sys.argv[2]))
