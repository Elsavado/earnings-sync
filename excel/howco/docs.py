"""Public record collections of documents (shared by the FCIC, examiner-report, Senate and antitrust sources).

discover(ctx) yields candidates {'url', 'group', 'title'}; each is downloaded once (by address and content), legacy
DOC/XLS/PPT/HTML are converted, scanned pages get text recognition (OCR; still skipped when it finds no text), people and
companies get the shared made-up names, and the file goes to <folder>/<group>/Folder K (Documents a-b)/<n> - <title>.
"""
import hashlib
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

from .anon import LEGACY, OOXML, convert_legacy

UA = 'HowCompaniesWork research collector (education; contact via github.com/Elsavado)'
EXT = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv', 'rtf', 'htm', 'html'}
PER_FOLDER = 50
BUSINESS = re.compile(r'\b(?:revenue|margin|budget|forecast|pricing|price|profit|financial|cost|sales|growth|market '
                      r'share|return on|investment|earnings|cash|capital|valuation|acquisition|merger|deal|contract|'
                      r'payment|fee|share|EBITDA|ROI|P&L|quarter|fiscal)\b', re.I)


def session():
    s = requests.Session()
    s.headers['User-Agent'] = UA
    return s


def links(s, url, timeout=60):
    """(absolute link, link text) of a page; [] when it cannot be read."""
    try:
        r = s.get(url, timeout=timeout)
    except requests.RequestException:
        return []
    if not r.ok or 'html' not in r.headers.get('content-type', 'html'):
        return []
    out = []
    for m in re.finditer(r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', r.text, re.I | re.S):
        text = re.sub(r'<[^>]+>|\s+', ' ', m.group(2)).strip()
        out.append((urljoin(r.url, m.group(1).replace('&amp;', '&')), text))
    return out


def crawl(s, seeds, allow, max_pages=3000, page_ok=None, log=print):
    """Breadth-first walk of index pages (allow: regex a page address must match). Yields (document url, text,
    page url) for links with a document extension."""
    todo, seen, n = list(seeds), set(), 0
    while todo and n < max_pages:
        u = todo.pop(0)
        if u in seen:
            continue
        seen.add(u)
        n += 1
        for v, text in links(s, u):
            v = v.split('#')[0]
            ext = urlparse(v).path.rsplit('.', 1)[-1].lower() if '.' in urlparse(v).path.rsplit('/', 1)[-1] else ''
            if ext in EXT:
                yield v, text, u
            elif re.search(allow, v) and v not in seen and '?C=' not in v and (not page_ok or page_ok(v)):
                todo.append(v)
        time.sleep(0.3)


def title_of(url, text=''):
    name = unquote(urlparse(url).path.rsplit('/', 1)[-1])
    stem = name.rsplit('.', 1)[0]
    t = text if text and len(text) > len(stem) and len(text) < 160 and not text.lower().endswith(('.pdf', 'download')) else stem
    return re.sub(r'[_\s]+', ' ', t).strip()


def ocr(src, work):
    """Searchable copy of a scanned PDF (ocrmypdf + Tesseract), or None when OCR is unavailable or fails."""
    if not shutil.which('ocrmypdf'):
        return None
    out = str(work / 'ocr.pdf')
    try:
        r = subprocess.run(['ocrmypdf', '--skip-text', '-l', 'eng', '--jobs', '2', '--optimize', '0', '--output-type',
                            'pdf', '--tesseract-timeout', '180', '-q', src, out], capture_output=True, timeout=3600)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return out if r.returncode == 0 and Path(out).exists() else None


def html_to_docx(src, work):
    """Word copy of an HTML filing (LibreOffice), or None."""
    outdir = work / 'html'
    outdir.mkdir(exist_ok=True)
    try:
        subprocess.run(['soffice', '--headless', '--convert-to', 'docx:MS Word 2007 XML', '--outdir', str(outdir), src],
                       capture_output=True, timeout=600)
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = outdir / (Path(src).stem + '.docx')
    return str(out) if out.exists() else None


def run(ctx, log, discover, business_only=False, min_text_per_page=200):
    import pymupdf
    st = ctx.state
    st.setdefault('seen', [])
    st.setdefault('hashes', [])
    st.setdefault('n', {})
    st.setdefault('skipped', {})
    if st.get('ocr_pass') != 1:
        # once: walk every list again so documents skipped as scans before get OCR; anything already on the drive is
        # recognised by its content key and skipped without processing
        st['seen'], st['ocr_pass'] = [], 1
    seen, hashes = set(st['seen']), set(st['hashes'])
    on_drive = set(ctx.drive.uploaded()) if not ctx.dry else set()
    A = ctx.make_anon()
    s = session()
    kept = 0
    seen_now = set()

    def skip(why):
        st['skipped'][why] = st['skipped'].get(why, 0) + 1

    finished = True
    for cand in discover(ctx, s, log):
        if ctx.left() < 600 or (ctx.dry and kept >= 8):
            finished = False
            break
        url = cand['url']
        k = hashlib.sha1(url.encode()).hexdigest()[:16]
        if k in seen:
            continue
        seen.add(k)
        ext = urlparse(url).path.rsplit('.', 1)[-1].lower()
        ext = cand.get('ext') or ext
        try:
            r = s.get(url, timeout=300, stream=True)
            path = ctx.work / f'in.{ext}'
            size = 0
            with open(path, 'wb') as f:
                for chunk in r.iter_content(1 << 20):
                    size += len(chunk)
                    if size > 1500 * 2**20:
                        break
                    f.write(chunk)
        except requests.RequestException:
            skip('download failed')
            continue
        if not r.ok or size > 1500 * 2**20:
            skip('download failed' if not r.ok else 'too large')
            continue
        h = hashlib.sha1(path.read_bytes()).hexdigest()
        if h in hashes and (f'doc:{h[:24]}' in on_drive or h in seen_now):
            skip('duplicate')
            continue
        hashes.add(h)
        seen_now.add(h)
        src, e = str(path), ext
        if ext in ('htm', 'html'):
            src = html_to_docx(src, ctx.work)
            if not src:
                skip('not converted')
                continue
            e = 'docx'
        elif ext in LEGACY:
            try:
                conv = convert_legacy([str(path)], ctx.work / 'conv').get(str(path))
            except (RuntimeError, OSError):
                conv = None
            if not conv:
                skip('not converted')
                continue
            src, e = conv, LEGACY[ext]
        if e == 'pdf':
            try:
                with pymupdf.open(src) as d:
                    pages = d.page_count
                    text = ''.join(p.get_text() for p in d)
            except Exception:  # noqa: BLE001
                skip('unreadable')
                continue
            if pages and len(text) / pages < min_text_per_page:
                done = ocr(src, ctx.work)
                if done:
                    try:
                        with pymupdf.open(done) as d:
                            text = ''.join(p.get_text() for p in d)
                    except Exception:  # noqa: BLE001
                        text = ''
                    if len(text) / pages >= min_text_per_page / 4:
                        src = done
                        st['ocr_done'] = st.get('ocr_done', 0) + 1
            if not pages or len(text) / pages < min_text_per_page / 4:
                skip('scanned pages without text')
                continue
        if business_only and e == 'pdf' and len(BUSINESS.findall(text[:200000])) < 5:
            skip('not about business or finance')
            continue
        A.start()
        dst = ctx.work / f'out.{e}'
        try:
            ok, out_text = A.file(src, str(dst), e)
        except Exception as ex:  # noqa: BLE001
            ok, out_text = False, ''
            log(f'  could not process a file: {type(ex).__name__}')
        if not ok:
            skip('could not process')
            continue
        leaks = A.leaks(out_text)
        group = cand.get('group') or ''
        st['n'][group] = st['n'].get(group, 0) + 1
        n = st['n'][group]
        kf = (n - 1) // PER_FOLDER + 1
        rel = '/'.join(x for x in (ctx.folder, A.text(group, learn=False) if cand.get('anon_group') else group,
                                   f'Folder {kf} (Documents {PER_FOLDER * (kf - 1) + 1}-{PER_FOLDER * kf})') if x)
        title = A.text(cand.get('title') or title_of(url))[:120]
        name = re.sub(r'[\\/:*?"<>|]+', ' ', f'{n} - {title}.{e}')
        ctx.drive.upload(str(dst), rel, name, f'doc:{h[:24]}')
        kept += 1
        ctx.sample(dst, name, leaks)
        if kept % 20 == 0:
            st['seen'], st['hashes'] = sorted(seen), sorted(hashes)
            ctx.save()
            log(f'{kept} documents kept this run; skipped so far {st["skipped"]}')
    st['seen'], st['hashes'] = sorted(seen), sorted(hashes)
    if finished and not ctx.dry:
        st['finished'] = time.strftime('%Y-%m-%d')
    log(f'this run: {kept} documents kept; skipped so far {st["skipped"]}')
    return kept
