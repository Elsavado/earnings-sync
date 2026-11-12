"""Google copies of existing Office files (user, 2026-11-12: "convert existing docs in hassan and shintiru and
financelitics into google docs"; originals kept, each file to the Google type of its original form).

  Word (.docx .doc .odt .rtf)          -> Google Docs
  Excel (.xlsx .xlsm .xls .ods .csv)   -> Google Sheets
  PowerPoint (.pptx .ppt .odp)         -> Google Slides

TARGET=shintiru      shintiru's My Drive: a converted copy beside each original (Drive converts it server side).
TARGET=financelitics Workspace shared drive "Research Collections", folder "Financelitics" and below: the same.
TARGET=salvador      salvadorsekwa's My Drive (asset library): a converted copy beside each original.
TARGET=hassan        hassan's drive is full (no new files can be made there), so its files are downloaded and the
                     Google copies go to shintiru's drive under "Hassan - Construction Operations Research/<same path>"
                     (user: "send them to shintiru too but assume it is hassan").

Each copy carries appProperties gcFrom=<original id>, so a file is converted once and runs can resume anywhere.
A file Drive cannot convert (too large, damaged) is recorded in the state file and skipped.
Environment: TARGET, RUN_MINUTES, DRY_RUN; credentials via RCLONE_REMOTE (shintiru / hassan) and the WS_GOOGLE_*
refresh token for the Workspace.
"""
import io
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from models.store import RcloneCredentials

G = 'application/vnd.google-apps.'
GOOGLE = {
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'document',
    'application/msword': 'document',
    'application/vnd.oasis.opendocument.text': 'document',
    'application/rtf': 'document', 'text/rtf': 'document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'spreadsheet',
    'application/vnd.ms-excel.sheet.macroEnabled.12': 'spreadsheet',
    'application/vnd.ms-excel': 'spreadsheet',
    'application/vnd.oasis.opendocument.spreadsheet': 'spreadsheet',
    'text/csv': 'spreadsheet',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'presentation',
    'application/vnd.ms-powerpoint': 'presentation',
    'application/vnd.oasis.opendocument.presentation': 'presentation',
}
GOOGLE.update({k.lower(): v for k, v in list(GOOGLE.items())})  # Drive also reports lower-case variants
# Drive's conversion limits (larger files fail anyway): documents 50 MB, sheets 100 MB, slides 100 MB.
MAX = {'document': 50 * 2**20, 'spreadsheet': 100 * 2**20, 'presentation': 100 * 2**20}
FOLDER = 'application/vnd.google-apps.folder'
TARGET = os.environ['TARGET']
DRY = os.environ.get('DRY_RUN', '').lower() == 'true'
END = time.time() + float(os.environ.get('RUN_MINUTES', '320')) * 60
STATE = f'gconvert-{TARGET}.json'
HASSAN_ROOT = 'Hassan - Construction Operations Research'
FIN_COPY = 'Financelitics (Google)'


def ws_copy_drive(drive):
    """The shared drive for the Financelitics copies (made once, same organiser as Research Collections)."""
    token = None
    while True:
        res = retry(lambda: drive.drives().list(pageSize=100, pageToken=token, fields='nextPageToken, drives(id,name)').execute())
        for d in res.get('drives', []):
            if d['name'] == FIN_COPY:
                return d['id']
        token = res.get('nextPageToken')
        if not token:
            break
    if DRY:
        return None
    return retry(lambda: drive.drives().create(requestId='financelitics-google-copies-1', body={'name': FIN_COPY},
                                               fields='id').execute())['id']
RC = 'Research Collections'
WS_DRIVE = '0ACsHljU9Hj2_Uk9PVA'


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


def service(kind):
    if kind == 'ws':
        from google.oauth2.credentials import Credentials
        cred = Credentials(None, refresh_token=os.environ['WS_REFRESH_TOKEN'], client_id=os.environ['WS_CLIENT_ID'],
                           client_secret=os.environ['WS_CLIENT_SECRET'], token_uri='https://oauth2.googleapis.com/token')
    else:
        cred = RcloneCredentials(kind)
    return build('drive', 'v3', credentials=cred, cache_discovery=False)


_local = threading.local()


def svc(kind):
    """One Drive client per thread (the HTTP client is not thread-safe)."""
    d = getattr(_local, 'svcs', None)
    if d is None:
        d = _local.svcs = {}
    if kind not in d:
        d[kind] = service(kind)
    return d[kind]


def list_all(drive, q, fields, shared=None):
    out, token = [], None
    kw = {'corpora': 'drive', 'driveId': shared, 'includeItemsFromAllDrives': True, 'supportsAllDrives': True} \
        if shared else {}
    while True:
        res = retry(lambda: drive.files().list(q=q, fields=f'nextPageToken, files({fields})', pageSize=1000,
                                               pageToken=token, **kw).execute())
        out += res.get('files', [])
        token = res.get('nextPageToken')
        if not token:
            return out


def mime_q():
    return '(' + ' or '.join(f"mimeType = '{m}'" for m in GOOGLE) + ') and trashed = false'


def load_state(drive, shared=None):
    q = f"name = '{STATE}' and trashed = false and 'root' in parents" if not shared else \
        f"name = '{STATE}' and trashed = false"
    found = list_all(drive, q, 'id', shared)
    if not found:
        return None, {'failed': {}}
    data = retry(lambda: drive.files().get_media(fileId=found[0]['id'], supportsAllDrives=True).execute())
    return found[0]['id'], json.loads(data)


def save_state(drive, sid, state, parent):
    if DRY:
        return sid
    media = MediaIoBaseUpload(io.BytesIO(json.dumps(state).encode()), mimetype='application/json')
    if sid:
        retry(lambda: drive.files().update(fileId=sid, media_body=media, supportsAllDrives=True).execute())
        return sid
    return retry(lambda: drive.files().create(body={'name': STATE, 'parents': [parent]}, media_body=media,
                                              fields='id', supportsAllDrives=True).execute())['id']


def main():
    src_kind = {'shintiru': 'shintiru', 'hassan': 'hassan', 'financelitics': 'ws', 'salvador': 'salvador'}[TARGET]
    dst_kind = {'shintiru': 'shintiru', 'hassan': 'shintiru', 'financelitics': 'ws', 'salvador': 'salvador'}[TARGET]
    src, dst = service(src_kind), service(dst_kind)
    shared = WS_DRIVE if TARGET == 'financelitics' else None

    t0 = time.time()
    folders = list_all(src, f"mimeType = '{FOLDER}' and trashed = false", 'id, name, parents', shared)
    parent_of = {f['id']: (f.get('parents') or [None])[0] for f in folders}
    name_of = {f['id']: f['name'] for f in folders}
    mine = '' if shared else " and 'me' in owners"  # My Drive: own files, not those shared with the account
    files = list_all(src, mime_q() + mine, 'id, name, mimeType, size, parents', shared)
    log(f'{TARGET}: {len(folders)} folders, {len(files)} Office files listed ({time.time() - t0:.0f}s)')

    if TARGET == 'financelitics':
        top = [f['id'] for f in folders if f['name'] == 'Financelitics' and parent_of.get(f['id']) == WS_DRIVE]
        if not top:
            sys.exit('folder Financelitics not found at the top of Research Collections')

        def inside(fid, seen=0):
            while fid and seen < 60:
                if fid == top[0]:
                    return True
                fid, seen = parent_of.get(fid), seen + 1
            return False
        files = [f for f in files if inside((f.get('parents') or [None])[0])]
        log(f'  {len(files)} of them inside Financelitics')

    # Copies already made (any run): their originals are done.
    # Financelitics: the copies go to their own shared drive (Research Collections is near the item limit).
    dshared = ws_copy_drive(dst) if TARGET == 'financelitics' else None
    if dshared:
        log(f'  copies go to shared drive "{FIN_COPY}"')
    gq = ' or '.join(f"mimeType = '{G}{t}'" for t in ('document', 'spreadsheet', 'presentation'))
    done = {f['appProperties']['gcFrom'] for f in list_all(dst, f'trashed = false and ({gq})', 'appProperties', dshared)
            if (f.get('appProperties') or {}).get('gcFrom')}
    state_parent = dshared or 'root'
    sid, state = load_state(dst, dshared)
    failed = state.setdefault('failed', {})
    todo = [f for f in files if f['id'] not in done and f['id'] not in failed]
    by = {}
    for f in files:
        by[GOOGLE[f['mimeType']]] = by.get(GOOGLE[f['mimeType']], 0) + 1
    log(f'  by type {by}; already converted {len(done)}, failed before {len(failed)}, to do {len(todo)}')
    if DRY:
        return

    # hassan: the same folder path on shintiru's drive, made as needed.
    made_dirs, lock = {}, threading.Lock()

    def path_parts(fid):
        parts, n = [], 0
        while fid and fid in name_of and n < 60:
            parts.append(name_of[fid])
            fid, n = parent_of.get(fid), n + 1
        return list(reversed(parts))

    def dest_folder(parent):
        with lock:
            if parent in made_dirs:
                return made_dirs[parent]
            cur = dshared or 'root'
            for part in ([] if dshared else [HASSAN_ROOT]) + path_parts(parent):
                key = (cur, part)
                if key not in made_dirs:
                    esc = part.replace('\\', '\\\\').replace("'", "\\'")
                    got = list_all(dst, f"'{cur}' in parents and name = '{esc}' and mimeType = '{FOLDER}' "
                                        f"and trashed = false", 'id', dshared)
                    made_dirs[key] = got[0]['id'] if got else retry(lambda: dst.files().create(
                        body={'name': part, 'mimeType': FOLDER, 'parents': [cur]}, fields='id',
                        supportsAllDrives=True).execute())['id']
                cur = made_dirs[key]
            made_dirs[parent] = cur
            return cur

    stats = {'ok': 0, 'fail': 0}

    def one(f):
        if time.time() > END:
            return
        gtype = GOOGLE[f['mimeType']]
        stem = f['name'].rsplit('.', 1)[0] if '.' in f['name'] else f['name']
        parent = (f.get('parents') or [None])[0]
        body = {'name': stem, 'mimeType': G + gtype, 'appProperties': {'gcFrom': f['id']}}
        try:
            if int(f.get('size') or 0) > MAX[gtype]:
                raise ValueError('too large to convert')
            if TARGET == 'hassan':
                body['parents'] = [dest_folder(parent)]
                buf = io.BytesIO()
                req = svc('hassan').files().get_media(fileId=f['id'])
                dl = MediaIoBaseDownload(buf, req, chunksize=32 * 2**20)
                fin = False
                while not fin:
                    _, fin = dl.next_chunk(num_retries=5)
                buf.seek(0)
                media = MediaIoBaseUpload(buf, mimetype=f['mimeType'], resumable=True, chunksize=32 * 2**20)
                retry(lambda: svc('shintiru').files().create(body=body, media_body=media, fields='id').execute())
            else:
                if dshared:
                    body['parents'] = [dest_folder(parent)]
                elif parent:
                    body['parents'] = [parent]
                retry(lambda: svc(src_kind).files().copy(fileId=f['id'], body=body, fields='id',
                                                          supportsAllDrives=True).execute())
            with lock:
                stats['ok'] += 1
        except (HttpError, ValueError, OSError) as err:
            reason = (f'http {err.resp.status}' if isinstance(err, HttpError) else str(err))[:80]
            with lock:
                stats['fail'] += 1
                failed[f['id']] = reason

    t1, last = time.time(), time.time()
    with ThreadPoolExecutor(int(os.environ.get('THREADS', '4'))) as ex:
        for i, _ in enumerate(ex.map(one, todo), 1):
            if time.time() - last > 300:
                last = time.time()
                sid = save_state(dst, sid, state, state_parent)
                log(f'  {i}/{len(todo)}: {stats["ok"]} converted, {stats["fail"]} failed '
                    f'({stats["ok"] / max(1, time.time() - t1) * 3600:.0f}/h)')
            if time.time() > END:
                break
    sid = save_state(dst, sid, state, state_parent)
    left = len(todo) - stats['ok'] - stats['fail']
    log(f'done: {stats["ok"]} converted, {stats["fail"]} failed this run; {max(0, left)} left')
    with open(os.environ.get('GITHUB_OUTPUT', os.devnull), 'a') as fh:
        fh.write(f'left={max(0, left)}\n')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as fh:
            fh.write(f'## Google copies: {TARGET}\n\nOffice files {len(files)} {by}; converted this run '
                     f'{stats["ok"]}, failed {stats["fail"]}, left {max(0, left)}.\n')


if __name__ == '__main__':
    main()
