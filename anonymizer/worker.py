"""Anonymises earnings documents before they are uploaded.

Runs as a long-lived worker: the first stdin line is a config message, every
following line is one job. Each job reads a file, writes the anonymised copy and
answers with one JSON line on stdout.

  config: {"type": "config", "companies": [...], "company": true, "personal": true}
  job:    {"id": 1, "in": "/tmp/a.pdf", "out": "/tmp/b.pdf", "ext": "pdf", "ticker": "JPM"}
  reply:  {"id": 1, "ok": true, "ext": "pdf", "stats": {...}}

Company identity: every alias, the ticker in safe forms, web domains, the SEC CIK,
commission file number and EIN are replaced with the company code (or a tag).
Personal data: e-mail addresses, phone numbers and people's names (spaCy NER),
plus document author metadata. PDFs are truly redacted (text removed, not covered).

Test one file:  python worker.py --test companies.json TICKER in.pdf out.pdf
"""
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

NAME_TOKEN = r"[A-Z][a-zA-Z'’.\-]+"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Real phone layouts only ((212) 555-0100, 212-555-0100, 212.555.0100, +1 212 555 0100),
# not runs of numbers in financial tables.
PHONE_RE = re.compile(r"(?<![\w$.,%])(?:\+1[\s.\-]?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}|\(\d{3}\)[\s ]?\d{3}-\d{4}|\d{3}-\d{3}-\d{4}|\d{3}\.\d{3}\.\d{4})(?![\w,]|\.\d)")
EIN_RE = re.compile(r"(?<![\w\-])\d{2}-\d{7}(?![\w\-])")
FILE_NO_RE = re.compile(r"(?<![\w\-])(?:0\d{2}|333)-\d{5,6}(?![\w\-])")
EXCHANGES = r"(?:NYSE|NASDAQ|Nasdaq|NasdaqGS|Nasdaq Global Select Market|New York Stock Exchange|Nasdaq Stock Market)"
# Tickers that are ordinary English words in upper case; only replaced in safe forms.
WORD_TICKERS = {"LOW", "CAT", "COST", "DIS", "ALL", "PEP", "HON", "AMP", "KEY", "NOW", "ON", "IT", "ARE", "SO", "DE", "MO", "EL", "CL", "MA", "MS", "GS", "PM", "BA", "GE", "HD", "DG", "KO", "VZ"}
NER_MAX_CHARS = 3_000_000
NER_CHUNK = 100_000
OOXML_TEXT_PARTS = re.compile(r"^(word/.*\.xml|ppt/.*\.xml|xl/sharedStrings\.xml|xl/worksheets/sheet\d+\.xml|xl/comments\d*\.xml|xl/charts/.*\.xml|xl/drawings/.*\.xml|docProps/.*\.xml)$")
# Formats converted with LibreOffice before anonymising, so only documents reach Drive.
LEGACY = {"xls": "xlsx", "doc": "docx", "ppt": "pptx", "csv": "xlsx", "txt": "docx"}

nlp = None


def load_nlp():
    global nlp
    if nlp is None:
        try:
            import spacy

            nlp = spacy.load("en_core_web_sm", exclude=["parser", "lemmatizer", "attribute_ruler", "tagger", "senter"])
            nlp.max_length = NER_CHUNK + 10_000
        except Exception as err:  # noqa: BLE001
            sys.stderr.write(f"spaCy unavailable, people's names will not be redacted: {err}\n")
            nlp = False
    return nlp


def flex(term):
    """Regex for a literal term whose spaces may be any whitespace or missing ("JPMorganChase")."""
    parts = [re.escape(p) for p in term.split(" ")]
    return r"[\s ]*".join(parts)


def squash(text):
    return re.sub(r"[\s ]+", "", text)


def bounded(body):
    # Not inside a longer word, but a following capital or digit is allowed so that
    # XBRL identifiers ("MicrosoftCloudMember") and footnote marks ("Intel1") match.
    return rf"(?<![A-Za-z0-9]){body}(?![a-z])"


class Rules:
    def __init__(self, config):
        self.do_company = config.get("company", True)
        self.do_personal = config.get("personal", True)
        self.companies = {c["ticker"]: c for c in config["companies"]}
        self.alias_code = {}
        strong = []
        for c in config["companies"]:
            for alias in self._aliases(c):
                if self._strong(alias):
                    strong.append(alias)
                    self.alias_code.setdefault(squash(alias), c["code"])
        self.all_strong = self._union(strong)
        self.per_company = {}
        self.markup = {}

    @staticmethod
    def _aliases(c):
        out = []
        for a in [*(c.get("aliases") or []), c.get("name") or ""]:
            a = a.strip()
            if not a:
                continue
            out.append(a)
            if len(a) >= 6 and " " in a:
                out.append(a.upper())
            if "’" in a:
                out.append(a.replace("’", "'"))
            if "'" in a:
                out.append(a.replace("'", "’"))
        return list(dict.fromkeys(out))

    @staticmethod
    def _strong(alias):
        return len(alias) >= 6 or bool(re.search(r"[\s&.\-]", alias))

    @staticmethod
    def _union(terms):
        if not terms:
            return None
        terms = sorted(set(terms), key=len, reverse=True)
        return re.compile(bounded("(?:" + "|".join(flex(t) for t in terms) + ")"))

    def company(self, ticker):
        if ticker in self.per_company:
            return self.per_company[ticker]
        c = self.companies[ticker]
        code = c["code"]
        subs = []
        own = self._union(self._aliases(c))
        if own:
            subs.append((own, code))
        t = re.escape(ticker)
        subs.append((re.compile(rf"({EXCHANGES}\s*:\s*){t}(?![\w])"), rf"\g<1>{code}"))
        low = re.escape(ticker.lower().replace(".", ""))
        subs.append((re.compile(rf"(?<![\w]){low}(?=-20\d{{6}})"), code.lower()))
        # XBRL prefixes: name="msft:Revenue", xmlns:msft=..., msft:SatyaNadellaMember
        subs.append((re.compile(rf"(?<![\w\-]){low}(?=:[A-Z])"), code.lower()))
        if len(ticker) >= 3:
            subs.append((re.compile(rf"(?<![\w\-]){low}(?=[:_\-])"), code.lower()))
        # Namespace declarations are attribute names, which scrub_markup() otherwise leaves alone.
        self.markup.setdefault(ticker, re.compile(rf"(?<=xmlns:){low}(?==)"))
        if len(ticker) >= 3 and ticker not in WORD_TICKERS:
            subs.append((re.compile(bounded(t)), code))
        for cik in c.get("ciks") or []:
            subs.append((re.compile(rf"(CIK\W{{0,20}})0*{cik}(?!\d)", re.I), r"\g<1>[CIK]"))
            subs.append((re.compile(rf"(?<!\d){cik.zfill(10)}(?!\d)"), "[CIK]"))
            subs.append((re.compile(rf"(/data/){cik}(?=/)"), r"\g<1>[CIK]"))
        for d in c.get("domains") or []:
            subs.append((re.compile(rf"(?<![\w.\-])(?:[\w\-]+\.)*{re.escape(d)}(?![\w\-])", re.I), "[DOMAIN]"))
            stem = d.split(".")[0]
            if len(stem) >= 4:  # hosted IR sites such as jpmorganchaseco.gcs-web.com
                subs.append((re.compile(rf"(?<![\w.\-])[\w\-.]*{re.escape(stem)}[\w\-.]*\.[a-z]{{2,6}}(?![\w\-])", re.I), "[DOMAIN]"))
        self.per_company[ticker] = subs
        return subs


class Job:
    def __init__(self, rules, ticker):
        self.rules = rules
        self.ticker = ticker
        self.code = rules.companies[ticker]["code"]
        self.stats = {"company": 0, "email": 0, "phone": 0, "person": 0, "ids": 0, "metadata": 0}
        self.names_re = None

    # --- text rules -------------------------------------------------------
    def _sub(self, regex, repl, text, key):
        new, n = regex.subn(repl, text)
        self.stats[key] += n
        return new

    def scrub(self, text):
        if not text:
            return text
        r = self.rules
        if r.do_company:
            for regex, repl in r.company(self.ticker):
                text = self._sub(regex, repl, text, "company")
            if r.all_strong:
                text, n = r.all_strong.subn(lambda m: r.alias_code.get(squash(m.group(0)), self.code), text)
                self.stats["company"] += n
            text = self._sub(EIN_RE, "[EIN]", text, "ids")
            text = self._sub(FILE_NO_RE, "[FILE-NO]", text, "ids")
        if r.do_personal:
            text = self._sub(EMAIL_RE, "[EMAIL]", text, "email")
            text = self._sub(PHONE_RE, "[PHONE]", text, "phone")
            if self.names_re:
                text = self._sub(self.names_re, "[PERSON]", text, "person")
        return text

    def spans(self, text):
        """Character spans that scrub() would change, for PDF redaction."""
        r = self.rules
        regexes = []
        if r.do_company:
            regexes += [rx for rx, _ in r.company(self.ticker)]
            if r.all_strong:
                regexes.append(r.all_strong)
            regexes += [EIN_RE, FILE_NO_RE]
        if r.do_personal:
            regexes += [EMAIL_RE, PHONE_RE]
            if self.names_re:
                regexes.append(self.names_re)
        out = []
        for rx in regexes:
            for m in rx.finditer(text):
                start, end = m.span()
                if rx.groups and m.lastindex and rx.pattern.startswith("(") and m.group(1) is not None and m.start(1) == start:
                    start = m.end(1)  # keep the "NYSE:" / "CIK" prefix visible
                if end > start:
                    out.append((start, end))
        return out

    def learn_names(self, text):
        """Find people's names with NER and build one regex for them."""
        if not self.rules.do_personal or not text:
            return
        model = load_nlp()
        if not model:
            return
        text = text[:NER_MAX_CHARS]
        chunks = [text[i : i + NER_CHUNK] for i in range(0, len(text), NER_CHUNK)]
        # Words the document also uses in lower case ("statements", "gross") are ordinary
        # words, not names; this removes most of the NER's false positives in finance text.
        lower_words = set(re.findall(r"(?<![A-Za-z])[a-z][a-z'\-]+", text))
        own_terms = [a.lower() for a in Rules._aliases(self.rules.companies[self.ticker])]

        def plausible(tokens):
            for tk in tokens:
                if not (re.fullmatch(NAME_TOKEN, tk) or re.fullmatch(r"[A-Z]\.?", tk)):
                    return False
                if len(tk) > 2 and (tk.isupper() or tk.lower() in lower_words):
                    return False
            joined = " ".join(tokens).lower()
            return not any(t == joined or (len(t) > 3 and t in joined) for t in own_terms)

        names, singles = set(), set()
        for doc in model.pipe(chunks, batch_size=4):
            for ent in doc.ents:
                if ent.label_ != "PERSON":
                    continue
                tokens = re.sub(r"[\s ]+", " ", ent.text).strip(" .,'’").split(" ")
                if len(tokens) > 5:
                    continue
                # NER sometimes glues a heading on ("QoQ Jamie Dimon"): also try the tail.
                tails = [tokens[i:] for i in range(len(tokens) - 1)]
                full = [t for t in tails if plausible(t) and len(" ".join(t)) <= 40]
                for t in full:
                    names.add(" ".join(t))
                if len(tokens) == 1 and len(tokens[0]) >= 4 and plausible(tokens):
                    singles.add(tokens[0])
        # A lone surname ("Dimon added:") only counts when the full name is also present.
        surnames = {n.split(" ")[-1] for n in names}
        singles = {s for s in singles if s in surnames}
        surnames = {s for s in surnames if len(s) >= 4}
        if not names:
            return
        alts = sorted(names | singles | surnames, key=len, reverse=True)
        pattern = "|".join(flex(n) for n in alts)
        self.names_re = re.compile(rf"(?:(?:Mr|Ms|Mrs|Dr|Messrs)\.?[\s ]+)?" + bounded("(?:" + pattern + ")"))

    # --- formats ----------------------------------------------------------
    def text_file(self, data, is_html):
        text = decode(data)
        if is_html:
            visible = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
            visible = html.unescape(re.sub(r"<[^>]+>", " ", visible))
            self.learn_names(visible)
            parts = re.split(r"(<[^>]+>)", text)
            for i, part in enumerate(parts):
                if not part:
                    continue
                if part.startswith("<"):
                    parts[i] = self.scrub_markup(part)
                else:
                    parts[i] = html.escape(self.scrub(html.unescape(part)), quote=False)
            text = "".join(parts)
        else:
            self.learn_names(text)
            text = self.scrub(text)
        return text.encode("utf-8")

    def scrub_markup(self, tag):
        """Inside a tag only touch attribute values (links, titles, alt text)."""
        def fix(m):
            return m.group(1) + html.escape(self.scrub(html.unescape(m.group(2))), quote=True) + m.group(3)

        ns = self.rules.markup.get(self.ticker)
        if ns and self.rules.do_company:
            tag = ns.sub(self.code.lower(), tag)
        return re.sub(r'(=\s*")([^"]*)(")', fix, tag)

    def pdf(self, data):
        import fitz

        doc = fitz.open(stream=data, filetype="pdf")
        if doc.needs_pass:
            raise ValueError("PDF is password protected")
        pages_words = [page.get_text("words") for page in doc]
        self.learn_names("\n".join(" ".join(w[4] for w in words) for words in pages_words))
        for page, words in zip(doc, pages_words):
            if not words:
                continue
            text_parts, offsets = [], []
            pos = 0
            for idx, w in enumerate(words):
                offsets.append((pos, pos + len(w[4]), idx))
                text_parts.append(w[4])
                pos += len(w[4]) + 1
            text = " ".join(text_parts)
            hit = set()
            for start, end in self.spans(text):
                for s, e, idx in offsets:
                    if s < end and e > start:
                        hit.add(idx)
            for idx in hit:
                x0, y0, x1, y1 = words[idx][:4]
                page.add_redact_annot(fitz.Rect(x0, y0, x1, y1), fill=(0, 0, 0))
            for link in page.get_links():
                if link.get("uri"):
                    page.delete_link(link)
            if hit:
                self.stats["company"] += len(hit)
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        doc.set_metadata({})
        doc.del_xml_metadata()
        doc.set_toc([])
        self.stats["metadata"] += 1
        out = doc.tobytes(garbage=3, deflate=True)
        doc.close()
        return out

    def ooxml(self, data):
        src = zipfile.ZipFile(io.BytesIO(data))
        texts = []
        for info in src.infolist():
            if OOXML_TEXT_PARTS.match(info.filename):
                xml = src.read(info.filename).decode("utf-8", "replace")
                texts.append(" ".join(html.unescape(t) for t in re.findall(r">([^<]+)<", xml)))
        self.learn_names("\n".join(texts))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as dst:
            for info in src.infolist():
                raw = src.read(info.filename)
                name = info.filename
                if name == "docProps/core.xml" or name == "docProps/app.xml" or name == "docProps/custom.xml":
                    raw = self.strip_props(raw.decode("utf-8", "replace")).encode("utf-8")
                elif OOXML_TEXT_PARTS.match(name):
                    raw = self.ooxml_part(raw.decode("utf-8", "replace")).encode("utf-8")
                elif name.endswith(".rels"):
                    raw = re.sub(r'(Target=")([^"]*)(")', lambda m: m.group(1) + html.escape(self.scrub(html.unescape(m.group(2))), quote=True) + m.group(3), raw.decode("utf-8", "replace")).encode("utf-8")
                dst.writestr(info, raw)
        return buf.getvalue()

    def ooxml_part(self, xml):
        code = self.code

        def text_node(m):
            raw = html.unescape(m.group(1))
            if raw.strip() == self.ticker:  # spreadsheet cover cells such as "Trading Symbol | T"
                self.stats["company"] += 1
                new = raw.replace(self.ticker, code)
            else:
                new = self.scrub(raw)
            return ">" + html.escape(new, quote=False) + "<"

        xml = re.sub(r">([^<]+)<", text_node, xml)
        xml, n = re.subn(r'\b((?:w:)?author|w:initials|initials|userId|displayName)="[^"]*"', r'\1="[REDACTED]"', xml)
        self.stats["person"] += n
        return xml

    def strip_props(self, xml):
        tags = r"dc:creator|cp:lastModifiedBy|dc:title|dc:subject|cp:keywords|dc:description|cp:category|Company|Manager|HyperlinkBase|vt:lpwstr"
        xml, n = re.subn(rf"(<({tags})(?:\s[^>]*)?>)[^<]*(</\2>)", r"\1\3", xml)
        self.stats["metadata"] += n
        return xml


def decode(data):
    for enc in ("utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def convert_legacy(path, ext):
    target = LEGACY[ext]
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError(f".{ext} needs LibreOffice to convert before anonymising, and it is not installed")
    outdir = tempfile.mkdtemp()
    try:
        subprocess.run([soffice, "--headless", "--convert-to", target, "--outdir", outdir, path], check=True, capture_output=True, timeout=240)
        produced = [f for f in os.listdir(outdir) if f.lower().endswith("." + target)]
        if not produced:
            raise RuntimeError(f"LibreOffice did not produce a .{target} file")
        with open(os.path.join(outdir, produced[0]), "rb") as fh:
            return fh.read(), target
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


def run_job(rules, job):
    ext = job["ext"].lower()
    path = job["in"]
    with open(path, "rb") as fh:
        data = fh.read()
    if ext in LEGACY:
        data, ext = convert_legacy(path, ext)
    work = Job(rules, job["ticker"])
    if ext == "pdf":
        out = work.pdf(data)
    elif ext in ("docx", "xlsx", "xlsm", "pptx"):
        out = work.ooxml(data)
    elif ext in ("htm", "html", "xml"):
        out = work.text_file(data, True)
    elif ext in ("txt", "csv"):
        out = work.text_file(data, False)
    else:
        raise ValueError(f"no anonymiser for .{ext} files")
    with open(job["out"], "wb") as fh:
        fh.write(out)
    return {"ok": True, "ext": ext, "stats": work.stats}


def serve():
    rules = None
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("type") == "config":
            rules = Rules(msg)
            if rules.do_personal:
                load_nlp()
            print(json.dumps({"type": "ready"}), flush=True)
            continue
        try:
            reply = run_job(rules, msg)
        except Exception as err:  # noqa: BLE001
            reply = {"ok": False, "error": f"{type(err).__name__}: {err}"}
        reply["id"] = msg.get("id")
        print(json.dumps(reply), flush=True)


def test(config_path, ticker, src, dst):
    import hashlib

    with open(config_path, encoding="utf-8") as fh:
        raw = json.load(fh)
    companies = []
    for c in raw["companies"]:
        ciks = c.get("cik") or []
        companies.append({
            "ticker": c["ticker"],
            "code": "CO-" + hashlib.sha256(("test" + c["ticker"]).encode()).hexdigest()[:6].upper(),
            "name": c.get("name"),
            "aliases": c.get("aliases") or [],
            "domains": c.get("domains") or [],
            "ciks": [str(x) for x in (ciks if isinstance(ciks, list) else [ciks])],
        })
    rules = Rules({"companies": companies})
    ext = os.path.splitext(src)[1].lstrip(".").lower()
    print(json.dumps(run_job(rules, {"in": src, "out": dst, "ext": ext, "ticker": ticker})))


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--test":
        test(*sys.argv[2:])
    else:
        serve()
