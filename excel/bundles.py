"""Zip bundles of a Shared Drive's files, grouped by file type, 400-500 MB each.

Layout:  Bundles by File Type/PDF/1 500 MB.zip, 2 500 MB.zip, ... 37 212 MB.zip (the last one of a type is smaller)
         Bundles by File Type - private/plan.json.gz   (which file goes in which bundle)
The originals are never moved or changed. Inside a zip, files keep their folder path from the drive.
A file over the bundle size gets a bundle of its own. Files are stored (not recompressed), so a bundle's
size is the size of its files.

  python -m bundles plan                 list the drive and assign new files to bundles (earlier bundles stay as they are)
  python -m bundles build SHARD OF       make and upload the missing bundles of this shard (bundle index % OF == SHARD)
Environment: SHARED_DRIVE_ID, GOOGLE_* sign-in (see models/store.py), RUN_MINUTES, DRY_RUN.
"""
import gzip
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from models.store import FOLDER, Store, _retry, credentials

ROOT = 'Bundles by File Type'
PRIVATE = 'Bundles by File Type - private'
APP = 'irt-bundles'
MAX = 495_000_000   # bytes of files per bundle (the zip's own headers stay well under the 500 MB mark)
MIN = 400_000_000
PIECE = 480_000_000  # a file over MAX is split into parts of at most this size
LINES = {'CSV', 'TSV', 'TXT', 'JSONL', 'NDJSON', 'LOG', 'DAT', 'PSV'}  # split at line ends (a CSV part repeats the header)
URL = 'https://www.googleapis.com/drive/v3/files/'
GOOGLE = 'application/vnd.google-apps.'
KNOWN_NOEXT = {'application/pdf': 'PDF', 'text/plain': 'TXT', 'text/html': 'HTML', 'application/json': 'JSON',
               'application/zip': 'ZIP', 'text/csv': 'CSV'}


def log(*a):
    print(time.strftime('[%H:%M:%S]'), *a, flush=True)


def file_type(name, mime):
    stem, dot, ext = name.rpartition('.')
    ext = ext.strip().upper()
    if dot and stem and 1 <= len(ext) <= 6 and ext.isalnum():
        return ext
    return KNOWN_NOEXT.get(mime, 'Other')


def pieces(f):
    """A file over MAX becomes parts: 'data.part01-of07.csv' (whole lines) or 'video.webm.001' (bytes; 7-Zip joins them)."""
    if f['size'] <= MAX:
        return [f]
    n = -(-f['size'] // PIECE)
    chunk = -(-f['size'] // n)
    lines = f['type'] in LINES
    stem, dot, ext = f['path'].rpartition('.')
    out = []
    for k in range(n):
        start, end = k * chunk, min(f['size'], (k + 1) * chunk)
        path = f'{stem}.part{k + 1:02d}-of{n:02d}.{ext}' if lines and dot else f'{f["path"]}.{k + 1:03d}'
        out.append({'id': f'{f["id"]}#{k + 1}', 'src': f['id'], 'path': path, 'size': end - start, 'md5': None,
                    'start': start, 'end': end, 'total': f['size'], 'split': 'lines' if lines else 'bytes', 'type': f['type']})
    return out


def label(size):
    if MIN <= size <= MAX:
        return '500 MB'
    if size >= 1_000_000_000:
        return f'{size / 1e9:.1f} GB'
    return f'{max(1, round(size / 1e6))} MB'


class Bundler:
    def __init__(self, dry_run=False):
        self.store = Store(root_name=ROOT, private_name=PRIVATE, dry_run=dry_run, app=APP, state_name='plan.json.gz')
        self.files = self.store.drive.files()
        self.dry_run = dry_run

    # ---------- listing ----------
    def list_drive(self):
        skip = {self.store.root, self.store.private}
        items, token = [], None
        while True:
            r = _retry(lambda: self.files.list(
                q='trashed = false', pageSize=1000, pageToken=token,
                fields='nextPageToken, files(id, name, mimeType, size, parents, md5Checksum)').execute())
            items += r['files']
            token = r.get('nextPageToken')
            if len(items) % 20000 < 1000:
                log(f'  listed {len(items)}')
            if not token:
                break
        folders = {f['id']: f for f in items if f['mimeType'] == FOLDER}
        paths = {}

        def path_of(fid):
            if fid in paths:
                return paths[fid]
            f = folders.get(fid)
            if f is None:
                return ''
            parent = (f.get('parents') or [''])[0]
            if fid in skip or parent in skip:
                paths[fid] = None
            else:
                up = path_of(parent)
                paths[fid] = None if up is None else (f'{up}/{f["name"]}' if up else f['name'])
            return paths[fid]
        sys.setrecursionlimit(10000)
        out, native, skipped = [], {}, 0
        for f in items:
            if f['mimeType'] == FOLDER:
                continue
            parent = (f.get('parents') or [''])[0]
            if parent in skip:
                skipped += 1
                continue
            up = path_of(parent)
            if up is None or up.endswith(' - private') or '/' in up and any(p.endswith(' - private') for p in up.split('/')):
                skipped += 1
                continue
            if f['mimeType'].startswith(GOOGLE):
                native[f['mimeType'][len(GOOGLE):]] = native.get(f['mimeType'][len(GOOGLE):], 0) + 1
                continue
            out.append({'id': f['id'], 'path': f'{up}/{f["name"]}' if up else f['name'], 'size': int(f.get('size') or 0),
                        'md5': f.get('md5Checksum'), 'type': file_type(f['name'], f['mimeType'])})
        log(f'{len(items)} items: {len(folders)} folders, {len(out)} files to bundle, {skipped} in private/bundle folders, '
            f'Google-native (not bundled): {native}')
        return out

    # ---------- planning ----------
    def plan(self):
        plan = self.store.load_state() or {'bundles': [], 'files': {}}
        have = plan['files']
        new = [f for f in self.list_drive() if f['id'] not in have]
        by_type = {}
        for f in new:
            by_type.setdefault(f['type'], []).extend(pieces(f))
        top = {}
        for b in plan['bundles']:
            top[b['type']] = max(top.get(b['type'], 0), b['n'])
        for t, fs in sorted(by_type.items()):
            fs.sort(key=lambda f: f['path'].lower())
            groups, cur, size, carry = [], [], 0, []
            for f in fs:
                if f['size'] > MAX:
                    groups.append([f])
                    continue
                if size + f['size'] <= MAX:
                    cur.append(f)
                    size += f['size']
                    continue
                if size >= MIN:
                    groups.append(cur)
                    cur, size = [f], f['size']
                else:
                    carry.append(f)  # keeps filling this bundle with the files that follow; placed at the end
            for f in carry:
                if size + f['size'] > MAX:
                    groups.append(cur)
                    cur, size = [], 0
                cur.append(f)
                size += f['size']
            if cur:
                groups.append(cur)
            n = top.get(t, 0)
            for g in groups:
                n += 1
                plan['bundles'].append({'type': t, 'n': n, 'size': sum(f['size'] for f in g), 'files': [f['id'] for f in g]})
                for f in g:
                    have[f['id']] = {k: v for k, v in f.items() if k not in ('id', 'type')}
                    if 'src' in f:
                        have[f['src']] = {'path': f['path'], 'size': f['total'], 'split': True}
        if not self.dry_run:
            self.save(plan)
        self.summary(plan, len(new))
        return plan

    def save(self, plan):
        """Resumable upload: the plan is larger than a simple upload allows."""
        raw = gzip.compress(json.dumps(plan, separators=(',', ':')).encode())
        media = MediaIoBaseUpload(io.BytesIO(raw), mimetype='application/gzip', resumable=True, chunksize=16 * 2**20)
        if self.store.state_id:
            req = self.files.update(fileId=self.store.state_id, media_body=media)
        else:
            req = self.files.create(body={'name': self.store.state_name, 'parents': [self.store.private]}, media_body=media, fields='id')
        resp = None
        while resp is None:
            _, resp = _retry(lambda: req.next_chunk())
        log(f'plan saved ({len(raw) / 1e6:.1f} MB)')

    def summary(self, plan, new):
        per = {}
        for b in plan['bundles']:
            p = per.setdefault(b['type'], [0, 0, 0])
            p[0] += 1
            p[1] += len(b['files'])
            p[2] += b['size']
        log(f'{new} new files assigned; {len(plan["bundles"])} bundles in all, {sum(v[2] for v in per.values()) / 1e9:.1f} GB')
        sizes = [x['size'] for x in plan['bundles']]
        log(f'bundle sizes: {sum(MIN <= z <= MAX for z in sizes)} at 400-500 MB, {sum(z < MIN for z in sizes)} smaller '
            f'(the last of a type), {sum(z > MAX for z in sizes)} over; {sum(1 for v in plan["files"].values() if v.get("split") is True)} large files split into parts')
        for t, (nb, nf, sz) in sorted(per.items(), key=lambda kv: -kv[1][2]):
            log(f'  {t:8} {nb:5} bundles {nf:8} files {sz / 1e9:8.2f} GB')
        q = _retry(lambda: self.store.drive.about().get(fields='storageQuota').execute())['storageQuota']
        log(f'storage: used {int(q.get("usage", 0)) / 1e9:.0f} GB of {int(q.get("limit", 0) or 0) / 1e9:.0f} GB (0 = unlimited/pooled)')

    # ---------- building ----------
    def done(self):
        keys, token = {}, None
        while True:
            r = _retry(lambda: self.files.list(
                q=f"appProperties has {{ key='bdApp' and value='{APP}' }} and trashed = false", pageSize=1000,
                pageToken=token, fields='nextPageToken, files(id, size, appProperties)').execute())
            for f in r['files']:
                keys[f['appProperties'].get('bdKey')] = f
            token = r.get('nextPageToken')
            if not token:
                return keys

    def build(self, shard, of, minutes):
        end = time.time() + minutes * 60
        plan = self.store.load_state()
        if not plan and self.dry_run:
            plan = self.plan()
        if not plan:
            sys.exit('no plan yet: run "plan" first')
        done = self.done()
        todo = [b for i, b in enumerate(plan['bundles']) if i % of == shard and f'{b["type"]}#{b["n"]}' not in done]
        if self.dry_run:
            todo = todo[:2]
        log(f'shard {shard}/{of}: {len(todo)} bundles to make, {sum(b["size"] for b in todo) / 1e9:.1f} GB')
        made = 0
        for b in todo:
            if time.time() + 15 * 60 > end:
                log('time budget reached')
                break
            self.make(b, plan['files'])
            made += 1
        left = len(todo) - made
        log(f'done: {made} bundles made, {left} left in this shard')
        return left

    def make(self, b, files):
        t0 = time.time()
        tmp = Path(tempfile.mkdtemp(prefix='bundle-'))
        try:
            local = self.download(b['files'], files, tmp)
            name = f'{b["n"]} {label(b["size"])}.zip'
            zpath = tmp / name
            used = set()
            with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
                for fid in b['files']:
                    src = local.get(fid)
                    if src is None:
                        continue
                    arc = files[fid]['path']
                    stem, dot, ext = arc.rpartition('.')
                    k = 2
                    while arc.lower() in used:
                        arc = f'{stem} ({k}).{ext}' if dot else f'{files[fid]["path"]} ({k})'
                        k += 1
                    used.add(arc.lower())
                    z.write(src, arc)
                    src.unlink()
            size = zpath.stat().st_size
            missing = len(b['files']) - len(local)
            if self.dry_run:
                log(f'  [dry] {b["type"]}/{name}: {len(local)} files, {size / 1e6:.0f} MB, {missing} missing')
                return
            folder = self.store._folder(self.store.root, b['type'])
            body = {'name': name, 'parents': [folder], 'mimeType': 'application/zip',
                    'appProperties': {'bdApp': APP, 'bdKey': f'{b["type"]}#{b["n"]}'}}
            media = MediaFileUpload(str(zpath), mimetype='application/zip', resumable=True, chunksize=64 * 2**20)
            req = self.files.create(body=body, media_body=media, fields='id, size')
            resp = None
            while resp is None:
                _, resp = _retry(lambda: req.next_chunk())
            if int(resp['size']) != size:
                raise RuntimeError(f'{name}: uploaded {resp["size"]} bytes, expected {size}')
            log(f'  {b["type"]}/{name}: {len(local)} files, {size / 1e6:.0f} MB, {missing} missing, {time.time() - t0:.0f}s')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def fetch(s, fid, a, b, dst):
        """Bytes a..b-1 of a Drive file."""
        n = 0
        with s.get(URL + fid, params={'alt': 'media', 'supportsAllDrives': 'true'}, headers={'Range': f'bytes={a}-{b - 1}'},
                   stream=True, timeout=300) as r:
            if r.status_code in (403, 429) or r.status_code >= 500:
                raise IOError(f'HTTP {r.status_code}')
            r.raise_for_status()
            with open(dst, 'wb') as out:
                for chunk in r.iter_content(4 * 2**20):
                    out.write(chunk)
                    n += len(chunk)
        if n != b - a:
            raise IOError(f'range {a}-{b}: got {n} bytes')

    def piece(self, s, info, dst):
        """One part of a large file, read as a byte range. Line parts start after the first line end at or after
        their start offset and stop after the first line end at or after their end offset, so parts join back exactly."""
        src, start, end, total = info['src'], info['start'], info['end'], info['total']
        if info['split'] == 'bytes':
            self.fetch(s, src, start, end, dst)
            return
        import mmap
        raw = dst.with_suffix('.raw')
        margin = 4 * 2**20
        while True:
            a, b = max(0, start - 1), min(total, end + margin)
            self.fetch(s, src, a, b, raw)
            with open(raw, 'rb') as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                s_off = 0 if start == 0 else mm.find(b'\n') + 1
                if end >= total:
                    e_off = len(mm)
                else:
                    i = mm.find(b'\n', end - 1 - a)
                    if i < 0:
                        margin *= 8
                        continue
                    e_off = i + 1
                head = b''
                if start > 0 and info['path'].lower().endswith('.csv'):
                    hdr = dst.with_suffix('.hdr')
                    self.fetch(s, src, 0, min(total, 2**20), hdr)
                    first = hdr.read_bytes()
                    head = first[:first.find(b'\n') + 1] if b'\n' in first else b''
                    hdr.unlink()
                with open(dst, 'wb') as out:
                    out.write(head)
                    for k in range(s_off, max(s_off, e_off), 16 * 2**20):
                        out.write(mm[k:min(e_off, k + 16 * 2**20)])
            raw.unlink()
            return

    def download(self, ids, files, tmp):
        """Parallel downloads, each checked against Drive's md5. A file gone from the drive is left out."""
        local, lock = {}, threading.Lock()
        sessions = threading.local()

        def one(i, fid):
            s = getattr(sessions, 's', None)
            if s is None:
                s = sessions.s = AuthorizedSession(credentials())
            dst = tmp / f'{i}.bin'
            for attempt in range(6):
                try:
                    if 'src' in files[fid]:
                        self.piece(s, files[fid], dst)
                        with lock:
                            local[fid] = dst
                        return
                    with s.get(f'https://www.googleapis.com/drive/v3/files/{fid}', params={'alt': 'media', 'supportsAllDrives': 'true'},
                               stream=True, timeout=300) as r:
                        if r.status_code == 404:
                            return
                        if r.status_code in (403, 429) or r.status_code >= 500:
                            raise IOError(f'HTTP {r.status_code}')
                        r.raise_for_status()
                        h = hashlib.md5()
                        with open(dst, 'wb') as out:
                            for chunk in r.iter_content(4 * 2**20):
                                out.write(chunk)
                                h.update(chunk)
                    want = files[fid].get('md5')
                    if want and h.hexdigest() != want:
                        raise IOError('md5 mismatch')
                    with lock:
                        local[fid] = dst
                    return
                except Exception as err:  # noqa: BLE001 - retried, then reported
                    if attempt == 5:
                        log(f'  ! {fid}: {err}')
                        raise
                    time.sleep(2 ** attempt)
        with ThreadPoolExecutor(int(os.environ.get('WORKERS', '12'))) as ex:
            list(ex.map(lambda a: one(*a), enumerate(ids)))
        return local


def main():
    dry = os.environ.get('DRY_RUN', 'false') == 'true'
    cmd = sys.argv[1]
    b = Bundler(dry_run=dry)
    if cmd == 'plan':
        b.plan()
    elif cmd == 'build':
        left = b.build(int(sys.argv[2]), int(sys.argv[3]), float(os.environ.get('RUN_MINUTES', '330')))
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write(f'left={left}\n')


if __name__ == '__main__':
    main()
