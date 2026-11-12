"""Parallel Common Crawl index scanner for the shintiru office collector (user, 2026-11-12: "source for shintiru
mostly full force", then "search the internet at large").

Each scanner job (a separate runner, so a separate address) reads one crawl on its own and writes the PowerPoint /
Word / Excel addresses it finds to lists; the collector jobs (one per type) queue them, check robots.txt and download.

Two ways to read a crawl:
  columnar  the crawl's Parquet index (300 files, one per slice of top-level domains), queried with DuckDB for the
            Office file types only; slices with no English-leaning domain are skipped from the file's footer alone.
            About ten times faster than the text index, and it covers every English-leaning domain.
  text      the CDX text index block by block (the old way); used when a crawl has no columnar index.

  python -m fdocs.ccscan SHARD CURSORS_DIR OUT_DIR

Lists go to OUT_DIR/<type>/. Shard N takes the N-th crawl not yet finished (every crawl from 2012 on, newest and
oldest in turn). CURSORS_DIR holds one small file per crawl: {"pidx": next Parquet file, "pos": next text block,
"done": bool}; the workflow keeps it on the drive.
Environment: OFFICE_PROFILE, RUN_MINUTES, CC_MIN_YEAR (default 2012), SCAN_MODE (columnar | text).
"""
import gzip
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import ccweb

KINDS = ['gdocs', 'gsheets', 'slides']
END = time.time() + float(os.environ.get('RUN_MINUTES', '45')) * 60
DATA = 'https://data.commoncrawl.org/'
OFFICE_MIMES = (
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/msword', 'application/vnd.ms-powerpoint', 'application/x-tika-msoffice',
    'application/x-tika-ooxml')


def log(msg):
    print(time.strftime('[%H:%M:%S] ') + msg, flush=True)


def _get(s, url, **kw):
    for wait in (10, 30, 60, 120, None):
        try:
            r = s.get(url, timeout=600, **kw)
            if r.status_code == 200:
                return r
        except requests.RequestException:
            pass
        if wait is None:
            raise RuntimeError(f'{url.rsplit("/", 1)[-1]}: Common Crawl unavailable')
        time.sleep(wait)


def parquet_files(s, coll):
    r = _get(s, f'{DATA}crawl-data/{coll}/cc-index-table.paths.gz') if coll != 'CC-MAIN-2012' else None
    if r is None:
        return []
    return [p for p in gzip.decompress(r.content).decode().split() if '/subset=warc/' in p]


def columnar(coll, cur, files, write):
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET enable_progress_bar=false; SET http_retries=8; "
                "SET http_retry_wait_ms=5000; SET threads=8")
    wanted = set(ccweb.TLDS) | set(ccweb.OPEN_TLDS)
    mimes = ', '.join(f"'{m}'" for m in OFFICE_MIMES)
    found = skipped = 0
    while time.time() < END and cur['pidx'] < len(files):
        u = DATA + files[cur['pidx']]
        try:
            lo, hi = con.execute(f"select min(stats_min_value), max(stats_max_value) from parquet_metadata('{u}') "
                                 "where path_in_schema = 'url_host_tld'").fetchone()
            if lo and hi and not any(lo <= t <= hi for t in wanted):
                skipped += 1
            else:
                # crawls before about 2018 leave content_mime_detected empty: the server's own type and the
                # file ending are used as well
                rows = con.execute(f"select url from read_parquet('{u}') where fetch_status = 200 "
                                   f"and (content_mime_detected in ({mimes}) or content_mime_type in ({mimes}) "
                                   r"or regexp_matches(url_path, '(?i)\.(docx?|xlsx|pptx?)$'))").fetchall()
                for (url,) in rows:
                    hit = ccweb.accept_url(url)
                    if hit:
                        write(hit[0], url, hit[1])
                        found += 1
        except duckdb.Error as err:
            log(f'  {files[cur["pidx"]].rsplit("/", 1)[-1][:20]}: {type(err).__name__}; trying again next run')
            break
        cur['pidx'] += 1
        cur['save']()
    cur['done'] = cur['pidx'] >= len(files)
    return found, f'files {cur["pidx"]}/{len(files)} ({skipped} non-English slices skipped)'


def text(s, coll, cur, write):
    blocks = ccweb._blocks(s, coll, log)
    found, busy = 0, 0
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
                    write(kind, url, ext)
                    found += 1
            cur['save']()
    cur['done'] = cur['pos'] >= len(blocks)
    return found, f'blocks {cur["pos"]}/{len(blocks)}'


def main(shard, cursors, out):
    shard, cursors, out = int(shard), Path(cursors), Path(out)
    cursors.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers['User-Agent'] = ccweb.UA
    # every crawl from MIN_YEAR on (user: "from 2012"), newest and oldest taken in turn so the whole period fills
    every = [c for c in ccweb._collections(s) if c != 'CC-MAIN-2012'  # its old index format holds no file types
             if int((re.search(r'(\d{4})', c) or [0, 0])[1]) >= ccweb.MIN_YEAR]
    colls = list(dict.fromkeys([x for pair in zip(every, reversed(every)) for x in pair][:len(every)]))

    def cur_of(c):
        f = cursors / f'{c}.json'
        c = json.loads(f.read_text()) if f.exists() else {}
        if c.get('done') and c.get('v') != 2:  # finished by the reader that missed pre-2018 file types: read again
            c = {}
        return c
    pending = [c for c in colls if not cur_of(c).get('done')]
    if shard >= len(pending):
        log(f'shard {shard}: no crawl left for this shard ({len(pending)} unfinished)')
        return
    coll = pending[shard]
    cur = cur_of(coll)
    cur.setdefault('pos', 0)
    cur.setdefault('pidx', 0)
    cur['done'] = False
    cur['v'] = 2

    def save():
        (cursors / f'{coll}.json').write_text(json.dumps({k: v for k, v in cur.items() if k != 'save'}))
    cur['save'] = save

    stamp = f'{coll}-{shard}-{int(time.time())}.tsv'
    lists = {}
    for k in KINDS:
        (out / k).mkdir(exist_ok=True)
        lists[k] = (out / k / stamp).open('w', encoding='utf-8')

    def write(kind, url, ext):
        lists[kind].write(f'{kind}\t{url}\t{ext}\n')

    files = parquet_files(s, coll) if os.environ.get('SCAN_MODE', 'columnar') == 'columnar' else []
    if files:
        found, where = columnar(coll, cur, files, write)
    else:
        found, where = text(s, coll, cur, write)
    save()
    for k, fh in lists.items():
        fh.close()
        if (out / k / stamp).stat().st_size == 0:
            (out / k / stamp).unlink()
    done = ' (crawl finished)' if cur['done'] else ''
    log(f'shard {shard}: {coll} {"columnar" if files else "text"} {where}, {found} files found{done}')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write(f'- scanner {shard}: {coll} {where}, {found} files found{done}\n')


if __name__ == '__main__':
    main(*sys.argv[1:4])
