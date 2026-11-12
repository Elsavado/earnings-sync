"""Shintiru office collector (user, 2026-11-12): Google Slides, Docs and Sheets "massively" for the shintiru library
drive -- finance, learning and operations-team material, mostly English.

Source: the Common Crawl index, read straight from data.commoncrawl.org (as howco/src_edu.py does). Every capture
of a PowerPoint, Word or Excel file on a mostly-English part of the web (.edu, .gov, .ac.uk, .ca, .au, .org,
.com ...) whose site allows robots is a candidate; one cursor per type walks the index block by block, newest crawl
first, and moves to the previous crawl when it reaches the end. The Workspace office collector (Research
Collections drive) never reads Common Crawl, so the two drives do not share sources (no-cross-drive-duplicates).

Each file is kept only when its text is about finance / accounting, learning (lectures, course notes, exercises)
or operations (rosters, inventories, schedules, trackers, KPIs): subject(). At most PER_HOST files per site and type,
so no single site fills the library.
"""
import hashlib
import json
import re
import time
import urllib.robotparser
import zlib
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlparse

import requests

from . import topic
from .sources import _add as _queue, late

UA = 'Mozilla/5.0 (compatible; library-collector/1.0; open educational materials)'
CC = 'https://data.commoncrawl.org/cc-index/collections/{}/indexes/'
PER_HOST = 25
BLOCKS_PER_CALL = 64  # index blocks read per discovery call (8 at a time)
QUEUE_MAX = 80

MIMES = {
    'slides': {b'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
               b'application/vnd.ms-powerpoint': 'ppt'},
    'gdocs': {b'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
              b'application/msword': 'doc'},
    'gsheets': {b'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx'},
}
EXT_OK = {'slides': ('.pptx', '.ppt'), 'gdocs': ('.docx', '.doc'), 'gsheets': ('.xlsx',)}

# Mostly-English parts of the web, by the first label of the host in SURT order ('edu,', 'uk,ac,' ...).
TLDS = ('edu', 'gov', 'mil', 'us', 'uk', 'ca', 'au', 'nz', 'ie', 'za', 'ke', 'ng', 'gh', 'ug', 'tz', 'zm', 'zw', 'rw',
        'bw', 'na', 'mw', 'in', 'sg', 'ph', 'pk', 'lk', 'my', 'jm', 'tt', 'org', 'net', 'info', 'com', 'io', 'co')
OPEN_TLDS = ('edu', 'gov', 'mil', 'ac', 'sch', 'k12')  # educational / public hosts: every file is a candidate
# Elsewhere the address itself must hint at the subject, so a run does not download every brochure on .com.
URL_HINT = re.compile(
    r'financ|account|budget|audit|tax|invest|econom|bank|cost|fiscal|treasur|ledger|payroll|revenue|forecast|valuat|'
    r'lectur|lesson|course|module|unit[-_ ]?\d|week[-_ ]?\d|chapter|chap\d|syllab|tutorial|class|training|workshop|'
    r'curricul|teach|learn|student|exam|quiz|worksheet|exercise|assignment|homework|notes|slides|lab[-_ ]?\d|'
    r'operat|\bops\b|inventor|roster|rota|schedul|shift|timesheet|attendance|kpi|dashboard|tracker|logistic|supply|'
    r'procure|warehouse|maintenan|checklist|template|planner|capacity|headcount|staffing|project[-_ ]?plan|workplan',
    re.I)

LEARNING = re.compile(
    r'\b(?:lectures?|lessons?|learning (?:objectives|outcomes)|course (?:outline|code|objectives|overview)|syllabus|'
    r'module \d+|unit \d+|week \d+|chapter \d+|tutorials?|exercises?|assignments?|homework|quiz(?:zes)?|exams?|'
    r'examination|students?|instructors?|teachers?|curriculum|classroom|worksheets?|revision|study guide|'
    r'lab \d+|practicals?|textbook|key (?:terms|concepts)|review questions|case study|discussion questions|'
    r'objectives|summary|definitions?)\b', re.I)
OPERATIONS = re.compile(
    r'\b(?:operations?|inventory|stock (?:level|count|take)|sku|warehouse|suppliers?|purchase orders?|shipments?|'
    r'deliver(?:y|ies)|logistics|procurement|rosters?|rota|shifts?|schedul\w+|timesheets?|attendance|headcount|'
    r'staffing|capacity|utili[sz]ation|kpis?|sla|tickets?|incidents?|maintenance|work orders?|checklists?|'
    r'due dates?|owners?|status|action items?|tracker|production|throughput|downtime|lead time|backlog|escalation|'
    r'on-call|assigned to|priority|milestones?|deadlines?|resources?|quantity|qty|reorder|asset (?:register|tag)|'
    r'job (?:card|sheet)|dispatch|fleet|safety|compliance|standard operating procedure|sop)\b', re.I)


def subject(text):
    """'Finance', 'Operations' or 'Learning' when the text is about one of them (finance first), else ''."""
    text = (text or '')[:60000]
    if len(topic.terms(text)) >= 3:
        return 'Finance'
    ops = {m.group(0).lower() for m in OPERATIONS.finditer(text)}
    learn = {m.group(0).lower() for m in LEARNING.finditer(text)}
    if len(ops) >= 4 and len(ops) >= len(learn):
        return 'Operations'
    if len(learn) >= 3:
        return 'Learning'
    if len(ops) >= 4:
        return 'Operations'
    return ''


def title_from(url):
    """A readable title from the file name ('week-3_cost-accounting.pptx' -> 'Week 3 Cost Accounting'); '' when
    the name is only codes or numbers."""
    name = unquote(urlparse(url).path.rsplit('/', 1)[-1])
    name = re.sub(r'\.\w{2,5}$', '', name)
    name = re.sub(r'[_\-+.]+', ' ', name)
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    name = re.sub(r'\s+', ' ', name).strip()
    words = re.findall(r'[A-Za-z]{3,}', name)
    if len(words) < 2 or re.fullmatch(r'[0-9a-f]{12,}', name.replace(' ', ''), re.I):
        return ''
    return name[:80].title() if name.islower() or name.isupper() else name[:80]


class Robots:
    def __init__(self, s):
        self.s, self.cache = s, {}

    def ok(self, url):
        host = urlparse(url).netloc
        if host not in self.cache:
            if len(self.cache) > 20000:
                self.cache.clear()
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(f'https://{host}/robots.txt', timeout=10, headers={'User-Agent': UA})
                rp.parse(r.text.splitlines() if r.ok and len(r.content) < 500000 else [])
            except requests.RequestException:
                rp.parse([])
            self.cache[host] = rp
        return self.cache[host].can_fetch(UA, url)


_ROBOTS = None
_INDEX = {}  # collection -> [[file, offset, length], ...] of the chosen TLD blocks


def _collections(s):
    return [c['id'] for c in s.get('https://index.commoncrawl.org/collinfo.json', timeout=60).json()]


def _blocks(s, coll, log):
    """Index blocks whose hosts are in TLDS (the index is sorted by reversed host, so each TLD is one run)."""
    if coll in _INDEX:
        return _INDEX[coll]
    out, prev, inside = [], None, False
    want = tuple(t.encode() + b',' for t in TLDS)
    t0 = time.time()
    with s.get(CC.format(coll) + 'cluster.idx', stream=True, timeout=600) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            hit = line.startswith(want)
            if hit and not inside and prev is not None:
                out.append(prev)  # the block before a run may hold its first lines
            if hit:
                out.append(line)
            inside, prev = hit, line
    blocks = []
    for b in out:
        parts = b.decode('utf-8', 'replace').split('\t')
        if len(parts) >= 4:
            blocks.append([parts[1], int(parts[2]), int(parts[3])])
    _INDEX.clear()
    _INDEX[coll] = blocks
    log(f'  common crawl {coll}: {len(blocks)} index blocks on English-leaning hosts ({time.time() - t0:.0f}s)')
    return blocks


def _read_block(s, coll, block, kind):
    f, off, ln = block
    rows = None
    for wait in (5, 20, None):
        try:
            r = s.get(CC.format(coll) + f, headers={'Range': f'bytes={off}-{off + ln - 1}'}, timeout=120)
            if r.status_code in (200, 206):
                rows = zlib.decompress(r.content, 16 + zlib.MAX_WBITS).splitlines()
                break
        except (requests.RequestException, zlib.error):
            pass
        if wait is None:
            return None
        time.sleep(wait)
    mimes = MIMES[kind]
    out = []
    for row in rows:
        if b'"status": "200"' not in row or not any(m in row for m in mimes):
            continue
        try:
            surt, ts, js = row.split(b' ', 2)
            d = json.loads(js)
        except (ValueError, IndexError):
            continue
        mime = (d.get('mime-detected') or d.get('mime') or '').encode()
        if mime not in mimes:
            continue
        url = d.get('url', '')
        if not url.lower().split('?')[0].endswith(EXT_OK[kind]):
            continue
        tld = surt.split(b')')[0].split(b',')
        open_host = tld[0].decode() in OPEN_TLDS or (len(tld) > 1 and tld[1].decode() in OPEN_TLDS)
        if not open_host and not URL_HINT.search(url):
            continue
        out.append((url, mimes[mime], ts.decode()))
    return out


def cc_files(state, kind, s, log):
    """Walks the Common Crawl index for this type's files and queues those not seen before."""
    global _ROBOTS
    if kind not in MIMES:
        return 0
    if _ROBOTS is None:
        _ROBOTS = Robots(requests.Session())
    cur = state['cursors'].setdefault(f'cc:{kind}', {})
    hosts = state.setdefault('cc_hosts', {})
    if not cur.get('colls'):
        cur['colls'] = _collections(s)[:12]  # newest first; older crawls repeat most addresses
        cur['ci'], cur['pos'] = 0, 0
    added = 0
    while not late() and len(state['queue'].get(kind, [])) < QUEUE_MAX:
        if cur['ci'] >= len(cur['colls']):
            cur.clear()  # every crawl read: start again from the newest list next time
            break
        coll = cur['colls'][cur['ci']]
        blocks = _blocks(s, coll, log)
        if cur['pos'] >= len(blocks):
            cur['ci'] += 1
            cur['pos'] = 0
            continue
        batch = blocks[cur['pos']:cur['pos'] + BLOCKS_PER_CALL]
        with ThreadPoolExecutor(8) as ex:
            found = list(ex.map(lambda b: _read_block(s, coll, b, kind), batch))
        if any(f is None for f in found[:4]) and all(f is None for f in found):
            log(f'  common crawl {coll}: index not reachable; trying later')
            break
        cur['pos'] += len(batch)
        for urls in found:
            for url, ext, _ in urls or []:
                host = urlparse(url).netloc.lower()
                hk = f'{kind}:{host}'
                if hosts.get(hk, 0) >= PER_HOST:
                    continue
                key = 'cc:' + hashlib.sha1(url.split('#')[0].encode()).hexdigest()
                if key in state['seen'] or key in state['queued']:
                    continue
                try:
                    if not _ROBOTS.ok(url):
                        state['seen'][key] = 'rej:robots.txt'
                        continue
                except Exception:  # noqa: BLE001
                    continue
                cand = {'key': key, 'url': url, 'ext': ext, 'orgs': [], 'source': 'cc', 'topic': '',
                        'title': title_from(url), 'rules': 3}
                if _queue(state, kind, cand):
                    hosts[hk] = hosts.get(hk, 0) + 1
                    added += 1
    if added:
        log(f'  {kind}: common crawl crawl {cur.get("ci", 0) + 1}/{len(cur.get("colls") or [])}, '
            f'block {cur.get("pos", 0)}: +{added}')
    return added
