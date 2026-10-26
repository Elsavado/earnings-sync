"""Google Drive storage for financial documents, numbered per type in folders of twenty.

Layout:  Financial Documents/Earnings Call Transcripts/Folder 1 (Documents 1-20)/1 - Earnings call transcript.pdf
         Financial Documents - private/state.json.gz
Every upload carries appProperties fdApp, fdKind, fdNum and fdKey, so numbering can be
recovered from Drive itself.
"""
import hashlib
import os

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from models.store import FOLDER, Store as _Base, _retry

from .kinds import KINDS

APP = os.environ.get('FD_APP', 'fin-docs')  # the Workspace collector tags its files differently from the transferred ones
PER_FOLDER = 20
MIME = {'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'ipynb': 'application/x-ipynb+json', 'csv': 'text/csv', 'json': 'application/json', 'zip': 'application/zip'}


def prop(name, value, limit=124):
    """Drive caps each appProperty at 124 UTF-8 bytes, key and value together: a longer value keeps a prefix cut on
    a character boundary plus a hash of the whole value, so it stays unique."""
    room = limit - len(name.encode())
    if len(value.encode()) <= room:
        return value
    tail = '#' + hashlib.sha256(value.encode()).hexdigest()[:16]
    return value.encode()[:room - len(tail)].decode('utf-8', 'ignore') + tail


def folder_name(n):
    k = (n - 1) // PER_FOLDER + 1
    return f'Folder {k} (Documents {PER_FOLDER * (k - 1) + 1}-{PER_FOLDER * k})'


class Store(_Base):
    def __init__(self, dry_run=False, state_name='state.json.gz'):
        # FD_ROOT='' (with SHARED_DRIVE_ID) puts the type folders at the top of the Shared Drive.
        root = os.environ.get('FD_ROOT', 'Financial Documents')
        super().__init__(root or None, os.environ.get('FD_PRIVATE', 'Financial Documents - private'), dry_run=dry_run)
        self.kind_roots = {}
        self.state_name = state_name  # one state file per parallel job ('state-payroll.json.gz')

    def free_bytes(self):
        used, limit = self.quota()
        return (limit - used) if limit else float('inf')

    def load_state(self):
        import gzip
        import json
        q = f"name = '{self.state_name}' and '{self.private}' in parents and trashed = false"
        found = _retry(lambda: self.drive.files().list(q=q, fields='files(id)').execute())['files']
        if not found:
            return {}
        self.state_id = found[0]['id']
        data = _retry(lambda: self.drive.files().get_media(fileId=self.state_id).execute())
        return json.loads(gzip.decompress(data))

    def save_state(self, state):
        import gzip
        import io
        import json
        from googleapiclient.http import MediaIoBaseUpload
        if self.dry_run:
            return
        raw = gzip.compress(json.dumps(state, separators=(',', ':')).encode())
        media = MediaIoBaseUpload(io.BytesIO(raw), mimetype='application/gzip', resumable=False)
        if self.state_id:
            _retry(lambda: self.drive.files().update(fileId=self.state_id, media_body=media).execute())
        else:
            self.state_id = _retry(lambda: self.drive.files().create(
                body={'name': self.state_name, 'parents': [self.private]}, media_body=media, fields='id').execute())['id']

    def max_numbers(self):
        """{kind: highest number uploaded}."""
        best, token = {}, None
        while True:
            res = _retry(lambda: self.drive.files().list(
                q=f"appProperties has {{ key='fdApp' and value='{APP}' }} and trashed = false",
                fields='nextPageToken, files(appProperties)', pageSize=1000, pageToken=token).execute())
            for f in res.get('files', []):
                ap = f.get('appProperties', {})
                try:
                    best[ap.get('fdKind')] = max(best.get(ap.get('fdKind'), 0), int(ap.get('fdNum', 0)))
                except ValueError:
                    pass
            token = res.get('nextPageToken')
            if not token:
                return best

    def names(self, kind):
        """Names of every file of one type this collector has on Drive."""
        out, token = [], None
        while True:
            res = _retry(lambda: self.drive.files().list(
                q=f"appProperties has {{ key='fdApp' and value='{APP}' }} and "
                  f"appProperties has {{ key='fdKind' and value='{kind}' }} and trashed = false",
                fields='nextPageToken, files(name)', pageSize=1000, pageToken=token).execute())
            out += [f['name'] for f in res.get('files', [])]
            token = res.get('nextPageToken')
            if not token:
                return out

    def upload_doc(self, path, kind, n, label, ext, key):
        from .office import GOOGLE
        google = GOOGLE.get(kind) if ext in ('xlsx', 'docx', 'pptx') else None  # Drive converts the file to its Google type
        name = f'{n} - {label}' if google else f'{n} - {label}.{ext}'
        if self.dry_run:
            return name
        if kind not in self.kind_roots:
            self.kind_roots[kind] = self._folder(self.root, KINDS[kind]['folder'])
        fname = (kind, folder_name(n))
        if fname not in self.folders:
            self.folders[fname] = self._folder(self.kind_roots[kind], fname[1])
        body = {'name': name, 'parents': [self.folders[fname]],
                'appProperties': {'fdApp': APP, 'fdKind': kind, 'fdNum': str(n), 'fdKey': prop('fdKey', key)}}
        if google:
            body['mimeType'] = google
        import os
        big = os.path.getsize(path) > 5 * 2**20  # simple uploads stop at 5 MB; larger files go up in chunks
        media = MediaFileUpload(path, mimetype=MIME[ext], resumable=big, chunksize=32 * 2**20 if big else -1)

        def send():
            req = self.drive.files().create(body=body, media_body=media, fields='id')
            if not big:
                return req.execute()
            resp = None
            while resp is None:
                _, resp = req.next_chunk(num_retries=5)
            return resp
        _retry(send)
        return name

    def uploaded(self, key):
        """Ids of files already on the drive for this source key (an upload whose reply was lost can still land)."""
        v = prop('fdKey', key).replace('\\', '\\\\').replace("'", "\\'")
        q = (f"appProperties has {{ key='fdKey' and value='{v}' }} and "
             f"appProperties has {{ key='fdApp' and value='{APP}' }} and trashed = false")
        res = _retry(lambda: self.drive.files().list(q=q, fields='files(id)', pageSize=10).execute())
        return [f['id'] for f in res.get('files', [])]

    def reset(self, log=print):
        """Permanently deletes every uploaded document, the type folders and the run state."""
        n = 0
        folders = f"'{self.root}' in parents and mimeType = '{FOLDER}'"
        if self.root == self.shared:  # top of a Shared Drive that holds other data: only this collector's type folders
            names = ' or '.join(f"name = '{k['folder']}'" for k in KINDS.values() if k.get('workspace'))
            folders += f' and ({names})'
        for q in (f"appProperties has {{ key='fdApp' and value='{APP}' }}", folders, f"'{self.private}' in parents"):
            token = None
            while True:
                res = _retry(lambda: self.drive.files().list(q=q, fields='nextPageToken, files(id)', pageSize=1000,
                                                             pageToken=token).execute())
                for f in res.get('files', []):
                    try:
                        _retry(lambda: self.drive.files().delete(fileId=f['id']).execute())
                        n += 1
                    except HttpError as err:
                        if err.resp.status != 404:
                            raise
                token = res.get('nextPageToken')
                if not token:
                    break
        self.state_id = None
        log(f'reset: deleted {n} item(s); numbering restarts at 1 for every type')
