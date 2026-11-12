"""Parallel Common Crawl index scanner for the shintiru office collector (user, 2026-11-12: "source for shintiru
mostly full force").

Reading the index was the bottleneck: one job, four threads, about 13,000 index blocks an hour, and Common Crawl
throttles more threads from one address. Each scanner job (a separate runner, so a separate address) now reads one
crawl on its own and writes the PowerPoint / Word / Excel addresses it finds to a list; the collector jobs (one per
type) queue them, check robots.txt and download.

  python -m fdocs.ccscan SHARD CURSORS_DIR OUT_DIR

Lists go to OUT_DIR/<type>/, one folder per collector job. Shard N takes the N-th crawl not yet finished
(newest first). CURSORS_DIR holds one small file per crawl,
<crawl>.json = {"pos": next block, "blocks": total, "done": bool}; the workflow keeps it on the drive.
Environment: OFFICE_PROFILE, RUN_MINUTES, SCAN_CRAWLS (how many of the newest crawls to cover, default 24).
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import ccweb

KINDS = ['gdocs', 'gsheets', 'slides']
END = time.time() + float(os.environ.get('RUN_MINUTES', '45')) * 60


def log(msg):
    print(time.strftime('[%H:%M:%S] ') + msg, flush=True)


def main(shard, cursors, out):
    shard, cursors, out = int(shard), Path(cursors), Path(out)
    cursors.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers['User-Agent'] = ccweb.UA
    colls = ccweb._collections(s)[:int(os.environ.get('SCAN_CRAWLS', '24'))]

    def cur_of(c):
        f = cursors / f'{c}.json'
        return json.loads(f.read_text()) if f.exists() else {'pos': 0, 'done': False}
    pending = [c for c in colls if not cur_of(c).get('done')]
    if shard >= len(pending):
        log(f'shard {shard}: no crawl left for this shard ({len(pending)} unfinished)')
        return
    coll = pending[shard]
    cur = cur_of(coll)
    blocks = ccweb._blocks(s, coll, log)
    cur['blocks'] = len(blocks)
    start, found, busy = cur['pos'], 0, 0
    stamp = f'{coll}-{shard}-{int(time.time())}.tsv'
    lists = {}
    for k in KINDS:
        (out / k).mkdir(exist_ok=True)
        lists[k] = (out / k / stamp).open('w', encoding='utf-8')
    with ThreadPoolExecutor(ccweb.THREADS) as ex:
        while time.time() < END and cur['pos'] < len(blocks):
            batch = blocks[cur['pos']:cur['pos'] + ccweb.BLOCKS_PER_CALL]
            res = list(ex.map(lambda b: ccweb._read_block(s, coll, b, KINDS), batch))
            ok = [r is not None for r in res]
            if not any(ok):
                busy += 1
                time.sleep(min(120, 15 * busy))  # throttled: wait, then carry on
                continue
            busy = 0
            cur['pos'] += ok.index(False) if False in ok else len(batch)
            for r in res:
                for kind, url, ext in r or []:
                    lists[kind].write(f'{kind}\t{url}\t{ext}\n')
                    found += 1
            for fh in lists.values():
                fh.flush()
            (cursors / f'{coll}.json').write_text(json.dumps(cur))
    cur['done'] = cur['pos'] >= len(blocks)
    (cursors / f'{coll}.json').write_text(json.dumps(cur))
    for k, fh in lists.items():
        fh.close()
        if (out / k / stamp).stat().st_size == 0:
            (out / k / stamp).unlink()
    log(f'shard {shard}: {coll} blocks {start}-{cur["pos"]} of {len(blocks)}, {found} files found'
        f'{" (crawl finished)" if cur["done"] else ""}')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write(f'- scanner {shard}: {coll} {cur["pos"]}/{len(blocks)} blocks, {found} files found\n')


if __name__ == '__main__':
    main(*sys.argv[1:4])
