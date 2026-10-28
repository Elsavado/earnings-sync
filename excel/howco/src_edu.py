"""Equity research reports published by universities (.edu): student investment funds, research challenges,
course reports with a rating and a target price.

Discovery is a live search of the web through the Common Crawl index (index.commoncrawl.org, newest crawl first):
every PDF on a .edu site whose address mentions equity research, stock pitches, coverage initiations, investment
funds and the like. Each candidate is downloaded from the site itself (robots.txt respected; sites that challenge
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
    cur = st.setdefault('cursor', {'coll': colls[0], 'page': 0, 'pages': None})
    kept = checked = 0
    while ctx.left() > 600:
        api = f'https://index.commoncrawl.org/{cur["coll"]}-index'
        if cur['pages'] is None:
            try:
                cur['pages'] = s.get(api, params={'url': '*.edu', 'showNumPages': 'true'}, timeout=120).json()['pages']
            except (requests.RequestException, ValueError, KeyError):
                log('index unavailable; trying again next run')
                break
        if cur['page'] >= cur['pages']:
            older = [c for c in colls if c < cur['coll']]
            if not older:
                st['finished'] = True
                break
            cur.update(coll=older[0], page=0, pages=None)
            continue
        rows = None
        for attempt in range(4):
            try:
                r = s.get(api, params={'url': '*.edu', 'output': 'json', 'page': cur['page'],
                                       'filter': ['mime:application/pdf', 'status:200', f'~url:{URL_RE}']}, timeout=180)
                if r.status_code == 404:
                    rows = []
                    break
                if r.ok:
                    rows = [json.loads(x) for x in r.text.splitlines() if x.strip()]
                    break
            except (requests.RequestException, ValueError):
                pass
            time.sleep(15 * (attempt + 1))
        if rows is None:
            log(f'{cur["coll"]} page {cur["page"]}: index did not answer; trying again next run')
            break
        for row in rows:
            url = row['url']
            host = urlparse(url).netloc.lower()
            k = hashlib.sha1(url.encode()).hexdigest()[:16]
            if k in seen or host in blocked or ctx.left() < 300:
                continue
            seen.add(k)
            checked += 1
            if not robots.ok(url):
                continue
            try:
                resp = s.get(url, timeout=60, stream=True)
                data = b''
                for chunk in resp.iter_content(1 << 16):
                    data += chunk
                    if len(data) > 40 * 2**20:
                        break
            except requests.RequestException:
                continue
            if not resp.ok or len(data) > 40 * 2**20:
                continue
            if data[:5] != b'%PDF-':
                if BOT.search(data[:6000]):
                    blocked.add(host)
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
            if ctx.dry and kept >= 12:
                break
        if ctx.dry and kept >= 12:
            break
        cur['page'] += 1
        st['seen'], st['hashes'], st['titles'], st['blocked'] = sorted(seen), sorted(hashes), sorted(titles), sorted(blocked)
        if cur['page'] % 10 == 0:
            ctx.save()
            log(f'{cur["coll"]} page {cur["page"]}/{cur["pages"]}: {checked} PDFs checked, {kept} reports kept')
    st['seen'], st['hashes'], st['titles'], st['blocked'] = sorted(seen), sorted(hashes), sorted(titles), sorted(blocked)
    log(f'this run: {checked} PDFs checked, {kept} reports kept; index at {cur["coll"]} page {cur["page"]}')


def _subject(A, text):
    """The (made-up) company the report covers: the most named company in its first pages, else 'Company'."""
    from collections import Counter
    c = Counter()
    head = text[:8000]
    for name in set(A.co.map.values()):
        if name in head:
            c[name] = head.count(name)
    return c.most_common(1)[0][0] if c else 'Company'
