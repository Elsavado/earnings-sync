"""Matter files (user 2026-11-09): complete files of CLOSED matters, redacted (any size; long PDFs of matters under
500 documents split into marked parts, the true document count stated in each summary).

  Litigation   - concluded US federal court cases whose full record (every docket document and attachment) is public:
                 PACER via the RECAP archive. Only cases that really hold 500+ documents qualify; nothing is split
                 or padded to reach the count.
  Transactions - completed public-company acquisitions: every SEC filing (with all exhibits) by and about the target
                 from announcement to closing.

Redaction, per matter:
  * people (named-entity recognition over every document + the docket's party/attorney/judge lists, titles,
    signature lines) -> black boxes in PDFs, "Redacted Name" in text
  * parties / companies of the matter -> black boxes / role labels ("Plaintiff Company 1", "Target Company")
  * e-mail, phone, street address, SSN/EIN, bar numbers, account numbers, dates of birth, case numbers
  * DATES are not kept: every date is moved back by one fixed per-matter offset (a whole number of weeks, so
    intervals and weekdays are unchanged); stand-alone years move by the same amount. Citation years are left.
  * no document is left out: one that cannot be redacted is kept as downloaded and listed in the summary
  * PDF metadata, attachments, links, comments, form fields and JavaScript are removed; scanned pages are OCR'd
    first so their text can be found and the pixels under it removed.
Each matter: "00 Matter Summary.pdf" (practice area, matter type, jurisdiction, date range, document count),
"00 Matter Timeline.pdf" (redacted docket) and the documents in their original order and numbering.
State: "LAW - private/state-matters-<job>.json". Uploads only with --live.
"""
import argparse, collections, concurrent.futures as cf, csv, datetime as dt, functools, hashlib, html, json, os, re
import shutil
import subprocess, tempfile, threading, time, zlib

import requests

import law.__main__ as L
from law.__main__ import IA, clean, download_all, get, left, log

ROOT = os.environ.get("MATTERS_ROOT", "")  # the "Matter Files" shared drive itself; folders at its top
P = ROOT + "/" if ROOT else ""
LAW_REMOTE = os.environ.get("LAW_REMOTE") or "ws:"  # where the LAW folder (and its done-state) lives
MIN_DOCS, MAX_DOCS = 12, 3000  # user 2026-11-09: court cases of any size (12+ documents, as LAW), not only 500+
SPLIT_UNDER, SPLIT_PAGES = 500, 10  # matters under 500 documents: PDFs over 10 pages are split, marked part k of n
DEAL_MIN = 1  # user 2026-11-09: completed deals are kept whatever their document count

# ---------------------------------------------------------------- dates

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
MON = (r"(January|February|March|April|May|June|July|August|September|October|November|December|"
       r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)(\.?)")
P_A = re.compile(rf"\b{MON}\s+(\d{{1,2}})(st|nd|rd|th)?(,\s*|\s+)(\d{{4}})\b", re.I)
P_B = re.compile(rf"\b(\d{{1,2}})(st|nd|rd|th)?(\s+day\s+of\s+|\s+){MON}(,\s*|\s+)(\d{{4}})\b", re.I)
P_C = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?![\d/])")
P_D = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-])")
P_E = re.compile(rf"\b{MON}(,?\s+)(\d{{4}})\b", re.I)
P_Y = re.compile(r"(?<![\w/.$-])(19[3-9]\d|20[0-4]\d)(?![\w%/-])")


def _mon(s):
    return MONTHS.index(next(m for m in MONTHS if m.startswith(s.lower()[:3]))) + 1


def _mname(orig, dot, m):
    full = orig.lower() in MONTHS
    name = MONTHS[m - 1].capitalize() if full else MONTHS[m - 1][:3].capitalize()
    if orig.isupper() and len(orig) > 1:
        name = name.upper()
    return name + ("." if dot and not full else "")


def _ord(n):
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _date(y, m, d):
    try:
        x = dt.date(int(y), int(m), int(d))
        return x if 1900 <= x.year <= 2099 else None
    except ValueError:
        return None


# ---------------------------------------------------------------- redaction rules

CONTACT = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[Redacted Email]"),
    (re.compile(r"(?:Date of Birth|D\.?O\.?B\.?)\s*:?\s*[\w/.,-]+(?:\s+\d{1,2},?\s+\d{4})?", re.I), "[Redacted DOB]"),
    (re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)|\b[Xx*]{3}-[Xx*]{2}-\d{4}\b"), "[Redacted]"),
    (re.compile(r"(?<![\d-])\d{2}-\d{7}(?![\d-])"), "[Redacted]"),
    (re.compile(r"(?<![\d-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"), "[Redacted Phone]"),
    (re.compile(r"\b\d{1,6}\s+(?:[NSEW]\.?\s+)?(?:[A-Z][\w'.-]*\s+){1,4}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|"
                r"Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct|Place|Pl|Parkway|Pkwy|Highway|Hwy|Circle|Terrace|Square|"
                r"Plaza)\b\.?(?:,?\s+(?:Suite|Ste\.?|Floor|Fl\.?|Apt\.?|Unit|#)\s*[\w-]+)?"), "[Redacted Address]"),
    (re.compile(r"\bP\.?\s?O\.?\s+Box\s+\d+", re.I), "[Redacted Address]"),
    (re.compile(r"\b(?:State\s+)?Bar\s+(?:No|Number|#|I\.?D\.?)\.?:?\s*[A-Z]{0,3}\d[\w-]*|\bSBN\s*:?\s*\d+", re.I),
     "[Redacted Bar No.]"),
    (re.compile(r"\b(?:Account|Acct\.?|Loan|Policy|Claim)\s*(?:No\.?|Number|#)\s*:?\s*[\w-]*\d{4,}[\w-]*", re.I),
     "[Redacted Account No.]"),
    (re.compile(r"\b\d{1,2}\s?:\s?\d{2}\s?-\s?[a-zA-Z]{1,4}\s?-\s?\d{2,6}(?:\s?-\s?[A-Za-z0-9.]{1,6})*"),
     "[Case No. Redacted]"),
    (re.compile(r"\b(?:Case|Docket|Civil Action|Criminal Action|Adv(?:ersary)?(?:\.\s*Pro(?:c|ceeding)\.?)?|"
                r"Bankruptcy|Misc\.?|Appeal|Petition)\s+No(?:s)?\.?:?\s*[\w:.-]*\d[\w:.-]*", re.I),
     "[Case No. Redacted]"),
]
TITLES = re.compile(r"^(?:(?:mr|ms|mrs|dr|hon|judge|justice|magistrate|chief|honorable|the|defendant|plaintiff|"
                    r"debtor|officer|agent|detective|sgt|sergeant|lt|capt|trustee|attorney|counsel|witness|"
                    r"professor|prof|deputy|special|senior|district|bankruptcy|circuit|u\.s\.)\.?\s+)+", re.I)
NOT_NAMES = {"court", "plaintiff", "plaintiffs", "defendant", "defendants", "judge", "honorable", "united states",
             "esq", "clerk", "debtor", "debtors", "trustee", "government", "respondent", "petitioner", "appellant",
             "appellee", "exhibit", "section", "rule", "order", "id", "ibid", "pursuant", "fed", "llc", "inc",
             "page", "document", "filed", "dated", "signed", "motion", "counsel", "magistrate", "chapter", "see",
             "class", "state", "county", "district", "circuit", "bankruptcy", "case", "docket", "notice", "re",
             "honor", "your honor", "jury", "witness", "the court", "company", "corporation", "agreement", "board",
             "director", "officer", "chairman", "president", "secretary", "treasurer", "god", "christ", "jesus"}
PERSON_HONORIFIC = re.compile(r"\b(?:Mr|Ms|Mrs|Dr|Hon|Judge|Justice)\.?\s+((?:[A-Z][a-zA-Z'’-]+\.?\s+){0,3}"
                              r"[A-Z][a-zA-Z'’-]{1,})")
SIGNED = re.compile(r"/s/\s*((?:[A-Z][a-zA-Z.'’-]*\s+){1,3}[A-Z][a-zA-Z'’-]+)")
ORG_SUFFIX = re.compile(r"[,\s]+(?:inc|incorporated|corp|corporation|co|company|llc|l\.l\.c|ltd|limited|lp|l\.p|"
                        r"llp|plc|n\.v|s\.a|ag|holdings?|group|trust|et al)\.?$", re.I)


@functools.lru_cache(maxsize=None)
def zipf(w):
    try:
        from wordfreq import zipf_frequency
        return zipf_frequency(w, "en")
    except ImportError:
        return 0.0


def norm_person(s):
    s = re.sub(r"['’]s$", "", " ".join(s.split())).strip(" ,.;:()[]\"'")
    s = TITLES.sub("", s).strip(" ,.;:")
    if not (2 < len(s) <= 60) or re.search(r"\d|[@/\\_=<>]", s) or not re.search(r"[A-Z]", s):
        return None
    toks = s.split()
    if len(toks) > 5 or s.lower() in NOT_NAMES or all(t.lower() in NOT_NAMES for t in toks):
        return None
    return s


def org_variants(name):
    """'ACME WIDGETS CORP /DE/' -> acme widgets corp, acme widgets, (+ 'Acme' when distinctive)."""
    n = re.sub(r"\s*/[A-Z]{2,3}/?\s*$", "", " ".join(name.split())).strip(" ,.")
    n = re.sub(r"\s*\((?:the )?\"?[\w\s]+\"?\)$", "", n)
    out = {n}
    base = n
    for _ in range(3):
        b = ORG_SUFFIX.sub("", base).strip(" ,.")
        if b == base:
            break
        base = b
    if len(base) >= 4:
        out.add(base)
    first = base.split()[0] if base.split() else ""
    if len(first) >= 5 and zipf(first) < 3.0 and first.lower() not in NOT_NAMES:
        out.add(first)
    return {v for v in out if len(v) >= 3 and v.lower() not in NOT_NAMES}


class Redactor:
    """One per matter: fixed date offset, the matter's people and parties, compiled once per process."""

    def __init__(self, key, people=(), singles=(), orgs=None):
        h = int(hashlib.sha256(("matter-shift:" + key).encode()).hexdigest(), 16)
        self.days = 7 * (60 + h % 300)  # 1.2 to 7 years back, whole weeks
        self.years = round(self.days / 365.25)
        self.people, self.singles, self.orgs = set(people), set(singles), dict(orgs or {})
        self._c = None

    def __getstate__(self):
        d = dict(self.__dict__)
        d["_c"] = None
        return d

    def _compile(self):
        def alt(terms):
            terms = sorted({t for t in terms if t}, key=len, reverse=True)
            return "|".join(r"\s+".join(map(re.escape, t.split())) for t in terms)
        multi = [t for t in self.people if " " in t] + [t for t in self.orgs if " " in t]
        caps = [t for t in self.singles] + [t for t in self.orgs if " " not in t]
        caps += [t.upper() for t in caps]
        lab = {k.lower(): v for k, v in self.orgs.items()}
        self._c = (re.compile(rf"(?<![\w-])(?:{alt(multi)})(?![\w-])", re.I) if multi else None,
                   re.compile(rf"(?<![\w-])(?:{alt(caps)})(?![\w-])") if caps else None, lab)

    def shift(self, d):
        return d - dt.timedelta(days=self.days)

    def spans(self, text, dates=True):
        """[(start, end, replacement, kind)] - kind: contact | name | org | date - non-overlapping."""
        if self._c is None:
            self._compile()
        out, taken = [], []

        def free(s, e):
            return all(e <= a or s >= b for a, b in taken)

        def add(s, e, new, kind):
            if s < e and free(s, e):
                out.append((s, e, new, kind))
                taken.append((s, e))

        for rx, rep in CONTACT:
            for m in rx.finditer(text):
                add(m.start(), m.end(), rep, "contact")
        multi, caps, lab = self._c
        for rx in (multi, caps):
            if rx:
                for m in rx.finditer(text):
                    k = " ".join(m.group(0).split()).lower()
                    add(m.start(), m.end(), lab.get(k, "Redacted Name"), "org" if k in lab else "name")
        for rx in (PERSON_HONORIFIC, SIGNED):
            for m in rx.finditer(text):
                if norm_person(m.group(1)):
                    add(m.start(1), m.end(1), "Redacted Name", "name")
        if dates:
            self._dates(text, add)
        return sorted(out)

    def _dates(self, text, add):
        for m in P_A.finditer(text):
            d = _date(m.group(6), _mon(m.group(1)), m.group(3))
            if d:
                n = self.shift(d)
                add(m.start(), m.end(), f"{_mname(m.group(1), m.group(2), n.month)} {n.day}"
                    f"{_ord(n.day) if m.group(4) else ''}{m.group(5)}{n.year}", "date")
        for m in P_B.finditer(text):
            d = _date(m.group(7), _mon(m.group(4)), m.group(1))
            if d:
                n = self.shift(d)
                add(m.start(), m.end(), f"{n.day}{_ord(n.day) if m.group(2) else ''}{m.group(3)}"
                    f"{_mname(m.group(4), m.group(5), n.month)}{m.group(6)}{n.year}", "date")
        for m in P_D.finditer(text):
            d = _date(m.group(1), m.group(2), m.group(3))
            if d:
                add(m.start(), m.end(), self.shift(d).isoformat(), "date")
        for m in P_C.finditer(text):
            a, b, y = m.groups()
            yy = int(y) if len(y) == 4 else (2000 + int(y) if int(y) < 50 else 1900 + int(y))
            mo, da = (int(a), int(b)) if int(a) <= 12 else (int(b), int(a))
            d = _date(yy, mo, da)
            if d:
                n = self.shift(d)
                p = lambda v, src: f"{v:02d}" if len(src) == 2 else str(v)
                f1, f2 = (p(n.month, a), p(n.day, b)) if int(a) <= 12 else (p(n.day, a), p(n.month, b))
                add(m.start(), m.end(), f"{f1}/{f2}/{n.year if len(y) == 4 else '%02d' % (n.year % 100)}", "date")
        for m in P_E.finditer(text):
            d = _date(m.group(4), _mon(m.group(1)), 15)
            if d:
                n = self.shift(d)
                add(m.start(), m.end(), f"{_mname(m.group(1), m.group(2), n.month)}{m.group(3)}{n.year}", "date")
        for m in P_Y.finditer(text):
            before, after = text[max(0, m.start() - 30):m.start()], text[m.end():m.end() + 12]
            if (re.match(r"\s*(WL|U\.S\. Dist|U\.S\. App|Bankr\. LEXIS|LEXIS)", after)
                    or re.search(r"(Act of|Pub\. ?L\.|Stat\.|U\.S\.C\.|Code of|Rev\.)\s*$", before)
                    or (after.startswith(")") and "(" in before and ")" not in before[before.rfind("("):])):
                continue  # citation years stay correct
            add(m.start(), m.end(), str(int(m.group(1)) - self.years), "date")

    def text(self, s):
        if not s:
            return s
        out, i = [], 0
        for a, b, new, _ in self.spans(s):
            out.append(s[i:a])
            out.append(new)
            i = b
        out.append(s[i:])
        return "".join(out)

    def date_iso(self, s):
        d = _date(*(s or "")[:10].split("-")) if re.match(r"\d{4}-\d{2}-\d{2}", s or "") else None
        return self.shift(d).isoformat() if d else ""


# ---------------------------------------------------------------- worker processes

NLP = None
RED = None


def _nlp():
    global NLP
    if NLP is None:
        import spacy
        NLP = spacy.load("en_core_web_lg", exclude=["parser", "lemmatizer", "tagger", "attribute_ruler",
                                                    "senter"])
        NLP.max_length = 3_000_000
    return NLP


def _init_red(red):
    global RED
    RED = red


def page_words(page):
    """-> text with words joined by single spaces, [(start, end, word tuple)]"""
    words = page.get_text("words", sort=True)
    parts, idx, pos = [], [], 0
    for w in words:
        parts.append(w[4])
        idx.append((pos, pos + len(w[4]), w))
        pos += len(w[4]) + 1
    return " ".join(parts), idx


def plain_html(raw):
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return " ".join(html.unescape(t).replace("\xa0", " ").split())


def ocr_if_needed(path):
    import fitz
    try:
        doc = fitz.open(path)
        # pages that are pictures (scans): OCR them again even when an old, often incomplete OCR layer exists
        scanned = sum(1 for p in doc if p.get_images())
        n = len(doc)
        doc.close()
    except Exception:
        return False
    if scanned:
        tmp = path + ".ocr.pdf"
        try:
            r = None
            for mode in ("--redo-ocr", "--skip-text"):  # some files refuse --redo-ocr
                r = subprocess.run(["ocrmypdf", mode, "-q", "--jobs", "1", "--output-type", "pdf",
                                    "--optimize", "0", path, tmp], capture_output=True, timeout=60 + 20 * n)
                if r.returncode == 0:
                    break
            if r.returncode == 0 and os.path.getsize(tmp) > 0:
                os.replace(tmp, path)
        except (subprocess.TimeoutExpired, OSError):
            pass
        if os.path.exists(tmp):
            os.remove(tmp)
    return True


def w_names(path):
    """pass 1: OCR scans, then find people's names. -> (ok, Counter multi, Counter single)"""
    if path.endswith(".pdf"):
        if not ocr_if_needed(path):
            return False, {}, {}
        import fitz
        try:
            with fitz.open(path) as doc:
                text = "\n".join(page_words(p)[0] for p in doc)
        except Exception:
            return False, {}, {}
    else:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = plain_html(f.read())
    multi, single = collections.Counter(), collections.Counter()
    nlp = _nlp()
    for i in range(0, min(len(text), 2_500_000), 400_000):
        for ent in nlp(text[i:i + 400_000]).ents:
            if ent.label_ == "PERSON":
                n = norm_person(ent.text)
                if n:
                    (multi if " " in n else single)[n] += 1
    for rx in (PERSON_HONORIFIC, SIGNED):
        for m in rx.finditer(text):
            n = norm_person(m.group(1))
            if n:
                (multi if " " in n else single)[n] += 1
    return True, dict(multi), dict(single)


def w_redact(src, dst):
    """pass 2. -> (ok, n redactions, leftovers)"""
    try:
        if src.endswith(".pdf"):
            return _redact_pdf(src, dst)
        return _redact_html(src, dst)
    except Exception as e:  # unreadable/broken document: dropped
        return False, 0, str(e)[:100]


def _redact_pdf(src, dst):
    import fitz
    doc = fitz.open(src)
    if doc.needs_pass:
        return False, 0, "encrypted"
    total = 0
    for page in doc:
        for a in list(page.annots() or []):
            page.delete_annot(a)
        for w in list(page.widgets() or []):
            page.delete_widget(w)
        for lk in page.get_links():
            page.delete_link(lk)
        text, idx = page_words(page)
        sp = RED.spans(text)
        if not sp:
            continue
        for a, b, new, kind in sp:
            hit = [w for s, e, w in idx if s < b and e > a]
            lines = collections.OrderedDict()
            for w in hit:
                lines.setdefault((w[5], w[6]), []).append(w)
            for li, ws in enumerate(lines.values()):
                r = fitz.Rect(min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws),
                              max(w[3] for w in ws))
                if kind == "date":
                    t = new if li == 0 else ""
                    fs = max(4.0, min(12.0, r.height * 0.8))
                    while t and fs > 4 and fitz.get_text_length(t, "helv", fs) > r.width + 2:
                        fs -= 0.5
                    page.add_redact_annot(r, text=t, fontname="helv", fontsize=fs, fill=(1, 1, 1),
                                          text_color=(0, 0, 0), align=0)
                else:
                    page.add_redact_annot(r, fill=(0, 0, 0))
                total += 1
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
    try:
        doc.scrub(attached_files=True, clean_pages=True, embedded_files=True, hidden_text=False, javascript=True,
                  metadata=True, redactions=False, remove_links=True, reset_fields=True, reset_responses=True,
                  thumbnails=True, xml_metadata=True)
    except Exception:
        doc.set_metadata({})
        doc.del_xml_metadata()
    doc.save(dst, garbage=3, deflate=True)
    doc.close()
    left_over = 0  # check: no person, party or contact detail is still readable
    with fitz.open(dst) as d2:
        for p in d2:
            left_over += sum(1 for s in RED.spans(page_words(p)[0], dates=False))
    return True, total, left_over


def _redact_html(src, dst):
    with open(src, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    raw = re.sub(r"(?is)<img[^>]*>", "", raw)
    raw = re.sub(r"(?i)&nbsp;|&#160;|&#xa0;", " ", raw)

    def scrub(s):
        parts = re.split(r"(<[^>]+>)", s)
        n = 0
        for i in range(0, len(parts), 2):
            if parts[i].strip():
                t = html.unescape(parts[i])
                sp = RED.spans(t)
                if sp:
                    n += len(sp)
                    parts[i] = html.escape(RED.text(t), quote=False)
        return "".join(parts), n

    out, n = scrub(raw)
    if RED.spans(plain_html(out), dates=False):  # a name split by formatting tags: flatten inline tags, again
        out, n2 = scrub(re.sub(r"(?i)</?(?:font|span|b|i|u|a|strong|em|sup|sub)\b[^>]*>", "", out))
        n += n2
    with open(dst, "w", encoding="utf-8") as f:
        f.write(out)
    return True, n, len(RED.spans(plain_html(out), dates=False))


# ---------------------------------------------------------------- matter pipeline

def build_terms(results, known_people, orgs):
    multi, single = collections.Counter(), collections.Counter()
    for ok, m, s in results:
        multi.update(m)
        single.update(s)
    people = {n for n in multi} | {n for n in known_people if n}
    singles = set()
    for n, c in single.items():
        if n[0].isupper() and n.lower() not in NOT_NAMES and (zipf(n) < 4.0 or (c >= 3 and zipf(n) < 5.0)):
            singles.add(n)
    for n in people:  # surnames of full names used on their own
        last = n.split()[-1].strip(".,")
        if len(last) >= 4 and last[0].isupper() and zipf(last) < 3.5 and last.lower() not in NOT_NAMES:
            singles.add(last)
    org_labels = {}
    for name, label in orgs.items():
        for v in org_variants(name):
            org_labels.setdefault(v, label)
    people = {p for p in people if p.lower() not in {o.lower() for o in org_labels}}
    return people, singles, org_labels


def process_matter(key, docs, raw_dir, out_dir, known_people, orgs, minutes):
    """docs: [(raw filename, out relative path)] -> (red, kept [(out path, ok)], stats) or None when time ran out."""
    paths = [os.path.join(raw_dir, r) for r, _ in docs]
    workers = max(1, os.cpu_count() or 2)
    with cf.ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(w_names, paths, chunksize=4))
    if left(minutes) < 600:
        return None
    people, singles, org_labels = build_terms(res, known_people, orgs)
    red = Redactor(key, people, singles, org_labels)
    stats = collections.Counter()
    kept = []
    jobs = []
    # user 2026-11-09: no document is left out. A document that cannot be redacted is kept as downloaded, and one
    # where a detail may remain is kept too; both are listed in the matter summary.
    flagged = {"not redacted (unreadable or locked file, kept as downloaded)": [],
               "redacted, but a name or detail may remain": []}
    for rawname, rel in docs:
        dst = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        jobs.append((os.path.join(raw_dir, rawname), dst, rel))
    with cf.ProcessPoolExecutor(workers, initializer=_init_red, initargs=(red,)) as ex:
        for (src, dst, rel), (ok, n, lo) in zip(jobs, ex.map(w_redact, [j[0] for j in jobs], [j[1] for j in jobs],
                                                              chunksize=4)):
            if not ok:
                shutil.copyfile(src, dst)
                flagged["not redacted (unreadable or locked file, kept as downloaded)"].append(rel)
                stats["kept_unredacted"] += 1
            elif lo:
                flagged["redacted, but a name or detail may remain"].append(rel)
                stats["kept_with_leftovers"] += 1
            stats["redactions"] += n or 0
            kept.append(rel)
    stats["flagged"] = flagged
    stats["people"], stats["parties"] = len(people) + len(singles), len(org_labels)
    return red, kept, stats


def summary_pdf(path, mid, facts):
    L.timeline_pdf(path, f"Matter {mid} - Summary", facts, [])


def split_pdfs(folder):
    """user 2026-11-09: split long PDFs of smaller matters into SPLIT_PAGES-page parts. -> files after splitting"""
    import fitz
    for root, _, files in os.walk(folder):
        for fn in files:
            if not fn.lower().endswith(".pdf") or fn.startswith("00 "):
                continue
            path = os.path.join(root, fn)
            try:
                with fitz.open(path) as doc:
                    pages = len(doc)
                    if pages <= SPLIT_PAGES:
                        continue
                    parts = (pages + SPLIT_PAGES - 1) // SPLIT_PAGES
                    for k in range(parts):
                        out = fitz.open()
                        out.insert_pdf(doc, from_page=k * SPLIT_PAGES, to_page=min(pages, (k + 1) * SPLIT_PAGES) - 1)
                        out.save(os.path.join(root, f"{fn[:-4]} (part {k + 1} of {parts}).pdf"), garbage=3,
                                 deflate=True)
                        out.close()
            except Exception:
                continue
            os.remove(path)
    return sum(1 for _, _, f in os.walk(folder) for x in f if not x.startswith("00 "))


def finish(drive, mid, folder, dest, red, facts, rows, n_docs, index_row):
    files = n_docs
    if n_docs < SPLIT_UNDER:
        files = split_pdfs(folder)
        if files != n_docs:
            facts = facts + [("Files after splitting", f"{files} files from the {n_docs} original documents "
                              f"(documents over {SPLIT_PAGES} pages split into parts, each marked 'part k of n'); "
                              f"the original document count is {n_docs}")]
    index_row = dict(index_row, files=files)
    L.timeline_pdf(os.path.join(folder, "00 Matter Timeline.pdf"), f"Matter {mid} - Timeline",
                   [("Dates", f"all dates moved back {red.days} days (whole weeks; intervals and weekdays kept)")],
                   rows)
    summary_pdf(os.path.join(folder, "00 Matter Summary.pdf"), mid, facts)
    top, real = len(os.listdir(folder)), sum(len(f) for _, _, f in os.walk(folder))
    if drive.upload(folder, dest):
        drive.state["files"] += real - top  # Drive.upload counts only the top level
        drive.state.setdefault("index", []).append(index_row)
        write_index(drive)
        return True
    return False


def write_index(drive):
    p = os.path.join(tempfile.gettempdir(), f"index-{drive.job}.csv")
    rows = drive.state.get("index", [])
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["matter", "practice area", "matter type", "jurisdiction", "date range",
                                          "documents", "files", "folder"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    if drive.live:
        subprocess.run(["rclone", "copyto", p, f"{drive.remote}{P}00 Matter Index ({drive.job}).csv", "-q"],
                       check=False)


def flag_facts(stats, names):
    out = []
    for label, rels in (stats.get("flagged") or {}).items():
        if rels:
            out.append((f"Documents {label}", f"{len(rels)}: " + "; ".join(names.get(r, r) for r in rels)))
    return out


REDACTION_NOTE = ("People's names, parties, contact details, addresses, ID/account/bar/case numbers redacted; "
                  "every date moved back by one fixed offset for this matter (intervals and weekdays kept); "
                  "document metadata removed.")


# ---------------------------------------------------------------- litigation (RECAP)

# ---------------------------------------------------------------- CourtListener (Free Law Project REST API)

CL = "https://www.courtlistener.com/api/rest/v4"
# off unless COURTLISTENER_ON=true: the account allows 50 calls an hour (2026-11-09) - too few to check cases with
CL_TOKEN = os.environ.get("COURTLISTENER_TOKEN", "").strip() if os.environ.get("COURTLISTENER_ON") == "true" else ""
CLS = requests.Session()
if CL_TOKEN:
    CLS.headers["Authorization"] = "Token " + CL_TOKEN
_cl_last = [0.0]


def cl_get(path, params=None, tries=5):
    for i in range(tries):
        wait = _cl_last[0] + 0.8 - time.time()  # ~4,500 calls an hour, under the account's 5,000
        if wait > 0:
            time.sleep(wait)
        _cl_last[0] = time.time()
        try:
            r = CLS.get(path if path.startswith("http") else CL + path, params=params, timeout=120)
        except requests.RequestException:
            time.sleep(10 + 10 * i)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            ra = int(r.headers.get("Retry-After") or 60)
            if ra > 300:  # hourly allowance used up: carry on with the archive copy instead of waiting
                return None
            time.sleep(ra + 1)
            continue
        if r.status_code in (400, 403, 404):
            return None
        time.sleep(10 + 10 * i)
    return None


def cl_all(path, params):
    out, nxt, prm = [], path, dict(params, page_size=100)
    while nxt:
        page = cl_get(nxt, prm)
        if not page:
            break
        out += page.get("results") or []
        nxt, prm = page.get("next"), None
    return out


def cl_docket(ident):
    """IA identifier gov.uscourts.<court>.<pacer id> -> (docket dict, pdfs, court, terminated) | status | 'nocl'."""
    parts = ident.split(".")
    if len(parts) < 4:
        return "nocl"
    court, pacer = parts[2], parts[3]
    found = cl_get("/dockets/", {"court": court, "pacer_case_id": pacer,
                                 "fields": "id,case_name,docket_number,court_id,date_filed,date_terminated,"
                                           "nature_of_suit,cause,assigned_to_str"})
    rows = (found or {}).get("results") or []
    if not rows:
        return "nocl"
    k = rows[0]
    if not k.get("date_terminated"):
        return "open"
    if re.fullmatch(r"[a-z]{2,3}[nsewmc]?b", court) and not L.BUSINESS.search(k.get("case_name") or ""):
        return "personal"
    cnt = cl_get("/recap-documents/", {"docket_entry__docket": k["id"], "is_available": "true", "count": "on"})
    n = int((cnt or {}).get("count") or 0)
    if n < MIN_DOCS:
        return "few"
    if n > MAX_DOCS:
        return "huge"
    entries, pdfs = [], {}
    for e in cl_all("/docket-entries/", {"docket": k["id"]}):
        docs = []
        for rd in e.get("recap_documents") or []:
            dn = str(rd.get("document_number") or e.get("entry_number") or "")
            att = int(rd.get("attachment_number") or 0)
            docs.append((dn, att, rd.get("description") or ""))
            if rd.get("is_available") and rd.get("filepath_local") and dn:
                pdfs[(dn, att)] = (f"https://storage.courtlistener.com/{rd['filepath_local']}",
                                   int(rd.get("file_size") or 0))
        entries.append((e.get("entry_number"), e.get("date_filed") or "", e.get("description") or "", docs))
    if len(pdfs) < MIN_DOCS:
        return "few"
    if sum(x[1] for x in pdfs.values()) > 4e9:
        return "huge"
    parties = []
    atty = {a["id"]: a for a in cl_all("/attorneys/", {"docket": k["id"]})}
    for p in cl_all("/parties/", {"docket": k["id"]}):
        parties.append({"name": p.get("name"),
                        "party_types": [{"name": (t.get("name") or "")} for t in p.get("party_types") or []],
                        "attorneys": [{"name": (atty.get(a.get("attorney_id")) or {}).get("name") or "",
                                       "contact_raw": (atty.get(a.get("attorney_id")) or {}).get("contact_raw") or ""}
                                      for a in p.get("attorneys") or []]})
    entries.sort(key=lambda e: int(e[0]) if str(e[0] or "").isdigit() else 10 ** 9)
    d = dict(case_name=k.get("case_name"), docket=k.get("docket_number") or "", court=court,
             filed=k.get("date_filed"), terminated=k.get("date_terminated"), nos=k.get("nature_of_suit") or "",
             cause=k.get("cause") or "", judge=k.get("assigned_to_str"), entries=entries,
             raw={"parties": parties})
    return d, pdfs, court, k["date_terminated"]


def lit_parties(d):
    people, orgs = set(), {}
    raw = d.get("raw") or {}
    side_n = collections.Counter()

    def org(name, role):
        side_n[role] += 1
        orgs.setdefault(name, f"{role} Company {side_n[role]}")

    for p in raw.get("parties") or []:
        name = (p.get("name") or "").strip()
        role = ((p.get("party_types") or [{}])[0].get("name") or "Party").split()[0].title()
        if name:
            (org(name, role) if L.BUSINESS.search(name) else people.add(name))
        for a in p.get("attorneys") or []:
            if a.get("name"):
                people.add(a["name"].strip())
            firm = (a.get("contact_raw") or "").split("\n")[0].strip()
            if firm and L.BUSINESS.search(firm) or re.search(r"\b(LLP|PLLC|P\.C\.|P\.A\.|Law|Attorneys?)\b", firm):
                orgs.setdefault(firm, "Law Firm")
    if d.get("xml"):
        try:
            root = L.ET.fromstring(d["xml"])
            for p in root.iter("party"):
                name = (p.findtext("name") or "").strip()
                role = ((p.findtext("type") or "Party").split() or ["Party"])[0].title()
                if name:
                    (org(name, role) if L.BUSINESS.search(name) else people.add(name))
                for a in p.iter("attorney"):
                    if (a.findtext("name") or "").strip():
                        people.add(a.findtext("name").strip())
        except L.ET.ParseError:
            pass
    cn = d.get("case_name") or ""
    sides = re.split(r"\s+v(?:s)?\.?\s+", re.sub(r"^In re:?\s+", "", cn, flags=re.I), maxsplit=1)
    for role, s in zip(("Plaintiff", "Defendant"), sides):
        s = re.sub(r",?\s+et al\.?$", "", s.strip(), flags=re.I)
        if s and not re.fullmatch(r"(USA|United States( of America)?)", s, re.I):
            if L.BUSINESS.search(s) or not norm_person(s):
                orgs.setdefault(s, f"{role} Company {side_n[role] + 1}")
                side_n[role] += 1
            else:
                people.add(s)
    if d.get("judge"):
        people.add(d["judge"])
    people = {n for n in (norm_person(x) for x in people) if n}
    for p in list(people):  # "SMITH, JOHN A." -> John A. Smith
        m = re.fullmatch(r"([A-Za-z'’-]+),\s+(.+)", p)
        if m:
            people.add(f"{m.group(2)} {m.group(1)}")
    return people, orgs


def court_name(court):
    c = court.lower()
    if c in L.CIRCUITS:
        return f"US Court of Appeals for the {L.CIRCUITS[c]}"
    if c in L.OTHER:
        return L.OTHER[c]
    m = re.fullmatch(r"(nmi|[a-z]{2})([nsewmc]?)(d|b)", c)
    if not m:
        return c.upper()
    st, side, kind = m.groups()
    place = (f"{L.SIDE[side]} District of " if side else "District of ") + L.STATES.get(st, st.upper())
    return ("US Bankruptcy Court, " if kind == "b" else "US District Court, ") + place


def practice(court, docket, nos, name):
    c = court.lower()
    if re.fullmatch(r"[a-z]{2,3}[nsewmc]?b", c):
        return "Bankruptcy & Restructuring", "Business bankruptcy case (US Bankruptcy Court)"
    if c in L.CIRCUITS:
        return "Appellate", "Federal appeal (US Court of Appeals)"
    if re.search(r"-(cr|mj)-", docket or ""):
        return "White Collar & Criminal Defense", "Federal criminal prosecution (US District Court)"
    label = re.sub(r"^\d+\s*", "", nos or "").strip() or "General Civil"
    area = {"securities": "Securities Litigation", "antitrust": "Antitrust", "patent": "Intellectual Property",
            "trademark": "Intellectual Property", "copyright": "Intellectual Property", "contract": "Commercial "
            "Litigation", "civil rights": "Civil Rights", "employ": "Labor & Employment", "labor": "Labor & "
            "Employment", "erisa": "Employee Benefits (ERISA)", "insurance": "Insurance Coverage",
            "product liability": "Product Liability", "fraud": "Fraud & Consumer Protection",
            "environment": "Environmental", "tax": "Tax", "real property": "Real Estate"}
    for k, v in area.items():
        if k in label.lower():
            return v, f"Federal civil litigation - {label} (US District Court)"
    return "Commercial Litigation", f"Federal civil litigation - {label} (US District Court)"


def lit_matter(drive, ident, meta, minutes, sample=0):
    files = (meta or {}).get("files") or []
    pdfs = {}
    for f in files:
        m = re.fullmatch(re.escape(ident + ".") + r"(\d+)\.(\d+)\.pdf", f["name"])
        if m:
            pdfs[(m.group(1), int(m.group(2)))] = (f"{IA}/download/{ident}/{f['name']}", int(f.get("size") or 0))
    mains = {d for d, a in pdfs if a == 0}
    if CL_TOKEN:  # CourtListener holds the fuller docket and more documents than the archive copy
        got = cl_docket(ident)
        if isinstance(got, tuple):
            d, pdfs, court, terminated = got
            return lit_build(drive, ident, d, pdfs, court, terminated, minutes, sample)
        if got != "nocl":
            return got
    if len(pdfs) < MIN_DOCS or "1" not in mains:
        return "few"
    if len(pdfs) > MAX_DOCS or sum(s for _, s in pdfs.values()) > 4e9:
        return "huge"
    d = L.parse_docket(ident, files)
    if not d or not d["entries"]:
        return "nodocket"
    terminated = d.get("terminated") or (meta.get("metadata") or {}).get("date-case-terminated")
    if not terminated:
        return "open"
    court = d["court"] or ident.split(".")[2]
    if re.fullmatch(r"[a-z]{2,3}[nsewmc]?b", court) and not L.BUSINESS.search(d["case_name"] or ""):
        return "personal"
    numbered = [int(e[0]) for e in d["entries"] if str(e[0] or "").isdigit()]
    top = max(int(m) for m in mains if m.isdigit())
    last = max(numbered + [top])
    if len(mains) / last < 0.5 or top < 0.85 * last:
        return "incomplete"
    return lit_build(drive, ident, d, pdfs, court, terminated, minutes, sample)


def lit_build(drive, ident, d, pdfs, court, terminated, minutes, sample=0):
    """d: docket dict (case facts, entries, raw parties); pdfs: {(doc no, attachment): (url, size)}"""
    mid = "L-" + hashlib.sha1(ident.encode()).hexdigest()[:6].upper()
    log(f"  matter {mid}: {len(pdfs)} documents, downloading")
    dates = {str(e[0]): (e[1] or "")[:10] for e in d["entries"]}
    texts = {str(e[0]): e[2] for e in d["entries"]}
    descs = {(str(dn), att): desc for e in d["entries"] for dn, att, desc in e[3]}
    order = sorted(pdfs, key=lambda k: (int(k[0]) if k[0].isdigit() else 10 ** 9, k[1]))
    if sample:
        order = order[:sample]
    raw_dir, out_dir = tempfile.mkdtemp(prefix="raw-"), tempfile.mkdtemp(prefix="matter-")
    jobs = [(pdfs[k][0], f"{k[0]}.{k[1]}.pdf") for k in order]
    download_all(jobs, raw_dir)
    missing = [j for j in jobs if not os.path.exists(os.path.join(raw_dir, j[1]))]
    if missing:  # second attempt, slower, so nothing is left out for a passing network error
        time.sleep(20)
        download_all(missing, raw_dir, threads=2)
    have =[k for k in order if os.path.exists(os.path.join(raw_dir, f"{k[0]}.{k[1]}.pdf"))]
    people, orgs = lit_parties(d)
    docs = []
    for dn, att in have:
        label = descs.get((dn, att)) or (texts.get(dn) if att == 0 else f"Attachment {att}") or f"Document {dn}"
        docs.append((f"{dn}.{att}.pdf", (dn, att, dates.get(dn, ""), label)))
    # file names need the final redactor (names found in the documents too): build names after processing
    tmp_docs = [(r, f"{i:05d}.pdf") for i, (r, _) in enumerate(docs)]
    res = process_matter(ident, tmp_docs, raw_dir, out_dir, people, orgs, minutes)
    shutil.rmtree(raw_dir, ignore_errors=True)
    if res is None:
        shutil.rmtree(out_dir, ignore_errors=True)
        return "time"
    red, kept, stats = res
    names = {}
    final = tempfile.mkdtemp(prefix="final-")
    shifted = []
    for i, (r, (dn, att, date, label)) in enumerate(docs):
        rel = f"{i:05d}.pdf"
        if rel not in kept:
            continue
        sd = red.date_iso(date)
        shifted.append(sd)
        num = f"{int(dn):04d}" if dn.isdigit() else clean(dn, 10)
        fn = " ".join(x for x in (f"{num}{'-%02d' % att if att else ''}", sd, clean(red.text(label), 70)) if x)
        fn += ".pdf"
        os.replace(os.path.join(out_dir, rel), os.path.join(final, fn))
        names[rel] = fn
    shutil.rmtree(out_dir, ignore_errors=True)
    n = len(os.listdir(final))
    log(f"  matter {mid}: kept {n}, {json.dumps({k: v for k, v in stats.items() if k != 'flagged'})}")
    if n < MIN_DOCS and not sample:
        shutil.rmtree(final, ignore_errors=True)
        return "under500"
    area, mtype = practice(court, d["docket"], d["nos"], d["case_name"])
    juris = "United States - federal; " + court_name(court)
    first = red.date_iso(d.get("filed") or "") or min([x for x in shifted if x] or [""])
    rng = f"{first} to {red.date_iso(terminated)}"
    facts = [("Practice area", area), ("Matter type", mtype), ("Jurisdiction", juris),
             ("Status", "Concluded (case terminated)"), ("Date range", rng),
             ("Document count", f"{n} documents (every docket document and attachment in the public record)"),
             ("Record type", "Public court record of a concluded US federal case (docket and filings)"),
             ("Redaction", REDACTION_NOTE)] + flag_facts(stats, names)
    rows = [(no or "", red.date_iso(date), red.text(text), "") for no, date, text, _ in d["entries"]]
    dest = f"{P}Litigation/{clean(area, 50)}/Matter {mid}"
    if sample:
        shutil.copytree(final, os.path.join("sample", mid), dirs_exist_ok=True)
        L.timeline_pdf(os.path.join("sample", mid, "00 Matter Timeline.pdf"), mid, [], rows)
        summary_pdf(os.path.join("sample", mid, "00 Matter Summary.pdf"), mid, facts)
        shutil.rmtree(final, ignore_errors=True)
        return f"ok {n}"
    ok = finish(drive, mid, final, dest, red, facts, rows, n,
                {"matter": mid, "practice area": area, "matter type": mtype, "jurisdiction": juris,
                 "date range": rng, "documents": n, "folder": dest})
    shutil.rmtree(final, ignore_errors=True)
    return f"ok {n}" if ok else "failed"


def law_done(drive):
    """RECAP cases already in LAW: not repeated here."""
    seen = set()
    for job in ("recap-0of2", "recap-1of2", "enron-0of1"):
        r = subprocess.run(["rclone", "cat", f"{LAW_REMOTE}LAW - private/state-{job}.json"], capture_output=True,
                           text=True)
        if r.returncode == 0 and r.stdout.strip():
            seen |= set(json.loads(r.stdout).get("done", []))
    return seen


def litigation(drive, minutes, lane, max_files, sample=0):
    k, n = lane
    st = drive.state
    skip_law = law_done(drive) if drive.live else set()
    lo = 15000000
    q = f"collection:usfederalcourts AND mediatype:texts AND item_size:[{lo} TO 4000000000]"
    stats = st.setdefault("stats", {})
    while left(minutes) > 1800:
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
        ids = [x["identifier"] for x in page.get("items", []) if x["identifier"].startswith("gov.uscourts.")
               and zlib.crc32(x["identifier"].encode()) % n == k]
        ids = [i for i in ids if i not in drive.done and i not in drive.skip and i not in skip_law]
        log(f"page: {len(ids)} candidates; {len(drive.done)} matters, {st['files']} files so far")
        for ident in ids:
            if left(minutes) < 1800:
                return
            r = get(f"{IA}/metadata/{ident}", timeout=120)
            res = lit_matter(drive, ident, r.json(), minutes, sample) if r else "nometa"
            key = res.split()[0]
            stats[key] = stats.get(key, 0) + 1
            if res.startswith("ok"):
                drive.done.add(ident)
                drive.save()
                if sample:
                    return
            elif res not in ("failed", "nometa", "time", "open"):
                drive.skip.add(ident)
        nxt = page.get("cursor")
        st["cursor"] = nxt
        drive.save()
        log(f"checked: {json.dumps(stats)}")
        if not nxt:
            log("end of the archive listing")
            return


# ---------------------------------------------------------------- transactions (SEC EDGAR)

SECS = requests.Session()
SECS.headers["User-Agent"] = os.environ.get("SEC_USER_AGENT") or "LAW research collector admin@example.com"
_lock, _last = threading.Lock(), [0.0]


def sget(url, tries=4):
    for i in range(tries):
        with _lock:
            wait = _last[0] + 0.13 - time.time()
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            r = SECS.get(url, timeout=60)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(3 + 5 * i)
    return None


def sfetch(url, path):
    r = sget(url)
    if not r:
        return False
    with open(path, "wb") as f:
        f.write(r.content)
    return True


def deal_candidates(year):
    out, frm = [], 0
    while True:
        r = sget(f"https://efts.sec.gov/LATEST/search-index?q=%22merger%22&forms=DEFM14A,SC%2014D9"
                 f"&dateRange=custom&startdt={year}-01-01&enddt={year}-12-31&from={frm}")
        if not r:
            break
        hits = r.json()["hits"]["hits"]
        for h in hits:
            s = h["_source"]
            if s.get("ciks") and s.get("form") in ("DEFM14A", "SC 14D9"):
                out.append((int(s["ciks"][0]), s["file_date"], s["form"], s["display_names"][0]))
        frm += len(hits)
        if not hits or frm >= 1000:
            break
    return out


ITEMS = {}  # accession -> 8-K item numbers


def submissions(cik):
    r = sget(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    if not r:
        return None, []
    d = r.json()
    rows = []

    def add(b):
        for i in range(len(b["form"])):
            rows.append((b["filingDate"][i], b["form"][i], b["accessionNumber"][i]))
            if b.get("items") and b["items"][i]:
                ITEMS[b["accessionNumber"][i]] = b["items"][i]
    add(d["filings"]["recent"])
    for f in d["filings"].get("files") or []:
        r2 = sget(f"https://data.sec.gov/submissions/{f['name']}")
        if r2:
            add(r2.json())
    return d, sorted(set(rows))


def filing_docs(cik, acc):
    """-> [(seq, type, description, filename, url)] real documents of one filing (no graphics/XBRL)."""
    nod = acc.replace("-", "")
    r = sget(f"https://www.sec.gov/Archives/edgar/data/{cik}/{nod}/{acc}-index.htm")
    if not r:
        return [], []
    out = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", r.text):
        cells = re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)
        if len(cells) < 4:
            continue
        seq = re.sub(r"<[^>]+>", "", cells[0]).strip()
        href = re.search(r'href="([^"]+)"', cells[2])
        typ = re.sub(r"<[^>]+>", "", cells[3]).strip()
        if not seq.isdigit() or not href:
            continue
        name = href.group(1).split("/")[-1].split("?")[0]
        if (not re.search(r"\.(htm|html|txt|pdf|xml)$", name, re.I) or re.match(r"(GRAPHIC|ZIP|EX-101|XML|JSON)", typ)
                or re.fullmatch(r"R\d+\.htm", name) or (name.lower().endswith(".xml") and "/xsl" not in href.group(1)
                                                          and any(x[3].lower() == name.lower() for x in out))):
            continue
        desc = html.unescape(re.sub(r"<[^>]+>", "", cells[1])).strip()
        out.append((int(seq), typ, desc, name, "https://www.sec.gov" + href.group(1)
                    if href.group(1).startswith("/") else href.group(1)))
    filers = [(n.strip(), role.strip(), int(c)) for n, role, c in re.findall(
        r"(?is)<span class=\"companyName\">\s*([^<(]+)\(([^)]*)\).*?CIK=(\d+)", r.text)]
    return out, filers


def deal_matter(drive, cik, defm, form, minutes, sample=0):
    d, rows = submissions(cik)
    if not d:
        return "nometa"
    t0 = dt.date.fromisoformat(defm)
    close = [r for r in rows if r[1] in ("15-12B", "15-12G", "15-15D", "25-NSE") and
             t0 < dt.date.fromisoformat(r[0]) <= t0 + dt.timedelta(days=730)]
    if not close:
        return "notclosed"
    end = dt.date.fromisoformat(close[0][0])
    pre = [r for r in rows if r[1] in ("425", "DEFA14A", "PREM14A", "SC 14D9-C", "SC TO-C", "SC 14D9")
           and t0 - dt.timedelta(days=300) <= dt.date.fromisoformat(r[0]) <= t0]
    start = dt.date.fromisoformat(pre[0][0]) - dt.timedelta(days=4) if pre else t0 - dt.timedelta(days=120)
    win = [r for r in rows if start <= dt.date.fromisoformat(r[0]) <= end + dt.timedelta(days=5)]
    if not win:
        return "few"
    mid = "T-" + hashlib.sha1(f"{cik}{defm}".encode()).hexdigest()[:6].upper()
    filings, names, people, ndocs, seen = [], set(), set(), 0, set()
    parties = collections.Counter()

    def take(c, date, frm, acc):
        nonlocal ndocs
        if acc in seen:
            return
        seen.add(acc)
        docs, filers = filing_docs(c, acc)
        for n, role, fc in filers:
            if L.BUSINESS.search(n) or "reporting" not in role.lower():
                names.add(n)
                if fc != cik and frm.split("/")[0] in ("425", "S-4", "SC TO-T", "SC TO-C", "SC 13E3", "DEFM14A",
                                                        "SC 13D", "DEFA14A"):
                    parties[fc] += 1
            else:
                people.add(n)
        if docs:
            filings.append((date, frm, acc, docs, c))
            ndocs += len(docs)

    for date, frm, acc in win:
        take(cik, date, frm, acc)
        if left(minutes) < 1800:
            return "time"
    # the other side of the deal (buyer / tender offeror): its deal filings in the same period
    acq_forms = {"425", "S-4", "S-4/A", "S-4MEF", "424B3", "SC TO-T", "SC TO-T/A", "SC TO-C", "SC 13D", "SC 13D/A",
                 "SC 13E3", "SC 13E3/A", "DEFA14A", "EFFECT", "S-4 POS", "POS AM", "8-K", "8-K/A"}
    for pc, _ in parties.most_common(2):
        _, prow = submissions(pc)
        for date, frm, acc in prow:
            if (start <= dt.date.fromisoformat(date) <= end + dt.timedelta(days=5) and frm in acq_forms
                    and (not frm.startswith("8-K") or re.search(r"\b(1\.01|2\.01)\b", ITEMS.get(acc, "")))):
                take(pc, date, frm, acc)
        if left(minutes) < 1800:
            return "time"
    filings.sort()
    if ndocs < DEAL_MIN or ndocs > MAX_DOCS * 2:
        return "few" if ndocs < DEAL_MIN else "huge"
    log(f"  matter {mid}: {len(filings)} filings, {ndocs} documents, downloading")
    raw_dir, out_dir = tempfile.mkdtemp(prefix="raw-"), tempfile.mkdtemp(prefix="matter-")
    plan, jobs = [], []
    for fi, (date, frm, acc, docs, _) in enumerate(filings, 1):
        for seq, typ, desc, name, url in docs:
            ext = ".htm" if "/xsl" in url else os.path.splitext(name)[1].lower().replace(".html", ".htm")
            rawname = f"{acc}-{seq}{ext}"
            jobs.append((url, rawname))
            plan.append((rawname, fi, date, frm, seq, typ, desc, ext))
    if sample:
        jobs, plan = jobs[:sample], plan[:sample]
    with cf.ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda j: sfetch(j[0], os.path.join(raw_dir, j[1])), jobs))
    plan = [p for p in plan if os.path.exists(os.path.join(raw_dir, p[0]))]
    target = {n for n in [d.get("name") or ""] + [x.get("name") for x in d.get("formerNames") or []] if n}
    orgs = {n: "Target Company" for n in target}
    k = 0
    for n in sorted(names):
        if n.upper() not in {t.upper() for t in target}:
            k += 1
            orgs.setdefault(n, f"Counterparty Company {k}")
    res = process_matter(f"{cik}-{defm}", [(p[0], p[0]) for p in plan], raw_dir, out_dir, people, orgs, minutes)
    shutil.rmtree(raw_dir, ignore_errors=True)
    if res is None:
        shutil.rmtree(out_dir, ignore_errors=True)
        return "time"
    red, kept, stats = res
    names = {}
    final = tempfile.mkdtemp(prefix="final-")
    kept = set(kept)
    tl = {}
    for rawname, fi, date, frm, seq, typ, desc, ext in plan:
        if rawname not in kept:
            continue
        sd = red.date_iso(date)
        sub = f"{fi:03d} {sd} {clean(frm.replace('/', '-'), 20)}"
        os.makedirs(os.path.join(final, sub), exist_ok=True)
        fn = f"{seq:02d} {clean(typ.replace('/', '-'), 20)} - {clean(red.text(desc) or typ, 60)}{ext}"
        os.replace(os.path.join(out_dir, rawname), os.path.join(final, sub, fn))
        names[rawname] = f"{sub}/{fn}"
        tl.setdefault((fi, sd, frm), []).append(fn)
    shutil.rmtree(out_dir, ignore_errors=True)
    n = sum(len(v) for v in tl.values())
    log(f"  matter {mid}: kept {n}, {json.dumps({k: v for k, v in stats.items() if k != 'flagged'})}")
    if n < DEAL_MIN and not sample:
        shutil.rmtree(final, ignore_errors=True)
        return "under500"
    tender = form == "SC 14D9"
    mtype = "Public company acquisition - " + ("tender offer" if tender else "merger with shareholder vote")
    inc = d.get("stateOfIncorporation") or ""
    juris = "United States - federal securities law (SEC)" + (f"; incorporated in {L.STATES.get(inc.lower(), inc)}"
                                                               if inc else "")
    rng = f"{red.date_iso(start.isoformat())} to {red.date_iso(end.isoformat())}"
    facts = [("Practice area", "Mergers & Acquisitions"), ("Matter type", mtype), ("Jurisdiction", juris),
             ("Status", "Completed (target delisted / registration ended)"), ("Date range", rng),
             ("Document count", f"{n} documents in {len(tl)} filings (every filing and exhibit, announcement to "
                                f"closing)"),
             ("Record type", "Public SEC filing record of a completed acquisition"), ("Redaction", REDACTION_NOTE)] + flag_facts(stats, names)
    rows = [(fi, sd, frm, "; ".join(v)) for (fi, sd, frm), v in sorted(tl.items())]
    dest = f"{P}Transactions/Mergers and Acquisitions/Matter {mid}"
    if sample:
        shutil.copytree(final, os.path.join("sample", mid), dirs_exist_ok=True)
        summary_pdf(os.path.join("sample", mid, "00 Matter Summary.pdf"), mid, facts)
        shutil.rmtree(final, ignore_errors=True)
        return f"ok {n}"
    ok = finish(drive, mid, final, dest, red, facts, rows, n,
                {"matter": mid, "practice area": "Mergers & Acquisitions", "matter type": mtype,
                 "jurisdiction": juris, "date range": rng, "documents": n, "folder": dest})
    shutil.rmtree(final, ignore_errors=True)
    return f"ok {n}" if ok else "failed"


def transactions(drive, minutes, lane, max_files, sample=0):
    k, n = lane
    st = drive.state
    stats = st.setdefault("stats", {})
    for year in range(2023, 2004, -1):
        if str(year) in st.setdefault("years", []):
            continue
        cands = [c for c in deal_candidates(year) if c[0] % n == k]
        log(f"{year}: {len(cands)} candidate deals")
        for cik, date, form, name in cands:
            key = f"{cik}:{date}"
            if key in drive.done or key in drive.skip:
                continue
            if left(minutes) < 1800 or (max_files and st["files"] >= max_files):
                return
            res = deal_matter(drive, cik, date, form, minutes, sample)
            stats[res.split()[0]] = stats.get(res.split()[0], 0) + 1
            if res.startswith("ok"):
                drive.done.add(key)
                drive.save()
                if sample:
                    return
            elif res not in ("failed", "nometa", "time"):
                drive.skip.add(key)
                drive.save()
        st["years"].append(str(year))
        drive.save()
        log(f"checked: {json.dumps(stats)}")


# ---------------------------------------------------------------- Nuremberg (International Military Tribunal)
# user 2026-11-09: the full Nuremberg trial record from the Avalon Project (Yale Law School): every court document
# (charter, indictment, rules, orders, judgment, sentences) and the transcript of every hearing day.

AVALON = "https://avalon.law.yale.edu"
IMT_PEOPLE = ["Hermann Goering", "Hermann Göring", "Rudolf Hess", "Joachim von Ribbentrop", "Wilhelm Keitel",
              "Ernst Kaltenbrunner", "Alfred Rosenberg", "Hans Frank", "Wilhelm Frick", "Julius Streicher",
              "Walther Funk", "Hjalmar Schacht", "Karl Doenitz", "Karl Dönitz", "Erich Raeder", "Baldur von Schirach",
              "Fritz Sauckel", "Alfred Jodl", "Franz von Papen", "Arthur Seyss-Inquart", "Albert Speer",
              "Constantin von Neurath", "Hans Fritzsche", "Martin Bormann", "Robert Ley", "Gustav Krupp",
              "Robert H. Jackson", "Geoffrey Lawrence", "Hartley Shawcross", "Francis Biddle", "John J. Parker",
              "Henri Donnedieu de Vabres", "Iona Nikitchenko", "Roman Rudenko", "Norman Birkett", "David Maxwell-Fyfe",
              "Adolf Hitler", "Heinrich Himmler", "Reinhard Heydrich", "Joseph Goebbels", "Rudolf Hoess"]


def nuremberg(drive, minutes, lane, max_files, sample=0):
    if "imt" in drive.done:
        log("Nuremberg trial already done")
        return
    menu = get(f"{AVALON}/subject_menus/imt.asp", timeout=60)
    if not menu:
        return
    items, seen = [], set()

    def take(page, tag):
        for href, text in re.findall(r'(?i)href="\.\./imt/([^"#]+\.asp)"[^>]*>(.*?)</a', page, re.S):
            if href not in seen:
                seen.add(href)
                items.append((f"{AVALON}/imt/{href}", clean(re.sub(r"<[^>]+>", " ", text), 80), tag))

    take(menu.text, "court")
    for v in range(1, 23):
        r = get(f"{AVALON}/subject_menus/imtproc_v{v}menu.asp", timeout=60)
        if r:
            take(r.text, f"vol{v}")
    if sample:
        items = items[:sample]
    log(f"Nuremberg: {len(items)} documents")
    raw_dir, out_dir = tempfile.mkdtemp(prefix="raw-"), tempfile.mkdtemp(prefix="matter-")
    jobs = [(u, f"{i:04d}.htm") for i, (u, _, _) in enumerate(items, 1)]
    download_all(jobs, raw_dir, threads=3)
    missing = [j for j in jobs if not os.path.exists(os.path.join(raw_dir, j[1]))]
    if missing:
        time.sleep(20)
        download_all(missing, raw_dir, threads=1)
    have = [(j[1], j[1]) for j in jobs if os.path.exists(os.path.join(raw_dir, j[1]))]
    res = process_matter("avalon-imt", have, raw_dir, out_dir, set(IMT_PEOPLE), {}, minutes)
    shutil.rmtree(raw_dir, ignore_errors=True)
    if res is None:
        return
    red, kept, stats = res
    names, rows, shifted = {}, [], []
    final = tempfile.mkdtemp(prefix="final-")
    for i, (u, title, tag) in enumerate(items, 1):
        rel = f"{i:04d}.htm"
        if rel not in kept:
            continue
        m = re.search(r"/(\d{1,2})-(\d{1,2})-(\d{2})\.asp$", u)
        date = _date(1900 + int(m.group(3)), m.group(1), m.group(2)) if m else None
        sd = red.shift(date).isoformat() if date else ""
        if sd:
            shifted.append(sd)
        sub = "01 Court Documents" if tag == "court" else "02 Trial Transcripts"
        os.makedirs(os.path.join(final, sub), exist_ok=True)
        fn = " ".join(x for x in (f"{i:04d}", sd, clean(red.text(title), 70)) if x) + ".htm"
        os.replace(os.path.join(out_dir, rel), os.path.join(final, sub, fn))
        names[rel] = f"{sub}/{fn}"
        rows.append((i, sd, red.text(title), fn))
    shutil.rmtree(out_dir, ignore_errors=True)
    n = sum(len(f) for _, _, f in os.walk(final))
    log(f"  Nuremberg: kept {n}, {json.dumps({k: v for k, v in stats.items() if k != 'flagged'})}")
    mid = "L-" + hashlib.sha1(b"avalon-imt").hexdigest()[:6].upper()
    start = red.shift(dt.date(1945, 8, 8)).isoformat()
    end = red.shift(dt.date(1946, 10, 16)).isoformat()
    rng = f"{start} to {end}"
    area, mtype = "International Criminal Law", "International war crimes trial (international military tribunal)"
    juris = "International - four-power international military tribunal (Germany)"
    facts = [("Practice area", area), ("Matter type", mtype), ("Jurisdiction", juris),
             ("Status", "Concluded (judgment and sentences delivered)"), ("Date range", rng),
             ("Document count", f"{n} documents: court documents and the transcript of every hearing day "
                                f"(fewer than 500 - kept at the user's request)"),
             ("Record type", "Published official trial record (Avalon Project, Yale Law School)"),
             ("Redaction", REDACTION_NOTE)] + flag_facts(stats, names)
    dest = f"{P}Litigation/{area}/Matter {mid}"
    if sample:
        shutil.copytree(final, os.path.join("sample", mid), dirs_exist_ok=True)
        summary_pdf(os.path.join("sample", mid, "00 Matter Summary.pdf"), mid, facts)
        shutil.rmtree(final, ignore_errors=True)
        return
    if finish(drive, mid, final, dest, red, facts, rows, n,
              {"matter": mid, "practice area": area, "matter type": mtype, "jurisdiction": juris,
               "date range": rng, "documents": n, "folder": dest}):
        drive.done.add("imt")
        drive.save()
    shutil.rmtree(final, ignore_errors=True)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["litigation", "transactions", "nuremberg"], required=True)
    ap.add_argument("--lane", default="0/1")
    ap.add_argument("--remote", default="ws:")
    ap.add_argument("--minutes", type=float, default=300)
    ap.add_argument("--max-files", type=int, default=0)
    ap.add_argument("--sample", type=int, default=0, help="test: one matter, first N documents, to ./sample")
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    k, n = map(int, a.lane.split("/"))
    job = f"matters-{a.source}-{k}of{n}" + ("-sample" if a.sample else "")
    drive = L.Drive(a.remote if a.remote.endswith(":") else a.remote + ":", job, a.live and not a.sample)
    log(f"{job}: {len(drive.done)} matters done before, live={drive.live}")
    try:
        {"litigation": litigation, "transactions": transactions, "nuremberg": nuremberg}[a.source](drive, a.minutes, (k, n), a.max_files,
                                                                           a.sample)
    finally:
        drive.save()
        log(f"{job}: {len(drive.done)} matters, {drive.state['files']} files uploaded in total")


if __name__ == "__main__":
    main()
