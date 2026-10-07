"""Pseudonymises earnings documents before they are uploaded.

Identifying details are replaced with consistent, imaginary ones rather than tags or
black boxes: each company gets a fictional name, ticker, web domain and SEC numbers;
each brand a made-up brand name; each person a made-up name (same real name -> same
fictional name in every document); e-mails and phone numbers fictional ones
(555-01xx numbers are reserved for fiction). All of it is derived from a secret seed,
so the fictional details cannot be mapped back without ANON_KEY.

Runs as a long-lived worker: the first stdin line is a config message, every
following line is one job, and each job is answered with one JSON line on stdout.

  config: {"type": "config", "companies": [...], "seed": "...", "company": true, "personal": true}
  job:    {"id": 1, "in": "/tmp/a.pdf", "out": "/tmp/b.pdf", "ext": "pdf", "ticker": "JPM"}
  reply:  {"id": 1, "ok": true, "ext": "pdf", "stats": {...}}

PDFs: the real words are removed from the page (true redaction) and the fictional
text is written in their place.
"""
import hashlib
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
STREET_RE = re.compile(r"(?<![\w,])\d{1,6}(?:[\s ]+[NSEW]\.?)?(?:[\s ]+[A-Z][A-Za-z0-9.'\-]*){1,4}[\s ]+(?:Street|St\.|Avenue|Ave\.?|Boulevard|Blvd\.?|Road|Rd\.?|Drive|Dr\.|Way|Parkway|Pkwy\.?|Place|Plaza|Lane|Ln\.?|Court|Ct\.?|Circle|Square|Center|Centre)(?![A-Za-z])\.?")
CITY_ZIP_RE = re.compile(r"(?<![A-Za-z])[A-Z][A-Za-z]+(?:[\s ]+[A-Z][A-Za-z]+){0,2},[\s ]+(?:[A-Z]{2}|[A-Z][a-z]{1,4}\.(?:[\s ]?[A-Z]\.)?)[\s ]+\d{5}(?:-\d{4})?(?!\d)")
# Press-release datelines: "SANTA CLARA, Calif., July 23, 2026" / "NEW YORK, Jan. 14, 2026".
DATELINE_RE = re.compile(r"(?<![A-Za-z])[A-Z][A-Z.'\-]+(?:[\s ]+[A-Z][A-Z.'\-]+){0,2},(?:[\s ]+[A-Z][A-Za-z.]{1,6},)?(?=[\s ]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?[\s ]+\d{1,2},)")
STREET_NAMES = ["Larkspur", "Meridian", "Foxglen", "Harrowgate", "Willowmere", "Ashbourne", "Kestrel", "Brambleton", "Marrowfield", "Quillon"]
CITY_NAMES = ["Fairhaven", "Brookmere", "Eastvale", "Glenmoor", "Westerly Falls", "Ashford Springs", "Linden Bay", "Harrow Point"]
EXCHANGES = r"(?:NYSE|NASDAQ|Nasdaq|NasdaqGS|Nasdaq Global Select Market|New York Stock Exchange|Nasdaq Stock Market)"
# Tickers that are ordinary English words in upper case; only replaced in safe forms.
WORD_TICKERS = {"LOW", "CAT", "COST", "DIS", "ALL", "PEP", "HON", "AMP", "KEY", "NOW", "ON", "IT", "ARE", "SO", "DE", "MO", "EL", "CL", "MA", "MS", "GS", "PM", "BA", "GE", "HD", "DG", "KO", "VZ"}
NER_MAX_CHARS = 3_000_000
NER_CHUNK = 100_000
OOXML_TEXT_PARTS = re.compile(r"^(word/.*\.xml|ppt/.*\.xml|xl/sharedStrings\.xml|xl/worksheets/sheet\d+\.xml|xl/comments\d*\.xml|xl/charts/.*\.xml|xl/drawings/.*\.xml|docProps/.*\.xml)$")
# Formats converted with LibreOffice before anonymising, so only documents reach Drive.
LEGACY = {"xls": "xlsx", "doc": "docx", "ppt": "pptx", "csv": "xlsx", "txt": "docx"}
LEGAL_SUFFIX = re.compile(r"(?:,?\s+(?:Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.|& Co\.?|& Company|plc|PLC|Limited|Ltd\.?|LLC|L\.L\.C\.|N\.A\.|National Association))+$")
GENERIC_TAIL = {"Bank", "Cloud", "Health", "Financial", "Capital", "Energy", "Power", "Foods", "Pharmacy", "Video", "Store", "Stores", "Club", "Card", "Securities", "Services", "Holdings", "Group", "Network", "Media", "Mobile", "Wireless", "Pro", "Credit", "Freight", "Express", "Ground", "Aerospace", "Technologies", "Technology", "Systems", "Brands", "Gas", "Nuclear", "Partners", "Resources", "Motors"}

FIRST_NAMES = ["Avery", "Blake", "Camille", "Dorian", "Elena", "Felix", "Greta", "Hollis", "Imogen", "Jasper", "Kiara", "Leander", "Mirela", "Nolan", "Odette", "Pascal", "Quinn", "Rosalind", "Silas", "Tamsin", "Ulric", "Vivienne", "Wendell", "Xavia", "Yannick", "Zelda", "Anselm", "Beatrix", "Cassius", "Delphine", "Emrys", "Fiora", "Gideon", "Helena", "Ignatius", "Juno", "Kasimir", "Lucinda", "Magnus", "Noelle", "Octavian", "Petra", "Rafferty", "Saskia", "Thaddeus", "Ursula", "Valentin", "Wilhelmina", "Yvette", "Zachariah"]
LAST_NAMES = ["Ashcombe", "Bellweather", "Carrow", "Delacourt", "Everleigh", "Fairbanks", "Greywell", "Hartington", "Ingleby", "Jessop", "Kittredge", "Lockwood", "Merriweather", "Northcott", "Oakshott", "Pemberton", "Quayle", "Rothwell", "Stanhope", "Thistlewood", "Underhill", "Vandermeer", "Whitlock", "Yardley", "Zellweger", "Abernethy", "Blackwood", "Cresswell", "Dunleavy", "Ellsworth", "Fennimore", "Galloway", "Hollingsworth", "Ivanhoe", "Kingsford", "Langridge", "Marchetti", "Nightingale", "Ostrander", "Prescott", "Radcliffe", "Sallow", "Tremaine", "Upton", "Verhoeven", "Wetherby", "Ashdown", "Brightman", "Calloway", "Draycott"]
BRAND_HEADS = ["Vel", "Zor", "Quin", "Bra", "Tor", "Lum", "Kav", "Nex", "Sol", "Dra", "Mir", "Ost", "Pel", "Ryn", "Tal", "Ven", "Cor", "Fen", "Hal", "Jor", "Ard", "Bel", "Cal", "Dov", "Elm"]
BRAND_TAILS = ["ora", "ix", "ent", "ara", "ion", "yx", "ella", "ova", "ius", "eon", "ani", "ero", "aro", "una", "ell"]

nlp = None


def load_nlp():
    global nlp
    if nlp is None:
        try:
            import spacy

            nlp = spacy.load("en_core_web_sm", exclude=["parser", "lemmatizer", "attribute_ruler", "tagger", "senter"])
            nlp.max_length = NER_CHUNK + 10_000
        except Exception as err:  # noqa: BLE001
            sys.stderr.write(f"spaCy unavailable, people's names will not be replaced: {err}\n")
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


class Fake:
    """Deterministic fictional values derived from the secret seed."""

    def __init__(self, seed):
        self.seed = seed or "unseeded"

    def n(self, label):
        return int.from_bytes(hashlib.sha256(f"{self.seed}|{label}".encode()).digest()[:8], "big")

    def first(self, real):
        return FIRST_NAMES[self.n("first|" + real.lower()) % len(FIRST_NAMES)]

    def last(self, real):
        return LAST_NAMES[self.n("last|" + real.lower()) % len(LAST_NAMES)]

    def brand(self, real):
        v = self.n("brand|" + real.lower())
        return BRAND_HEADS[v % len(BRAND_HEADS)] + BRAND_TAILS[(v // 97) % len(BRAND_TAILS)]

    def digits_like(self, real, label):
        v = self.n(f"{label}|{real}")
        out = []
        for ch in real:
            if ch.isdigit():
                out.append(str(v % 10))
                v //= 10
            else:
                out.append(ch)
        return "".join(out)

    def street(self, real):
        v = self.n("street|" + real)
        kind = re.search(r"(Street|St\.|Avenue|Ave\.?|Boulevard|Blvd\.?|Road|Rd\.?|Drive|Dr\.|Way|Parkway|Pkwy\.?|Place|Plaza|Lane|Ln\.?|Court|Ct\.?|Circle|Square|Center|Centre)\.?$", real)
        return f"{100 + v % 8900} {STREET_NAMES[(v // 9000) % len(STREET_NAMES)]} {kind.group(0) if kind else 'Way'}"

    def city_zip(self, real):
        v = self.n("city|" + real)
        return f"{CITY_NAMES[v % len(CITY_NAMES)]}, ZZ {90000 + v % 9000:05d}"

    def phone(self, real):
        return f"(555) 555-01{self.n('phone|' + real) % 100:02d}"

    def person(self, real):
        """'Jamie Dimon' -> 'Petra Ostrander'; 'J. Dimon' -> 'K. Ostrander'; 'SatyaNadella' (XBRL) stays joined."""
        honor = re.match(r"((?:Mr|Ms|Mrs|Dr|Messrs)\.?[\s ]+)", real)
        prefix = honor.group(1) if honor else ""
        core = real[len(prefix):]
        joined = " " not in core.strip() and bool(re.fullmatch(r"(?:[A-Z][a-z'’\-]+){2,4}", core))
        tokens = re.findall(r"[A-Z][a-z'’\-]+", core) if joined else re.split(r"[\s ]+", core.strip())
        out = []
        for i, tk in enumerate(tokens):
            if i == len(tokens) - 1:
                out.append(self.last(tk.strip(".")) if len(tokens) > 1 or prefix or len(tk) > 2 else tk)
            elif re.fullmatch(r"[A-Z]\.?", tk):
                out.append(chr(65 + self.n("initial|" + tk) % 26) + ("." if tk.endswith(".") else ""))
            else:
                out.append(self.first(tk))
        if len(tokens) == 1 and not prefix:
            out = [self.last(tokens[0])]
        return prefix + ("".join(out) if joined else " ".join(out))


class Rules:
    def __init__(self, config):
        self.do_company = config.get("company", True)
        self.do_personal = config.get("personal", True)
        self.fake = Fake(config.get("seed"))
        self.companies = {c["ticker"]: c for c in config["companies"]}
        self.alias_map = {}  # squashed real alias -> fictional replacement (all companies)
        self.own_map = {}
        strong = []
        for c in config["companies"]:
            pairs = self._alias_pairs(c)
            self.own_map[c["ticker"]] = {squash(a): r for a, r in pairs}
            for alias, repl in pairs:
                # Bulk-added companies are only replaced in their own documents: thousands
                # of names in one pattern would make every document slow to process.
                if self._strong(alias) and not c.get("auto"):
                    strong.append(alias)
                    self.alias_map.setdefault(squash(alias), repl)
        self.all_strong = self._union(strong)
        self.per_company = {}
        self.markup = {}
        self.own_regex = {}

    def _alias_pairs(self, c):
        """(real alias, fictional replacement) for every spelling of a company's names and brands."""
        fake_name = c["fake"]["name"]
        name = (c.get("name") or "").strip()
        name_core = LEGAL_SUFFIX.sub("", re.sub(r"^The\s+", "", name)).strip()
        name_first = name_core.split(" ")[0].lower() if name_core else ""
        pairs = []
        for alias in [*(c.get("aliases") or []), name]:
            alias = alias.strip()
            if not alias:
                continue
            the = "The " if alias.startswith("The ") else ""
            body = alias[4:] if the else alias
            m = LEGAL_SUFFIX.search(body)
            core = body[: m.start()] if m else body
            suffix = body[m.start():] if m else ""
            lc, ln = core.lower(), name_core.lower()
            same_company = lc == ln or ln.startswith(lc) or (lc.startswith(ln) and ln) or (len(name_first) > 2 and lc.split(" ")[0] == name_first)
            if same_company:
                extra = core[len(name_core):] if ln and lc.startswith(ln) else ""
                extra = extra if re.fullmatch(r"(?:\s+(?:\d+|[A-Z][a-z]+))*", extra) and all(w in GENERIC_TAIL or w.isdigit() for w in extra.split()) else ""
                # One-word names get the one-word form ("Intel" -> "Northwind",
                # "Intel Corporation" -> "Northwind Corporation"), which also fits in PDFs.
                base = fake_name.split(" ")[0] if " " not in core.strip() else fake_name
                repl = f"{the}{base}{extra}{suffix}"
            else:
                words = core.split(" ")
                tail = f" {words[-1]}" if len(words) > 1 and words[-1] in GENERIC_TAIL else ""
                repl = f"{the}{self.fake.brand(core)}{tail}{suffix}"
            variants = {alias: repl}
            if len(alias) >= 6 and " " in alias:
                variants[alias.upper()] = repl.upper()
            if "’" in alias:
                variants[alias.replace("’", "'")] = repl
            if "'" in alias:
                variants[alias.replace("'", "’")] = repl
            pairs.extend(variants.items())
        return list(dict(pairs).items())

    @staticmethod
    def _strong(alias):
        return len(alias) >= 6 or bool(re.search(r"[\s&.\-]", alias))

    @staticmethod
    def _union(terms):
        if not terms:
            return None
        terms = sorted(set(terms), key=len, reverse=True)
        return re.compile(bounded("(?:" + "|".join(flex(t) for t in terms) + ")"))

    def own_aliases(self, ticker):
        return list(self.own_map[ticker].keys())

    def company(self, ticker):
        if ticker in self.per_company:
            return self.per_company[ticker]
        c = self.companies[ticker]
        fake = c["fake"]
        own_map = self.own_map[ticker]
        subs = []
        if c.get("auto"):
            # Names taken from SEC data ("1 800 Flowers COM") must still match the way
            # documents write them ("1-800-FLOWERS.COM"): any case, any separator.
            terms = sorted({a for a, _ in self._alias_pairs(c)}, key=len, reverse=True)
            loose = "|".join(r"[\s .\-]*".join(re.escape(p) for p in t.split(" ")) for t in terms)
            own = re.compile(rf"(?<![A-Za-z0-9])(?:{loose})(?![A-Za-z])", re.I) if terms else None
        else:
            own = self._union([a for a, _ in self._alias_pairs(c)])
        self.own_regex[ticker] = own
        if own:
            subs.append((own, lambda m: own_map.get(squash(m.group(0)), fake["name"])))
        t = re.escape(ticker)
        ft, fl = fake["ticker"], fake["ticker"].lower()
        subs.append((re.compile(rf"({EXCHANGES}\s*:\s*){t}(?![\w])"), rf"\g<1>{ft}"))
        low = re.escape(ticker.lower().replace(".", ""))
        subs.append((re.compile(rf"(?<![\w]){low}(?=-20\d{{6}})"), fl))
        # XBRL prefixes: name="msft:Revenue", msft:SatyaNadellaMember, msft-ex10_1.htm
        subs.append((re.compile(rf"(?<![\w\-]){low}(?=:[A-Z])"), fl))
        if len(ticker) >= 3:
            subs.append((re.compile(rf"(?<![\w\-]){low}(?=[:_\-])"), fl))
        # Namespace declarations are attribute names, which scrub_markup() otherwise leaves alone.
        self.markup[ticker] = (re.compile(rf"(?<=xmlns:){low}(?==)"), fl)
        if len(ticker) >= 3 and ticker not in WORD_TICKERS:
            subs.append((re.compile(bounded(t)), ft))
        for cik in c.get("ciks") or []:
            subs.append((re.compile(rf"(CIK\W{{0,20}})0*{cik}(?!\d)", re.I), rf"\g<1>{fake['cik']}"))
            subs.append((re.compile(rf"(?<!\d){cik.zfill(10)}(?!\d)"), fake["cik"].zfill(10)))
            subs.append((re.compile(rf"(/data/){cik}(?=/)"), rf"\g<1>{fake['cik']}"))
        for d in c.get("domains") or []:
            subs.append((re.compile(rf"(?<![\w.\-@])(?:[\w\-]+\.)*{re.escape(d)}(?![\w\-])", re.I), fake["domain"]))
            stem = d.split(".")[0]
            if len(stem) >= 4:  # hosted IR sites such as jpmorganchaseco.gcs-web.com
                subs.append((re.compile(rf"(?<![\w.\-@])[\w\-.]*{re.escape(stem)}[\w\-.]*\.[a-z]{{2,6}}(?![\w\-])", re.I), fake["domain"]))
        self.per_company[ticker] = subs
        return subs

    def email_domain(self, domain, subject):
        d = domain.lower()
        for c in self.companies.values():
            for real in c.get("domains") or []:
                stem = real.split(".")[0]
                if d == real or d.endswith("." + real) or (len(stem) >= 4 and stem in d):
                    return c["fake"]["domain"]
        return "example.com"


class Job:
    def __init__(self, rules, ticker):
        self.rules = rules
        self.fake = rules.fake
        self.ticker = ticker
        self.company = rules.companies[ticker]
        self.stats = {"company": 0, "email": 0, "phone": 0, "person": 0, "ids": 0, "metadata": 0}
        self.names_re = None
        self.skip = set()

    def prepare(self, text):
        """For bulk-added companies, a one-word name that the document also uses as an
        ordinary lowercase word ("gap", "target") is left alone in that document."""
        if not self.company.get("auto") or not text:
            return
        lower = set(re.findall(r"(?<![A-Za-z])[a-z]+(?![A-Za-z])", text))
        for alias in self.rules.own_map[self.ticker]:
            if alias.isalpha() and alias.lower() in lower:
                self.skip.add(alias.lower())

    def _own_ok(self, rx, m):
        return not (self.skip and rx is self.rules.own_regex.get(self.ticker) and squash(m.group(0)).lower() in self.skip)

    # --- text rules -------------------------------------------------------
    def _sub(self, regex, repl, text, key):
        new, n = regex.subn(repl, text)
        self.stats[key] += n
        return new

    def _email(self, m):
        local, _, domain = m.group(0).partition("@")
        dom = self.rules.email_domain(domain, self.ticker)
        low = local.lower()
        if re.search(r"invest|^ir\b|^ir[._]|shareholder|stockholder", low):
            user = "investor.relations"
        elif re.search(r"media|press|news|comms|communications", low):
            user = "media.relations"
        else:
            parts = re.split(r"[._\-]+", local)
            user = ".".join([self.fake.first(parts[0]), self.fake.last(parts[-1])]).lower() if len(parts) > 1 else self.fake.last(local).lower()
        return f"{user}@{dom}"

    def scrub(self, text):
        if not text:
            return text
        r = self.rules
        if r.do_personal:
            # E-mails first, while their domains are still recognisable.
            text = self._sub(EMAIL_RE, self._email, text, "email")
        if r.do_company:
            for regex, repl in r.company(self.ticker):
                if callable(repl) and self.skip:
                    repl = (lambda rx, fn: lambda m: fn(m) if self._own_ok(rx, m) else m.group(0))(regex, repl)
                text = self._sub(regex, repl, text, "company")
            if r.all_strong:
                text, n = r.all_strong.subn(lambda m: r.alias_map.get(squash(m.group(0)), self.company["fake"]["name"]), text)
                self.stats["company"] += n
            text = self._sub(EIN_RE, lambda m: self.fake.digits_like(m.group(0), "ein"), text, "ids")
            text = self._sub(FILE_NO_RE, lambda m: self.fake.digits_like(m.group(0), "fileno"), text, "ids")
            text = self._sub(STREET_RE, lambda m: self.fake.street(m.group(0)), text, "ids")
            text = self._sub(CITY_ZIP_RE, lambda m: self.fake.city_zip(m.group(0)), text, "ids")
            text = self._sub(DATELINE_RE, lambda m: self.fake.city_zip(m.group(0)).split(",")[0].upper() + ",", text, "ids")
        if r.do_personal:
            text = self._sub(PHONE_RE, lambda m: self.fake.phone(m.group(0)), text, "phone")
            if self.names_re:
                text = self._sub(self.names_re, lambda m: self.fake.person(m.group(0)), text, "person")
        return text

    def spans(self, text):
        """Character spans that scrub() would change, for PDF redaction."""
        r = self.rules
        regexes = []
        if r.do_company:
            regexes += [rx for rx, _ in r.company(self.ticker)]
            if r.all_strong:
                regexes.append(r.all_strong)
            regexes += [EIN_RE, FILE_NO_RE, STREET_RE, CITY_ZIP_RE, DATELINE_RE]
        if r.do_personal:
            regexes += [EMAIL_RE, PHONE_RE]
            if self.names_re:
                regexes.append(self.names_re)
        out = []
        for rx in regexes:
            for m in rx.finditer(text):
                if not self._own_ok(rx, m):
                    continue
                start, end = m.span()
                if rx.groups and m.lastindex and rx.pattern.startswith("(") and m.group(1) is not None and m.start(1) == start:
                    start = m.end(1)  # keep the "NYSE:" / "CIK" prefix as it is
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
        own_terms = [a.lower() for a in self.rules.own_aliases(self.ticker)]

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
                # NER sometimes glues a heading on ("QoQ Jamie Dimon"): also try the tails.
                for tail in (tokens[i:] for i in range(len(tokens) - 1)):
                    if plausible(tail) and len(" ".join(tail)) <= 40:
                        names.add(" ".join(tail))
                if len(tokens) == 1 and len(tokens[0]) >= 4 and plausible(tokens):
                    singles.add(tokens[0])
        if not names:
            return
        # A lone first name or surname ("Dimon added:") only counts when the full name is present.
        surnames = {n.split(" ")[-1] for n in names if len(n.split(" ")[-1]) >= 4}
        firsts = {n.split(" ")[0] for n in names if len(n.split(" ")[0]) >= 3 and not n.split(" ")[0].endswith(".")}
        singles = {s for s in singles if s in surnames or s in firsts}
        alts = sorted(names | singles | surnames, key=len, reverse=True)
        pattern = "|".join(flex(n) for n in alts)
        self.names_re = re.compile(rf"(?:(?:Mr|Ms|Mrs|Dr|Messrs)\.?[\s ]+)?" + bounded("(?:" + pattern + ")"))

    # --- formats ----------------------------------------------------------
    def text_file(self, data, is_html):
        text = decode(data)
        if is_html:
            visible = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
            visible = html.unescape(re.sub(r"<[^>]+>", " ", visible))
            self.prepare(visible)
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
            self.prepare(text)
            self.learn_names(text)
            text = self.scrub(text)
        return text.encode("utf-8")

    def scrub_markup(self, tag):
        """Inside a tag only touch attribute values (links, titles, alt text)."""
        def fix(m):
            return m.group(1) + html.escape(self.scrub(html.unescape(m.group(2))), quote=True) + m.group(3)

        ns = self.rules.markup.get(self.ticker)
        if ns and self.rules.do_company:
            tag = ns[0].sub(ns[1], tag)
        return re.sub(r'(=\s*")([^"]*)(")', fix, tag)

    def pdf(self, data):
        import pymupdf as fitz

        doc = fitz.open(stream=data, filetype="pdf")
        if doc.needs_pass:
            raise ValueError("PDF is password protected")
        pages_words = [page.get_text("words") for page in doc]
        all_text = "\n".join(" ".join(w[4] for w in words) for words in pages_words)
        self.prepare(all_text)
        self.learn_names(all_text)
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
            # Group hit words into runs on the same line, and replace each run as a whole.
            runs, current = [], []
            for idx in sorted(hit):
                if current and (idx != current[-1] + 1 or words[idx][5:7] != words[current[-1]][5:7]):
                    runs.append(current)
                    current = []
                current.append(idx)
            if current:
                runs.append(current)
            inserts = []
            for run in runs:
                original = " ".join(words[i][4] for i in run)
                new = self.scrub(original)
                if new == original:  # matched only with context; never leave it visible
                    new = self.company["fake"]["ticker"] if original.strip() == self.ticker else ""
                rect = fitz.Rect(words[run[0]][:4])
                for i in run[1:]:
                    rect |= fitz.Rect(words[i][:4])
                # Only the original words are removed; nothing next to them is touched.
                page.add_redact_annot(rect, fill=False)
                if new:
                    size = rect.height * 0.74
                    width = fitz.get_text_length(new, fontname="helv", fontsize=size)
                    if width > rect.width * 1.05:
                        size = max(size * rect.width * 1.05 / width, rect.height * 0.55)
                    inserts.append((fitz.Point(rect.x0, rect.y1 - rect.height * 0.24), new, size))
            # Logos: small images in the top or bottom band of a page (charts stay).
            page_h, page_w = page.rect.height, page.rect.width
            logos = 0
            for info in page.get_image_info():
                box = fitz.Rect(info["bbox"]) & page.rect
                in_band = box.y1 < page_h * 0.18 or box.y0 > page_h * 0.9
                if in_band and not box.is_empty and box.width < page_w * 0.45 and box.height < page_h * 0.12:
                    page.add_redact_annot(box, fill=(1, 1, 1))
                    logos += 1
            for link in page.get_links():
                if link.get("uri"):
                    page.delete_link(link)
            if runs or logos:
                self.stats["company"] += len(runs) + logos
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
                for point, text_new, size in inserts:
                    page.insert_text(point, text_new, fontsize=size, fontname="helv", color=(0, 0, 0))
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
        self.prepare("\n".join(texts))
        self.learn_names("\n".join(texts))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as dst:
            for info in src.infolist():
                raw = src.read(info.filename)
                name = info.filename
                if name in ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"):
                    raw = self.strip_props(raw.decode("utf-8", "replace")).encode("utf-8")
                elif OOXML_TEXT_PARTS.match(name):
                    raw = self.ooxml_part(raw.decode("utf-8", "replace")).encode("utf-8")
                elif name.endswith(".rels"):
                    raw = re.sub(r'(Target=")([^"]*)(")', lambda m: m.group(1) + html.escape(self.scrub(html.unescape(m.group(2))), quote=True) + m.group(3), raw.decode("utf-8", "replace")).encode("utf-8")
                dst.writestr(info, raw)
        return buf.getvalue()

    def ooxml_part(self, xml):
        fake_ticker = self.company["fake"]["ticker"]

        def text_node(m):
            raw = html.unescape(m.group(1))
            if raw.strip() == self.ticker:  # spreadsheet cover cells such as "Trading Symbol | T"
                self.stats["company"] += 1
                new = raw.replace(self.ticker, fake_ticker)
            else:
                new = self.scrub(raw)
            return ">" + html.escape(new, quote=False) + "<"

        def author(m):
            self.stats["person"] += 1
            value = m.group(2)
            return f'{m.group(1)}="{html.escape(self.fake.person(value) if re.search(r"[A-Za-z]{2}", value) else value, quote=True)}"'

        xml = re.sub(r">([^<]+)<", text_node, xml)
        return re.sub(r'\b((?:w:)?author|w:initials|initials|userId|displayName)="([^"]*)"', author, xml)

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


if __name__ == "__main__":
    serve()
