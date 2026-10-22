"""Counts the files of each type on every drive of the Workspace account (My Drive and each Shared Drive).
Duplicates (same MD5) count once; Google Docs/Sheets/Slides have no MD5, so each counts once.
Read-only: lists metadata, changes nothing."""
import collections
import os

from googleapiclient.discovery import build

from bundles import file_type, log
from models.store import FOLDER, _retry, credentials


def main():
    drive = build('drive', 'v3', credentials=credentials(), cache_discovery=False)
    names = {'': 'My Drive'}
    token = None
    while True:
        r = _retry(lambda: drive.drives().list(pageSize=100, pageToken=token).execute())
        names.update({d['id']: d['name'] for d in r.get('drives', [])})
        token = r.get('nextPageToken')
        if not token:
            break
    per = {k: collections.defaultdict(dict) for k in names}   # drive -> type -> key -> size
    total = collections.Counter()
    for did in names:
        kw = dict(corpora='drive', driveId=did, includeItemsFromAllDrives=True, supportsAllDrives=True) if did else \
            dict(corpora='user', q="'me' in owners and trashed = false")
        kw.setdefault('q', 'trashed = false')
        token, n = None, 0
        while True:
            r = _retry(lambda: drive.files().list(pageSize=1000, pageToken=token,
                                                  fields='nextPageToken, files(id, name, mimeType, size, md5Checksum)', **kw).execute())
            for f in r['files']:
                if f['mimeType'] == FOLDER:
                    continue
                t = file_type(f['name'], f['mimeType'])
                per[did][t].setdefault(f.get('md5Checksum') or f['id'], int(f.get('size') or 0))
                total[(did, t)] += 1
                n += 1
            token = r.get('nextPageToken')
            if n % 50000 < 1000:
                log(f'{names[did]}: {n:,} files')
            if not token:
                break
        log(f'{names[did]}: done, {n:,} files')

    out = ['# Files by type on the Workspace drives', '', 'Unique = duplicates (same content) counted once.', '']
    every = collections.defaultdict(dict)
    for did, types in per.items():
        if not types:
            continue
        u = sum(len(v) for v in types.values())
        a = sum(c for (d, _), c in total.items() if d == did)
        out += [f'## {names[did]}: {u:,} unique files ({a:,} incl. duplicates)', '', '| Type | Unique files | Size (GB) |', '|---|--:|--:|']
        for t, v in sorted(types.items(), key=lambda x: -len(x[1])):
            out.append(f'| {t} | {len(v):,} | {sum(v.values()) / 1e9:,.2f} |')
            every[t].update(v)
        out.append('')
    out += [f'## All drives together: {sum(len(v) for v in every.values()):,} unique files', '', '| Type | Unique files | Size (GB) |', '|---|--:|--:|']
    for t, v in sorted(every.items(), key=lambda x: -len(x[1])):
        out.append(f'| {t} | {len(v):,} | {sum(v.values()) / 1e9:,.2f} |')
    text = '\n'.join(out)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8').write(text + '\n')


if __name__ == '__main__':
    main()
