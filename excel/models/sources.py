"""Where spreadsheets come from (free and openly published only).

Each source appends candidates {key, url, name, source} to state['queue'] and keeps its own
cursor in state, so every run continues where the last stopped.
- damodaran: Aswath Damodaran's public valuation spreadsheets (NYU Stern)
- github:    public repositories found by finance-model searches and topics; blob SHA dedupes forks
- zenodo / figshare: open research repositories
- websites:  company websites (all industries): robots.txt-permitted sitemap entries and
             investor-relations pages that link to Excel files
"""
import gzip
import os
import re
import time
import urllib.parse
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

EXCEL_URL = re.compile(r'\.(xlsx|xlsm|xls|xlsb)(\?[^"\'\s<>]*)?$', re.I)
HREF = re.compile(r'href\s*=\s*["\']([^"\'#]+)["\']', re.I)


def _ua():
    contact = os.environ.get('SEC_USER_AGENT', '')
    return f'Mozilla/5.0 (compatible; ExcelModels/1.0; research{"; " + contact if contact else ""})'


def session():
    s = requests.Session()
    s.headers['User-Agent'] = _ua()
    return s


def _add(state, key, url, name, source):
    if key in state['seen'] or key in state['queued']:
        return False
    state['queue'].append({'key': key, 'url': url, 'name': name, 'source': source})
    state['queued'][key] = 1
    return True


# --- Damodaran -----------------------------------------------------------------------
DAMODARAN_PAGES = ['https://pages.stern.nyu.edu/~adamodar/New_Home_Page/spreadsh.htm',
                   'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/valquestions.htm',
                   'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/cfspreadsheets.htm']


def damodaran(state, s, log):
    st = state.setdefault('damodaran', {})
    if st.get('done_at', 0) > time.time() - 30 * 86400:
        return 0
    n = 0
    for page in DAMODARAN_PAGES:
        try:
            html = s.get(page, timeout=60).text
        except requests.RequestException:
            continue
        for href in HREF.findall(html):
            url = urllib.parse.urljoin(page, href)
            if EXCEL_URL.search(urllib.parse.urlparse(url).path) and '/datasets/' not in url:
                n += _add(state, f'url:{url}', url, urllib.parse.unquote(url.rsplit('/', 1)[-1]), 'damodaran')
    st['done_at'] = time.time()
    log(f'damodaran: {n} new candidates')
    return n


# --- GitHub --------------------------------------------------------------------------
GH_QUERIES = ['dcf model', 'discounted cash flow', 'dcf valuation excel', 'lbo model', 'leveraged buyout', 'financial model excel',
              'three statement model', '3 statement model', 'financial modeling', 'financial modelling', 'valuation model',
              'merger model', 'm&a model', 'accretion dilution', 'comparable companies analysis', 'equity research model',
              'investment banking excel', 'fp&a', 'budget model excel', 'operating model', 'real estate pro forma',
              'real estate financial model', 'project finance model', 'startup financial model', 'saas financial model',
              'excel financial projections', 'corporate finance excel', 'wall street prep', 'breaking into wall street',
              'pitchbook excel', 'cash flow model excel', 'npv irr excel', 'capital budgeting excel', 'rnpv biotech',
              'oil gas economics excel', 'mining financial model', 'solar financial model', 'hotel financial model',
              'restaurant financial model', 'bank valuation model', 'insurance financial model', 'reit model',
              'xlsx financial model', 'excel valuation', 'sum of the parts valuation', 'dividend discount model excel',
              'topic:financial-modeling', 'topic:financial-model', 'topic:dcf', 'topic:dcf-model', 'topic:lbo',
              'topic:valuation', 'topic:excel-model', 'topic:financial-analysis', 'topic:corporate-finance',
              'topic:investment-banking', 'topic:private-equity', 'topic:real-estate-finance', 'topic:fpa']


def github(state, s, log, max_calls=700):
    st = state.setdefault('github', {'qi': 0, 'page': 1, 'repos': [], 'done_repos': {}})
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    h = {'Accept': 'application/vnd.github+json'}
    if token:
        h['Authorization'] = f'Bearer {token}'
    calls, n = 0, 0
    # 1. Discover repositories (search API: 30 requests/minute).
    while st['qi'] < len(GH_QUERIES) and len(st['repos']) < 400 and calls < max_calls // 3:
        q = GH_QUERIES[st['qi']]
        r = s.get('https://api.github.com/search/repositories', headers=h,
                  params={'q': q, 'per_page': 100, 'page': st['page'], 'sort': 'stars'}, timeout=60)
        calls += 1
        if r.status_code in (403, 429):
            break
        items = r.json().get('items', []) if r.ok else []
        for it in items:
            full = it['full_name']
            if full not in st['done_repos'] and full not in st['repos'] and it.get('size', 0) < 2_000_000:
                st['repos'].append(full)
        if len(items) < 100 or st['page'] >= 10:
            st['qi'] += 1
            st['page'] = 1
        else:
            st['page'] += 1
        time.sleep(2.1)
    # 2. List each repository's files and queue its spreadsheets.
    while st['repos'] and calls < max_calls:
        full = st['repos'].pop(0)
        st['done_repos'][full] = 1
        r = s.get(f'https://api.github.com/repos/{full}', headers=h, timeout=60)
        calls += 1
        if not r.ok:
            continue
        branch = r.json().get('default_branch', 'main')
        r = s.get(f'https://api.github.com/repos/{full}/git/trees/{urllib.parse.quote(branch)}', headers=h,
                  params={'recursive': '1'}, timeout=60)
        calls += 1
        if r.status_code in (403, 429):
            st['repos'].insert(0, full)
            del st['done_repos'][full]
            break
        if not r.ok:
            continue
        for node in r.json().get('tree', []):
            if node.get('type') == 'blob' and EXCEL_URL.search(node['path']) and node.get('size', 0) <= 40_000_000:
                raw = f'https://raw.githubusercontent.com/{full}/{urllib.parse.quote(branch)}/{urllib.parse.quote(node["path"])}'
                n += _add(state, f'blob:{node["sha"]}', raw, node['path'].rsplit('/', 1)[-1], 'github')
    log(f'github: {n} new candidates ({calls} API calls, {len(st["repos"])} repositories waiting, '
        f'query {st["qi"]}/{len(GH_QUERIES)})')
    return n


# --- Zenodo and Figshare -------------------------------------------------------------
OPEN_QUERIES = ['"financial model"', 'DCF valuation', '"discounted cash flow"', '"leveraged buyout"', '"techno-economic" excel',
                '"cost model" spreadsheet', '"business model" excel financial', '"project finance"', '"levelized cost" excel',
                '"net present value" spreadsheet', '"financial projections"', 'budget model spreadsheet', 'valuation spreadsheet']


def zenodo(state, s, log, max_pages=20):
    st = state.setdefault('zenodo', {'qi': 0, 'page': 1})
    n = 0
    for _ in range(max_pages):
        if st['qi'] >= len(OPEN_QUERIES):
            break
        q = OPEN_QUERIES[st['qi']]
        try:
            r = s.get('https://zenodo.org/api/records', params={'q': q, 'size': 100, 'page': st['page']}, timeout=60)
            hits = r.json().get('hits', {}).get('hits', []) if r.ok else []
        except (requests.RequestException, ValueError):
            hits = []
        for rec in hits:
            for f in rec.get('files', []) or []:
                key = f.get('key', '')
                if EXCEL_URL.search(key) and f.get('size', 0) <= 40_000_000:
                    url = f.get('links', {}).get('self') or f'https://zenodo.org/records/{rec["id"]}/files/{urllib.parse.quote(key)}'
                    n += _add(state, f'zenodo:{rec["id"]}:{key}', url, key.rsplit('/', 1)[-1], 'zenodo')
        if len(hits) < 100:
            st['qi'] += 1
            st['page'] = 1
        else:
            st['page'] += 1
        time.sleep(1)
    log(f'zenodo: {n} new candidates')
    return n


def figshare(state, s, log, max_pages=10):
    st = state.setdefault('figshare', {'qi': 0, 'page': 1})
    n = 0
    for _ in range(max_pages):
        if st['qi'] >= len(OPEN_QUERIES):
            break
        q = OPEN_QUERIES[st['qi']].replace('"', '')
        try:
            r = s.post('https://api.figshare.com/v2/articles/search', json={'search_for': q, 'page_size': 100, 'page': st['page']}, timeout=60)
            arts = r.json() if r.ok else []
        except (requests.RequestException, ValueError):
            arts = []
        for a in arts:
            try:
                files = s.get(f'https://api.figshare.com/v2/articles/{a["id"]}/files', timeout=60).json()
            except (requests.RequestException, ValueError):
                continue
            for f in files if isinstance(files, list) else []:
                if EXCEL_URL.search(f.get('name', '')) and f.get('size', 0) <= 40_000_000:
                    n += _add(state, f'figshare:{f["id"]}', f['download_url'], f['name'], 'figshare')
            time.sleep(0.3)
        if len(arts) < 100:
            st['qi'] += 1
            st['page'] = 1
        else:
            st['page'] += 1
    log(f'figshare: {n} new candidates')
    return n


# --- Company websites ----------------------------------------------------------------
IR_PATHS = ['/investors', '/investor-relations', '/investor', '/ir', '/financials', '/investors/financials',
            '/investors/financial-information', '/investor-relations/financial-information']
WIKIDATA = '''SELECT DISTINCT ?cik ?w WHERE { ?c wdt:P5531 ?cik ; wdt:P856 ?w . }'''


def company_domains(s, companies_json=None):
    """Website domains for SEC-registered companies (Wikidata official websites + companies.json)."""
    domains = set()
    try:
        r = s.get('https://query.wikidata.org/sparql', params={'query': WIKIDATA, 'format': 'json'},
                  headers={'Accept': 'application/sparql-results+json'}, timeout=180)
        for b in r.json()['results']['bindings']:
            host = urllib.parse.urlparse(b['w']['value']).hostname
            if host:
                domains.add(host.lower().removeprefix('www.'))
    except Exception:  # noqa: BLE001
        pass
    if companies_json:
        for c in companies_json.get('companies', []):
            for d in c.get('domains') or []:
                domains.add(d.lower().removeprefix('www.'))
    return sorted(domains)


def _crawl_domain(domain, deadline):
    """Excel links on one website: sitemap entries plus investor-relations pages."""
    s = session()
    found = set()
    base = f'https://{domain}'
    rp = urllib.robotparser.RobotFileParser()
    sitemaps = []
    try:
        r = s.get(base + '/robots.txt', timeout=20)
        lines = r.text.splitlines() if r.ok else []
        rp.parse(lines)
        sitemaps = [ln.split(':', 1)[1].strip() for ln in lines if ln.lower().startswith('sitemap:')]
    except requests.RequestException:
        return found
    ua = s.headers['User-Agent']
    allowed = lambda u: rp.can_fetch(ua, u)  # noqa: E731
    sitemaps = sitemaps or [base + '/sitemap.xml', base + '/sitemap_index.xml']
    seen_maps, budget = set(), 40
    while sitemaps and budget and time.time() < deadline:
        sm = sitemaps.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        budget -= 1
        try:
            r = s.get(sm, timeout=30)
            if not r.ok:
                continue
            body = r.content
            if sm.endswith('.gz') or body[:2] == b'\x1f\x8b':
                body = gzip.decompress(body)
            text = body.decode('utf-8', 'replace')
        except Exception:  # noqa: BLE001
            continue
        for loc in re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', text):
            loc = loc.replace('&amp;', '&')
            if EXCEL_URL.search(urllib.parse.urlparse(loc).path):
                if allowed(loc):
                    found.add(loc)
            elif re.search(r'sitemap[^/]*\.xml(\.gz)?$', loc, re.I) and len(seen_maps) + len(sitemaps) < 200:
                if re.search(r'invest|ir[-_.]|financ|report|document|download|resource|media|file|asset|sitemap\d*\.xml|index', loc, re.I):
                    sitemaps.append(loc)
        time.sleep(1)
    pages = [base + '/'] + [base + p for p in IR_PATHS]
    for page in pages:
        if time.time() > deadline or not allowed(page):
            continue
        try:
            r = s.get(page, timeout=20)
        except requests.RequestException:
            continue
        if not r.ok or 'html' not in r.headers.get('content-type', ''):
            continue
        for href in HREF.findall(r.text):
            u = urllib.parse.urljoin(r.url, href)
            if EXCEL_URL.search(urllib.parse.urlparse(u).path) and allowed(u):
                found.add(u)
        time.sleep(1)
    return found


def websites(state, s, log, companies_json=None, max_domains=250, minutes=12):
    st = state.setdefault('web', {'domains': [], 'i': 0, 'listed_at': 0})
    if not st['domains'] or st['listed_at'] < time.time() - 30 * 86400 and st['i'] >= len(st['domains']):
        st['domains'] = company_domains(s, companies_json)
        st['i'] = 0
        st['listed_at'] = time.time()
    todo = st['domains'][st['i']:st['i'] + max_domains]
    deadline = time.time() + minutes * 60
    n = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = {pool.submit(_crawl_domain, d, deadline): d for d in todo}
        for fut in as_completed(futs):
            try:
                for url in fut.result():
                    n += _add(state, f'url:{url}', url, urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit('/', 1)[-1]), 'website')
            except Exception:  # noqa: BLE001
                pass
    st['i'] += len(todo)
    log(f'websites: {n} new candidates from {len(todo)} company sites ({st["i"]}/{len(st["domains"])} done)')
    return n
