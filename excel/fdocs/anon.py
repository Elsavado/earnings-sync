"""Anonymises one document: company names become 'Redacted Company Name Inc', people's names
'Redacted Name'; e-mails, web links, phone numbers and tickers are removed; every picture
(logos, photos, signatures, scanned charts) is deleted; document metadata is cleared.

Names come from three places: the SEC registrant list (models.anonymize.Anonymizer), the
filer names of the SEC filing the document came from, and a spaCy pass over the whole
document that learns its PERSON names and its organisation names with a legal suffix.

PDF: words are truly removed (redaction) and the replacement is written in their place.
DOCX/PPTX: text is rewritten paragraph by paragraph at XML level. IPYNB: markdown, code
comments and strings, and text outputs; image and HTML outputs are dropped.
"""
import difflib
import io
import json
import re
import tokenize
import zipfile

from models.anonymize import SUFFIX_RE
from models.xl import REDACTED

PERSON = 'Redacted Name'
TICKER = 'TICKER'
TITLES = r'(?:Mr|Mrs|Ms|Miss|Dr|Prof|Sir|Dame|Lord|Hon)\.?'
POSSESSIVE = "(?:['’�]s)$"
# Words that mark a replacement, so the leak check never reports our own output.
OURS = {'redacted', 'company', 'name', 'inc', 'inc.', '[link', 'removed]', '[phone', 'redacted@example.com', 'ticker'}
NOT_NAMES = set('''january february march april may june july august september october november december monday tuesday
wednesday thursday friday saturday sunday q1 q2 q3 q4 fy ebitda capex gaap ifrs ceo cfo coo cto chairman president
operator question answer thank thanks good morning afternoon evening analyst page table figure exhibit section
section annex appendix total net gross'''.split())

# First names that are also everyday words: replaced only as part of a full name.
WORDLIKE = set('''mark will bill rose grant frank guy june may art chase dean hope joy faith pat sue rich bob ray jack
gene don earl lance wade drew rob gale dale glen miles king joe max ken sky summer autumn amber ruby pearl crystal
sandy rusty victor hunter page lane price young long rocky dawn eve ivy holly penny sterling bond cash gray grey
brown green white black stone wood carter mason cook baker bishop parker major chance'''.split())

# Upper-case words that are also SEC tickers but mean something else in a financial document.
ACRONYMS = set('''CEO CFO COO CTO CIO CMO EVP SVP EPS EBIT EBITDA EBITDAR GAAP IFRS USA USD EUR GBP JPY CAD AUD CHF CNY
LLC INC LTD PLC IPO LBO DCF IRR NPV ROE ROA ROI ROIC ROCE SEC NYSE FDA FTC DOJ ESG CAGR YOY QOQ TTM LTM NTM FCF
CAPEX OPEX SGA COGS AND THE FOR NOT ARE ALL ONE TWO NEW NOW OUT TOP BIG KEY BUY SELL HOLD WACC CAPM BETA APR APY
LIBOR SOFR OTC ETF REIT MLP BDC SPAC NAV AUM LPA LOI NDA CIM QOE TAM SAM SOM KPI ARR MRR SAAS API CPI GDP PMI ISM
FED ECB BOE IMF OECD NATO YTD MTD QTD TBD TBA NOI FFO AFFO DSCR LTV MOIC DPI TVPI RVPI PIK OID ABL TLA TLB RCF SOX
FCPA AML KYC CFPB FINRA FASB PCAOB IRS NAIC OCC FDIC CFTC SBA USDA DOE EPA NASA NIH CDC WHO WTO OPEC LNG CNG BEV
ICE HVAC ERP CRM SKU FYE PPE SBC DTA DTL NOL'''.split())
_FIRST = None


def first_names():
    global _FIRST
    if _FIRST is None:
        from pathlib import Path
        f = Path(__file__).with_name('first_names.txt')
        _FIRST = {ln.strip().lower() for ln in f.read_text(encoding='utf-8').splitlines() if ln and not ln.startswith('#')}
    return _FIRST


class DocAnon:
    def __init__(self, base, nlp, tickers=()):
        """base: models.anonymize.Anonymizer with nlp=None (registrant names, e-mails, links, phones,
        tickers in context); tickers: every SEC ticker, replaced when it stands alone."""
        from wordfreq import zipf_frequency
        self.base = base
        self.nlp = nlp
        self.tickers = {t.upper() for t in tickers if 3 <= len(t) <= 6 and t.upper() not in ACRONYMS
                        and zipf_frequency(t.lower(), 'en') < 3.0}
        self.all_tickers = {t.upper() for t in tickers}  # only to recognise a table of tickers
        self.reset()

    def reset(self):
        self.people_re = None
        self.surname_re = None
        self.org_re = None
        self.own_tickers = set()
        self.page_tickers = set()
        self.learned = {'people': 0, 'orgs': 0}

    # --- learning ----------------------------------------------------------
    def learn(self, text, orgs=()):
        """Learns this document's people and organisations. orgs: known names (SEC filer names,
        e.g. 'Brand Engagement Network Inc.  (BNAI, BNAIW)  (CIK 0001838163)')."""
        from wordfreq import zipf_frequency
        self.reset()
        firsts = first_names()
        people, surnames, org_names = set(), set(), set()
        for o in orgs:
            for group in re.findall(r'\(([A-Z0-9.\-, ]{1,40})\)', o):
                self.own_tickers |= {t.strip() for t in group.split(',') if len(t.strip()) >= 2 and not t.strip().isdigit()}
            o = re.sub(r'\s*\((?:CIK [^)]*|[A-Z0-9.\-, ]{1,40})\)', '', o).strip()
            if len(o) >= 3:
                org_names.add(o)
        if self.nlp:
            text = text[:800000]
            for i in range(0, len(text), 100000):
                chunk = text[i:i + 100000]
                try:
                    doc = self.nlp(chunk)
                except Exception:  # noqa: BLE001
                    continue
                for ent in doc.ents:
                    t = re.sub(POSSESSIVE, '', ent.text.strip()).strip(' ,.;:')
                    titled = bool(re.search(rf'\b{TITLES}\s*$', chunk[max(0, ent.start_char - 6):ent.start_char]))
                    t = re.sub(rf'^{TITLES}\s+', '', t)
                    if ent.label_ == 'PERSON':
                        toks = t.split()
                        if not (2 <= len(toks) <= 4 and all(re.fullmatch(r"[A-Z][A-Za-z'’\-]+\.?|[A-Z]\.", w) for w in toks)
                                and not any(w.lower().strip('.') in NOT_NAMES for w in toks)):
                            continue
                        given = next((w.strip('.') for w in toks if len(w.strip('.')) > 1), '')
                        # A person needs a known first name, a title such as 'Mr.', or (written in mixed
                        # case) no everyday English word in it: slide headings like 'Exit Multiple' or
                        # 'DISCUSSION MATERIALS' are not people, 'Sonal Shah' is.
                        uncommon = not t.isupper() and all(zipf_frequency(w.lower().strip('.'), 'en') < 4.0 for w in toks)
                        if given.lower() not in firsts and not titled and not uncommon:
                            continue
                        name = ' '.join(toks)
                        people |= {name, name.title(), name.upper()}
                        last = toks[-1].strip('.')
                        if len(last) >= 3:
                            rare = zipf_frequency(last.lower(), 'en') < 3.3
                            surnames |= {(last, rare), (last.title(), rare), (last.upper(), rare)}
                        if len(given) >= 3 and given.lower() not in WORDLIKE and zipf_frequency(given.lower(), 'en') < 5.0:
                            surnames |= {(given, True), (given.title(), True)}  # 'Anthony' on its own; not 'Mark'
                    elif ent.label_ == 'ORG' and re.search(SUFFIX_RE + r'\.?$', t, re.I) and len(t) <= 80:
                        org_names.add(t)

        def alt(names):
            names = sorted({n for n in names if n}, key=len, reverse=True)
            return '|'.join(r'\s+'.join(re.escape(w) for w in n.split()) for n in names)

        # Organisations first: a word of a company name is never treated as a person's name.
        cores = set()
        for o in org_names:
            core = re.sub(rf'(?:{SUFFIX_RE})+\.?$', '', o, flags=re.I).strip(' ,')
            core = re.sub(r'^the\s+', '', core, flags=re.I)
            if len(core) >= 3 and (len(core.split()) > 1 or zipf_frequency(core.lower(), 'en') < 3.6):
                cores |= {core, core.title(), core.upper()}  # SEC filer names are often in capitals
        org_words = {w.lower() for c in cores for w in c.split()}
        people = {p for p in people if not any(w.lower().strip('.') in org_words for w in p.split())}
        surnames = {(n, r) for n, r in surnames if n.lower() not in org_words}
        if cores:
            self.org_re = re.compile(rf'(?:\b[Tt]he\s+)?\b(?:{alt(cores)})(?:{SUFFIX_RE})*\.?(?![A-Za-z])')
        if people:
            self.people_re = re.compile(rf'(?:\b{TITLES}\s+)?\b(?:{alt(people)})\b')
        rare = [n for n, is_rare in surnames if is_rare]
        common = [n for n, is_rare in surnames if not is_rare]
        parts = []
        if rare:
            parts.append(rf'(?:\b{TITLES}\s+)?\b(?:{alt(rare)})\b')
        if common:  # 'Mr. Brown' only with a title, so the colour brown stays
            parts.append(rf'\b{TITLES}\s+(?:{alt(common)})\b')
        if parts:
            self.surname_re = re.compile('|'.join(parts))
        self.learned = {'people': len({p.lower() for p in people}), 'orgs': len({c.lower() for c in cores}),
                        'tickers': len(self.own_tickers)}

    # --- text --------------------------------------------------------------
    def scrub(self, s):
        if not s or not any(ch.isalpha() for ch in s):
            return s
        out = s
        if self.org_re:
            out = self.org_re.sub(REDACTED, out)
        if self.people_re:
            out = self.people_re.sub(PERSON, out)
        if self.surname_re:
            out = self.surname_re.sub(PERSON, out)
        out = self.base.text(out)
        out = re.sub(r'\bREDACTED\b', TICKER, out)  # tickers the base anonymiser found in context ('NYSE: X')
        return re.sub(r'(?<![A-Za-z0-9])\$?([A-Z][A-Z0-9]{0,5}(?:[.\-][A-Z]{1,2})?)(?![A-Za-z0-9])',
                      lambda m: TICKER if m.group(1) in self.own_tickers or m.group(1) in self.tickers
                      or m.group(1) in self.page_tickers else m.group(0), out)

    def _ticker_table(self, tokens):
        """On a page that lists several known tickers (a peer or comparables table), the other short
        capitalised labels next to them are tickers too, including delisted ones and word-like ones ('ROCK')."""
        toks = [t.strip('(),;:*$') for t in tokens]
        caps = {t for t in toks if re.fullmatch(r'[A-Z]{2,5}(?:\.[A-Z])?', t) and t not in ACRONYMS and t != TICKER}
        known = {t for t in caps if t in self.all_tickers or t in self.own_tickers}
        return caps if len(known) >= 2 and len(caps) >= 4 else set()

    def leaks(self, text):
        """Words in text that scrub() would still change (empty when the text is clean)."""
        a = text.split()
        b = self.scrub(' '.join(a)).split()
        out = []
        for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag != 'equal':
                out += [w for w in a[i1:i2] if w.lower().strip('.,;:()') not in OURS]
        return out

    # --- PDF -----------------------------------------------------------------
    def pdf_text(self, path):
        import pymupdf as fitz
        with fitz.open(path) as doc:
            if doc.needs_pass and not doc.authenticate(''):
                raise ValueError('password protected')
            return '\n'.join(page.get_text('text') for page in doc), doc.page_count

    def pdf(self, src, dst):
        """Anonymises a PDF in place of the original words. Returns a reason string on failure, else None."""
        import pymupdf as fitz
        doc = fitz.open(src)
        if doc.needs_pass and not doc.authenticate(''):
            return 'password protected'
        if doc.page_count > 400:
            return f'too many pages ({doc.page_count})'
        for page in doc:
            words = page.get_text('words')
            dirs = {}  # (block, line) -> text direction, so replacements run the same way as the words they replace
            for b in page.get_text('dict', flags=0)['blocks']:
                for li, line in enumerate(b.get('lines', [])):
                    dirs[(b['number'], li)] = line['dir']
            lines = {}
            for w in words:
                lines.setdefault((w[5], w[6]), []).append(w)
            self.page_tickers = self._ticker_table(w[4] for w in words)
            inserts = []
            for ws in lines.values():
                toks = [w[4] for w in ws]
                new = self.scrub(' '.join(toks)).split()
                if new == toks:
                    continue
                for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, toks, new, autojunk=False).get_opcodes():
                    if tag == 'equal' or i1 == i2:
                        continue
                    rect = fitz.Rect(ws[i1][:4])
                    for w in ws[i1 + 1:i2]:
                        rect |= fitz.Rect(w[:4])
                    page.add_redact_annot(rect, fill=False)
                    rep = ' '.join(new[j1:j2])
                    if rep:
                        inserts.append((rect, rep, dirs.get((ws[0][5], ws[0][6]), (1, 0))))
            for link in page.get_links():
                page.delete_link(link)
            if inserts:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
                for rect, rep, d in inserts:
                    _insert(page, rect, rep, d)
            for img in page.get_images(full=True):
                try:
                    page.delete_image(img[0])
                except Exception:  # noqa: BLE001  (inline or shared image already gone)
                    pass
            for annot in list(page.annots() or []):
                page.delete_annot(annot)
            for widget in list(page.widgets() or []):
                page.delete_widget(widget)
        # Names split over two lines: find them across the page and cover them.
        for page in doc:
            self.page_tickers = self._ticker_table(page.get_text('text').split())
            left = self.leaks(page.get_text('text'))
            if not left:
                continue
            for phrase in self._leak_phrases(page.get_text('text')):
                for quad in page.search_for(phrase, quads=True):
                    page.add_redact_annot(quad, fill=(1, 1, 1))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
            if self.leaks(page.get_text('text')):
                return f'name left on page {page.number + 1}'
        for name in doc.embfile_names():
            doc.embfile_del(name)
        doc.set_metadata({})
        doc.del_xml_metadata()
        self.page_tickers = set()
        doc.save(dst, garbage=4, deflate=True, clean=True)
        doc.close()
        return None

    def _leak_phrases(self, text):
        a = text.split()
        b = self.scrub(' '.join(a)).split()
        out = []
        for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag != 'equal' and i1 < i2:
                out.append(' '.join(a[i1:i2]))
                out += a[i1:i2]
        return [p for p in dict.fromkeys(out) if p.lower().strip('.,;:()') not in OURS]

    # --- DOCX / PPTX ----------------------------------------------------------
    def ooxml(self, src, dst):
        """Anonymises a .docx or .pptx. Returns a reason string on failure, else None."""
        zin = zipfile.ZipFile(src)
        parts = {i.filename: zin.read(i.filename) for i in zin.infolist()}
        zin.close()
        word = 'word/document.xml' in parts
        if not word and 'ppt/presentation.xml' not in parts:
            return 'not a Word or PowerPoint file'
        if any(p.startswith(('word/vbaProject', 'ppt/vbaProject')) for p in parts):
            return 'contains macros'
        text_re = re.compile(r'^(word/(document|header\d*|footer\d*|footnotes|endnotes|comments\w*)\.xml|'
                             r'ppt/(slides/slide|notesSlides/notesSlide|slideLayouts/slideLayout|slideMasters/slideMaster|'
                             r'comments/comment|handoutMasters/handoutMaster|notesMasters/notesMaster)\d*\.xml|'
                             r'(word|ppt)/charts/chart\d*\.xml|(word|ppt)/diagrams/data\d*\.xml)$')
        texts = [p for p in parts if text_re.match(p)]
        # Learn names from all visible text first.
        allt = []
        for p in texts:
            x = parts[p].decode('utf-8', 'replace')
            allt += [_unesc(t) for t in re.findall(r'<(?:w|a):t(?:\s[^>]*)?>(.*?)</(?:w|a):t>', x, re.S)]
        self.learn(' '.join(allt))

        dropped = set()
        for p in list(parts):
            if re.match(r'^(word|ppt)/(media|embeddings)/', p) or p.startswith('docProps/custom') or p.endswith('/people.xml'):
                dropped.add(p)
                del parts[p]
        for p in texts:
            x = parts[p].decode('utf-8')
            for tag in ('w:drawing', 'w:pict', 'w:object', 'mc:AlternateContent', 'p:pic', 'w:fldSimple'):
                x = _remove_elem(x, tag, keep_inner=(tag == 'w:fldSimple'))
            x = _remove_elem(x, 'p:graphicFrame', only_if='oleObj')
            x = _remove_elem(x, 'a:blipFill', replace='<a:noFill/>')
            x = _remove_elem(x, 'p:blipFill', replace='')
            x = _remove_elem(x, 'w:hyperlink', keep_inner=True)
            x = re.sub(r'<a:hlink(?:Click|Hover)\b[^>]*?(?:/>|>.*?</a:hlink(?:Click|Hover)>)', '', x, flags=re.S)
            x = re.sub(r'\b(w:author|author)="[^"]*"', rf'\1="{PERSON}"', x)
            x = re.sub(r'\b(w:initials|initials)="[^"]*"', r'\1="RN"', x)
            shown = [a or b for a, b in re.findall(r'<(?:w|a):t(?:\s[^>]*)?>(.*?)</(?:w|a):t>|<c:v>(.*?)</c:v>', x, re.S)]
            self.page_tickers = self._ticker_table(_unesc(' '.join(shown)).split())  # per slide / per part
            x = re.sub(r'<(w|a):p\b(?:(?!<\1:p\b).)*?</\1:p>', lambda m: self._para(m.group(0), m.group(1)), x, flags=re.S)
            x = re.sub(r'(<c:v>)(.*?)(</c:v>)', lambda m: m.group(1) + _esc(self.scrub(_unesc(m.group(2)))) + m.group(3), x, flags=re.S)
            x = re.sub(r'<w:instrText(?:\s[^>]*)?>[^<]*HYPERLINK[^<]*</w:instrText>', '', x)
            parts[p] = x.encode('utf-8')
        if 'ppt/commentAuthors.xml' in parts:
            x = parts['ppt/commentAuthors.xml'].decode('utf-8')
            x = re.sub(r'\bname="[^"]*"', f'name="{PERSON}"', x)
            parts['ppt/commentAuthors.xml'] = re.sub(r'\binitials="[^"]*"', 'initials="RN"', x).encode('utf-8')
        # Relationships: drop pictures, embedded objects, hyperlinks and anything external.
        bad = re.compile(r'/(image|oleObject|package|hyperlink|video|audio|media|people|customProperties|attachedTemplate)"|TargetMode="External"')
        for p in [q for q in parts if q.endswith('.rels')]:
            x = parts[p].decode('utf-8')
            x = re.sub(r'<Relationship\b[^>]*/>', lambda m: '' if bad.search(m.group(0)) else m.group(0), x)
            parts[p] = x.encode('utf-8')
        ct = parts['[Content_Types].xml'].decode('utf-8')
        ct = re.sub(r'<Override\b[^>]*PartName="/([^"]+)"[^>]*/>', lambda m: '' if m.group(1) in dropped else m.group(0), ct)
        parts['[Content_Types].xml'] = ct.encode('utf-8')
        _props(parts, self)
        for p, data in parts.items():
            if p.endswith('.xml') or p.endswith('.rels'):
                try:
                    from xml.dom import minidom
                    minidom.parseString(data)
                except Exception:  # noqa: BLE001
                    return f'broken XML in {p}'
        with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in ['[Content_Types].xml'] + [q for q in parts if q != '[Content_Types].xml']:
                z.writestr(p, parts[p])
        return None

    def _para(self, para, ns):
        pat = re.compile(rf'(<{ns}:t)((?:\s[^>]*)?)>(.*?)(</{ns}:t>)', re.S)
        runs = pat.findall(para)
        if not runs:
            return para
        old = ''.join(_unesc(r[2]) for r in runs)
        new = self.scrub(old)
        if new == old:
            return para
        it = iter(range(len(runs)))

        def put(m):
            i = next(it)
            if i == 0:
                attrs = m.group(2) if 'xml:space' in m.group(2) or ns == 'a' else m.group(2) + ' xml:space="preserve"'
                return f'{m.group(1)}{attrs}>{_esc(new)}{m.group(4)}'
            return f'{m.group(1)}{m.group(2)}>{m.group(4)}'
        return pat.sub(put, para)

    # --- Jupyter -----------------------------------------------------------------
    def ipynb(self, src, dst):
        nb = json.loads(open(src, encoding='utf-8').read())
        if not isinstance(nb, dict) or 'cells' not in nb:
            return 'not a notebook'
        cells = nb['cells']
        self.learn('\n'.join(_src(c) for c in cells if c.get('cell_type') == 'markdown'))
        for c in cells:
            text = _src(c)
            c.pop('attachments', None)
            if c.get('cell_type') == 'markdown':
                text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
                text = re.sub(r'<img\b[^>]*>', '', text, flags=re.I)
                c['source'] = self.scrub(text)
            elif c.get('cell_type') == 'code':
                c['source'] = self._code(text)
                outs = []
                for o in c.get('outputs', []):
                    t = o.get('output_type')
                    if t == 'stream':
                        o['text'] = self.scrub(_join(o.get('text', '')))
                        outs.append(o)
                    elif t in ('execute_result', 'display_data'):
                        data = o.get('data', {})
                        if 'text/plain' in data:
                            o['data'] = {'text/plain': self.scrub(_join(data['text/plain']))}
                            o['metadata'] = {}
                            outs.append(o)
                c['outputs'] = outs
            else:
                c['source'] = self.scrub(text)
            c['metadata'] = {}
        meta = nb.get('metadata', {})
        nb['metadata'] = {k: meta[k] for k in ('kernelspec', 'language_info') if k in meta}
        with open(dst, 'w', encoding='utf-8') as f:
            json.dump(nb, f, indent=1, ensure_ascii=False)
        return None

    def _code(self, code):
        """Scrubs comments and string literals only, so the code still runs."""
        try:
            toks = list(tokenize.generate_tokens(io.StringIO(code).readline))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            return re.sub(r'#[^\n]*|\'[^\'\n]*\'|"[^"\n]*"', lambda m: self.scrub(m.group(0)), code)
        kinds = {tokenize.COMMENT, tokenize.STRING}
        if hasattr(tokenize, 'FSTRING_MIDDLE'):
            kinds.add(tokenize.FSTRING_MIDDLE)
        lines = code.splitlines(keepends=True)
        starts = [0]
        for ln in lines:
            starts.append(starts[-1] + len(ln))
        edits = []
        for t in toks:
            if t.type in kinds and any(ch.isalpha() for ch in t.string):
                a = starts[t.start[0] - 1] + t.start[1]
                b = starts[t.end[0] - 1] + t.end[1]
                new = self.scrub(code[a:b])
                if new != code[a:b]:
                    edits.append((a, b, new))
        for a, b, new in reversed(edits):
            code = code[:a] + new + code[b:]
        return code


def _insert(page, rect, text, direction):
    """Writes text over a redacted word box, in the direction the original words ran
    (rotated pages keep upright-looking text that runs vertically in page coordinates)."""
    import pymupdf as fitz
    cos, sin = direction
    rot = 90 if sin < -0.7 else 270 if sin > 0.7 else 180 if cos < -0.7 else 0
    long_side, short = (rect.width, rect.height) if rot in (0, 180) else (rect.height, rect.width)
    size = max(short * 0.74, 3)
    length = fitz.get_text_length(text, fontname='helv', fontsize=size)
    if length > long_side > 0:  # shrink to the original word's width so nothing next to it is covered
        size = max(size * long_side / length, 2.5)
    at = {0: (rect.x0, rect.y1 - short * 0.22), 90: (rect.x1 - short * 0.22, rect.y1),
          180: (rect.x1, rect.y0 + short * 0.22), 270: (rect.x0 + short * 0.22, rect.y0)}[rot]
    page.insert_text(fitz.Point(*at), text, fontsize=size, fontname='helv', color=(0, 0, 0), rotate=rot)


def _src(cell):
    return _join(cell.get('source', ''))


def _join(v):
    return ''.join(v) if isinstance(v, list) else (v or '')


def _esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _unesc(s):
    return (s.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&apos;', "'")
            .replace('&amp;', '&'))


def _remove_elem(x, tag, keep_inner=False, replace='', only_if=None):
    """Removes every <tag>...</tag> (nesting-aware) or self-closing <tag/>."""
    open_re = re.compile(rf'<{re.escape(tag)}(?=[\s/>])[^>]*?(/?)>')
    out, pos = [], 0
    while True:
        m = open_re.search(x, pos)
        if not m:
            out.append(x[pos:])
            return ''.join(out)
        if m.group(1) == '/':
            end, inner = m.end(), ''
        else:
            depth, i = 1, m.end()
            tok = re.compile(rf'<{re.escape(tag)}(?=[\s/>])[^>]*?(/?)>|</{re.escape(tag)}>')
            while depth:
                n = tok.search(x, i)
                if not n:
                    out.append(x[pos:])
                    return ''.join(out)
                if n.group(0).startswith('</'):
                    depth -= 1
                elif n.group(1) != '/':
                    depth += 1
                i = n.end()
            end, inner = i, x[m.end():i - len(f'</{tag}>')]
        whole = x[m.start():end]
        out.append(x[pos:m.start()])
        if only_if and only_if not in whole:
            out.append(whole)
        else:
            out.append(inner if keep_inner else replace)
        pos = end


def _props(parts, anon):
    if 'docProps/core.xml' in parts:
        x = parts['docProps/core.xml'].decode('utf-8')
        for tag in ('dc:creator', 'cp:lastModifiedBy'):
            x = re.sub(rf'<{tag}>.*?</{tag}>', f'<{tag}>{PERSON}</{tag}>', x, flags=re.S)
        for tag in ('dc:title', 'dc:subject', 'dc:description', 'cp:keywords', 'cp:category'):
            x = re.sub(rf'(<{tag}>)(.*?)(</{tag}>)', lambda m: m.group(1) + _esc(anon.scrub(_unesc(m.group(2)))) + m.group(3), x, flags=re.S)
        parts['docProps/core.xml'] = x.encode('utf-8')
    if 'docProps/app.xml' in parts:
        x = parts['docProps/app.xml'].decode('utf-8')
        for tag in ('Company', 'Manager'):
            x = re.sub(rf'<{tag}>.*?</{tag}>', f'<{tag}>Redacted</{tag}>', x, flags=re.S)
        x = re.sub(r'<HyperlinkBase>.*?</HyperlinkBase>', '<HyperlinkBase></HyperlinkBase>', x, flags=re.S)
        x = re.sub(r'<Template>.*?</Template>', '<Template></Template>', x, flags=re.S)
        parts['docProps/app.xml'] = x.encode('utf-8')
    if '_rels/.rels' in parts:
        x = parts['_rels/.rels'].decode('utf-8')
        parts['_rels/.rels'] = re.sub(r'<Relationship\b[^>]*Target="docProps/custom\.xml"[^>]*/>', '', x).encode('utf-8')
    ct = parts['[Content_Types].xml'].decode('utf-8')
    parts['[Content_Types].xml'] = re.sub(r'<Override[^>]*PartName="/docProps/custom\.xml"[^>]*/>', '', ct).encode('utf-8')


def html_clean(raw):
    """SEC exhibit HTML/TXT → HTML without pictures, scripts, links or tracking; ready for LibreOffice."""
    text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw
    if not re.search(r'<(html|body|div|p|table)\b', text[:5000], re.I):
        return '<html><body><pre>' + _esc(text) + '</pre></body></html>'
    text = re.sub(r'<(script|style|noscript|iframe|object|embed|svg)\b.*?</\1>', '', text, flags=re.S | re.I)
    text = re.sub(r'<(img|link|meta|base|input)\b[^>]*>', '', text, flags=re.I)
    text = re.sub(r'<a\b[^>]*>', '', text, flags=re.I).replace('</a>', '').replace('</A>', '')
    text = re.sub(r'url\([^)]*\)', 'none', text, flags=re.I)
    return text
