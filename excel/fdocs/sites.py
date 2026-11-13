"""Site explorer and Wayback Machine source for the shintiru office collector (user, 2026-11-12: "search the
internet at large", "from 2012").

A site that gave one good file (a course page, a council's document library, a consultancy's resources page) usually
holds many more that Common Crawl never saw. For every such site (state 'good_hosts', filled by the collector):
  site  read robots.txt and the site's sitemaps, then walk its pages (same site, robots.txt obeyed, at most one page
        a second, up to PAGES pages) and list every Word / Excel / PowerPoint link;
  wb    ask the Internet Archive's Wayback Machine for every Office file it saved from the site since 2012 and list
        the saved copies (web.archive.org/web/<time>id_/<address>), including files gone from the live site.
The lists go to OUT_DIR/<type>/site-*.tsv and wb-*.tsv for the collector jobs (ccweb inbox), which check robots.txt
of the original site, the topic, the language and the date as for every other file.

  python -m fdocs.sites SHARD SHARDS STATE_DIR CURSORS_DIR OUT_DIR

Hosts are split between shards by hash; CURSORS_DIR/sites-<shard>.json records when each host was explored, and a
host is explored again after REVISIT_DAYS.
"""
import gzip
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import requests

from . import ccweb

END = time.time() + float(os.environ.get('RUN_MINUTES', '45')) * 60
PAGES = int(os.environ.get('SITE_PAGES', '400'))
HOST_SECONDS = 900
REVISIT_DAYS = 60
THREADS = 8
SKIP = re.compile(r'\.(?:pdf|zip|rar|7z|gz|tgz|jpe?g|png|gif|svg|webp|ico|bmp|tiff?|mp[34]|m4a|wav|avi|mov|wmv|webm|'
                  r'exe|msi|dmg|iso|css|js|json|xml|rss|woff2?|ttf|eot|xls|xlsm|csv|odt|ods|odp|txt)$', re.I)
HREF = re.compile(r'''(?:href|src)\s*=\s*["']([^"'#<>\s]+)''', re.I)
CDX = 'https://web.archive.org/cdx/search/cdx'
WB_MIMES = 'mimetype:application/(msword|vnd\\.ms-powerpoint|vnd\\.openxmlformats-officedocument\\..*)'


def log(msg):
    print(time.strftime('[%H:%M:%S] ') + msg, flush=True)


def office_kind(url):
    """(kind, ext) for an Office link on a site already known to be good (no address hint needed)."""
    ext = os.path.splitext(urlparse(url).path.lower())[1]
    kind = ccweb.EXT_KIND.get(ext)
    return (kind, ext.lstrip('.')) if kind else None


class Lists:
    def __init__(self, out, prefix, shard):
        self.lock, self.fh, self.n = threading.Lock(), {}, 0
        stamp = f'{prefix}-{shard}-{int(time.time())}.tsv'
        for k in ('gdocs', 'gsheets', 'slides'):
            (out / k).mkdir(parents=True, exist_ok=True)
            self.fh[k] = (out / k / stamp).open('w', encoding='utf-8')
        self.paths = [out / k / stamp for k in self.fh]

    def add(self, kind, url, ext, check=None):
        with self.lock:
            self.fh[kind].write(f'{kind}\t{url}\t{ext}' + (f'\t{check}' if check else '') + '\n')
            self.n += 1

    def close(self):
        for fh in self.fh.values():
            fh.close()
        for p in self.paths:
            if p.stat().st_size == 0:
                p.unlink()


def _robots(s, base):
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = s.get(base + '/robots.txt', timeout=15)
        rp.parse(r.text.splitlines() if r.ok and len(r.content) < 500000 else [])
    except requests.RequestException:
        rp.parse([])
    return rp


def _sitemap_urls(s, rp, base, limit=20000):
    """Addresses listed in the site's sitemaps (sitemap indexes followed, gzip read)."""
    todo = list(rp.site_maps() or []) or [base + '/sitemap.xml', base + '/sitemap_index.xml']
    seen, out = set(), []
    while todo and len(seen) < 60 and len(out) < limit:
        sm = todo.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            r = s.get(sm, timeout=30)
            if not r.ok or len(r.content) > 50 * 2**20:
                continue
            body = gzip.decompress(r.content) if r.content[:2] == b'\x1f\x8b' else r.content
        except (requests.RequestException, OSError, EOFError):
            continue
        locs = [unescape(x.decode('utf-8', 'replace').strip()) for x in re.findall(rb'<loc>\s*([^<]+?)\s*</loc>', body)]
        if b'<sitemapindex' in body[:2000]:
            todo += locs
        else:
            out += locs
    return out


def explore(s, host, lists):
    """Sitemaps plus a polite walk of the site's pages; every Office link goes to the lists."""
    base = f'https://{host}'
    rp = _robots(s, base)
    delay = max(1.0, float(rp.crawl_delay(ccweb.UA) or 0))
    t0, files, pages = time.time(), set(), 0
    queue, seen = [base + '/'], {base + '/'}

    def note(url):
        hit = office_kind(url)
        if hit and url not in files and rp.can_fetch(ccweb.UA, url):
            files.add(url)
            lists.add(hit[0], url, hit[1])
        return bool(hit)

    for u in _sitemap_urls(s, rp, base):
        if urlparse(u).netloc.lower() != host:
            continue
        if not note(u) and not SKIP.search(urlparse(u).path) and u not in seen and len(seen) < PAGES * 4:
            seen.add(u)
            queue.append(u)
    while queue and pages < PAGES and time.time() - t0 < HOST_SECONDS and time.time() < END:
        url = queue.pop(0)
        if not rp.can_fetch(ccweb.UA, url):
            continue
        try:
            r = s.get(url, timeout=20, stream=True)
            ctype = r.headers.get('content-type', '')
            if not r.ok or 'html' not in ctype:
                r.close()
                continue
            body = r.raw.read(3 * 2**20, decode_content=True).decode(r.encoding or 'utf-8', 'replace')
            final = r.url
            r.close()
        except (requests.RequestException, OSError, ValueError):
            continue
        pages += 1
        for href in HREF.findall(body):
            try:  # a malformed link (e.g. "http://[bad") must not stop the crawl
                u = urldefrag(urljoin(final, unescape(href)))[0]
                p = urlparse(u)
            except ValueError:
                continue
            if p.scheme not in ('http', 'https') or p.netloc.lower().removeprefix('www.') != host.removeprefix('www.'):
                continue
            if note(u) or SKIP.search(p.path) or u in seen or len(seen) > PAGES * 6:
                continue
            seen.add(u)
            queue.append(u)
        time.sleep(delay)
    return len(files), pages


def wayback(s, host, lists):
    """Every Office file the Wayback Machine saved from the site since MIN_YEAR (latest copy of each address)."""
    params = [('url', f'{host}/*'), ('output', 'json'), ('fl', 'original,timestamp'), ('filter', 'statuscode:200'),
              ('filter', WB_MIMES), ('from', str(ccweb.MIN_YEAR)), ('collapse', 'urlkey'), ('limit', '20000')]
    rows = None
    for wait in (5, 20, 60, None):
        try:
            r = s.get(CDX, params=params, timeout=180)
            if r.status_code == 200:
                rows = r.json() if r.text.strip() else []
                break
        except (requests.RequestException, ValueError):
            pass
        if wait is None:
            return -1
        time.sleep(wait)
    n = 0
    for row in rows[1:]:
        original, ts = row[0], row[1]
        hit = office_kind(original)
        if hit:
            lists.add(hit[0], f'https://web.archive.org/web/{ts}id_/{original}', hit[1], original)
            n += 1
    time.sleep(4)  # the Wayback Machine asks for a gentle pace
    return n


def main(shard, shards, state_dir, cursors, out):
    shard, shards, out = int(shard), int(shards), Path(out)
    good = {}
    for f in Path(state_dir).glob('state*.json.gz'):
        try:
            for h, n in (json.loads(gzip.decompress(f.read_bytes())).get('good_hosts') or {}).items():
                good[h] = good.get(h, 0) + n
        except (OSError, ValueError, EOFError):
            continue
    mine = sorted((h for h in good if int(hashlib.sha1(h.encode()).hexdigest(), 16) % shards == shard),
                  key=lambda h: -good[h])
    cfile = Path(cursors) / f'sites-{shard}.json'
    cfile.parent.mkdir(parents=True, exist_ok=True)
    done = json.loads(cfile.read_text()) if cfile.exists() else {}
    now = time.time()
    todo = [h for h in mine if now - done.get(h, {}).get('at', 0) > REVISIT_DAYS * 86400]
    log(f'shard {shard}: {len(good)} good sites in all, {len(mine)} in this shard, {len(todo)} to explore')
    s_lists, w_lists = Lists(out, 'site', shard), Lists(out, 'wb', shard)
    lock = threading.Lock()
    stats = {'sites': 0, 'pages': 0, 'site files': 0, 'wayback files': 0}

    def one(host):
        if time.time() > END - 120:
            return
        s = requests.Session()
        s.headers['User-Agent'] = ccweb.UA
        w = wayback(s, host, w_lists)
        f, p = explore(s, host, s_lists)
        with lock:
            stats['sites'] += 1
            stats['pages'] += p
            stats['site files'] += f
            stats['wayback files'] += max(0, w)
            done[host] = {'at': time.time(), 'site': f, 'wb': w}
            cfile.write_text(json.dumps(done))

    # the Wayback Machine is asked one site at a time across the job; site walks run in parallel
    with ThreadPoolExecutor(THREADS) as ex:
        list(ex.map(one, todo))
    s_lists.close()
    w_lists.close()
    cfile.write_text(json.dumps(done))
    log(f'shard {shard}: {stats}')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as fh:
            fh.write(f'- explorer {shard}: {stats}\n')


if __name__ == '__main__':
    main(*sys.argv[1:6])
