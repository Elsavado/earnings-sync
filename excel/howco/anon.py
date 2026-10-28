"""Made-up names for people and companies in text and files (people.py, companies.py).

Text: people first (a pair that is a company name is left to the company pass), then companies.
Files: PDF (words truly removed, the made-up name written in their place), DOCX/PPTX/XLSX (text rewritten at
XML level: paragraphs, cells, sheet names, comments, headers; document properties cleared), CSV/TXT/MD/HTML/EML.
Legacy DOC/XLS/PPT are converted to DOCX/XLSX/PPTX with LibreOffice first.
"""
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, unescape

from . import companies as _co
from . import people as _pp

TEXT_EXT = {'csv', 'txt', 'md', 'htm', 'html', 'xml', 'json', 'tsv', 'eml'}
OOXML = {'docx', 'xlsx', 'pptx', 'xlsm'}
LEGACY = {'doc': 'docx', 'xls': 'xlsx', 'ppt': 'pptx', 'rtf': 'docx', 'wpd': 'docx'}


class Anon:
    def __init__(self, people_maps, people_own, co_maps, co_own, key, registrants=(), top=(), tickers=(), tick_maps=(),
                 tick_own=None, ner=True):
        self.co = _co.Companies(co_maps, co_own, key, registrants, top, tickers, tick_maps, tick_own)
        self.use_ner = ner  # spaCy finds the people of documents the rules do not know (first names not on the list)
        self.check_ner = False  # dry runs: spaCy also looks for people left in the output
        self.nlp = None
        self.pp = _pp.People(people_maps, people_own, key, avoid=self.co.words(), domain=self.co.domain,
                             is_company=self.co.is_company)

    def text(self, s, participants=(), learn=True):
        if not s:
            return s
        if learn:
            self.co.learn_all(s)  # from the original text only: never from made-up names
        s = self.pp.sub(s, participants, learn=learn)
        return self.co.sub(s, learn=False)

    def start(self):
        """A new document: forget which real names were replaced (the leak check is per document)."""
        self.co.start()

    def prelearn(self, s, ner=None):
        """Learns the companies (and, with spaCy, the people) of a whole message or document before any part of it
        is rewritten. Returns the people found, so their surnames alone are replaced in the document too."""
        self.co.learn_all(s)
        found = []
        if self.use_ner if ner is None else ner:
            for f, l in self.people_in(s):
                self.pp.pseudo(f, l)
                found.append((f, l))
        return found

    def _nlp(self):
        if self.nlp is None:
            try:
                import spacy
                self.nlp = spacy.load('en_core_web_sm', exclude=['parser', 'lemmatizer', 'attribute_ruler', 'tagger',
                                                                 'senter'])
                self.nlp.max_length = 2_000_000
            except Exception:  # noqa: BLE001 - without spaCy the rules alone are used
                self.nlp = False
        return self.nlp

    def people_in(self, s, limit=800000):
        """('First', 'Last') of the people spaCy finds in s (two to four capitalised words, not a company, not a
        made-up name, not a phrase of everyday words)."""
        nlp = self._nlp()
        if not nlp or not s:
            return []
        out, seen = [], set()
        for i in range(0, min(len(s), limit), 100000):
            for ent in nlp(s[i:i + 100000]).ents:
                if ent.label_ != 'PERSON':
                    continue
                toks = re.findall(r"[A-Za-z][A-Za-z'’\-]+", ent.text)
                toks = [t for t in toks if not (len(t) == 1)]
                if not 2 <= len(toks) <= 4 or not all(t[0].isupper() for t in toks):
                    continue
                f, l = toks[0], re.sub(r"['’]s$", '', toks[-1])
                key = (f.lower(), l.lower())
                if key in seen or self.pp.fake(f, l) or self.co.is_company(f, l):
                    continue
                if (f.lower() in _pp.NOT_NAMES or l.lower() in _pp.NOT_NAMES or l.lower() in _pp.NOT_LAST
                        or f.lower() in _pp.PLACE_FIRST or f'{f} {l}'.lower() in _pp.NOT_PEOPLE
                        or any(w.lower() in self.co.taken_flat for w in (f, l))
                        or all(self.pp.common(w) >= 4.5 for w in (f, l)) or (f.isupper() and l.isupper())):
                    continue
                seen.add(key)
                out.append((f, l))
        return out

    def leaks(self, s, participants=()):
        out = self.pp.leaks(s, participants) + self.co.leaks(s)
        if self.check_ner:  # people the rules never learned: listed as 'possible' for checking
            fake = {w.lower() for v in self.pp.taken for w in v.split()}
            for f, l in self.people_in(s, limit=300000):
                if f.lower() not in fake and l.lower() not in fake:
                    out.append(f'possible person: {f} {l}')
        return out

    # --- files --------------------------------------------------------------------------------------
    def file(self, src, dst, ext, participants=()):
        """Writes the made-up-name version of src to dst. Returns (ok, text for the leak check)."""
        ext = ext.lower()
        if ext == 'pdf':
            return self.pdf(src, dst, participants)
        if ext in OOXML:
            return self.ooxml(src, dst, participants)
        if ext in TEXT_EXT:
            raw = Path(src).read_bytes()
            t = raw.decode('utf-8', 'replace') if _utf8(raw) else raw.decode('cp1252', 'replace')
            participants = list(participants) + self.prelearn(t)
            out = self.text(t, participants)
            Path(dst).write_text(out, encoding='utf-8')
            return True, out
        return False, ''

    def pdf(self, src, dst, participants=()):
        import pymupdf
        doc = pymupdf.open(src)
        if doc.needs_pass:
            return False, ''
        participants = list(participants) + self.prelearn(''.join(p.get_text() for p in doc)[:2000000])
        full = []
        for page in doc:
            text = page.get_text()
            new = self.text(text, participants)
            if new == text:
                full.append(new)
                continue
            # The words that changed: search each original phrase and write the replacement over it.
            for old, rep in _changes(text, new):
                for rect in page.search_for(old):
                    page.add_redact_annot(rect, text=rep, fontsize=0, fill=(1, 1, 1), cross_out=False)
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
            full.append(page.get_text())
        doc.set_metadata({})
        try:
            doc.del_xml_metadata()
        except Exception:  # noqa: BLE001
            pass
        doc.save(dst, garbage=3, deflate=True)
        return True, '\n'.join(full)

    def ooxml(self, src, dst, participants=()):
        texts = []
        with zipfile.ZipFile(src) as zin:
            participants = list(participants) + self.prelearn(' '.join(
                re.sub(r'<[^>]+>', ' ', zin.read(n).decode('utf-8', 'replace'))
                for n in zin.namelist() if n.endswith('.xml'))[:2000000])
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                n = item.filename
                if n.startswith('docProps/') and n.endswith('.xml'):
                    data = re.sub(rb'(<(?:dc:creator|cp:lastModifiedBy|dc:title|dc:subject|cp:keywords|dc:description|'
                                  rb'Company|Manager)[^>]*>)[^<]*', rb'\1', data)
                elif n.endswith(('.xml', '.rels')) and not n.startswith(('customXml/', '[Content_Types]')):
                    x = data.decode('utf-8', 'replace')
                    x = self._xml(x, participants, n)
                    texts.append(re.sub(r'<[^>]+>', ' ', x))
                    data = x.encode('utf-8')
                zout.writestr(item, data)
        return True, '\n'.join(texts)

    def _xml(self, x, participants, name):
        # Word / PowerPoint paragraphs: the text of a paragraph is joined, changed, and put back in its first run.
        def para(m):
            p = m.group(0)
            runs = list(re.finditer(r'(<(w|a):t(?:\s[^>]*)?>)(.*?)(</\2:t>)', p, re.S))
            if not runs:
                return p
            old = ''.join(unescape(r.group(3)) for r in runs)
            new = self.text(old, participants)
            if new == old:
                return p
            out, last = [], 0
            for i, r in enumerate(runs):
                out.append(p[last:r.start()])
                body = escape(new) if i == 0 else ''
                tag = r.group(1) if i or 'xml:space' in r.group(1) else r.group(1)[:-1] + ' xml:space="preserve">'
                out.append(f'{tag}{body}{r.group(4)}')
                last = r.end()
            out.append(p[last:])
            return ''.join(out)
        x = re.sub(r'<(w|a):p\b.*?</\1:p>', para, x, flags=re.S)
        # Spreadsheet strings, comments, sheet names, chart text.
        x = re.sub(r'(<t(?:\s[^>]*)?>)(.*?)(</t>)', lambda m: m.group(1) + escape(self.text(unescape(m.group(2)),
                   participants)) + m.group(3), x, flags=re.S)
        x = re.sub(r'(<(?:c:v|v)>)([^<]*[A-Za-z][^<]*)(</(?:c:v|v)>)', lambda m: m.group(1) + escape(self.text(
            unescape(m.group(2)), participants)) + m.group(3) if 'chart' in name else m.group(0), x)
        x = re.sub(r'(<sheet\b[^>]*\bname=")([^"]*)(")', lambda m: m.group(1) + escape(self.text(unescape(m.group(2)),
                   participants)[:31]) + m.group(3), x)
        x = re.sub(r'(\b(?:author|authorId|w:author|w:initials)=")([^"]*)(")', lambda m: m.group(1) + escape(
            self.text(unescape(m.group(2)), participants)) + m.group(3), x)
        x = re.sub(r'(<author>)([^<]*)(</author>)', lambda m: m.group(1) + escape(self.text(unescape(m.group(2)),
                   participants)) + m.group(3), x)
        # Links: hyperlink targets and their text.
        x = re.sub(r'(Target=")(https?://[^"]+|mailto:[^"]+)(")', lambda m: m.group(1) + escape(self.text(unescape(
            m.group(2)), participants, learn=False)) + m.group(3), x)
        return x


def _utf8(b):
    try:
        b.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


def _changes(old, new):
    """(original phrase, replacement) pairs between a text and its changed version, at word level."""
    import difflib
    a, b = re.findall(r'\S+', old), re.findall(r'\S+', new)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == 'replace' and i2 > i1:
            out.append((' '.join(a[i1:i2]), ' '.join(b[j1:j2])))
        elif op == 'delete':
            out.append((' '.join(a[i1:i2]), ''))
    # Longest first, so 'Phillip K. Allen' goes before 'Allen'.
    return sorted(set(out), key=lambda p: -len(p[0]))


def convert_legacy(paths, outdir):
    """{path: converted path or None} for DOC/XLS/PPT/RTF (LibreOffice, one call per target format)."""
    from models.lo import _profile, soffice
    out = {}
    by = {}
    for p in paths:
        by.setdefault(LEGACY[Path(p).suffix.lower().lstrip('.')], []).append(p)
    for target, group in by.items():
        for i in range(0, len(group), 40):
            chunk = group[i:i + 40]
            try:
                subprocess.run([soffice(), f'-env:UserInstallation={_profile()}', '--headless', '--norestore',
                                '--convert-to', target, '--outdir', str(outdir), *map(str, chunk)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900, check=False)
            except subprocess.TimeoutExpired:
                subprocess.run(['pkill', '-9', '-f', 'soffice'], check=False)
            for p in chunk:
                q = Path(outdir) / (Path(p).stem + '.' + target)
                out[p] = str(q) if q.exists() and q.stat().st_size else None
    return out


def which(*names):
    return next((shutil.which(n) for n in names if shutil.which(n)), None)
