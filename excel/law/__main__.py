"""LAW collector (user 2026-11-08): complete court cases, traced from the first filing to the final decision, into the
IR Transcripts shared drive, folder "LAW".

Sources (public court records, US government works):
  scotus  US Supreme Court argued cases, October Term 2017 onward (electronic dockets): every docket filing PDF in
          order (petition, briefs in opposition, amicus, merits briefs, motions, orders), the oral argument
          transcript and audio, the opinion of the Court, plus a case timeline and the docket.
  icj     International Court of Justice contentious and advisory cases, closed ones only: application, written and
          oral proceedings, orders, judgments (English or bilingual editions).
  sec     SEC closed litigated administrative proceedings: order instituting proceedings, briefs, initial decision,
          Commission opinion, finality order.
  recap   Closed US federal court cases from the RECAP archive (Free Law Project, mirrored on the Internet Archive)
          whose documents are nearly all present from the complaint/indictment to the judgment.

Layout:
  LAW/01 US Supreme Court/October Term <yyyy>/<docket> <case name>/
  LAW/02 US District Courts/<Civil|Criminal>/<nature of suit>/<case name> (<docket>, <court>)/
  LAW/03 US Bankruptcy Courts/<court>/<case name> (<docket>)/        business debtors only
  LAW/04 US Courts of Appeals/<circuit>/<case name> (<docket>)/
  LAW/05 Other Federal Courts/<court>/<case name> (<docket>)/
  LAW/06 International Court of Justice/<no> <case>/<01 Institution of Proceedings .. 10 Summaries>/
  LAW/07 SEC Administrative Proceedings/<year>/<file no> <respondents>/
  LAW/09 Permanent Court of Arbitration/<case type>/<case no> <case>/
  LAW/08 Enron Cases/<US Supreme Court|SEC Enforcement|US District Courts|US Bankruptcy Courts|...>/<case>/
Each case folder: "00 Case Timeline.pdf" (every docket entry with its date and file), "00 Docket.json", then the
documents numbered in docket order ("0001 2019-03-02 Complaint.pdf", attachments "0001-01 Exhibit A.pdf").

State: "LAW - private/state-<job>.json". Uploads only with --live.
"""
import argparse, concurrent.futures as cf, html, json, os, re, shutil, subprocess, sys, tempfile, time, zlib
import xml.etree.ElementTree as ET

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
S = requests.Session()
S.headers["User-Agent"] = UA
SC = "https://www.supremecourt.gov"
IA = "https://archive.org"
T0 = time.time()
# Top folder for new uploads (user 2026-11-09: new cases go to a new folder, nothing more added to "LAW").
# The done-state stays in "LAW - private", so cases already in "LAW" are not uploaded again.
ROOT = os.environ.get("LAW_ROOT") or "LAW"

STATES = {"al": "Alabama", "ak": "Alaska", "az": "Arizona", "ar": "Arkansas", "ca": "California", "co": "Colorado",
          "ct": "Connecticut", "de": "Delaware", "dc": "District of Columbia", "fl": "Florida", "ga": "Georgia",
          "hi": "Hawaii", "id": "Idaho", "il": "Illinois", "in": "Indiana", "ia": "Iowa", "ks": "Kansas",
          "ky": "Kentucky", "la": "Louisiana", "me": "Maine", "md": "Maryland", "ma": "Massachusetts",
          "mi": "Michigan", "mn": "Minnesota", "ms": "Mississippi", "mo": "Missouri", "mt": "Montana",
          "ne": "Nebraska", "nv": "Nevada", "nh": "New Hampshire", "nj": "New Jersey", "nm": "New Mexico",
          "ny": "New York", "nc": "North Carolina", "nd": "North Dakota", "oh": "Ohio", "ok": "Oklahoma",
          "or": "Oregon", "pa": "Pennsylvania", "ri": "Rhode Island", "sc": "South Carolina", "sd": "South Dakota",
          "tn": "Tennessee", "tx": "Texas", "ut": "Utah", "vt": "Vermont", "va": "Virginia", "wa": "Washington",
          "wv": "West Virginia", "wi": "Wisconsin", "wy": "Wyoming", "pr": "Puerto Rico", "gu": "Guam",
          "vi": "Virgin Islands", "nmi": "Northern Mariana Islands"}
SIDE = {"n": "Northern", "s": "Southern", "e": "Eastern", "w": "Western", "m": "Middle", "c": "Central"}
CIRCUITS = {f"ca{i}": f"{n} Circuit" for i, n in enumerate(
    ["", "First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth", "Eleventh"])
    if i}
CIRCUITS.update({"cadc": "D.C. Circuit", "cafc": "Federal Circuit"})
OTHER = {"cit": "Court of International Trade", "uscfc": "Court of Federal Claims", "jpml": "Judicial Panel on "
         "Multidistrict Litigation", "cavc": "Court of Appeals for Veterans Claims", "fisc": "Foreign Intelligence "
         "Surveillance Court"}
BUSINESS = re.compile(r"\b(inc|llc|l\.l\.c|corp|corporation|company|co\.|ltd|limited|lp|l\.p|llp|holdings?|bank|"
                      r"group|partners|partnership|trust|fund|capital|industries|enterprises|association|authority|"
                      r"city of|county|hospital|university|church|diocese)\b", re.I)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def left(minutes):
    return minutes * 60 - (time.time() - T0)


def clean(s, n=90):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if len(s) > n:
        s = s[:n].rsplit(" ", 1)[0].rstrip(" ,;.-")
    return s or "Document"


def get(url, tries=4, **kw):
    for i in range(tries):
        try:
            r = S.get(url, timeout=kw.pop("timeout", 60), **kw)
            if r.status_code == 200:
                return r
            if r.status_code in (404, 410, 403):
                return None
        except requests.RequestException:
            pass
        time.sleep(2 + 3 * i)
    return None


def fetch(url, path):
    for i in range(4):
        try:
            with S.get(url, timeout=120, stream=True) as r:
                if r.status_code != 200:
                    if r.status_code in (403, 404, 410):
                        return False
                    raise requests.RequestException(r.status_code)
                with open(path, "wb") as f:
                    for c in r.iter_content(1 << 20):
                        f.write(c)
            return os.path.getsize(path) > 0
        except (requests.RequestException, OSError):
            time.sleep(3 + 4 * i)
    return False


# ---------------------------------------------------------------- drive

class Drive:
    def __init__(self, remote, job, live):
        self.remote, self.job, self.live = remote, job, live
        self.last_dest = None
        self.state_path = f"{remote.split(':')[0]}:LAW - private/state-{job}.json"
        self.local_state = os.path.join(tempfile.gettempdir(), f"law-state-{job}.json")
        self.state = {}
        try:
            r = subprocess.run(["rclone", "cat", self.state_path], capture_output=True, text=True)
        except FileNotFoundError:
            r = None
        if r and r.returncode == 0 and r.stdout.strip():
            self.state = json.loads(r.stdout)
        self.state.setdefault("done", [])
        self.state.setdefault("skip", [])
        self.state.setdefault("files", 0)
        self.done = set(self.state["done"])
        self.skip = set(self.state["skip"])

    def save(self):
        self.state["done"], self.state["skip"] = sorted(self.done), sorted(self.skip)
        with open(self.local_state, "w") as f:
            json.dump(self.state, f)
        if self.live:
            subprocess.run(["rclone", "copyto", self.local_state, self.state_path, "-q"], check=False)

    def upload(self, folder, dest, people=(), orgs=None, second_pass=False):
        if os.environ.get("LAW_REDACT") == "true":
            # user 2026-11-09: every upload redacted (names, contacts, case numbers; dates moved per case)
            import matters.__main__ as M
            if not orgs and not people:
                people, orgs = M.case_parties(dest.rsplit("/", 1)[-1])
            if "Enron" in dest:
                orgs = dict(orgs or {}, **{"Enron Corp.": "Energy Company", "Enron Corp": "Energy Company",
                                           "Enron": "Energy Company", "Arthur Andersen LLP": "Audit Firm",
                                           "Arthur Andersen": "Audit Firm", "Andersen": "Audit Firm"})
            red = M.redact_folder(folder, dest, people, orgs, shift=not second_pass)
            if not second_pass:  # a second pass keeps the folder's (already redacted) name and dates
                dest = M.redact_dest(dest, red)
        self.last_dest = dest
        n = sum(len(f) for _, _, f in os.walk(folder))
        if not n:
            return False
        if not self.live:
            log(f"  dry run: {n} files -> {dest}")
            return True
        r = subprocess.run(["rclone", "copy", folder, f"{self.remote}{dest}", "--transfers", "8", "--checkers", "8",
                            "--drive-chunk-size", "64M", "--retries", "5", "--low-level-retries", "20", "-q"])
        if r.returncode == 0:
            self.state["files"] += n
        return r.returncode == 0


# ---------------------------------------------------------------- timeline

def timeline_pdf(path, title, facts, rows):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    ss = getSampleStyleSheet()
    small = ss["BodyText"].clone("small", fontSize=8, leading=10)
    esc = lambda s: html.escape(str(s or ""))
    story = [Paragraph(esc(title), ss["Title"])]
    for k, v in facts:
        if v:
            story.append(Paragraph(f"<b>{esc(k)}:</b> {esc(v)}", small))
    story.append(Spacer(1, 10))
    from reportlab.platypus.doctemplate import LayoutError
    # very long docket entries (or unbroken strings) can make one row taller than a page: retry shorter
    cut = lambda s, n: re.sub(r"(\S{60})", r"\1 ", str(s or ""))[:n]
    for limit in (3000, 1200, 300):
        data = [[Paragraph(f"<b>{h}</b>", small) for h in ("No.", "Date", "Docket entry", "File")]]
        for no, date, text, fname in rows:
            data.append([Paragraph(esc(no), small), Paragraph(esc(date), small),
                         Paragraph(esc(cut(text, limit)), small), Paragraph(esc(cut(fname, 300)), small)])
        t = Table(data, colWidths=[40, 62, 430, 190], repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8"))]))
        try:
            SimpleDocTemplate(path, pagesize=landscape(letter), leftMargin=30, rightMargin=30, topMargin=30,
                              bottomMargin=30, title=title).build(story + [t])
            return
        except LayoutError:
            continue
    log(f"  timeline too large, skipped: {title[:80]}")


def download_all(jobs, folder, threads=8):
    """jobs: [(url, filename)] -> number fetched; failed ones are removed from the folder."""
    ok = 0
    with cf.ThreadPoolExecutor(threads) as ex:
        futs = {ex.submit(fetch, u, os.path.join(folder, n)): n for u, n in jobs}
        for f in cf.as_completed(futs):
            if f.result():
                ok += 1
            else:
                try:
                    os.remove(os.path.join(folder, futs[f]))
                except OSError:
                    pass
    return ok


# ---------------------------------------------------------------- Supreme Court

def scotus_cases(term):
    """Argued cases of one October Term: [(docket, name, transcript url)]."""
    r = get(f"{SC}/oral_arguments/argument_transcript/{term}")
    out, seen = [], set()
    if not r:
        return out
    for m in re.finditer(r"href='\.\./argument_transcripts/(\d{4})/([^']+\.pdf)'[^>]*>([^<]+)</a></span>\s*"
                         r"<span[^>]*>([^<]+)</span>", r.text):
        yr, pdf, docket, name = m.groups()
        docket = docket.strip()
        if docket in seen:
            continue
        seen.add(docket)
        out.append((docket, html.unescape(name).strip(), f"{SC}/oral_arguments/argument_transcripts/{yr}/{pdf}"))
    return out


def scotus_opinions(term):
    r = get(f"{SC}/opinions/slipopinion/{term % 100:02d}")
    ops = {}
    if r:
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S):
            link = re.search(r"href='(/opinions/\d+pdf/[^']+\.pdf)'", row)
            if not link:
                continue
            for d in re.findall(r">\s*(\d{2}A?-\d+)\s*<", row):
                ops.setdefault(d, SC + link.group(1))
    return ops


def scotus(drive, minutes, lane):
    k, n = lane
    terms = [t for t in range(2017, time.gmtime().tm_year + 1) if t % n == k]
    for term in terms:
        ops = scotus_opinions(term)
        cases = scotus_cases(term)
        log(f"OT{term}: {len(cases)} argued cases, {len(ops)} opinions")
        for docket, name, transcript in cases:
            if left(minutes) < 900:
                return
            key = f"scotus:{docket}"
            if key in drive.done:
                continue
            r = get(f"{SC}/RSS/Cases/JSON/{docket}.json")
            if not r:
                continue
            try:
                d = r.json()
            except ValueError:
                continue
            procs = d.get("ProceedingsandOrder") or []
            text = " ".join(p.get("Text", "") for p in procs)
            link = re.search(r"href\s*=\s*['\"]([^'\"]+/opinions/[^'\"]+\.pdf)", text)
            opinion = ops.get(docket) or (link.group(1) if link else None)
            if opinion and opinion.startswith("/"):
                opinion = SC + opinion
            finished = re.search(r"JUDGMENT ISSUED|Adjudged to be|DISMISSED|Certified copy", text, re.I)
            if not finished:
                log(f"  {docket} not finished yet")
                continue
            folder = tempfile.mkdtemp(prefix="scotus-")
            jobs, rows = [], []
            for i, p in enumerate(procs, 1):
                date = p.get("Date", "")
                try:
                    iso = time.strftime("%Y-%m-%d", time.strptime(date, "%b %d %Y"))
                except ValueError:
                    iso = date
                links = p.get("Links") or []
                names = []
                for j, l in enumerate(links, 1):
                    url = l.get("DocumentUrl", "")
                    if not url.lower().endswith(".pdf"):
                        continue
                    sub = f"-{j}" if len(links) > 1 else ""
                    fn = f"{i:03d}{sub} {iso} {clean(l.get('Description') or l.get('File'), 70)}.pdf"
                    jobs.append((url, fn))
                    names.append(fn)
                rows.append((i, iso, re.sub(r"<[^>]+>", "", p.get("Text", "")), "; ".join(names)))
            if d.get("QPLink"):
                jobs.append((SC + "/" + d["QPLink"].lstrip("./").replace("../", ""), "000 Questions Presented.pdf"))
            jobs.append((transcript, "900 Oral Argument Transcript.pdf"))
            jobs.append((f"{SC}/media/audio/mp3files/{docket}.mp3", "901 Oral Argument Audio.mp3"))
            if opinion:
                jobs.append((opinion, "999 Opinion of the Court.pdf"))
            got = download_all(jobs, folder)
            title = f"{docket} {name}"
            facts = [("Court", "Supreme Court of the United States"), ("Term", f"October Term {term}"),
                     ("Petitioner", d.get("PetitionerTitle")), ("Respondent", d.get("RespondentTitle")),
                     ("Docketed", d.get("DocketedDate")), ("Lower court", d.get("LowerCourt")),
                     ("Lower court case numbers", d.get("LowerCourtCaseNumbers")),
                     ("Lower court decision", d.get("LowerCourtDecision")),
                     ("Files in this folder", f"{got} documents plus this timeline and the docket")]
            rows += [("", "", "Oral argument transcript", "900 Oral Argument Transcript.pdf"),
                     ("", "", "Oral argument audio", "901 Oral Argument Audio.mp3"),
                     ("", "", "Opinion of the Court", "999 Opinion of the Court.pdf")]
            timeline_pdf(os.path.join(folder, "00 Case Timeline.pdf"), title, facts, rows)
            with open(os.path.join(folder, "00 Docket.json"), "w", encoding="utf-8") as f:
                json.dump(d, f, indent=1)
            dest = f"{ROOT}/01 US Supreme Court/October Term {term}/{clean(title, 120)}"
            if got >= 3 and drive.upload(folder, dest):
                drive.done.add(key)
                log(f"  {docket}: {got} files")
                drive.save()
            shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- RECAP (federal courts)

def court_place(court, docket, name, nos):
    c = court.lower()
    case = clean(name, 110)
    docket = (docket or "").replace(":", "-")
    if c in CIRCUITS:
        return f"04 US Courts of Appeals/{CIRCUITS[c]}/{case} ({clean(docket, 30)})"
    if c in OTHER:
        return f"05 Other Federal Courts/{OTHER[c]}/{case} ({clean(docket, 30)})"
    m = re.fullmatch(r"(nmi|[a-z]{2})([nsewmc]?)(d|b)", c)
    if not m:
        return f"05 Other Federal Courts/{c.upper()}/{case} ({clean(docket, 30)})"
    st, side, kind = m.groups()
    place = (f"{SIDE[side]} District of " if side else "District of ") + STATES.get(st, st.upper())
    if kind == "b":
        return f"03 US Bankruptcy Courts/Bankruptcy Court, {place}/{case} ({clean(docket, 30)})"
    crim = bool(re.search(r"-(cr|mj|po)-", docket))
    if crim:
        return f"02 US District Courts/Criminal/{place}/{case} ({clean(docket, 30)})"
    label = re.sub(r"^\d+\s*", "", nos or "").replace(":", " -").strip() or "Other Civil"
    return f"02 US District Courts/Civil/{clean(label, 60)}/{case} ({clean(docket, 30)}, {place})"


def parse_docket(ident, files):
    """The fuller of the JSON and XML dockets (the archive's copies are often partial)."""
    names = {f["name"] for f in files}
    got = [d for d in (_docket(ident, names, "json"), _docket(ident, names, "xml")) if d]
    if not got:
        return None
    best = max(got, key=lambda d: len(d["entries"]))
    for d in got:  # fill case facts the fuller one lacks
        for k, v in d.items():
            if v and not best.get(k):
                best[k] = v
    return best


def _docket(ident, names, kind):
    """-> dict(case_name, docket, court, filed, terminated, nos, entries=[(no, date, text, [(doc, att, desc)])])."""
    base = ident
    if kind == "json" and f"{base}.docket.json" in names:
        r = get(f"{IA}/download/{ident}/{base}.docket.json", timeout=120)
        if not r:
            return None
        try:
            d = r.json()
        except ValueError:
            return None
        ents = []
        for e in d.get("docket_entries") or []:
            docs = [(str(x.get("document_number") or e.get("entry_number") or ""), int(x.get("attachment_number")
                     or 0), x.get("description") or "") for x in e.get("recap_documents") or []]
            ents.append((e.get("entry_number"), e.get("date_filed") or "", e.get("description") or "", docs))
        return dict(case_name=d.get("case_name") or d.get("case_name_full"), docket=d.get("docket_number") or "",
                    court=d.get("court") or "", filed=d.get("date_filed"), terminated=d.get("date_terminated"),
                    nos=d.get("nature_of_suit") or "", cause=d.get("cause") or "", judge=d.get("assigned_to_str"),
                    entries=ents, raw=d)
    if kind == "xml" and f"{base}.docket.xml" in names:
        r = get(f"{IA}/download/{ident}/{base}.docket.xml", timeout=120)
        if not r:
            return None
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            return None
        g = lambda p: (root.findtext(p) or "").strip()
        by = {}
        for doc in root.iter("document"):
            no = (doc.findtext("doc_num") or "").strip()
            att = int((doc.findtext("attachment_num") or "0").strip() or 0)
            e = by.setdefault(no, [no, (doc.findtext("date_filed") or "").strip(), "", []])
            desc = (doc.findtext("long_desc") or doc.findtext("short_desc") or "").strip()
            if att == 0 and desc:
                e[2] = desc
            e[3].append((no, att, (doc.findtext("short_desc") or desc or "").strip()))
        ents = sorted(by.values(), key=lambda e: int(e[0]) if e[0].isdigit() else 10 ** 9)
        return dict(case_name=g("case_details/case_name"), docket=g("case_details/docket_num"),
                    court=g("case_details/court"), filed=g("case_details/date_case_filed"),
                    terminated=g("case_details/date_case_terminated"), nos=g("case_details/nature_of_suit"),
                    cause=g("case_details/case_cause"), judge=g("case_details/assigned_to"),
                    entries=[tuple(e) for e in ents], raw=None, xml=r.text)
    return None


def recap_case(drive, ident, meta, topic=None):
    """topic: (regex, folder) - keep every case whose name or parties match, complete or not."""
    files = (meta or {}).get("files") or []
    pdfs = {}
    pre = ident + "."
    for f in files:
        m = re.fullmatch(re.escape(pre) + r"(\d+)\.(\d+)\.pdf", f["name"])
        if m:
            pdfs[(m.group(1), int(m.group(2)))] = (f["name"], int(f.get("size") or 0))
    mains = {d for d, a in pdfs if a == 0}
    if not topic and (len(mains) < 12 or "1" not in mains):
        return "few"
    d = parse_docket(ident, files)
    if not d or not d["entries"]:
        return "nodocket"
    terminated = d.get("terminated") or (meta.get("metadata") or {}).get("date-case-terminated")
    if topic:
        who = (d["case_name"] or "") + " " + json.dumps((d.get("raw") or {}).get("parties") or "") + (d.get("xml") or "")[:20000]
        if not mains or not re.search(topic[0], who, re.I):
            return "offtopic"
    elif not terminated:
        return "open"
    court = d["court"] or ident.split(".")[2]
    if not topic and re.search(ENRON_WHO, d["case_name"] or "", re.I):
        return "enron"  # kept by the enron job in 08 Enron Cases
    if not topic and re.fullmatch(r"[a-z]{2,3}[nsewmc]?b", court) and not BUSINESS.search(d["case_name"] or ""):
        return "personal"
    numbered = [int(e[0]) for e in d["entries"] if str(e[0] or "").isdigit()]
    top = max(int(m) for m in mains if m.isdigit())
    last = max(numbered + [top])
    # a docket number without a PDF is often a text-only order, so half the numbers carrying a document is complete
    if not topic and (len(mains) / last < 0.5 or top < 0.85 * last):
        return "incomplete"
    known = {str(e[0]) for e in d["entries"]}
    for dn in sorted(mains - known, key=lambda x: int(x) if x.isdigit() else 0):  # documents missing from the docket
        d["entries"].append((dn, "", "", [(dn, 0, "")]))
    for (dn, att) in pdfs:
        for e in d["entries"]:
            if str(e[0]) == dn and att and (dn, att) not in {(str(x[0]), x[1]) for x in e[3]}:
                e[3].append((dn, att, ""))
    d["entries"].sort(key=lambda e: int(e[0]) if str(e[0]).isdigit() else 10 ** 9)
    with_doc = mains
    total = sum(s for _, s in pdfs.values())
    if total > 2.5e9 or len(pdfs) > 3000:
        return "huge"
    folder = tempfile.mkdtemp(prefix="recap-")
    jobs, rows, used = [], [], set()
    for no, date, text, docs in d["entries"]:
        names = []
        for dn, att, desc in sorted(set(docs), key=lambda x: x[1]):
            if (str(dn), att) not in pdfs or (str(dn), att) in used:
                continue
            used.add((str(dn), att))
            label = clean(desc or (text if att == 0 else f"Attachment {att}") or f"Document {dn}", 70)
            num = f"{int(dn):04d}" if str(dn).isdigit() else clean(str(dn), 10)
            fn = f"{num}{'-%02d' % att if att else ''} {date[:10]} {label}.pdf"
            jobs.append((f"{IA}/download/{ident}/{pdfs[(str(dn), att)][0]}", fn))
            names.append(fn)
        rows.append((no or "", (date or "")[:10], text, "; ".join(names)))
    got = download_all(jobs, folder)
    title = f"{d['case_name']} ({d['docket']})"
    place = court_place(court, d["docket"], d["case_name"] or ident, d["nos"])
    if topic:
        place = topic[1] + "/" + place.split("/", 1)[0][3:] + "/" + place.rsplit("/", 1)[1]
    facts = [("Court", place.split("/")[-2] if "/" in place else court), ("Docket number", d["docket"]),
             ("Filed", d["filed"]), ("Terminated", terminated), ("Nature of suit", d["nos"]), ("Cause", d["cause"]),
             ("Assigned to", d["judge"]),
             ("Documents", f"{got} of {len(with_doc)} docket documents (with attachments) in this folder"),
             ("Source", "PACER via the RECAP archive (Free Law Project), US government public court records")]
    timeline_pdf(os.path.join(folder, "00 Case Timeline.pdf"), title, facts, rows)
    if d.get("raw") is not None:
        with open(os.path.join(folder, "00 Docket.json"), "w", encoding="utf-8") as f:
            json.dump(d["raw"], f, indent=1)
    elif d.get("xml"):
        with open(os.path.join(folder, "00 Docket.xml"), "w", encoding="utf-8") as f:
            f.write(d["xml"])
    lp = {}
    if os.environ.get("LAW_REDACT") == "true":  # the docket's parties, attorneys and judge are redacted too
        import matters.__main__ as M
        lp = dict(zip(("people", "orgs"), M.lit_parties(d)))
    ok = got >= (1 if topic else 12) and drive.upload(folder, f"{ROOT}/" + place, **lp)
    shutil.rmtree(folder, ignore_errors=True)
    return f"ok {got}" if ok else "failed"


def recap(drive, minutes, lane, max_files):
    k, n = lane
    st = drive.state
    q = ("collection:usfederalcourts AND mediatype:texts AND item_size:[15000000 TO 3000000000]")
    stats = st.setdefault("stats", {})
    while left(minutes) > 900:
        if max_files and st["files"] >= max_files:
            log(f"file cap {max_files} reached")
            return
        params = {"q": q, "fields": "identifier", "count": 1000}
        if st.get("cursor"):
            params["cursor"] = st["cursor"]
        r = get(f"{IA}/services/search/v1/scrape", params=params, timeout=120)
        if not r:
            time.sleep(30)
            continue
        page = r.json()
        idents = [x["identifier"] for x in page.get("items", []) if x["identifier"].startswith("gov.uscourts.")
                  and zlib.crc32(x["identifier"].encode()) % n == k]
        idents = [i for i in idents if i not in drive.done and i not in drive.skip]
        log(f"page: {len(idents)} candidates (lane {k}/{n}); uploaded so far {st['files']} files, "
            f"{len(drive.done)} cases")
        for ident in idents:
            if left(minutes) < 900:
                drive.save()
                return
            r = get(f"{IA}/metadata/{ident}", timeout=120)
            res = recap_case(drive, ident, r.json() if r else None) if r else "nometa"
            key = res.split()[0]
            stats[key] = stats.get(key, 0) + 1
            if res.startswith("ok"):
                drive.done.add(ident)
                log(f"  case {len(drive.done)}: {res.split()[1]} documents")
                drive.save()
            elif res not in ("failed", "nometa", "open"):
                drive.skip.add(ident)
        nxt = page.get("cursor")
        if not nxt:
            st["cursor"] = None
            st["passes"] = st.get("passes", 0) + 1
            drive.save()
            log("reached the end of the archive listing; starting over for newly added cases")
            if st["passes"] > 3:
                return
            continue
        st["cursor"] = nxt
        drive.save()
        log(f"checked: {json.dumps(stats)}")


# ---------------------------------------------------------------- International Court of Justice

ICJ = "https://www.icj-cij.org"
ICJ_SECTIONS = [("institution-proceedings", "01 Institution of Proceedings"),
                ("written-proceedings", "02 Written Proceedings"),
                ("preliminary-objections", "03 Preliminary Objections"),
                ("oral-proceedings", "04 Oral Proceedings"), ("orders", "05 Orders"),
                ("judgments", "06 Judgments and Advisory Opinions"), ("other-documents", "07 Other Documents"),
                ("correspondence", "08 Correspondence"), ("press-releases", "09 Press Releases"),
                ("summaries", "10 Summaries")]


def icj(drive, minutes, lane):
    k, n = lane
    r = get(f"{ICJ}/pending-cases")
    pending = set(re.findall(r'href="/case/(\d+)"', r.text)) if r else set()
    for num in range(1, 260):
        if num % n != k or str(num) in pending or f"icj:{num}" in drive.done:
            continue
        if left(minutes) < 900:
            return
        r = get(f"{ICJ}/case/{num}")
        if not r:
            continue
        m = re.search(r"<title>([^<|]+)", r.text)
        title = html.unescape(m.group(1)).strip() if m else f"Case {num}"
        if title.lower().startswith(("page not found", "international court")):
            continue
        folder = tempfile.mkdtemp(prefix="icj-")
        jobs, rows, seen = [], [], set()
        for slug, label in ICJ_SECTIONS:
            p = get(f"{ICJ}/case/{num}/{slug}")
            if not p:
                continue
            os.makedirs(os.path.join(folder, label), exist_ok=True)
            i = 0
            for href, text in re.findall(r'<a href="(https://www\.icj-cij\.org/sites/default/files/[^"]+\.pdf)"'
                                         r'\s+class="title"[^>]*>(.*?)</a>', p.text, re.S):
                if href in seen or href.endswith("-FR.pdf"):
                    continue
                seen.add(href)
                i += 1
                date = re.search(r"-(\d{4})(\d{2})(\d{2})-", href)
                d = "-".join(date.groups()) if date else ""
                fn = f"{label}/{i:03d}{' ' + d if d else ''} {clean(text, 80)}.pdf"
                jobs.append((href, fn))
                rows.append((i, d, f"{label[3:]}: {clean(text, 400)}", fn))
        got = download_all(jobs, folder)
        for sub in os.listdir(folder):
            if not os.listdir(os.path.join(folder, sub)):
                os.rmdir(os.path.join(folder, sub))
        timeline_pdf(os.path.join(folder, "00 Case Timeline.pdf"), title,
                     [("Court", "International Court of Justice"), ("Case number", num),
                      ("Files in this folder", f"{got} documents")], rows)
        dest = f"{ROOT}/06 International Court of Justice/{num:03d} {clean(title, 120)}"
        if got >= 3 and drive.upload(folder, dest):
            drive.done.add(f"icj:{num}")
            log(f"  ICJ {num}: {got} files")
            drive.save()
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- SEC administrative proceedings

SEC = "https://www.sec.gov"


def sec_ap(drive, minutes, lane):
    k, n = lane
    S2 = requests.Session()
    S2.headers["User-Agent"] = os.environ.get("SEC_USER_AGENT") or "LAW research collector admin@example.com"
    base = f"{SEC}/enforcement-litigation/administrative-proceedings"
    files = []
    for page in range(0, 200):
        r = S2.get(f"{base}/closed-litigated-administrative-proceedings", params={"page": page}, timeout=60)
        time.sleep(0.3)
        got = sorted(set(re.findall(r'href="/enforcement-litigation/administrative-proceedings/(3-[^"]+)"',
                                    r.text))) if r.status_code == 200 else []
        if not got:
            break
        files += [f for f in got if f not in files]
    log(f"SEC: {len(files)} closed litigated proceedings")
    for fno in files:
        if zlib.crc32(fno.encode()) % n != k or f"sec:{fno}" in drive.done:
            continue
        if left(minutes) < 900:
            return
        r = S2.get(f"{base}/{fno}", timeout=60)
        time.sleep(0.3)
        if r.status_code != 200:
            continue
        t = r.text
        resp = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t[t.find("<h1"):t.find("<table")]))
        resp = re.sub(r"^.*?Respondents?\s*", "", html.unescape(resp)).strip()
        rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)
        entries = []
        for row in rows_html:
            a = re.search(r'<a href="([^"]+)"[^>]*>(.*?)</a>', row, re.S)
            dt = re.search(r'datetime="(\d{4}-\d{2}-\d{2})', row)
            rel = re.search(r'field-release-number">\s*([^<\s][^<]*?)\s*<', row)
            if a and dt:
                entries.append((dt.group(1), rel.group(1) if rel else "", html.unescape(re.sub(r"<[^>]+>", "",
                                a.group(2))).strip(), a.group(1)))
        if len(entries) < 2:
            continue
        entries.sort()
        folder = tempfile.mkdtemp(prefix="sec-")
        jobs, rows = [], []
        for i, (d, rel, text, href) in enumerate(entries, 1):
            url = href if href.startswith("http") else SEC + href
            ext = os.path.splitext(url.split("?")[0])[1].lower() or ".pdf"
            if ext not in (".pdf", ".txt", ".htm", ".html"):
                ext = ".pdf"
            fn = f"{i:03d} {d} {clean(text, 80)}{'.pdf' if ext.startswith('.htm') else ext}"
            if ext.startswith(".htm"):
                rows.append((i, d, f"{text} ({rel}) - web page, not saved: {url}", ""))
                continue
            jobs.append((url, fn))
            rows.append((i, d, f"{text}{' (' + rel + ')' if rel else ''}", fn))
        got = 0
        for url, fn in jobs:  # the SEC asks for at most 10 requests a second
            try:
                rr = S2.get(url, timeout=120)
                if rr.status_code == 200 and rr.content:
                    open(os.path.join(folder, fn), "wb").write(rr.content)
                    got += 1
            except requests.RequestException:
                pass
            time.sleep(0.25)
        title = f"{fno.upper()} {resp}" if resp else fno.upper()
        timeline_pdf(os.path.join(folder, "00 Case Timeline.pdf"), title,
                     [("Forum", "U.S. Securities and Exchange Commission, administrative proceeding"),
                      ("File number", fno.upper()), ("Respondents", resp), ("Files in this folder", got)], rows)
        year = entries[0][0][:4]
        dest = f"{ROOT}/07 SEC Administrative Proceedings/{year}/{clean(title, 120)}"
        if got >= 2 and drive.upload(folder, dest):
            drive.done.add(f"sec:{fno}")
            log(f"  SEC {fno}: {got} files")
            drive.save()
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- Enron (user 2026-11-08: "the enron corpus case too")
# The court and regulatory cases around Enron's collapse. The e-mail corpus itself (released by FERC from docket
# PA02-2) is already on the Workspace in Research Collections/How Companies Work, so it is not copied again.

ENRON = "08 Enron Cases"
ENRON_WHO = (r"enron|jeffrey k(eith|\.)? skilling|andrew s(tuart|\.)? fastow|kenneth l(ee|\.)? lay\b|"
             r"richard a(lan|\.)? causey|michael (j\.? )?kopper|nigerian barge|"
             r"(usa|united states( of america)?) v\.? arthur andersen")
USREP = "https://tile.loc.gov/storage-services/service/ll/usrep/"
ENRON_SCOTUS = [("08-1394", "Skilling v. United States", 2009, USREP + "usrep561/usrep561358/usrep561358.pdf"),
                ("04-368", "Arthur Andersen LLP v. United States", 2004, USREP + "usrep544/usrep544696/usrep544696.pdf")]


def html_pdf(html_text, path, base):
    src = path[:-4] + ".html"
    open(src, "w", encoding="utf-8").write(re.sub(r"<head>", f'<head><base href="{base}">', html_text, count=1))
    for chrome in ("google-chrome", "chromium", "chromium-browser"):
        if shutil.which(chrome):
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", f"--print-to-pdf={path}",
                            "--no-pdf-header-footer", "file://" + os.path.abspath(src)], capture_output=True,
                           timeout=180)
            break
    os.remove(src)
    return os.path.exists(path) and os.path.getsize(path) > 1000


def enron(drive, minutes, lane):
    # 1. US Supreme Court: argument transcripts, audio, opinions, docket (electronic filings begin in 2017)
    for docket, name, term, usrep in ENRON_SCOTUS:
        key = f"enron:scotus:{docket}"
        if key in drive.done:
            continue
        folder = tempfile.mkdtemp(prefix="enron-")
        ops = scotus_opinions(term)
        jobs = [(f"{SC}/oral_arguments/argument_transcripts/{term}/{docket}.pdf", "01 Oral Argument Transcript.pdf"),
                (f"{SC}/media/audio/mp3files/{docket}.mp3", "02 Oral Argument Audio.mp3")]
        jobs.append((ops.get(docket) or usrep, "03 Opinion of the Court.pdf"))
        got = download_all(jobs, folder)
        r = get(f"{SC}/search.aspx?filename=/docketfiles/{docket}.htm")
        if r and html_pdf(r.text, os.path.join(folder, "00 Docket.pdf"), SC + "/"):
            got += 1
        if got and drive.upload(folder, f"{ROOT}/{ENRON}/US Supreme Court/{docket} {name}"):
            drive.done.add(key)
            drive.save()
            log(f"  Enron SCOTUS {docket}: {got} files")
        shutil.rmtree(folder, ignore_errors=True)
    # 2. SEC enforcement: every litigation document linked from the SEC's Enron page
    if "enron:sec" not in drive.done:
        S2 = requests.Session()
        S2.headers["User-Agent"] = os.environ.get("SEC_USER_AGENT") or "LAW research collector admin@example.com"
        r = S2.get(f"{SEC}/spotlight/enron.htm", timeout=60)
        if r.status_code == 200:
            folder = tempfile.mkdtemp(prefix="enron-")
            links, seen = [], set()
            for href, text in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', r.text, re.S):
                url = href if href.startswith("http") else SEC + "/" + href.lstrip("/")
                if "sec.gov" not in url or url in seen or not re.search(r"/litigation/|/news/press", url):
                    continue
                seen.add(url)
                links.append((url, clean(re.sub(r"<[^>]+>", "", text), 80)))
            rows, got = [], 0
            for i, (url, text) in enumerate(links, 1):
                fn = f"{i:03d} {text}.pdf"
                try:
                    rr = S2.get(url, timeout=120)
                    time.sleep(0.25)
                    if rr.status_code != 200:
                        continue
                    low = url.lower().split("?")[0]
                    if low.endswith(".pdf"):
                        open(os.path.join(folder, fn), "wb").write(rr.content)
                        ok = True
                    elif low.endswith(".txt"):
                        fn = fn[:-4] + ".txt"
                        open(os.path.join(folder, fn), "wb").write(rr.content)
                        ok = True
                    else:
                        ok = html_pdf(rr.text, os.path.join(folder, fn), url)
                    if ok:
                        got += 1
                        rows.append((i, "", text, fn))
                except (requests.RequestException, subprocess.SubprocessError, OSError):
                    pass
            timeline_pdf(os.path.join(folder, "00 Index.pdf"), "SEC enforcement actions related to Enron",
                         [("Source", "U.S. Securities and Exchange Commission, Spotlight on Enron"),
                          ("Files in this folder", got)], rows)
            if got and drive.upload(folder, f"{ROOT}/{ENRON}/SEC Enforcement"):
                drive.done.add("enron:sec")
                drive.save()
                log(f"  Enron SEC: {got} files")
            shutil.rmtree(folder, ignore_errors=True)
    # 3. Federal court dockets: bankruptcy, securities class action, criminal trials, appeals
    q = ('collection:usfederalcourts AND (enron OR skilling OR fastow OR "arthur andersen" OR "kenneth lay" '
         'OR kopper OR causey OR "Enron Creditors Recovery")')
    cursor = None
    while left(minutes) > 900:
        params = {"q": q, "fields": "identifier", "count": 1000}
        if cursor:
            params["cursor"] = cursor
        r = get(f"{IA}/services/search/v1/scrape", params=params, timeout=120)
        if not r:
            break
        page = r.json()
        for x in page.get("items", []):
            ident = x["identifier"]
            if not ident.startswith("gov.uscourts.") or ident in drive.done or ident in drive.skip:
                continue
            if left(minutes) < 900:
                return
            m = get(f"{IA}/metadata/{ident}", timeout=120)
            res = recap_case(drive, ident, m.json(), topic=(ENRON_WHO, ENRON)) if m else "nometa"
            if res.startswith("ok"):
                drive.done.add(ident)
                drive.save()
                log(f"  Enron court case {ident}: {res.split()[1]} documents")
            elif res not in ("failed", "nometa"):
                drive.skip.add(ident)
        cursor = page.get("cursor")
        if not cursor:
            break
    drive.save()


# ---------------------------------------------------------------- Permanent Court of Arbitration
# The PCA case repository's own JSON feed (the page builds its list from it with JavaScript): concluded cases
# with published documents - notices of arbitration, written submissions, procedural orders, hearing
# transcripts, awards. English (or bilingual) documents; hearing videos are left out.

PCA = "https://pcacases.com/web/api/cases"


def pca(drive, minutes, lane):
    k, n = lane
    r = get(f"{PCA}/search?1", timeout=120)
    if not r:
        return
    cases = [c for c in r.json() if c.get("case_status") == "Concluded" and c["id"] % n == k]
    log(f"PCA: {len(cases)} concluded cases")
    for c in cases:
        key = f"pca:{c['id']}"
        if key in drive.done or key in drive.skip:
            continue
        if left(minutes) < 900:
            return
        r = get(f"{PCA}/{c['id']}", timeout=120)
        if not r:
            continue
        d = r.json()
        att = [a for a in d.get("attachments") or [] if a.get("ismultimedia") != "Y"
               and (a.get("language") or {}).get("name", "English") in ("English", "Multilingual", "Bilingual")]
        if not att:
            drive.skip.add(key)
            continue
        att.sort(key=lambda a: (a.get("date") or "", a.get("position") or 0))
        folder = tempfile.mkdtemp(prefix="pca-")
        jobs, rows = [], []
        for i, a in enumerate(att, 1):
            date = (a.get("date") or "")[:10]
            kind = (a.get("typeofdocument") or {}).get("name") or ""
            fn = f"{i:03d} {date} {clean(kind, 30)} - {clean(a.get('title') or a.get('filename'), 70)}.pdf"
            jobs.append((a["download_link"], fn))
            rows.append((i, date, f"{kind}: {a.get('title') or ''}", fn))
        got = download_all(jobs, folder, threads=4)
        name = c.get("case_name") or d.get("casename") or f"Case {c['id']}"
        title = f"PCA Case No. {c.get('case_number') or ''} {name}".strip()
        timeline_pdf(os.path.join(folder, "00 Case Timeline.pdf"), title,
                     [("Forum", "Permanent Court of Arbitration"), ("Case type", c.get("case_type")),
                      ("Claimants", ", ".join(c.get("claimants_names") or [])),
                      ("Respondents", ", ".join(c.get("respondents_names") or [])),
                      ("Filed", (c.get("date_of_filling") or "")[:10]), ("Status", "Concluded"),
                      ("Summary", re.sub(r"<[^>]+>", " ", html.unescape(c.get("case_description") or ""))[:3000]),
                      ("Files in this folder", got)], rows)
        dest = (f"{ROOT}/09 Permanent Court of Arbitration/{clean(c.get('case_type') or 'Other', 50)}/"
                f"{clean((c.get('case_number') or '') + ' ' + name, 120)}")
        if got and drive.upload(folder, dest):
            drive.done.add(key)
            drive.save()
            log(f"  PCA {c.get('case_number')}: {got} files")
        shutil.rmtree(folder, ignore_errors=True)


def redact_existing(drive, minutes, lane):
    """user 2026-11-09: redact what LAW 2 already holds - each case folder is downloaded, redacted, uploaded under
    its redacted name, and the unredacted original deleted."""
    k, n = lane
    base = f"{drive.remote}{ROOT}"
    r = subprocess.run(["rclone", "lsf", "-R", "--files-only", "--fast-list", base], capture_output=True, text=True)
    dirs = sorted({os.path.dirname(x) for x in r.stdout.splitlines() if x.strip()})
    dirs = [d for d in dirs if zlib.crc32(d.encode()) % n == k and d not in drive.done
            and not re.search(r"(^|/)Case [0-9A-F]{6}$", d)]
    # folders redacted before the docket-number fix (2026-11-09): one more pass, dates NOT moved again
    r2 = subprocess.run(["rclone", "cat", f"{drive.remote}LAW - private/pass2.txt"], capture_output=True, text=True)
    redo = [x[len(ROOT) + 1:] if x.startswith(ROOT + "/") else x for x in r2.stdout.splitlines() if x.strip()]
    redo = [d for d in redo if zlib.crc32(d.encode()) % n == k and "pass2:" + d not in drive.done]
    dirs = [(d, True) for d in redo] + [(d, False) for d in dirs]
    log(f"redact: {len(dirs)} folders to redact in lane {k}/{n} ({len(redo)} second passes)")
    for d, again in dirs:
        if left(minutes) < 1200:
            return
        folder = tempfile.mkdtemp(prefix="law2-")
        src = f"{base}/{d}" if d else base
        if subprocess.run(["rclone", "copy", src, folder, "--max-depth", "1", "-q"]).returncode != 0:
            shutil.rmtree(folder, ignore_errors=True)
            continue
        originals = sorted(os.listdir(folder))
        os.environ["LAW_REDACT"] = "true"
        ok = drive.upload(folder, f"{ROOT}/{d}" if d else ROOT, second_pass=again)
        if ok and drive.live:  # redacted copy is up: move the unredacted originals of this folder to the trash
            redacted = set(os.listdir(folder)) if drive.last_dest == f"{ROOT}/{d}" else set()
            gone = [x for x in originals if x not in redacted]
            lst = os.path.join(folder, "..", f"orig-{zlib.crc32(d.encode())}.txt")
            with open(lst, "w", encoding="utf-8") as f:
                f.write("".join(x + "\n" for x in gone))
            subprocess.run(["rclone", "delete", src, "--max-depth", "1", "--files-from-raw", lst, "-q"])
            subprocess.run(["rclone", "rmdir", src, "-q"])  # only removed when it is now empty
            os.remove(lst)
        before = len(originals)
        if ok:
            drive.done.add("pass2:" + d if again else d)
            drive.save()
            log(f"  redacted folder {len(drive.done)}: {before} files")
        shutil.rmtree(folder, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["scotus", "recap", "icj", "sec", "enron", "pca", "redact"], required=True)
    ap.add_argument("--lane", default="0/1")
    ap.add_argument("--remote", default="ws:")
    ap.add_argument("--minutes", type=float, default=300)
    ap.add_argument("--max-files", type=int, default=0)
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    k, n = map(int, a.lane.split("/"))
    job = f"{a.source}-{k}of{n}"
    drive = Drive(a.remote if a.remote.endswith(":") else a.remote + ":", job, a.live)
    log(f"{job}: {len(drive.done)} cases done before, live={a.live}")
    try:
        if a.source == "redact":
            redact_existing(drive, a.minutes, (k, n))
        elif a.source == "recap":
            recap(drive, a.minutes, (k, n), a.max_files)
        else:
            {"scotus": scotus, "icj": icj, "sec": sec_ap, "enron": enron, "pca": pca}[a.source](drive, a.minutes, (k, n))
    finally:
        drive.save()
        log(f"{job}: {len(drive.done)} cases, {drive.state['files']} files uploaded in total")


if __name__ == "__main__":
    main()
