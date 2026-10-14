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
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path

import requests

from models.anonymize import Anonymizer

from . import kinds as K
from . import sources
from .anon import DocAnon, html_clean
from .store import Store
from .tab import Table

START = time.time()
BUDGET = float(os.environ.get('RUN_MINUTES', '50')) * 60
DRY = os.environ.get('DRY_RUN', '').lower() == 'true'
ONLY = [k for k in os.environ.get('KINDS', '').split(',') if k.strip()]
FILE_SECONDS = 240
MAX_BYTES = 60 * 2**20
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


NOTEBOOK_WORDS = re.compile(r'portfolio|returns?|valuation|dcf|discount|option|black.?scholes|volatility|sharpe|backtest|'
                            r'stock|equity|bond|yield|interest rate|credit|risk|var\b|cash flow|wacc|ebitda|revenue|'
                            r'financial|price|trading|hedg', re.I)


def process(cand, kind, work):
    """Downloads and anonymises one candidate. Returns {'ok', 'path', 'ext', 'label'} or {'ok': False, 'reason'}."""
    A = ANON['doc']
    work = Path(work)
    s = sources.session()
    r = s.get(cand['url'], timeout=90, stream=True)
    if not r.ok:
        return {'ok': False, 'reason': f'http {r.status_code}'}
    raw = work / 'download.bin'
    size, t0 = 0, time.time()
    with open(raw, 'wb') as f:
        for chunk in r.iter_content(1 << 16):
            size += len(chunk)
            if size > MAX_BYTES or time.time() - t0 > 120:
                return {'ok': False, 'reason': 'too large or too slow'}
            f.write(chunk)
    data = raw.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
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
            why = getattr(tab, ext)(src, dst, kind)
        except Exception as err:  # noqa: BLE001
            why = f'unreadable ({type(err).__name__})'
        if why:
            return {'ok': False, 'reason': why, 'raw': digest}
        return {'ok': True, 'path': str(dst), 'ext': ext, 'label': K.LABEL[kind], 'raw': digest}

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
    if ext in ('htm', 'html', 'txt'):
        src = work / 'doc.html'
        src.write_text(html_clean(data), encoding='utf-8')
        pdf = convert(src, work, 'pdf')
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
    if why:
        return {'ok': False, 'reason': why, 'raw': digest}
    return {'ok': True, 'path': str(dst), 'ext': ext, 'label': label, 'raw': digest}


def _process_one(args):
    cand, kind, work = args
    try:
        return process(cand, kind, work)
    except requests.RequestException as err:
        return {'ok': False, 'reason': f'download failed ({type(err).__name__})'}
    except Exception as err:  # noqa: BLE001
        traceback.print_exc(limit=3)
        return {'ok': False, 'reason': f'error {type(err).__name__}: {str(err)[:80]}'}


class Worker:
    """Runs process() in a child process so a pathological file can be killed."""

    def __init__(self):
        self.pool = multiprocessing.get_context('fork').Pool(1)

    def run(self, args):
        try:
            return self.pool.apply_async(_process_one, (args,)).get(timeout=FILE_SECONDS)
        except multiprocessing.TimeoutError:
            self.pool.terminate()
            os.system('pkill -9 -f soffice >/dev/null 2>&1')
            self.pool = multiprocessing.get_context('fork').Pool(1)
            return {'ok': False, 'reason': f'processing took longer than {FILE_SECONDS}s'}

    def close(self):
        self.pool.terminate()


class Run:
    def __init__(self):
        self.store = None if DRY and not os.environ.get('GOOGLE_REFRESH_TOKEN') else Store(dry_run=DRY)
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
        digest = hashlib.sha256(Path(res['path']).read_bytes()).hexdigest()
        if digest in self.state['hashes']:
            self.state['seen'][cand['key']] = 'rej:duplicate'
            return
        n = self.state['next'].get(kind, 1)
        name = (self.store.upload_doc(res['path'], kind, n, res['label'], res['ext'], cand['key']) if self.store
                else f'{n} - {res["label"]}.{res["ext"]}')
        self.state['next'][kind] = n + 1
        self.state['hashes'][digest] = f'{kind}:{n}'
        self.state['seen'][cand['key']] = f'ok:{kind}:{n}'
        c = self.state['counts']
        c[kind] = c.get(kind, 0) + 1
        c[f'source:{cand["source"]}'] = c.get(f'source:{cand["source"]}', 0) + 1
        self.made[kind] = self.made.get(kind, 0) + 1
        log(f'  {K.KINDS[kind]["folder"]}: #{n} {name}')
        self.save()

    def discover(self, kind, s, until):
        q = self.state['queue'].setdefault(kind, [])
        for fn in sources.DISCOVER[kind]:
            if len(q) >= 60 or time.time() > until:
                break
            try:
                n = fn(self.state, kind, s, log)
                if n:
                    log(f'  {kind}: +{n} candidates from {fn.__name__}')
            except Exception as err:  # noqa: BLE001
                log(f'  {kind}: {fn.__name__} failed ({type(err).__name__}: {err})')

    def work(self, kind, until, worker):
        q = self.state['queue'].setdefault(kind, [])
        done = 0
        while q and time.time() < until:
            cand = q.pop(0)
            self.state['queued'].pop(cand['key'], None)
            if cand['key'] in self.state['seen']:
                continue
            work = self.tmp / f'{kind}{done}'
            work.mkdir()
            try:
                res = worker.run((cand, kind, str(work)))
                if res.get('raw'):
                    if f'raw:{res["raw"]}' in self.state['seen']:
                        self.state['seen'][cand['key']] = 'rej:duplicate download'
                        continue
                    self.state['seen'][f'raw:{res["raw"]}'] = 1
                if not res.get('ok'):
                    self.state['seen'][cand['key']] = f'rej:{res.get("reason")}'[:120]
                    continue
                self.publish(kind, res, cand)
            finally:
                shutil.rmtree(work, ignore_errors=True)
                done += 1
        return done

    def go(self):
        nexts = {k: self.state['next'].get(k, 1) for k in K.KINDS}
        log(f'start: next numbers {nexts}')
        if self.store:
            used, limit = self.store.quota()
            log(f'Drive: {used / 2**30:.1f} GB used of {limit / 2**30:.1f} GB')
            if limit and limit - used < 2 * 2**30:
                log('Drive has less than 2 GB free; stopping')
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

        order = [k for k in K.KINDS if not ONLY or k in ONLY]
        worker = Worker()
        rounds = 0
        while left() > 90:
            rounds += 1
            slice_s = max(60, (left() - 60) / len(order))
            for kind in order:
                if left() < 90:
                    break
                until = time.time() + slice_s
                self.discover(kind, s, time.time() + min(120, slice_s / 3))
                n = self.work(kind, until, worker)
                log(f'{kind}: processed {n}, {len(self.state["queue"].get(kind, []))} queued, '
                    f'{self.made.get(kind, 0)} made this run')
                self.save(force=True)
            if all(not self.state['queue'].get(k) for k in order) and rounds > 1:
                break
        worker.close()
        self.save(force=True)
        c = self.state['counts']
        log(f'done: {sum(self.made.values())} documents this run {json.dumps(self.made)}; totals {json.dumps(c, sort_keys=True)}')
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a', encoding='utf-8') as f:
                f.write(f'## Financial documents\n\n{sum(self.made.values())} documents this run.\n\n| Type | This run | Total |\n|---|---|---|\n')
                for k in K.KINDS:
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
