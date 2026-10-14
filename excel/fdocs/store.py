"""Google Drive storage for financial documents, numbered per type in folders of twenty.

Layout:  Financial Documents/Earnings Call Transcripts/Folder 1 (Documents 1-20)/1 - Earnings call transcript.pdf
         Financial Documents - private/state.json.gz
Every upload carries appProperties fdApp, fdKind, fdNum and fdKey, so numbering can be
recovered from Drive itself.
"""
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from models.store import FOLDER, Store as _Base, _retry

from .kinds import KINDS

APP = 'fin-docs'
PER_FOLDER = 20
MIME = {'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'ipynb': 'application/x-ipynb+json', 'csv': 'text/csv', 'json': 'application/json'}


def folder_name(n):
    k = (n - 1) // PER_FOLDER + 1
    return f'Folder {k} (Documents {PER_FOLDER * (k - 1) + 1}-{PER_FOLDER * k})'


class Store(_Base):
    def __init__(self, dry_run=False):
        super().__init__('Financial Documents', 'Financial Documents - private', dry_run=dry_run)
        self.kind_roots = {}

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

    def upload_doc(self, path, kind, n, label, ext, key):
        name = f'{n} - {label}.{ext}'
        if self.dry_run:
            return name
        if kind not in self.kind_roots:
            self.kind_roots[kind] = self._folder(self.root, KINDS[kind]['folder'])
        fname = (kind, folder_name(n))
        if fname not in self.folders:
            self.folders[fname] = self._folder(self.kind_roots[kind], fname[1])
        body = {'name': name, 'parents': [self.folders[fname]],
                'appProperties': {'fdApp': APP, 'fdKind': kind, 'fdNum': str(n), 'fdKey': key[:100]}}
        media = MediaFileUpload(path, mimetype=MIME[ext], resumable=False)
        _retry(lambda: self.drive.files().create(body=body, media_body=media, fields='id').execute())
        return name

    def reset(self, log=print):
        """Permanently deletes every uploaded document, the type folders and the run state."""
        n = 0
        for q in (f"appProperties has {{ key='fdApp' and value='{APP}' }}",
                  f"'{self.root}' in parents and mimeType = '{FOLDER}'",
                  f"'{self.private}' in parents"):
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
