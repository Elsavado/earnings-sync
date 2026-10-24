"""Replace the generated models on the Workspace drives with their enhanced rebuilds, in place (user, 2026-10-24:
"replace the old one with the enhanced one"; nothing goes to the SFTP server).

    python -m models.replace plan <collection>                  # list the targets, save the plan on the drive
    python -m models.replace run <collection> <shard> <shards>  # rebuild, verify and overwrite one shard
    python -m models.replace status <collection> <shards>       # totals; 'remaining' for the chain step

collection:
  excel       IR Transcripts drive, 'Excel Models': the SEC-built models, identified by number from the collector state
  enterprise  Enterprise Wide Models drive: the corporate kinds, identified by their key (recomputed with ENT_NAME_KEY)

Each file keeps its id, name, folder and properties; only the content changes. Exact copies elsewhere on the same
drive (same MD5) get the same new content. A model that cannot be rebuilt, or fails verification, keeps its original.
Plan and progress live in '<drive>/Enhance Models - private'. Logs carry counts only (the repository is public).
"""
import collections
import gzip
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import requests
from googleapiclient.discovery import build as gbuild
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from . import enhanced, enterprise, three_x, unique
from .main import model_code
from .store import FOLDER, MIME, _retry, _SharedDrive, credentials
from .xl import REDACTED

DRIVES = {'excel': os.environ.get('IRT_DRIVE_ID') or '0AM6PzKRbJBK-Uk9PVA',
          'enterprise': os.environ.get('ENTERPRISE_DRIVE_ID') or '0AG5EzL2T7ZlfUk9PVA'}
PRIVATE = 'Enhance Models - private'
XLSX = MIME['xlsx']
# Excel Models kinds -> how the enhanced model is built (corporate kinds reuse the Enterprise engine with this title)
EXCEL = {'three': ('three', None), 'reit': ('three', None), 'dcf': ('valuation', 'DCF valuation model'),
         'lbo': ('buyout', 'LBO model'), 'fpa': ('budget', 'Operating & FP&A model')}
CORPORATE = tuple(enterprise.KINDS)
SEC_UA = os.environ.get('SEC_USER_AGENT') or 'ExcelModels research contact@example.com'
START = time.time()
BUDGET = float(os.environ.get('RUN_MINUTES', '50')) * 60
DRY = os.environ.get('REPLACE_DRY', '').lower() == 'true'  # rebuild and verify only: nothing is overwritten or recorded


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def left():
    return BUDGET - (time.time() - START)


class Drive:
    def __init__(self, drive_id):
        self.d = _SharedDrive(gbuild('drive', 'v3', credentials=credentials(), cache_discovery=False), drive_id)
        self.id = drive_id
        self.private = self.folder(drive_id, PRIVATE)

    def folder(self, parent, name, create=True):
        q = f"name = '{name}' and mimeType = '{FOLDER}' and '{parent}' in parents and trashed = false"
        found = _retry(lambda: self.d.files().list(q=q, fields='files(id)', pageSize=5, orderBy='createdTime').execute())['files']
        if found or not create:
            return found[0]['id'] if found else None
        return _retry(lambda: self.d.files().create(body={'name': name, 'mimeType': FOLDER, 'parents': [parent]},
                                                    fields='id').execute())['id']

    def each(self, q, fields='id, name, md5Checksum, appProperties, parents'):
        token = None
        while True:
            res = _retry(lambda: self.d.files().list(q=q, fields=f'nextPageToken, files({fields})', pageSize=1000,
                                                     pageToken=token).execute())
            yield from res.get('files', [])
            token = res.get('nextPageToken')
            if not token:
                return

    def get_json(self, name, parent=None):
        q = f"name = '{name}' and '{parent or self.private}' in parents and trashed = false"
        found = _retry(lambda: self.d.files().list(q=q, fields='files(id)').execute())['files']
        if not found:
            return None, None
        data = _retry(lambda: self.d.files().get_media(fileId=found[0]['id']).execute())
        return json.loads(gzip.decompress(data)), found[0]['id']

    def put_json(self, name, obj, file_id=None):
        media = MediaIoBaseUpload(io.BytesIO(gzip.compress(json.dumps(obj, separators=(',', ':')).encode())),
                                  mimetype='application/gzip', resumable=False)
        if file_id:
            _retry(lambda: self.d.files().update(fileId=file_id, media_body=media).execute())
            return file_id
        return _retry(lambda: self.d.files().create(body={'name': name, 'parents': [self.private]}, media_body=media,
                                                    fields='id').execute())['id']

    def overwrite(self, file_id, path):
        media = MediaFileUpload(str(path), mimetype=XLSX, resumable=False)
        _retry(lambda: self.d.files().update(fileId=file_id, media_body=media, fields='id').execute())


def md5_index(drv):
    """MD5 -> ids of every .xlsx on the drive (to find exact copies of a model outside its own folder)."""
    idx = collections.defaultdict(list)
    for f in drv.each(f"mimeType = '{XLSX}' and trashed = false", 'id, md5Checksum'):
        if f.get('md5Checksum'):
            idx[f['md5Checksum']].append(f['id'])
    return idx


# ---------------------------------------------------------------- plans
def plan_excel(drv):
    state, _ = drv.get_json('state.json.gz', drv.folder(drv.id, 'Excel Models - private', create=False))
    by_n = {int(v[3:]): k for k, v in state['seen'].items() if isinstance(v, str) and v.startswith('ok:') and k.startswith('sec:')}
    root = drv.folder(drv.id, 'Excel Models', create=False)
    files = {}
    for sub in drv.each(f"'{root}' in parents and mimeType = '{FOLDER}' and trashed = false", 'id'):
        for f in drv.each(f"'{sub['id']}' in parents and trashed = false", 'id, name, md5Checksum'):
            m = re.match(r'(\d+) - ', f['name'])
            if m and int(m.group(1)) in by_n:
                files[int(m.group(1))] = f
    idx = md5_index(drv)
    items = []
    for n, f in sorted(files.items()):
        _, cik, kind = by_n[n].split(':')
        ids = sorted(set([f['id']] + idx.get(f.get('md5Checksum'), [])))
        items.append({'n': n, 'key': by_n[n], 'cik': int(cik), 'kind': kind, 'ids': ids, 'name': f['name']})
    copies = sum(len(i['ids']) - 1 for i in items)
    log(f'plan excel: {len(items)} models ({len(by_n)} in the collector state), {copies} exact copies elsewhere on the drive')
    return items


def plan_enterprise(drv):
    if not os.environ.get('ENT_NAME_KEY'):
        raise SystemExit('ENT_NAME_KEY is needed to match the Enterprise file codes')
    s = requests.Session()
    s.headers['User-Agent'] = SEC_UA
    tickers = s.get('https://www.sec.gov/files/company_tickers.json', timeout=60).json()
    ciks = sorted({v['cik_str'] for v in tickers.values()})
    items, unmatched = [], 0
    for kind in CORPORATE:
        codes = {model_code(f'{cik}:{kind}:{t}'): (cik, t) for cik in ciks for t in enterprise.TRIMS}
        n = 0
        for f in drv.each(f"appProperties has {{ key='xmApp' and value='ent-{kind}' }} and trashed = false"):
            key = (f.get('appProperties') or {}).get('xmKey', '')
            got = codes.get(key[4:]) if key.startswith('ent:') else None
            if not got:
                unmatched += 1
                continue
            m = re.search(r'FY(\d\d)\b', f['name'])
            items.append({'key': key, 'cik': got[0], 'trim': got[1], 'kind': kind, 'ids': [f['id']], 'name': f['name'],
                          'fy': m.group(1) if m else None})
            n += 1
        log(f'plan enterprise {kind}: {n} models')
    log(f'plan enterprise: {len(items)} models, {unmatched} not matched to a company (left as they are)')
    return items


def plan(collection):
    drv = Drive(DRIVES[collection])
    items = plan_excel(drv) if collection == 'excel' else plan_enterprise(drv)
    _, fid = drv.get_json(f'plan-{collection}.json.gz')
    drv.put_json(f'plan-{collection}.json.gz', {'items': items, 'at': time.time()}, fid)


# ---------------------------------------------------------------- rebuild
def _fy(wb):
    return str(getattr(wb, 'asof', '') or '')[-2:]


def rebuild(item, facts, sector, sic, collection):
    """The enhanced workbook for one plan item, or (None, reason)."""
    key = item['key']
    if collection == 'excel':
        kind, title = EXCEL.get(item['kind'], (None, None))
        if kind is None:
            return None, f'no enhanced builder for {item["kind"]} yet'
        if kind == 'three':
            wb = three_x.build(facts, sector, key, is_reit=item['kind'] == 'reit')
        else:
            prof = unique.Profile(key)
            for trim in (0, 1):  # a year earlier when the latest year does not qualify (as the original was built)
                wb = enterprise.build(facts, sector, enhanced.market(), sic, kind, trim, profile=prof, title=title,
                                      fin_range=range(6000, 6500) if kind == 'valuation' else enterprise.FIN)
                if wb is not None:
                    wb.profile = prof
                    break
        if wb is not None:
            wb.properties.creator = wb.properties.lastModifiedBy = REDACTED  # Excel Models naming rule
        return (wb, None) if wb is not None else (None, 'company does not suit the enhanced model')
    prof = unique.Profile(key)
    trims = [item['trim']] + [t for t in (0, 1, 2) if t != item['trim']]
    for trim in trims:  # the same as-of year as the original file name
        wb = enterprise.build(facts, sector, enhanced.market(), sic, item['kind'], trim, profile=prof)
        if wb is None:
            continue
        if not item.get('fy') or _fy(wb) == item['fy']:
            wb.profile = prof
            return wb, None
    return None, 'as-of year of the original not available'


def run(collection, shard, shards):
    drv = Drive(DRIVES[collection])
    data, _ = drv.get_json(f'plan-{collection}.json.gz')
    if not data:
        log('no plan yet: run the plan step first')
        return 1
    name = f'state-{collection}-{shard}-of-{shards}.json.gz'
    state, sid = drv.get_json(name)
    state = state or {'done': {}}
    mine = [i for i in data['items'] if i['cik'] % shards == shard]
    todo = [i for i in mine if i['key'] not in state['done']]
    log(f'{collection} shard {shard}/{shards}: {len(mine)} models, {len(todo)} to do')
    by_cik = collections.defaultdict(list)
    for i in todo:
        by_cik[i['cik']].append(i)
    s = requests.Session()
    s.headers['User-Agent'] = SEC_UA
    tally, tmp, last_save = collections.Counter(), Path(tempfile.mkdtemp()), time.time()
    for cik, items in by_cik.items():
        if left() < 300:
            break
        got = enhanced.company(s, cik)
        if not got:
            for i in items:
                tally['kept: company data unavailable'] += 1
            continue
        facts, sector, sic = got
        for i in items:
            if left() < 240:
                break
            work = tmp / re.sub(r'\W', '_', i['key'])
            work.mkdir()
            try:
                wb, why = rebuild(i, facts, sector, sic, collection)
                out = None
                if wb is not None:
                    allowed = enhanced.finish(wb, i['key'])
                    out, why = enhanced.verify(wb, work / 'model.xlsx', allowed)
            except Exception as err:  # noqa: BLE001
                out, why = None, f'error {type(err).__name__}'
            if out and DRY:
                tally['would replace'] += 1
            elif out:
                for fid in i['ids']:
                    drv.overwrite(fid, out)
                state['done'][i['key']] = 'replaced'
                tally['replaced'] += 1
                tally['copies updated'] += len(i['ids']) - 1
            else:
                if not DRY:
                    state['done'][i['key']] = f'kept: {why}'[:120]
                tally[f'kept: {why}'[:80]] += 1
            shutil.rmtree(work, ignore_errors=True)
            if time.time() - last_save > 300 and not DRY:
                sid = drv.put_json(name, state, sid)
                last_save = time.time()
    if not DRY:
        sid = drv.put_json(name, state, sid)
    remaining = len([i for i in mine if i['key'] not in state['done']])
    log('\n'.join(f'{k}: {v}' for k, v in sorted(tally.items())))
    log(f'remaining in this shard: {remaining}')
    with open(os.environ.get('GITHUB_OUTPUT', os.devnull), 'a') as f:
        f.write(f'remaining={remaining}\n')
    return 0


def status(collection, shards):
    drv = Drive(DRIVES[collection])
    data, _ = drv.get_json(f'plan-{collection}.json.gz')
    done, tally = set(), collections.Counter()
    for k in range(shards):
        st, _ = drv.get_json(f'state-{collection}-{k}-of-{shards}.json.gz')
        for key, v in ((st or {}).get('done') or {}).items():
            done.add(key)
            tally['replaced' if v == 'replaced' else 'kept (original stays)'] += 1
    remaining = len([i for i in (data or {}).get('items', []) if i['key'] not in done])
    log(f'{collection}: {len((data or {}).get("items", []))} planned, ' + ', '.join(f'{k} {v}' for k, v in sorted(tally.items()))
        + f', remaining {remaining}')
    with open(os.environ.get('GITHUB_OUTPUT', os.devnull), 'a') as f:
        f.write(f'remaining={remaining}\n')


if __name__ == '__main__':
    if sys.argv[1] == 'plan':
        plan(sys.argv[2])
    elif sys.argv[1] == 'status':
        status(sys.argv[2], int(sys.argv[3]))
    elif sys.argv[1] == 'run':
        sys.exit(run(sys.argv[2], int(sys.argv[3]), int(sys.argv[4])))
