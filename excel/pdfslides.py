"""Google Slides copies of PDF presentations (user, 2026-11-12, irtranscripts account).

Drive cannot turn a PDF into Slides itself, so each PDF is rebuilt as a deck first: every page becomes one slide
holding an image of that page (it looks exactly like the original) and the page's text goes into the speaker notes
(searchable, copyable). The deck is uploaded as Google Slides beside its PDF; the PDF is kept.

Each copy carries appProperties gcFrom=<PDF id>, so a PDF is converted once and runs resume anywhere. A PDF that
fails (damaged, image-only pages too large) is recorded in the state file on the account's My Drive and skipped.
Environment: PDF_FOLDER (top folder id, from a repository variable, never in this repository), RUN_MINUTES, DRY_RUN,
THREADS, WS_* refresh token for joseph@irtranscripts.com.
"""
import io
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pymupdf as fitz
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
from pptx import Presentation
from pptx.util import Emu

FOLDER = 'application/vnd.google-apps.folder'
SLIDES = 'application/vnd.google-apps.presentation'
PPTX = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
ROOT = os.environ['PDF_FOLDER'].strip()
DRY = os.environ.get('DRY_RUN', '').lower() == 'true'
END = time.time() + float(os.environ.get('RUN_MINUTES', '320')) * 60
STATE = 'pdfslides-state.json'
MAX_PDF = 150 * 2**20
MAX_PAGES = 300
DECK_LIMIT = 90 * 2**20  # Drive's Slides import stops at 100 MB
WIDTH_PX = 1600  # rendered page width: sharp on a laptop screen, small enough for long decks
NOTES_MAX = 4000


def log(msg):
    print(time.strftime('[%H:%M:%S] ') + msg, flush=True)


def retry(fn, tries=6):
    for i in range(tries):
        try:
            return fn()
        except HttpError as err:
            code = err.resp.status
            if code in (403, 429, 500, 502, 503, 504) and i < tries - 1 and (
                    code != 403 or b'rateLimit' in err.content or b'userRateLimit' in err.content):
                time.sleep(min(60, 2 ** i * 3))
                continue
            raise
        except (OSError, TimeoutError):
            if i == tries - 1:
                raise
            time.sleep(min(60, 2 ** i * 3))


def service():
    cred = Credentials(None, refresh_token=os.environ['WS_REFRESH_TOKEN'], client_id=os.environ['WS_CLIENT_ID'],
                       client_secret=os.environ['WS_CLIENT_SECRET'], token_uri='https://oauth2.googleapis.com/token')
    return build('drive', 'v3', credentials=cred, cache_discovery=False)


_local = threading.local()


def svc():
    if not hasattr(_local, 's'):
        _local.s = service()
    return _local.s


ALL = {'supportsAllDrives': True, 'includeItemsFromAllDrives': True}


def children(drive, fid, fields):
    out, token = [], None
    while True:
        res = retry(lambda: drive.files().list(q=f"'{fid}' in parents and trashed = false", pageSize=1000,
                                               pageToken=token, fields=f'nextPageToken, files({fields})',
                                               **ALL).execute())
        out += res.get('files', [])
        token = res.get('nextPageToken')
        if not token:
            return out


def walk(drive):
    """Every PDF under ROOT, and the PDF ids that already have a Slides copy."""
    pdfs, done, queue, nfold = [], set(), [ROOT], 0
    while queue:
        fid = queue.pop()
        nfold += 1
        for f in children(drive, fid, 'id, name, mimeType, size, appProperties'):
            if f['mimeType'] == FOLDER:
                queue.append(f['id'])
            elif f['mimeType'] == 'application/pdf':
                f['parent'] = fid
                pdfs.append(f)
            elif f['mimeType'] == SLIDES and (f.get('appProperties') or {}).get('gcFrom'):
                done.add(f['appProperties']['gcFrom'])
    return nfold, pdfs, done


def build_deck(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    if doc.page_count == 0:
        raise ValueError('no pages')
    if doc.page_count > MAX_PAGES:
        raise ValueError('too many pages')
    first = doc[0].rect
    prs = Presentation()
    prs.slide_width = Emu(12192000)  # 13.333 in, the usual widescreen width
    prs.slide_height = Emu(int(12192000 * first.height / first.width))
    blank = prs.slide_layouts[6]
    sw, sh = prs.slide_width, prs.slide_height
    for page in doc:
        r = page.rect
        zoom = WIDTH_PX / max(1.0, r.width)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = io.BytesIO(pix.tobytes('jpg', jpg_quality=82))
        slide = prs.slides.add_slide(blank)
        # fit the page inside the slide, centred (pages of another shape keep their proportions)
        scale = min(sw / r.width, sh / r.height)
        w, h = int(r.width * scale), int(r.height * scale)
        slide.shapes.add_picture(img, (sw - w) // 2, (sh - h) // 2, w, h)
        text = ' '.join(page.get_text().split())
        if text:
            slide.notes_slide.notes_text_frame.text = text[:NOTES_MAX]
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue(), doc.page_count


def main():
    drive = service()
    top = retry(lambda: drive.files().get(fileId=ROOT, fields='name, driveId, capabilities(canAddChildren)',
                                          supportsAllDrives=True).execute())
    if not top.get('capabilities', {}).get('canAddChildren'):
        raise SystemExit('the account cannot add files to this folder (view-only access)')
    t0 = time.time()
    nfold, pdfs, done = walk(drive)
    found = retry(lambda: drive.files().list(q=f"name = '{STATE}' and 'root' in parents and trashed = false",
                                             fields='files(id)').execute()).get('files', [])
    sid = found[0]['id'] if found else None
    state = json.loads(retry(lambda: drive.files().get_media(fileId=sid).execute())) if sid else {'failed': {}}
    failed = state.setdefault('failed', {})
    todo = [p for p in pdfs if p['id'] not in done and p['id'] not in failed]
    log(f'{nfold} folders, {len(pdfs)} PDFs; already converted {len(done)}, failed before {len(failed)}, '
        f'to do {len(todo)} ({time.time() - t0:.0f}s)')
    if DRY:
        return

    lock, stats = threading.Lock(), {'ok': 0, 'fail': 0, 'slides': 0}

    def save():
        media = MediaIoBaseUpload(io.BytesIO(json.dumps(state).encode()), mimetype='application/json')
        nonlocal sid
        if sid:
            retry(lambda: drive.files().update(fileId=sid, media_body=media).execute())
        else:
            sid = retry(lambda: drive.files().create(body={'name': STATE, 'parents': ['root']}, media_body=media,
                                                     fields='id').execute())['id']

    def one(p):
        if time.time() > END:
            return
        try:
            if int(p.get('size') or 0) > MAX_PDF:
                raise ValueError('pdf too large')
            data = retry(lambda: svc().files().get_media(fileId=p['id'], supportsAllDrives=True).execute())
            deck, pages = build_deck(data)
            if len(deck) > DECK_LIMIT:
                raise ValueError('deck too large for Slides')
            stem = p['name'][:-4] if p['name'].lower().endswith('.pdf') else p['name']
            body = {'name': stem, 'mimeType': SLIDES, 'parents': [p['parent']], 'appProperties': {'gcFrom': p['id']}}
            media = MediaIoBaseUpload(io.BytesIO(deck), mimetype=PPTX, resumable=True, chunksize=16 * 2**20)
            retry(lambda: svc().files().create(body=body, media_body=media, fields='id',
                                               supportsAllDrives=True).execute())
            with lock:
                stats['ok'] += 1
                stats['slides'] += pages
        except Exception as err:  # noqa: BLE001  (a bad PDF must not stop the run)
            reason = (f'http {err.resp.status}' if isinstance(err, HttpError) else
                      f'{type(err).__name__}: {err}')[:80]
            with lock:
                stats['fail'] += 1
                failed[p['id']] = reason

    t1 = last = time.time()
    with ThreadPoolExecutor(int(os.environ.get('THREADS', '4'))) as ex:
        for i, _ in enumerate(ex.map(one, todo), 1):
            if time.time() - last > 300:
                last = time.time()
                with lock:
                    save()
                log(f'  {i}/{len(todo)}: {stats["ok"]} decks ({stats["slides"]} slides), {stats["fail"]} failed '
                    f'({stats["ok"] / max(1, time.time() - t1) * 3600:.0f}/h)')
    save()
    left = max(0, len(todo) - stats['ok'] - stats['fail'])
    reasons = {}
    for r in failed.values():
        k = r.split(':')[0]
        reasons[k] = reasons.get(k, 0) + 1
    log(f'done: {stats["ok"]} decks ({stats["slides"]} slides), {stats["fail"]} failed this run; {left} left; '
        f'all failures by reason {reasons}')
    with open(os.environ.get('GITHUB_OUTPUT', os.devnull), 'a') as fh:
        fh.write(f'left={left}\n')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as fh:
            fh.write(f'## PDF presentations -> Google Slides\n\nPDFs {len(pdfs)}; converted this run {stats["ok"]} '
                     f'({stats["slides"]} slides), failed {stats["fail"]}, left {left}; earlier copies {len(done)}.\n')


if __name__ == '__main__':
    main()
