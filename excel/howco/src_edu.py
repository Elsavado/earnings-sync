"""Equity research reports published by universities (.edu): student investment funds, research challenges,
course reports with a rating and a target price.

Discovery is a live search of the web through the Common Crawl index, newest crawl first: every PDF on a .edu site
whose address mentions equity research, stock pitches, coverage initiations, investment funds and the like. The
index files are read straight from data.commoncrawl.org (the .edu part of each crawl's sorted index, ~6,700 blocks,
several at a time): the index API took minutes per filtered page (2 PDFs in 102 min). Each candidate is downloaded from the site itself (robots.txt respected; sites that challenge
automated visitors are skipped), and kept only when its text is a real equity research report: a target price, a
rating or recommendation, and valuation work. Unique by content and by title. People and companies get the
made-up names every source shares; the university is kept.

  Equity Research (.edu)/Folder K (Reports a-b)/<n> - <made-up company> equity research - <year>.pdf
"""
import hashlib
import json
import re
import time
import urllib.robotparser
import zlib
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

UA = 'HowCompaniesWork research collector (education; contact via github.com/Elsavado)'
URL_RE = (r'.*(equity|stock.?pitch|initiat|research.?report|investment.?fund|smif|student.?managed|investment.?club|'
          r'valuation.?report|buy.?side|sell.?side|analyst.?report|stock.?report|company.?report|investment.?report|'
          r'research.?challenge|cfa|portfolio.?management|target.?price|price.?target|pitch.?book|stock.?rec).*')
TARGET = re.compile(r'\b(?:target\s+price|price\s+target|TP\s*[:=]|12[- ]month\s+(?:target|price))', re.I)
RATING = re.compile(r'\b(?:recommendation|rating|strong\s+buy|buy|sell|hold|overweight|underweight|outperform|'
                    r'underperform|accumulate|reduce)\b', re.I)
VALUATION = re.compile(r'\b(?:DCF|discounted\s+cash\s+flow|WACC|P/E|EV/EBITDA|multiples?|valuation|intrinsic\s+value|'
                       r'comparable\s+compan|terminal\s+(?:value|growth))\b', re.I)
BOT = re.compile(rb'captcha|are you a robot|verify you are human|checking your browser|cf-challenge|Just a moment', re.I)
PER_FOLDER = 20


def _collections(s):
    return [c['id'] for c in s.get('https://index.commoncrawl.org/collinfo.json', timeout=60).json()]


CC = 'https://data.commoncrawl.org/cc-index/collections/{}/indexes/'
URL_ANY = re.compile(URL_RE[2:-2], re.I)


def _edu_blocks(s, coll):
    """[file, offset, length] of every index block that holds .edu addresses (the index is sorted by host)."""
    blocks, prev = [], None
    with s.get(CC.format(coll) + 'cluster.idx', stream=True, timeout=300) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith(b'edu,'):
                if not blocks and prev is not None:
                    blocks.append(prev)  # the block before the first .edu entry may hold the first .edu lines
                blocks.append(line)
            elif blocks:
                break
            prev = line
    out = []
    for b in blocks:
        _, f, off, ln, _ = b.decode().split('\t')
        out.append([f, int(off), int(ln)])
    return out


def _block_pdfs(s, coll, block):
    """Candidate report PDFs in one index block ([] when it could not be read)."""
    f, off, ln = block
    rows = None
    for wait in (5, 20, 60, None):
        try:
            r = s.get(CC.format(coll) + f, headers={'Range': f'bytes={off}-{off + ln - 1}'}, timeout=120)
            if r.status_code in (200, 206):
                rows = zlib.decompress(r.content, 16 + zlib.MAX_WBITS).splitlines()
                break
        except (requests.RequestException, zlib.error):
            pass
        if wait is None:
            return []
        time.sleep(wait)
    urls = []
    for row in rows:
        if not row.startswith(b'edu,') or b'"application/pdf"' not in row or b'"status": "200"' not in row:
            continue
        try:
            url = json.loads(row.split(b' ', 2)[2])['url']
        except (ValueError, KeyError, IndexError):
            continue
        if URL_ANY.search(url):
            urls.append(url)
    return urls


class Robots:
    def __init__(self, s):
        self.s, self.cache = s, {}

    def ok(self, url):
        host = urlparse(url).netloc
        if host not in self.cache:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(f'https://{host}/robots.txt', timeout=15)
                rp.parse(r.text.splitlines() if r.ok else [])
            except requests.RequestException:
                rp.parse([])
            self.cache[host] = rp
        return self.cache[host].can_fetch(UA, url)


def is_report(text):
    head = text[:60000]
    return (len(TARGET.findall(head)) >= 1 and len(RATING.findall(head)) >= 3 and len(VALUATION.findall(head)) >= 3
            and len(text) > 4000)


def norm_title(t):
    return re.sub(r'[^a-z0-9]+', ' ', (t or '').lower()).strip()[:120]


def run(ctx, log):
    import pymupdf
    st = ctx.state
    st.setdefault('seen', [])
    st.setdefault('hashes', [])
    st.setdefault('titles', [])
    st.setdefault('n', 0)
    st.setdefault('blocked', [])
    seen, hashes, titles, blocked = set(st['seen']), set(st['hashes']), set(st['titles']), set(st['blocked'])
    A = ctx.make_anon()
    s = requests.Session()
    s.headers['User-Agent'] = UA
    robots = Robots(s)
    colls = _collections(s)
    # One resumable cursor per crawl (index block reached); newest crawl first. Cursors of the index-API version
    # (pages) start again at block 0: addresses already seen are skipped.
    st.pop('cursor', None)
    curs = {c: v for c, v in st.setdefault('crawls', {}).items() if 'block' in v or v.get('done')}
    st['crawls'] = curs
    queue = st.setdefault('queue', [])
    kept = checked = 0

    def fill():
        """Scan index blocks of the newest unfinished crawl until candidates are queued (or the time is up)."""
        while len(queue) < 50 and ctx.left() > 900:
            todo = [c for c in colls if not curs.get(c, {}).get('done')]
            if not todo:
                st['finished'] = True
                return
            cur = curs.setdefault(todo[0], {'coll': todo[0], 'block': 0, 'blocks': None})
            cur.setdefault('block', 0)
            if st.get('list_of') != cur['coll']:
                try:
                    st['block_list'] = _edu_blocks(s, cur['coll'])
                except (requests.RequestException, ValueError) as e:
                    log(f'{cur["coll"]}: index list not readable ({type(e).__name__}); next crawl')
                    cur['done'] = True
                    continue
                st['list_of'], cur['blocks'] = cur['coll'], len(st['block_list'])
                log(f'{cur["coll"]}: {cur["blocks"]} index blocks with .edu addresses')
            blist = st['block_list']
            if cur['block'] >= len(blist):
                cur['done'] = True
                continue
            batch = blist[cur['block']:cur['block'] + 64]
            with ThreadPoolExecutor(8) as pool:
                found = list(pool.map(lambda b: _block_pdfs(s, cur['coll'], b), batch))
            for urls in found:
                queue.extend(u for u in urls if hashlib.sha1(u.encode()).hexdigest()[:16] not in seen)
            cur['block'] += len(batch)
            if cur['block'] % 640 < 64:
                log(f'{cur["coll"]}: block {cur["block"]}/{cur["blocks"]}, {len(queue)} candidates queued')

    def fetch(url):
        """(url, PDF bytes or None, why not)."""
        if not robots.ok(url):
            return url, None, 'robots'
        try:
            resp = s.get(url, timeout=60, stream=True)
            data = b''
            for chunk in resp.iter_content(1 << 16):
                data += chunk
                if len(data) > 40 * 2**20:
                    break
        except requests.RequestException:
            return url, None, 'error'
        if not resp.ok or len(data) > 40 * 2**20:
            return url, None, 'error'
        if data[:5] != b'%PDF-':
            return url, None, 'bot' if BOT.search(data[:6000]) else 'not a pdf'
        return url, data, None

    while ctx.left() > 600:
        fill()
        if not queue:
            break
        batch = []
        while queue and len(batch) < 16:
            url = queue.pop(0)
            k = hashlib.sha1(url.encode()).hexdigest()[:16]
            if k in seen or urlparse(url).netloc.lower() in blocked:
                continue
            seen.add(k)
            batch.append(url)
        with ThreadPoolExecutor(8) as pool:  # downloads in parallel; checking and uploading stay one at a time
            got = list(pool.map(fetch, batch))
        for url, data, why in got:
            checked += 1
            if why == 'bot':
                blocked.add(urlparse(url).netloc.lower())
            if data is None or ctx.left() < 300:
                continue
            h = hashlib.sha1(data).hexdigest()
            if h in hashes:
                continue
            hashes.add(h)
            src = ctx.work / 'in.pdf'
            src.write_bytes(data)
            try:
                with pymupdf.open(src) as d:
                    if d.page_count > 80 or d.needs_pass:
                        continue
                    text = ''.join(p.get_text() for p in d)
                    title = (d.metadata or {}).get('title') or ''
            except Exception:  # noqa: BLE001
                continue
            if not is_report(text):
                continue
            first = next((ln.strip() for ln in text.splitlines() if len(ln.strip()) > 12), '')
            t = norm_title(title if len(title) > 12 else first)
            if t and t in titles:
                continue
            titles.add(t)
            A.start()
            dst = ctx.work / 'out.pdf'
            try:
                ok, out_text = A.file(str(src), str(dst), 'pdf')
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                continue
            leaks = A.leaks(out_text)
            subject = _subject(A, out_text)
            year = re.search(r'\b(20[0-2]\d|19[89]\d)\b', text[:3000])
            st['n'] += 1
            n = st['n']
            k0 = (n - 1) // PER_FOLDER + 1
            folder = f'{ctx.folder}/Folder {k0} (Reports {PER_FOLDER * (k0 - 1) + 1}-{PER_FOLDER * k0})'
            name = f'{n} - {subject} equity research{" - " + year.group(1) if year else ""}.pdf'
            name = re.sub(r'[\\/:*?"<>|]+', ' ', name)
            ctx.drive.upload(str(dst), folder, name, f'edu:{h[:20]}')
            kept += 1
            ctx.sample(dst, name, leaks)
        st['seen'], st['hashes'], st['titles'], st['blocked'] = sorted(seen), sorted(hashes), sorted(titles), sorted(blocked)
        ctx.save()
        if ctx.dry and kept >= 12:
            break
    st['seen'], st['hashes'], st['titles'], st['blocked'] = sorted(seen), sorted(hashes), sorted(titles), sorted(blocked)
    log(f'this run: {checked} PDFs checked, {kept} reports kept, {len(queue)} queued; crawls: '
        + ', '.join(f'{c["coll"]} {c.get("block", 0)}/{c.get("blocks")}' for c in curs.values() if c.get('blocks')))


def _subject(A, text):
    """The (made-up) company the report covers: the most named company in its first pages, else 'Company'."""
    from collections import Counter
    c = Counter()
    head = text[:8000]
    for name in set(A.co.map.values()):
        if name in head:
            c[name] = head.count(name)
    return c.most_common(1)[0][0] if c else 'Company'
