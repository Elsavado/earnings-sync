"""One collection run of financial documents: find candidates for every type, download,
convert (DOC → DOCX, PPT → PPTX, HTML/TXT exhibits → PDF), check the type, anonymise,
number per type and upload to Google Drive in folders of twenty.

Environment: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN (Drive),
SEC_USER_AGENT, GITHUB_TOKEN, RUN_MINUTES (budget), DRY_RUN=true (no uploads),
KINDS (comma list to limit the run to some types).
"""
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path

import requests
from googleapiclient.errors import HttpError

from models.anonymize import Anonymizer

from . import kinds as K
from . import feeds
from . import llm
from . import office
from . import research
from . import sources
from .anon import DocAnon, html_clean
from .store import Store
from .tab import Table

START = time.time()
BUDGET = float(os.environ.get('RUN_MINUTES', '50')) * 60
DRY = os.environ.get('DRY_RUN', '').lower() == 'true'
ONLY = [k for k in os.environ.get('KINDS', '').split(',') if k.strip()]
# Documents are small; transaction and payroll datasets are downloaded whole (up to 1.5 GB).
FILE_SECONDS = {'doc': 240, 'data': 1800}
MAX_BYTES = {'doc': 60 * 2**20, 'data': 1536 * 2**20}
DOWNLOAD_SECONDS = {'doc': 120, 'data': 900}
FLOOR = float(os.environ.get('DRIVE_FLOOR_GB', '10')) * 2**30  # stop when Drive has less free space than this
STATE_NAME = f'state-{ONLY[0]}.json.gz' if len(ONLY) == 1 else 'state.json.gz'


sources.DISCOVER.update(research.DISCOVER)
sources.DISCOVER.update(office.DISCOVER)


def size_class(kind):
    return 'data' if kind in K.TABULAR or kind in ('figma', 'styleguides') else 'doc'  # these download many files
ANON = None  # set before the worker pool forks


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def left():
    return BUDGET - (time.time() - START)


# --- LibreOffice -------------------------------------------------------------------------
def convert(src, outdir, target):
    """target: 'pdf' (from HTML or an Office file), 'docx' or 'pptx'. Returns the output path or None."""
    from models.lo import _profile, soffice
    filt = {'pdf': 'pdf', 'docx': 'docx:MS Word 2007 XML', 'pptx': 'pptx:Impress MS PowerPoint 2007 XML'}[target]
    cmd = [soffice(), f'-env:UserInstallation={_profile()}', '--headless', '--norestore', '--nolockcheck']
    if str(src).endswith('.html'):
        cmd += ['--infilter=HTML (StarWriter)']
    cmd += ['--convert-to', filt, '--outdir', str(outdir), str(src)]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180, check=False)
    except subprocess.TimeoutExpired:
        subprocess.run(['pkill', '-9', '-f', 'soffice'], check=False)
        return None
    out = Path(outdir) / (Path(src).stem + '.' + target)
    return str(out) if out.exists() and out.stat().st_size > 0 else None


def html_to_pdf(src, outdir):
    """HTML → PDF. Chrome lays out SEC exhibits (slide-like pages, tables) as a browser shows them;
    LibreOffice is the fallback."""
    chrome = next((c for c in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser') if shutil.which(c)), None)
    if chrome:
        out = Path(outdir) / (Path(src).stem + '.pdf')
        try:
            subprocess.run([chrome, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-pdf-header-footer',
                            f'--user-data-dir={Path(outdir) / "chrome"}', f'--print-to-pdf={out}', Path(src).resolve().as_uri()],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=False)
        except subprocess.TimeoutExpired:
            subprocess.run(['pkill', '-9', '-f', 'chrome'], check=False)
        if out.exists() and out.stat().st_size > 0:
            return str(out)
    return convert(src, outdir, 'pdf')


def readable(pdf):
    """None when the PDF shows its text; otherwise why not. SEC slide exhibits are often pictures with an
    invisible copy of the text (white or 1-point) for search: with the pictures removed they look empty."""
    import pymupdf
    total = shown = 0
    full_pages = 0
    with pymupdf.open(pdf) as doc:
        for page in doc:
            vis = 0
            for b in page.get_text('dict', flags=0)['blocks']:
                for line in b.get('lines', []):
                    for sp in line['spans']:
                        n = len(sp['text'].split())
                        total += n
                        c = sp.get('color', 0)
                        white = all(((c >> s) & 255) > 235 for s in (16, 8, 0))
                        if sp.get('size', 0) >= 4 and not white and sp.get('alpha', 255) > 40:
                            vis += n
            shown += vis
            full_pages += vis >= 25
        pages = doc.page_count
    if not total or shown < 0.6 * total:
        return 'text is hidden (slides are pictures)'
    if full_pages < 0.5 * pages:
        return f'mostly empty pages ({full_pages} of {pages} have text)'
    return None


_SECTORS = {}


def describe(label, cand):
    """'Fairness opinion presentation' → 'Fairness opinion presentation - Semiconductors - 2024' (SEC filings:
    the filer's industry and the filing year; never a name)."""
    parts = [label]
    cik = cand.get('cik') or next(iter(re.findall(r'CIK 0*(\d+)', ' '.join(cand.get('orgs') or []))), '')
    if cik:
        if cik not in _SECTORS:
            try:
                r = sources.session().get(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json', timeout=30)
                _SECTORS[cik] = (r.json().get('sicDescription') or '').strip().title() if r.ok else ''
            except (requests.RequestException, ValueError):
                _SECTORS[cik] = ''
        if _SECTORS[cik]:
            parts.append(re.sub(r'\s+', ' ', _SECTORS[cik])[:50])
    if re.match(r'\d{4}', cand.get('date') or ''):
        parts.append(cand['date'][:4])
    return ' - '.join(parts)


def ooxml_text(path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.match(r'(word/document|ppt/slides/slide\d+)\.xml$', n)]
        names.sort(key=lambda n: int(re.sub(r'\D', '', n) or 0))
        paras = []
        for n in names:
            x = z.read(n).decode('utf-8', 'replace')
            for p in re.findall(r'<(?:w|a):p\b.*?</(?:w|a):p>', x, re.S):
                paras.append(''.join(re.findall(r'<(?:w|a):t(?:\s[^>]*)?>(.*?)</(?:w|a):t>', p, re.S)))
    return '\n'.join(paras)


BOT_CHECK = re.compile(rb"not a bot|are you a robot|verify you are human|checking your browser|captcha|"
                       rb"cf-challenge|Just a moment\.\.\.|access denied", re.I)
NOTEBOOK_WORDS = re.compile(r'portfolio|returns?|valuation|dcf|discount|option|black.?scholes|volatility|sharpe|backtest|'
                            r'stock|equity|bond|yield|interest rate|credit|risk|var\b|cash flow|wacc|ebitda|revenue|'
                            r'financial|price|trading|hedg', re.I)


_BLOCK = re.compile(r'<(p|div|tr|table)\b[^>]*>.*?</\1>', re.S | re.I)
_CONTACT = re.compile(r'\b(?:investor|media|press|company)?\s*contacts?\b\s*:?', re.I)


def _text(fragment):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>|&nbsp;|&#160;', ' ', fragment)).strip()


def sec_exhibit_clean(html):
    """SEC exhibit HTML for a Google Doc: no EDGAR header (exhibit type, file name, description), no page title, no
    contact blocks (the 'Contacts:' line, the short name / title lines after it and small contact tables), no
    telephone numbers or e-mail addresses."""
    html = re.sub(r'^.*?<TEXT>', '', html, count=1, flags=re.S | re.I)
    html = re.sub(r'<title\b.*?</title>', '', html, flags=re.S | re.I)
    out, drop, pos = [], 0, 0
    for m in _BLOCK.finditer(html):
        text = _text(m.group(0))
        if m.group(1).lower() == 'table' and len(text) < 600 and _CONTACT.search(text):
            cut = True
        elif _CONTACT.match(text) and len(text) < 200:
            cut, drop = True, 6  # the contact heading and up to six short lines after it
        elif drop and len(text) < 90:
            cut, drop = True, drop - 1
        else:
            cut, drop = False, 0
        out.append(html[pos:m.start()] + ('' if cut else m.group(0)))
        pos = m.end()
    html = ''.join(out) + html[pos:]
    html = re.sub(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', '', html)
    return re.sub(r'(?:\+?1[\s.-]?)?\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}\b', '', html)


def process(cand, kind, work):
    """Downloads and anonymises one candidate. Returns {'ok', 'path', 'ext', 'label'} or {'ok': False, 'reason'}."""
    A = ANON['doc']
    if kind in office.KINDS:
        office.setup(kind)
    work = Path(work)
    s = sources.session()
    r = s.get(cand['url'], timeout=90, stream=True)
    if not r.ok:
        return {'ok': False, 'reason': f'http {r.status_code}'}
    raw = work / 'download.bin'
    size, t0 = 0, time.time()
    cap = office.MAX_SIZE['xlsx'] if kind in office.KINDS and cand['ext'] == 'xlsx' else MAX_BYTES[size_class(kind)]
    with open(raw, 'wb') as f:
        for chunk in r.iter_content(1 << 16):
            size += len(chunk)
            if size > cap or time.time() - t0 > DOWNLOAD_SECONDS[size_class(kind)]:
                return {'ok': False, 'reason': 'too large or too slow'}
            f.write(chunk)
    digest = file_hash(raw)
    if kind in research.KINDS:
        res = research.process(cand, kind, raw, work, A)
        res.setdefault('raw', digest)
        return res
    data = raw.read_bytes() if kind not in K.TABULAR else open(raw, 'rb').read(65536)  # datasets: only the start
    if data[:5] != b'%PDF-' and (kind not in K.TABULAR or data.lstrip()[:1] == b'<') and BOT_CHECK.search(data[:6000]):  # a site that challenges automated visitors: respect it and skip the site
        return {'ok': False, 'reason': 'site blocks automated downloads',
                'blocked': re.sub(r'^https?://([^/]+).*$', r'\1', r.url)}
    ext = cand['ext']
    if data[:5] == b'%PDF-':
        ext = 'pdf'
    elif data[:2] == b'PK' and ext not in ('docx', 'pptx', 'xlsx'):
        return {'ok': False, 'reason': 'unexpected archive', 'raw': digest}
    elif ext == 'pdf':
        ext = 'html' if re.search(rb'<html|<body|<div', data[:4000], re.I) else 'bad'
        if ext == 'bad':
            return {'ok': False, 'reason': 'not a PDF', 'raw': digest}
    out = work / 'out'
    out.mkdir()

    if kind in K.TABULAR:
        tab = Table(A)
        if ext not in ('csv', 'xlsx', 'json'):
            return {'ok': False, 'reason': f'unsupported {ext}', 'raw': digest}
        src = work / f'data.{ext}'
        shutil.copy(raw, src)
        dst = out / f'data.{ext}'
        try:
            if kind in office.KINDS and ext != 'json':
                A.learn(office.table_text(src, ext))  # the sheet's own people, as documents do
            why = getattr(tab, ext)(src, dst, kind)
            if not why and kind in office.KINDS and ext != 'json':
                left_over = A.leaks(office.table_text(dst, ext))
                if left_over:
                    why = f'names left ({left_over[:3]})'
        except Exception as err:  # noqa: BLE001
            why = f'unreadable ({type(err).__name__})'
        if why:
            return {'ok': False, 'reason': why, 'raw': digest}
        lab = office.label(kind, cand, A) if kind in office.KINDS else K.LABEL[kind]
        sample = ''
        if kind in llm.KINDS and ext != 'json':
            try:
                sample = office.table_text(dst, ext, limit=llm.EXCERPT)
            except Exception:  # noqa: BLE001
                sample = ''
        return {'ok': True, 'path': str(dst), 'ext': ext, 'label': lab, 'raw': digest, 'sample': sample}

    if kind == 'notebooks':
        src = work / 'nb.ipynb'
        shutil.copy(raw, src)
        try:
            nb = json.loads(data.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return {'ok': False, 'reason': 'not JSON', 'raw': digest}
        cells = nb.get('cells', []) if isinstance(nb, dict) else []
        code = [c for c in cells if c.get('cell_type') == 'code']
        allsrc = '\n'.join(''.join(c.get('source', '')) if isinstance(c.get('source'), list) else c.get('source', '') for c in cells)
        if len(code) < 6:
            return {'ok': False, 'reason': f'only {len(code)} code cells', 'raw': digest}
        if len(set(m.group(0).lower() for m in NOTEBOOK_WORDS.finditer(allsrc))) < 4:
            return {'ok': False, 'reason': 'not a finance notebook', 'raw': digest}
        letters = [ch for ch in allsrc if ch.isalpha()]
        if letters and sum(ch.isascii() for ch in letters) / len(letters) < 0.9:
            return {'ok': False, 'reason': 'not English', 'raw': digest}
        dst = out / 'nb.ipynb'
        why = A.ipynb(src, dst)
        if why:
            return {'ok': False, 'reason': why, 'raw': digest}
        return {'ok': True, 'path': str(dst), 'ext': 'ipynb', 'label': K.LABEL[kind], 'raw': digest}

    # Documents
    if kind == 'gdocs' and ext in ('htm', 'html'):  # SEC exhibits for Google Docs: HTML -> Word (feeds.sec_docs)
        src = work / 'doc.html'
        html = sec_exhibit_clean(html_clean(data))
        src.write_text(html, encoding='utf-8')
        conv = convert(src, work, 'docx')
        if not conv:
            return {'ok': False, 'reason': 'HTML conversion failed', 'raw': digest}
        ext, src = 'docx', Path(conv)
    elif ext in ('htm', 'html', 'txt'):
        src = work / 'doc.html'
        src.write_text(html_clean(data), encoding='utf-8')
        pdf = html_to_pdf(src, work)
        if not pdf:
            return {'ok': False, 'reason': 'HTML conversion failed', 'raw': digest}
        ext, src = 'pdf', Path(pdf)
    elif ext in ('doc', 'ppt'):
        src = work / f'doc.{ext}'
        shutil.copy(raw, src)
        conv = convert(src, work, 'docx' if ext == 'doc' else 'pptx')
        if not conv:
            return {'ok': False, 'reason': f'{ext} conversion failed', 'raw': digest}
        ext, src = ('docx' if ext == 'doc' else 'pptx'), Path(conv)
    else:
        src = work / f'doc.{ext}'
        shutil.copy(raw, src)
    if ext not in ('pdf', 'docx', 'pptx'):
        return {'ok': False, 'reason': f'unsupported {ext}', 'raw': digest}

    if ext == 'pdf':
        try:
            text, pages = A.pdf_text(src)
        except Exception as err:  # noqa: BLE001
            return {'ok': False, 'reason': f'unreadable PDF ({type(err).__name__})', 'raw': digest}
        if len(text.split()) < 40 * max(1, pages) * 0.5:
            return {'ok': False, 'reason': 'scanned or image-only', 'raw': digest}
        why = readable(src)
        if why:
            return {'ok': False, 'reason': why, 'raw': digest}
    else:
        try:
            text = ooxml_text(src)
        except Exception as err:  # noqa: BLE001
            return {'ok': False, 'reason': f'unreadable {ext} ({type(err).__name__})', 'raw': digest}
    why = K.gate(kind, text)
    if why:
        return {'ok': False, 'reason': why, 'raw': digest}
    label = K.label(kind, text)
    dst = out / f'doc.{ext}'
    if ext == 'pdf':
        A.learn(text, cand.get('orgs') or [])
        why = A.pdf(src, dst)
    else:
        why = A.ooxml(src, dst)  # learns from the file's own text
        if not why:
            check = convert(dst, work / 'check', 'pdf')  # it must open, and nothing may be left
            if not check:
                why = f'{ext} does not open after anonymising'
            else:
                left_over = A.leaks(A.pdf_text(check)[0])
                if left_over:
                    why = f'names left ({left_over[:3]})'
    if not why and ext == 'pdf':
        why = readable(dst)  # the delivered file itself must show its text
    if why:
        return {'ok': False, 'reason': why, 'raw': digest}
    if kind in office.KINDS:
        want = {'gdocs': 'docx', 'slides': 'pptx', 'presentations': 'pdf'}[kind]
        if ext != want:
            return {'ok': False, 'reason': f'{ext}, not {want}', 'raw': digest}
        if kind == 'slides' and office.slide_count(dst) < 5:
            return {'ok': False, 'reason': 'fewer than 5 slides', 'raw': digest}
        if kind == 'presentations':
            pages, wide = office.landscape_share(dst)
            if pages < 5 or wide < 0.6:
                return {'ok': False, 'reason': 'not a slide presentation', 'raw': digest}
        label = office.label(kind, cand, A)
    return {'ok': True, 'path': str(dst), 'ext': ext, 'label': describe(label, cand), 'raw': digest,
            'sample': text[:llm.EXCERPT]}


def _process_one(args):
    cand, kind, work = args
    try:
        return process(cand, kind, work)
    except requests.RequestException as err:
        return {'ok': False, 'reason': f'download failed ({type(err).__name__})'}
    except Exception as err:  # noqa: BLE001
        traceback.print_exc(limit=3)
        return {'ok': False, 'reason': f'error {type(err).__name__}: {str(err)[:80]}'}


WORKER_MEM = float(os.environ.get('WORKER_MEM_GB', '3')) * 2**30


def _limit_memory():
    """Caps each child's heap: a spreadsheet that unpacks to gigabytes raises MemoryError in its own child (the file
    is rejected) instead of exhausting the runner, which GitHub then reports only as 'The operation was canceled'."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_DATA, (int(WORKER_MEM), int(WORKER_MEM)))
    except (ImportError, ValueError, OSError):
        pass


class Worker:
    """Runs process() in child processes (several files at once) so a pathological file can be killed."""

    def __init__(self, n):
        self.n = n
        self.pool = multiprocessing.get_context('fork').Pool(n, initializer=_limit_memory)

    def start(self, args):
        return self.pool.apply_async(_process_one, (args,))

    def reset(self):
        self.pool.terminate()
        os.system('pkill -9 -f soffice >/dev/null 2>&1; pkill -9 -f chrome >/dev/null 2>&1')
        self.pool = multiprocessing.get_context('fork').Pool(self.n, initializer=_limit_memory)

    def close(self):
        self.pool.terminate()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


class Run:
    def __init__(self):
        signed_in = os.environ.get('GOOGLE_REFRESH_TOKEN') or os.environ.get('GOOGLE_SA_JSON')
        self.store = None if DRY and not signed_in else Store(dry_run=DRY, state_name=STATE_NAME)
        self.state = (self.store.load_state() if self.store else {}) or {}
        st = self.state
        for k, v in {'next': {}, 'seen': {}, 'queued': {}, 'queue': {}, 'cursors': {}, 'hashes': {}, 'counts': {}}.items():
            st.setdefault(k, v)
        if self.store and not DRY:
            for kind, n in self.store.max_numbers().items():
                if kind in K.KINDS:
                    st['next'][kind] = max(st['next'].get(kind, 1), n + 1)
        self.tmp = Path(tempfile.mkdtemp(prefix='fd_'))
        self.made = {}
        self.uploaded_bytes = self.checked_at = 0
        self.full = False
        self.last_save = time.time()

    def save(self, force=False):
        if self.store and (force or time.time() - self.last_save > 300):
            try:
                self.store.save_state(self.state)
            except Exception as err:  # noqa: BLE001
                log(f'state save failed, will retry: {type(err).__name__}: {err}')
                return
            self.last_save = time.time()

    def publish(self, kind, res, cand):
        digest = file_hash(res['path'])
        fp = res.get('fp')  # a content fingerprint (research notebooks: their code cells)
        if digest in self.state['hashes'] or (fp and fp in self.state['hashes']):
            self.state['seen'][cand['key']] = 'rej:duplicate'
            return
        if kind in office.KINDS and office.repeated_label(self.state, kind, res['label']):
            self.state['seen'][cand['key']] = 'rej:same title as an earlier file'
            log(f'  - {kind} {cand["source"]}: same title as an earlier file')
            return
        n = self.state['next'].get(kind, 1)
        try:
            name = (self.store.upload_doc(res['path'], kind, n, res['label'], res['ext'], cand['key']) if self.store
                    else f'{n} - {res["label"]}.{res["ext"]}')
        except (HttpError, ssl.SSLError, ConnectionError, TimeoutError, OSError) as err:
            # Drive keeps failing on this one file (it cannot convert it, or converting outlasts the read timeout):
            # count it if it landed after all, else skip it and go on. Several failures in a row: Drive is down, stop.
            if isinstance(err, HttpError) and err.resp.status not in (400, 500):  # 400: Drive will not take this file
                raise
            self.upload_fails = getattr(self, 'upload_fails', 0) + 1
            if self.upload_fails >= 3:
                raise
            got = self.store.uploaded(cand['key'])
            if not got:
                self.state['seen'][cand['key']] = 'rej:Drive could not take the file'
                log(f'  - {kind}: Drive could not take one file ({type(err).__name__}); skipped')
                return
            name = f'#{n}'
            log(f'  {kind}: #{n} landed despite the error ({len(got)} copies on the drive)')
        self.upload_fails = 0
        self.state['next'][kind] = n + 1
        self.state['hashes'][digest] = f'{kind}:{n}'
        if fp:
            self.state['hashes'][fp] = f'{kind}:{n}'
        self.state['seen'][cand['key']] = f'ok:{kind}:{n}'
        c = self.state['counts']
        c[kind] = c.get(kind, 0) + 1
        c[f'source:{cand["source"]}'] = c.get(f'source:{cand["source"]}', 0) + 1
        self.made[kind] = self.made.get(kind, 0) + 1
        if DRY and self.made[kind] <= 3:  # dry runs keep a few outputs per type for inspection
            d = Path('samples') / kind
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy(res['path'], d / name)
        log(f'  {K.KINDS[kind]["folder"]}: #{n}')  # numbers only: the repository is public
        self.save()
        self.uploaded_bytes += Path(res['path']).stat().st_size
        if self.store and not DRY and (self.uploaded_bytes - self.checked_at > 2 * 2**30 or self.made[kind] % 50 == 0):
            self.checked_at = self.uploaded_bytes
            if self.store.free_bytes() < FLOOR:
                log(f'Drive has less than {FLOOR / 2**30:.0f} GB free; stopping')
                self.full = True

    def discover(self, kind, s, until):
        q = self.state['queue'].setdefault(kind, [])
        sources.DEADLINE = until
        added = 0
        for fn in sources.DISCOVER[kind]:
            if len(q) >= 60 or time.time() > until:
                break
            try:
                n = fn(self.state, kind, s, log)
                added += n or 0
                if n:
                    log(f'  {kind}: +{n} candidates from {fn.__name__}')
            except Exception as err:  # noqa: BLE001
                log(f'  {kind}: {fn.__name__} failed ({type(err).__name__}: {err})')
        return added

    def work(self, kind, until, worker):
        """Processes the queue several files at a time; results are numbered and uploaded one by one."""
        q = self.state['queue'].setdefault(kind, [])
        done = 0
        pending = []  # (cand, work dir, async result, deadline)
        # A spreadsheet (8 MB at most) that takes minutes is stuck: it must not hold up the run (2026-10-29).
        limit = 300 if kind == 'gsheets' else FILE_SECONDS[size_class(kind)]
        while (q or pending) and not self.full:
            while q and len(pending) < worker.n and time.time() < until:
                cand = q.pop(0)
                self.state['queued'].pop(cand['key'], None)
                if cand['key'] in self.state['seen']:
                    continue
                host = re.sub(r'^https?://([^/]+).*$', r'\1', cand['url'])
                if host in self.state.setdefault('blocked', {}):
                    self.state['seen'][cand['key']] = 'rej:site blocks automated downloads'
                    continue
                work = self.tmp / f'{kind}{done}_{len(pending)}_{int(time.time() * 1000)}'
                work.mkdir()
                pending.append((cand, work, worker.start((cand, kind, str(work))), time.time() + limit))
            if not pending:
                break
            cand, work, ar, deadline = pending.pop(0)
            try:
                res = ar.get(timeout=max(1, deadline - time.time()))
            except multiprocessing.TimeoutError:
                res = {'ok': False, 'reason': f'processing took longer than {limit}s'}
                worker.reset()  # kills the other files in progress too: put them back in the queue
                for c, w, _, _ in pending:
                    q.insert(0, c)
                    self.state['queued'][c['key']] = 1
                    shutil.rmtree(w, ignore_errors=True)
                pending = []
            try:
                self.handle(kind, cand, res)
            finally:
                shutil.rmtree(work, ignore_errors=True)
                done += 1
        return done

    def handle(self, kind, cand, res):
        if res.get('raw'):
            if f'raw:{res["raw"]}' in self.state['seen']:
                self.state['seen'][cand['key']] = 'rej:duplicate download'
                return
            self.state['seen'][f'raw:{res["raw"]}'] = 1
        blocked = res.get('blocked')  # the site that challenged us, after any redirects
        if blocked and not re.search(r'(^|\.)(sec\.gov|github\.com|githubusercontent\.com|handle\.net|doi\.org)$', blocked):
            self.state.setdefault('blocked', {})[blocked] = 1
            log(f'  {blocked} blocks automated downloads; skipping that site from now on')
        if res.get('ok') and kind in llm.KINDS:
            res = self.llm_check(kind, cand, res)
        if not res.get('ok'):
            self.state['seen'][cand['key']] = f'rej:{res.get("reason")}'[:120]
            log(f'  - {kind} {cand["source"]}: {str(res.get("reason"))[:90]}')
            return
        self.publish(kind, res, cand)

    def llm_check(self, kind, cand, res):
        """The LLM acceptance check (llm.py) on the title and the start of the content; a candidate the keyword
        filter alone would reject ('weak') needs its yes."""
        weak = cand.get('weak') or res.get('weak')
        verdict = llm.judge(self.state, kind, cand.get('title') or res.get('label'),
                            res.get('sample') or cand.get('about') or '')
        if verdict is False:
            return {'ok': False, 'reason': 'LLM check: not finance' + (' / English / US-Canada content' if kind in office.KINDS else ' content')}
        if verdict is None and weak:
            return {'ok': False, 'reason': 'not about finance (keyword filter; no LLM check)'}
        if weak:
            self.state['counts']['llm:rescued'] = self.state['counts'].get('llm:rescued', 0) + 1
        return res

    def go(self):
        nexts = {k: self.state['next'].get(k, 1) for k in K.KINDS}
        log(f'start: next numbers {nexts}')
        if self.store:
            used, limit = self.store.quota()
            log(f'Drive: {used / 2**30:.1f} GB used of {limit / 2**30:.1f} GB')
            if limit and limit - used < FLOOR:
                log(f"Drive has less than {FLOOR / 2**30:.0f} GB free; stopping")
                return
        s = sources.session()
        tickers = s.get('https://www.sec.gov/files/company_tickers.json', timeout=60).json()
        names = [v['title'] for v in tickers.values()]
        cj = Path(__file__).resolve().parents[2] / 'companies.json'
        if cj.exists():
            for c in json.loads(cj.read_text(encoding='utf-8')).get('companies', []):
                names += [c.get('name', '')] + list(c.get('aliases') or [])
        try:
            import spacy
            nlp = spacy.load('en_core_web_sm', exclude=['parser', 'lemmatizer', 'attribute_ruler', 'tagger', 'senter'])
        except Exception:  # noqa: BLE001
            nlp = None
        global ANON
        base = Anonymizer(names, [v['title'] for v in list(tickers.values())[:1500]], None)
        ANON = {'doc': DocAnon(base, nlp, [v['ticker'] for v in tickers.values()])}
        log(f'anonymizer: {len(base.multi)} multi-word and {len(base.single)} one-word company names, '
            f'{len(ANON["doc"].tickers)} tickers, spaCy {"on" if nlp else "OFF"}')

        order = [k for k in K.KINDS if k in ONLY] if ONLY else list(K.FIN_KINDS)
        worker = Worker(int(os.environ.get('WORKERS') or (3 if all(k in K.TABULAR for k in order) else 2)))
        for kind in order:
            if kind in office.KINDS:
                office.start(self.state, kind, log, self.store)
                feeds.status(self.state, ('office:',), log, kind)
            if kind in research.KINDS:
                research.prune(self.state, kind, log)
                feeds.status(self.state, ('sci:',) if kind == 'scinotebooks' else (f'{kind}:',), log, kind)
        self.llm_start = dict(self.state.get('llm') or {})
        rounds = 0
        idle = 0  # rounds in a row with empty queues and nothing found
        while left() > 90 and not self.full:
            rounds += 1
            slice_s = max(60, (left() - 60) / len(order))
            for kind in order:
                if left() < 90:
                    break
                until = time.time() + slice_s
                found = self.discover(kind, s, time.time() + min(120, slice_s / 3))
                idle = 0 if found or self.state['queue'].get(kind) else idle + 1
                n = self.work(kind, until, worker)
                log(f'{kind}: processed {n}, {len(self.state["queue"].get(kind, []))} queued, '
                    f'{self.made.get(kind, 0)} made this run')
                self.save(force=True)
            # Research kinds keep searching for the whole run (their sources are slow, paced APIs). Office kinds go
            # on to the next queries and sources while they find anything; three empty rounds in a row end the run.
            if all(not self.state['queue'].get(k) for k in order) and idle >= 3 * len(order)                     and not set(order) & set(research.KINDS):
                break
        worker.close()
        if any(k in llm.KINDS for k in order):
            log(llm.summary(self.state, self.llm_start) + (f'; keyword misses accepted so far: '
                f'{self.state["counts"].get("llm:rescued", 0)}' if llm.available() else '; off (no key)'))
        self.save(force=True)
        c = self.state['counts']
        log(f'done: {sum(self.made.values())} documents this run {json.dumps(self.made)}; totals {json.dumps(c, sort_keys=True)}')
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a', encoding='utf-8') as f:
                title = os.environ.get('COLLECTOR_TITLE', 'Financial documents')
                f.write(f'## {title}\n\n{sum(self.made.values())} documents this run.\n\n| Type | This run | Total |\n|---|---|---|\n')
                for k in order:
                    f.write(f'| {K.KINDS[k]["folder"]} | {self.made.get(k, 0)} | {c.get(k, 0)} |\n')


if __name__ == '__main__':
    code = 0
    try:
        if os.environ.get('RESET', '').lower() == 'true':
            Store().reset(log)
        Run().go()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)
