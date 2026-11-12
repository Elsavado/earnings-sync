"""Cleaned copies of a learning-materials folder (user, 2026-11-12: "remove details to the real files"; copies on
shintiru's drive, originals untouched).

Each file is renamed to its manifest title and its identifying details are removed:
  - people: names after cues (Name:, Lecturer, Prepared/Presented by, Dr./Mr./Mrs./Ms./Prof./Sr.), person names
    spaCy finds on the title and closing pages/slides, and every name in the private identifier list -> 'Redacted Name'
  - the institution, its course codes, places and other terms in the private list -> removed
  - e-mail addresses, phone numbers, registration numbers, web links -> removed
  - file properties (author, last modified by, company, comments) -> cleared
  - logos: pictures in slide masters / layouts and in Word headers / footers are dropped; content pictures stay
Word / PowerPoint / Excel (OOXML) are edited in place; .doc / .ppt are converted first (LibreOffice); PDFs get true
redactions (PyMuPDF). Scanned PDFs and photos cannot be checked, so they are left out and counted.

The identifier list (names, institution, places) is never in this public repository: it is read from the private
file IDS_PATH on the drive (one literal per line; 're:' prefix for a regex; 'drop:' lines only for file titles).
Logs show counts only.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

PERSON = 'Redacted Name'
CUES = re.compile(r"\b(?:Name|Names|Lecturer|Tutor|Instructor|Facilitator|Presenter|Prepared by|Presented by|"
                  r"Compiled by|Submitted by|Submitted to|Supervisor|Author|Dr|Mr|Mrs|Ms|Miss|Prof)\b\.?"
                  r"\s*[:\-]?\s*((?:[A-Z][a-zA-Z'’-]+\.?\s+){0,3}[A-Z][a-zA-Z'’-]+)")
EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
PHONE = re.compile(r'(?:\+?254|\b0)[\s-]?7\d{2}[\s-]?\d{3}[\s-]?\d{3}\b|\+\d{1,3}[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{3,4}\b')
REGNO = re.compile(r'\b[A-Z]{2,5}/\d{2,6}/\d{2,4}\b|\bReg(?:istration)?\.?\s*(?:No|Number)\.?\s*[:\-]?\s*\S+', re.I)
URL = re.compile(r'https?://\S+|www\.\S+')
# Names spaCy calls people that are subject matter (eponyms and theorists) stay.
KEEP = re.compile(r'Parkinson|Alzheimer|Guillain|Barr[eé]|Huntington|Down|Bloom|Maslow|Freud|Erikson|Piaget|Nightingale|'
                  r'Henderson|Orem|Roy|Peplau|Watson|Leininger|Neuman|Rogers|Kohlberg|Skinner|Pavlov|Bandura|Hippocrates|'
                  r'Apgar|Bishop|Braxton|Hicks|Leopold|Naegele|Kegel|Graves|Hashimoto|Cushing|Addison|Crohn|Kaposi|Wilms|'
                  r'Hodgkin|Burkitt|Bell|Tourette|Asperger|Kraepelin|Bleuler|Beck|Ellis|Jung|Adler|Kubler|Ross|Selye|'
                  r'Gibbs|Kolb|Tyler|Gagne|Dewey|Vygotsky|Gardner|Mendel|Darwin|Pasteur|Koch|Lister|Semmelweis|Snow|WHO', re.I)


def load_ids(path):
    lits, regs, drops = [], [], []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('re:'):
            regs.append(re.compile(line[3:], re.I))
        elif line.startswith('drop:'):
            drops.append(re.compile(line[5:], re.I))
        else:
            lits.append(line)
    lits.sort(key=len, reverse=True)
    pat = re.compile('|'.join(r'\b' + re.escape(x) + r'\b' for x in lits), re.I) if lits else None
    return pat, regs, drops


class Cleaner:
    def __init__(self, ids_path, nlp=None):
        self.lit, self.regs, self.drops = load_ids(ids_path)
        self.nlp = nlp
        self.people = set()

    def learn(self, text):
        """People named on title / closing pages, and after name cues."""
        for m in CUES.finditer(text):
            name = m.group(1).strip()
            if not KEEP.search(name) and len(name) > 3:
                self.people.add(name)
        if self.nlp is not None and text.strip():
            for ent in self.nlp(text[:20000]).ents:
                if ent.label_ == 'PERSON' and len(ent.text.split()) >= 2 and not KEEP.search(ent.text) \
                        and all(w[:1].isupper() for w in ent.text.split()):
                    self.people.add(ent.text.strip())

    def text(self, s):
        if not s:
            return s
        s = EMAIL.sub('', s)
        s = URL.sub('', s)
        s = PHONE.sub('', s)
        s = REGNO.sub('', s)
        for p in sorted(self.people, key=len, reverse=True):
            s = re.sub(r'\b' + re.escape(p) + r'\b', PERSON, s)
        s = CUES.sub(lambda m: m.group(0).replace(m.group(1), PERSON) if not KEEP.search(m.group(1)) else m.group(0), s)
        if self.lit is not None:
            s = self.lit.sub('', s)
        for r in self.regs:
            s = r.sub('', s)
        return s

    def leaks(self, text):
        found = 0
        if self.lit is not None:
            found += len(self.lit.findall(text))
        found += sum(len(r.findall(text)) for r in self.regs)
        found += len(EMAIL.findall(text)) + len(PHONE.findall(text))
        return found


# --- OOXML --------------------------------------------------------------------------------------------------------
TEXT_PART = re.compile(r'^(?:word/(?:document|header\d*|footer\d*|footnotes|endnotes)\.xml|'
                       r'ppt/(?:slides/slide|notesSlides/notesSlide|slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml|'
                       r'xl/sharedStrings\.xml|xl/worksheets/sheet\d+\.xml)$')
T_ELEM = re.compile(r'(<(?:w:t|a:t|t)(?:\s[^>]*)?>)([^<]*)(</(?:w:t|a:t|t)>)')
LOGO_RELS = re.compile(r'^(?:ppt/slideMasters|ppt/slideLayouts|word)/_rels/(?:slideMaster\d+|slideLayout\d+|header\d*|footer\d*)\.xml\.rels$')


def _unesc(s):
    return s.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&apos;', "'").replace('&amp;', '&')


def _esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def ooxml_text(path):
    out = []
    with zipfile.ZipFile(path) as z:
        for n in sorted(z.namelist()):
            if TEXT_PART.match(n):
                xml = z.read(n).decode('utf-8', 'replace')
                out.append(' '.join(_unesc(m.group(2)) for m in T_ELEM.finditer(xml)))
    return '\n'.join(out)


def ooxml_edge_text(path):
    """Title and closing slides / first page of text: where authors and presenters are named."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        slides = sorted((n for n in names if re.match(r'ppt/slides/slide\d+\.xml$', n)),
                        key=lambda n: int(re.findall(r'\d+', n)[-1]))
        parts = slides[:2] + slides[-2:] if slides else [n for n in names if n == 'word/document.xml']
        parts += [n for n in names if re.match(r'word/(header|footer)\d*\.xml$', n)]
        text = []
        for n in parts:
            xml = z.read(n).decode('utf-8', 'replace')
            t = ' '.join(_unesc(m.group(2)) for m in T_ELEM.finditer(xml))
            text.append(t[:4000] if n == 'word/document.xml' else t)
    return '\n'.join(text)


def clean_ooxml(src, dst, C):
    C.learn(ooxml_edge_text(src))
    C.learn(ooxml_text(src)[:40000])  # cues anywhere ('Name: ...')
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
        drop_targets = set()
        for n in zin.namelist():
            if LOGO_RELS.match(n):
                rels = zin.read(n).decode('utf-8', 'replace')
                for m in re.finditer(r'<Relationship [^>]*Type="[^"]*/image"[^>]*Target="([^"]+)"[^>]*/>', rels):
                    drop_targets.add(m.group(1).rsplit('/', 1)[-1])
        for item in zin.infolist():
            n = item.filename
            data = zin.read(n)
            if n.endswith(('comments.xml', 'people.xml', 'commentsExtended.xml', 'commentsIds.xml')) or \
                    n.startswith(('ppt/comments/', 'ppt/commentAuthors', 'xl/comments', 'docProps/custom')):
                continue
            if re.match(r'^(?:ppt|word|xl)/media/', n) and n.rsplit('/', 1)[-1] in drop_targets:
                data = _BLANK_PNG  # a logo: keep the part (layouts still point at it) but make it blank
            elif TEXT_PART.match(n):
                xml = data.decode('utf-8', 'replace')
                xml = T_ELEM.sub(lambda m: m.group(1) + _esc(C.text(_unesc(m.group(2)))) + m.group(3), xml)
                xml = re.sub(r'<w:hyperlink [^>]*>', '<w:hyperlink>', xml)
                data = xml.encode('utf-8')
            elif n == 'docProps/core.xml':
                xml = data.decode('utf-8', 'replace')
                for tag in ('dc:creator', 'cp:lastModifiedBy', 'dc:title', 'dc:subject', 'cp:keywords', 'dc:description'):
                    xml = re.sub(rf'<{tag}>[^<]*</{tag}>', f'<{tag}></{tag}>', xml)
                data = xml.encode('utf-8')
            elif n == 'docProps/app.xml':
                xml = data.decode('utf-8', 'replace')
                xml = re.sub(r'<(Company|Manager)>[^<]*</\1>', r'<\1></\1>', xml)
                data = xml.encode('utf-8')
            elif n.endswith('.rels'):
                xml = data.decode('utf-8', 'replace')
                xml = re.sub(r'<Relationship [^>]*TargetMode="External"[^>]*/>', '', xml)
                data = xml.encode('utf-8')
            zout.writestr(item, data)


_BLANK_PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                           '1f15c4890000000d4944415478da6364f8ffbf1e000502027f3d2fc3800000000049454e44ae426082')


# --- PDF ----------------------------------------------------------------------------------------------------------
def pdf_text(path):
    import fitz
    with fitz.open(path) as d:
        return [p.get_text() for p in d]


def clean_pdf(src, dst, C):
    import fitz
    pages = pdf_text(src)
    if sum(len(p.split()) for p in pages) < 30 * max(1, len(pages)) * 0.3:
        return 'scanned'
    C.learn('\n'.join(pages[:2] + pages[-1:]))
    C.learn('\n'.join(pages)[:60000])
    with fitz.open(src) as d:
        for page, text in zip(d, pages):
            terms = set(C.people)
            for rx in [EMAIL, PHONE, REGNO, URL] + ([C.lit] if C.lit is not None else []) + C.regs:
                terms.update(m.group(0) for m in rx.finditer(text) if m.group(0).strip())
            for t in terms:
                for rect in page.search_for(t):
                    page.add_redact_annot(rect, fill=(1, 1, 1))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
            for link in page.get_links():
                page.delete_link(link)
        d.set_metadata({})
        d.del_xml_metadata()
        d.save(dst, garbage=4, deflate=True)
    return None


# --- titles (as in the manifest) ------------------------------------------------------------------------------------
def title(name, C):
    t = unicodedata.normalize('NFKC', os.path.splitext(name)[0])
    if re.match(r'CamScanner|IMG_\d{8}', t, re.I):
        return 'Scanned document'
    if t.lower() == 'name':
        return 'Untitled document'
    t = re.sub(r'-\d{9,}$', '', t)
    t = re.sub(r'_\d{6}_\d{6}', '', t)
    t = re.sub(r'_(?=\d{3})', ' ', t)
    t = re.sub(r'\((?:\d+|Z-Library|Recovered)\)|\[Autosaved\]|- Copy(?:_copy)?|_copy', ' ', t, flags=re.I)
    for r in C.drops:
        t = r.sub(' ', t)
    if C.lit is not None:
        t = C.lit.sub(' ', t)
    for r in C.regs:
        t = r.sub(' ', t)
    t = re.sub(r'\bpptx\b', ' ', t, flags=re.I)
    t = re.sub(r'[_;]+', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip(' -.,')
    t = re.sub(r'\.{2,}', '.', t).replace(' .', '.')
    t = re.sub(r'[\\/:*?"<>|]', ' ', t).strip()
    return t or 'Untitled document'


def convert(src, outdir, ext):
    r = subprocess.run(['soffice', '--headless', '--convert-to', ext, '--outdir', str(outdir), str(src)],
                       capture_output=True, timeout=300)
    out = Path(outdir) / (Path(src).stem + '.' + ext)
    return out if r.returncode == 0 and out.exists() else None


def main(src_dir, out_dir, ids_path, mapping_json):
    """mapping: [[source path, destination folder]] (sections and courses as in the manifest)."""
    try:
        import spacy
        nlp = spacy.load('en_core_web_sm', exclude=['parser', 'lemmatizer', 'attribute_ruler', 'tagger'])
    except Exception:  # noqa: BLE001
        nlp = None
    mapping = json.loads(Path(mapping_json).read_text(encoding='utf-8'))
    stats = {'cleaned': 0, 'scanned left out': 0, 'system files left out': 0, 'failed': 0, 'leaks left': 0}
    used = set()
    for rel, folder in mapping:
        src = Path(src_dir) / rel
        name = src.name
        ext = src.suffix.lower()
        if ext == '.lnk' or name.startswith('~$'):
            stats['system files left out'] += 1
            continue
        if ext in ('.jpeg', '.jpg', '.png'):
            stats['scanned left out'] += 1
            continue
        C = Cleaner(ids_path, nlp)
        work = Path(tempfile.mkdtemp())
        try:
            if ext in ('.doc', '.ppt'):
                conv = convert(src, work, 'docx' if ext == '.doc' else 'pptx')
                if not conv:
                    raise RuntimeError('conversion failed')
                src, ext = conv, conv.suffix.lower()
            base = title(name, C)
            if base == 'Scanned document' and ext == '.pdf':
                stats['scanned left out'] += 1
                continue
            dst_dir = Path(out_dir) / folder
            dst_dir.mkdir(parents=True, exist_ok=True)
            fname, k = f'{base}{ext}', 2
            while (folder, fname.lower()) in used:
                fname, k = f'{base} ({k}){ext}', k + 1
            used.add((folder, fname.lower()))
            dst = dst_dir / fname
            if ext in ('.docx', '.pptx', '.xlsx') and not zipfile.is_zipfile(src):
                # an older format saved under the new extension: let LibreOffice re-save it properly
                old = work / ('legacy' + {'.docx': '.doc', '.pptx': '.ppt', '.xlsx': '.xls'}[ext])
                shutil.copy(src, old)
                conv = convert(old, work, ext.lstrip('.'))
                if not conv:
                    raise RuntimeError('conversion failed')
                src = conv
            if ext in ('.docx', '.pptx', '.xlsx'):
                clean_ooxml(src, dst, C)
                after = ooxml_text(dst)
            elif ext == '.pdf':
                if clean_pdf(src, dst, C) == 'scanned':
                    stats['scanned left out'] += 1
                    continue
                after = '\n'.join(pdf_text(dst))
            else:
                raise RuntimeError('unsupported type')
            left = C.leaks(after)
            if left:
                stats['leaks left'] += 1
                dst.unlink()
                continue
            stats['cleaned'] += 1
        except Exception as err:  # noqa: BLE001
            stats['failed'] += 1
            print(f'  failed: {type(err).__name__}', flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print(json.dumps(stats), flush=True)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write('## Cleaned learning materials\n\n' + '\n'.join(f'- {k}: {v}' for k, v in stats.items()) + '\n')


if __name__ == '__main__':
    main(*sys.argv[1:5])
