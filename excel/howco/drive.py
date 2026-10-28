"""Google Drive storage for "How Companies Work" (Workspace Shared Drive "Research Collections").

Layout:  How Companies Work/<Source folder>/...      (folders are created on demand, 'A/B/C' nests)
         How Companies Work - private/state-<source>.json.gz, names-<source>.json.gz, drives.json.gz
A Shared Drive holds at most 400,000 items: when "Research Collections" reaches CAP items, content goes to a new
Shared Drive "How Companies Work 2" (then 3, ...) with the same source folders at its top (user, 2026-10-28). The
private folder (state, names) always stays in the first drive. Every upload carries appProperties hcApp='howco',
hcSrc and hcKey, so an interrupted run never uploads a file twice and a file can be replaced in place.
"""
import gzip
import hashlib
import io
import json
import mimetypes
import os

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from models.store import FOLDER, _SharedDrive, _retry, credentials

APP = 'howco'
ROOT = 'How Companies Work'
PRIVATE = 'How Companies Work - private'
CAP = 350000  # items per Shared Drive (Google allows 400,000)
BASELINE = 11776  # items already on "Research Collections" before this collector (2026-10-28)
MIME = {'pdf': 'application/pdf', 'csv': 'text/csv', 'txt': 'text/plain', 'md': 'text/markdown',
        'json': 'application/json', 'jsonl': 'application/json', 'zip': 'application/zip', 'eml': 'message/rfc822',
        'mp3': 'audio/mpeg', 'wav': 'audio/wav',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'xlsm': 'application/vnd.ms-excel.sheet.macroEnabled.12',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'}


def _q(s):
    return s.replace('\\', '\\\\').replace("'", "\\'")


class Drive:
    def __init__(self, source, dry_run=False):
        self.source, self.dry = source, dry_run
        self.svc = build('drive', 'v3', credentials=credentials(), cache_discovery=False)
        self.top = os.environ['SHARED_DRIVE_ID']
        self.drive = _SharedDrive(self.svc, self.top)  # the first drive: private folder, state
        self.private = self._folder(self.drive, self.top, PRIVATE, create=True)
        self.ids = {}
        self.sent_bytes = 0  # uploaded since the state was last saved
        self.sent_items = 0
        self.overflow = self.load('drives.json.gz', {'drives': []})
        self.use(self.top)

    # --- which drive gets the content ---------------------------------------------------------
    def drive_ids(self):
        return [self.top] + [d['id'] for d in self.overflow['drives']]

    def use(self, drive_id):
        self.target = drive_id
        self.content = self.drive if drive_id == self.top else _SharedDrive(self.svc, drive_id)
        self.root = self._folder(self.content, self.top, ROOT) if drive_id == self.top else drive_id
        self.paths = {}

    def choose(self, counts):
        """counts: {drive id: items}. Picks the first drive with room, creating "How Companies Work N" when every
        drive is full. Returns False when no drive has room (a new one could not be made)."""
        for d in self.drive_ids():
            if counts.get(d, 0) + (BASELINE if d == self.top else 0) < CAP:
                self.use(d)
                return True
        if self.dry:
            return True
        n = len(self.overflow['drives']) + 2
        name = f'{ROOT} {n}'
        try:
            found = _retry(lambda: self.svc.drives().list(q=f"name = '{_q(name)}'", pageSize=10,
                                                           fields='drives(id,name)').execute()).get('drives', [])
            if found:
                did = found[0]['id']
            else:
                rid = hashlib.sha1(f'{self.top}:{name}'.encode()).hexdigest()  # same request id: no second drive
                did = _retry(lambda: self.svc.drives().create(requestId=rid, body={'name': name},
                                                              fields='id').execute())['id']
        except HttpError as err:
            self.overflow['denied'] = f'{err.resp.status}: {str(err)[:200]}'
            self.save('drives.json.gz', self.overflow)
            return False
        self.overflow['drives'].append({'name': name, 'id': did})
        self.save('drives.json.gz', self.overflow)
        self.use(did)
        return True

    def free_bytes(self):
        """Free space of the Workspace storage pool, when the API reports a limit (None otherwise)."""
        try:
            q = _retry(lambda: self.svc.about().get(fields='storageQuota').execute())['storageQuota']
        except HttpError:
            return None
        limit = int(q.get('limit') or 0)
        return limit - int(q.get('usage') or 0) if limit else None

    # --- folders and files -------------------------------------------------------------------------
    def _folder(self, drv, parent, name, create=False):
        q = f"name = '{_q(name)}' and mimeType = '{FOLDER}' and '{parent}' in parents and trashed = false"
        found = _retry(lambda: drv.files().list(q=q, fields='files(id)', pageSize=5,
                                                orderBy='createdTime').execute())['files']
        if found:
            return found[0]['id']
        if self.dry and not create:
            return f'dry:{parent}/{name}'
        return _retry(lambda: drv.files().create(body={'name': name, 'mimeType': FOLDER, 'parents': [parent]},
                                                 fields='id').execute())['id']

    def folder(self, parent, name, create=False):
        """A folder in the first drive (the private folder and its sub-folders)."""
        return self._folder(self.drive, parent, name, create)

    def path(self, rel):
        """Folder id of '<root>/<rel>' in the content drive (created when missing)."""
        if self.dry:
            return f'dry:{rel}'
        if rel not in self.paths:
            fid = self.root
            for part in rel.split('/'):
                if part:
                    fid = self._folder(self.content, fid, part)
            self.paths[rel] = fid
        return self.paths[rel]

    def uploaded(self):
        """{hcKey: file id} of everything this source has uploaded, on every drive."""
        keys = {}
        if self.dry:
            return keys
        q = (f"appProperties has {{ key='hcApp' and value='{APP}' }} and "
             f"appProperties has {{ key='hcSrc' and value='{self.source}' }} and trashed = false")
        for d in self.drive_ids():
            drv = self.drive if d == self.top else _SharedDrive(self.svc, d)
            token = None
            while True:
                res = _retry(lambda: drv.files().list(q=q, fields='nextPageToken, files(id, appProperties)',
                                                      pageSize=1000, pageToken=token).execute())
                for f in res.get('files', []):
                    k = f.get('appProperties', {}).get('hcKey')
                    if k:
                        keys[k] = f['id']
                token = res.get('nextPageToken')
                if not token:
                    break
        return keys

    def upload(self, local, rel, name, key, replace=None):
        """Uploads local as '<root>/<rel>/<name>'; replace: id of an earlier version to overwrite."""
        ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
        mime = MIME.get(ext) or mimetypes.guess_type(name)[0] or 'application/octet-stream'
        if self.dry:
            return 'dry'
        size = os.path.getsize(local)
        self.sent_bytes += size
        big = size > 20 * 2**20
        media = MediaFileUpload(local, mimetype=mime, resumable=big, chunksize=32 * 2**20 if big else -1)
        if replace:
            return _retry(lambda: self.svc.files().update(fileId=replace, media_body=media, fields='id',
                                                          supportsAllDrives=True).execute())['id']
        body = {'name': name[:250], 'parents': [self.path(rel)],
                'appProperties': {'hcApp': APP, 'hcSrc': self.source, 'hcKey': key[:100]}}
        fid = _retry(lambda: self.content.files().create(body=body, media_body=media, fields='id').execute())['id']
        self.sent_items += 1
        return fid

    # --- private files ----------------------------------------------------------------
    def _find(self, name):
        q = f"name = '{_q(name)}' and '{self.private}' in parents and trashed = false"
        found = _retry(lambda: self.drive.files().list(q=q, fields='files(id)').execute())['files']
        return found[0]['id'] if found else None

    def load(self, name, default=None):
        fid = self._find(name)
        if not fid:
            return {} if default is None else default
        self.ids[name] = fid
        data = _retry(lambda: self.drive.files().get_media(fileId=fid).execute())
        return json.loads(gzip.decompress(data))

    def save(self, name, obj):
        if self.dry:
            return
        raw = gzip.compress(json.dumps(obj, separators=(',', ':')).encode())
        media = MediaIoBaseUpload(io.BytesIO(raw), mimetype='application/gzip', resumable=False)
        fid = self.ids.get(name) or self._find(name)
        if fid:
            _retry(lambda: self.drive.files().update(fileId=fid, media_body=media).execute())
        else:
            self.ids[name] = _retry(lambda: self.drive.files().create(
                body={'name': name, 'parents': [self.private]}, media_body=media, fields='id').execute())['id']

    def private_names(self):
        """Names of the files in the private folder."""
        q = f"'{self.private}' in parents and trashed = false"
        return [f['name'] for f in _retry(lambda: self.drive.files().list(q=q, fields='files(name)',
                                                                            pageSize=200).execute())['files']]
