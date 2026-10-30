"""Google Drive storage for "Meeting Recordings" (Workspace Shared Drive "Research Collections").

Layout:  Meeting Recordings/<source type>/<organisation>/<date> <title>/audio.m4a, transcript.vtt, transcript.txt,
         meta.json   (one folder per recording; meta.json is uploaded last, so its presence means "complete")
         Meeting Recordings - private/state-<source>.json.gz
Every upload carries appProperties mtApp='meetings', mtSrc=<source> and mtKey=<recording id>/<file name>, so an
interrupted run never uploads a file twice.
"""
import gzip
import io
import json
import os

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from models.store import FOLDER, _SharedDrive, _retry, credentials

APP = 'meetings'
ROOT = 'Meeting Recordings'
PRIVATE = 'Meeting Recordings - private'
MIME = {'m4a': 'audio/mp4', 'mp3': 'audio/mpeg', 'vtt': 'text/vtt', 'srt': 'application/x-subrip',
        'txt': 'text/plain', 'json': 'application/json', 'pdf': 'application/pdf'}


def _q(s):
    return s.replace('\\', '\\\\').replace("'", "\\'")


class Drive:
    def __init__(self, source):
        self.source = source
        self.svc = build('drive', 'v3', credentials=credentials(), cache_discovery=False)
        self.top = os.environ['SHARED_DRIVE_ID']
        self.drive = _SharedDrive(self.svc, self.top)
        self.private = self._folder(self.top, PRIVATE)
        self.root = self._folder(self.top, ROOT)
        self.paths, self.ids = {}, {}
        self.sent_bytes = self.sent_items = 0

    def _folder(self, parent, name):
        q = f"name = '{_q(name)}' and mimeType = '{FOLDER}' and '{parent}' in parents and trashed = false"
        found = _retry(lambda: self.drive.files().list(q=q, fields='files(id)', pageSize=5,
                                                       orderBy='createdTime').execute())['files']
        if found:
            return found[0]['id']
        return _retry(lambda: self.drive.files().create(body={'name': name, 'mimeType': FOLDER, 'parents': [parent]},
                                                        fields='id').execute())['id']

    def path(self, rel):
        """Folder id of 'Meeting Recordings/<rel>' (created when missing)."""
        if rel not in self.paths:
            fid = self.root
            for part in rel.split('/'):
                if part:
                    fid = self._folder(fid, part)
            self.paths[rel] = fid
        return self.paths[rel]

    def uploaded(self):
        """{mtKey: file id} of everything this source has uploaded."""
        keys, token = {}, None
        q = (f"appProperties has {{ key='mtApp' and value='{APP}' }} and "
             f"appProperties has {{ key='mtSrc' and value='{self.source}' }} and trashed = false")
        while True:
            res = _retry(lambda: self.drive.files().list(q=q, fields='nextPageToken, files(id, appProperties)',
                                                         pageSize=1000, pageToken=token).execute())
            for f in res.get('files', []):
                k = f.get('appProperties', {}).get('mtKey')
                if k:
                    keys[k] = f['id']
            token = res.get('nextPageToken')
            if not token:
                return keys

    def upload(self, local, rel, name, key):
        ext = name.rsplit('.', 1)[-1].lower()
        size = os.path.getsize(local)
        big = size > 20 * 2**20
        media = MediaFileUpload(str(local), mimetype=MIME.get(ext, 'application/octet-stream'), resumable=big,
                                chunksize=32 * 2**20 if big else -1)
        body = {'name': name[:250], 'parents': [self.path(rel)],
                'appProperties': {'mtApp': APP, 'mtSrc': self.source, 'mtKey': key[:100]}}
        fid = _retry(lambda: self.drive.files().create(body=body, media_body=media, fields='id').execute())['id']
        self.sent_bytes += size
        self.sent_items += 1
        return fid

    # --- private state ----------------------------------------------------------------------------
    def _find(self, name):
        q = f"name = '{_q(name)}' and '{self.private}' in parents and trashed = false"
        found = _retry(lambda: self.drive.files().list(q=q, fields='files(id)').execute())['files']
        return found[0]['id'] if found else None

    def load(self, name):
        fid = self._find(name)
        if not fid:
            return {}
        self.ids[name] = fid
        return json.loads(gzip.decompress(_retry(lambda: self.drive.files().get_media(fileId=fid).execute())))

    def save(self, name, obj):
        raw = gzip.compress(json.dumps(obj, separators=(',', ':')).encode())
        media = MediaIoBaseUpload(io.BytesIO(raw), mimetype='application/gzip', resumable=False)
        fid = self.ids.get(name) or self._find(name)
        if fid:
            _retry(lambda: self.drive.files().update(fileId=fid, media_body=media).execute())
        else:
            self.ids[name] = _retry(lambda: self.drive.files().create(
                body={'name': name, 'parents': [self.private]}, media_body=media, fields='id').execute())['id']
