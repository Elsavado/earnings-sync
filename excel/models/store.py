"""Google Drive storage: numbered models in folders of twenty, plus the run state.

Layout:  Excel Models/Folder 1 (Models 1-20)/1 - DCF valuation model - Semiconductors.xlsx
         Excel Models - private/state.json.gz   (what has been seen, made or rejected)
Every uploaded model carries appProperties (xmApp, xmNum, xmKey), so numbering can always be
recovered from Drive itself.
"""
import gzip
import io
import json
import os
import ssl
import time

import httplib2

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

FOLDER = 'application/vnd.google-apps.folder'
MIME = {'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'xlsm': 'application/vnd.ms-excel.sheet.macroEnabled.12'}
APP = 'excel-models'
PER_FOLDER = 20


def folder_name(n):
    k = (n - 1) // PER_FOLDER + 1
    return f'Folder {k} (Models {PER_FOLDER * (k - 1) + 1}-{PER_FOLDER * k})'


def _retry(fn, tries=6):
    """Retries Drive calls on rate limits, server errors and dropped connections (a connection
    left idle while sources are crawled can be closed by the far end: SSLEOFError, resets)."""
    for i in range(tries):
        try:
            return fn()
        except HttpError as err:
            if err.resp.status in (403, 429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(2 ** i)
                continue
            raise
        except (ssl.SSLError, ConnectionError, TimeoutError, OSError, httplib2.HttpLib2Error):
            if i < tries - 1:
                time.sleep(2 ** i)
                continue
            raise


class Store:
    def __init__(self, root_name='Excel Models', private_name='Excel Models - private', dry_run=False):
        self.dry_run = dry_run
        creds = Credentials(None, refresh_token=os.environ['GOOGLE_REFRESH_TOKEN'],
                            client_id=os.environ['GOOGLE_CLIENT_ID'], client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
                            token_uri='https://oauth2.googleapis.com/token')
        self.drive = build('drive', 'v3', credentials=creds, cache_discovery=False)
        self.root = self._folder('root', root_name)
        self.private = self._folder('root', private_name)
        self.folders = {}
        self.state_id = None

    def _folder(self, parent, name):
        q = f"name = '{name}' and mimeType = '{FOLDER}' and '{parent}' in parents and trashed = false"
        found = _retry(lambda: self.drive.files().list(q=q, fields='files(id)', pageSize=5).execute())['files']
        if found:
            return found[0]['id']
        return _retry(lambda: self.drive.files().create(body={'name': name, 'mimeType': FOLDER, 'parents': [parent]},
                                                        fields='id').execute())['id']

    def quota(self):
        q = self.drive.about().get(fields='storageQuota').execute()['storageQuota']
        return int(q.get('usage', 0)), int(q.get('limit', 0) or 0)

    def max_number(self):
        best, token = 0, None
        while True:
            res = _retry(lambda: self.drive.files().list(
                q=f"appProperties has {{ key='xmApp' and value='{APP}' }} and trashed = false",
                fields='nextPageToken, files(appProperties)', pageSize=1000, pageToken=token).execute())
            for f in res.get('files', []):
                try:
                    best = max(best, int(f.get('appProperties', {}).get('xmNum', 0)))
                except ValueError:
                    pass
            token = res.get('nextPageToken')
            if not token:
                return best

    def upload(self, path, n, label, ext, key, category):
        name = f'{n} - {label}.{ext}'
        if self.dry_run:
            return name
        fname = folder_name(n)
        if fname not in self.folders:
            self.folders[fname] = self._folder(self.root, fname)
        body = {'name': name, 'parents': [self.folders[fname]],
                'appProperties': {'xmApp': APP, 'xmNum': str(n), 'xmKey': key[:110], 'xmCat': category[:100]}}
        media = MediaFileUpload(path, mimetype=MIME[ext], resumable=False)
        _retry(lambda: self.drive.files().create(body=body, media_body=media, fields='id').execute())
        return name

    def reset(self, log=print):
        """Permanently deletes every uploaded model, the numbered folders and the run state."""
        n = 0
        for q in (f"appProperties has {{ key='xmApp' and value='{APP}' }}",
                  f"'{self.root}' in parents and mimeType = '{FOLDER}'",
                  f"'{self.private}' in parents"):
            token = None
            while True:
                res = _retry(lambda: self.drive.files().list(q=q, fields='nextPageToken, files(id, name)', pageSize=1000,
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
        log(f'reset: deleted {n} item(s); numbering restarts at 1')

    # --- state ------------------------------------------------------------
    def load_state(self):
        q = f"name = 'state.json.gz' and '{self.private}' in parents and trashed = false"
        found = _retry(lambda: self.drive.files().list(q=q, fields='files(id)').execute())['files']
        if not found:
            return {}
        self.state_id = found[0]['id']
        data = _retry(lambda: self.drive.files().get_media(fileId=self.state_id).execute())
        return json.loads(gzip.decompress(data))

    def save_state(self, state):
        if self.dry_run:
            return
        raw = gzip.compress(json.dumps(state, separators=(',', ':')).encode())
        media = MediaIoBaseUpload(io.BytesIO(raw), mimetype='application/gzip', resumable=False)
        if self.state_id:
            _retry(lambda: self.drive.files().update(fileId=self.state_id, media_body=media).execute())
        else:
            self.state_id = _retry(lambda: self.drive.files().create(
                body={'name': 'state.json.gz', 'parents': [self.private]}, media_body=media, fields='id').execute())['id']
