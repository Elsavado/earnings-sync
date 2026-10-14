"""Where documents come from. Every source is public: SEC EDGAR filings (full-text search),
World Bank documents, open-access papers and theses (OpenAlex), government open-data portals
(Socrata), openly licensed GitHub repositories and Zenodo datasets.

Each discover function adds candidates to state['queue'][kind] and keeps its own cursor in
state['cursors'], so later runs continue where the last one stopped. A candidate is
{'key', 'url', 'ext', 'orgs', 'source'}.
"""
import os
import re
import time
from urllib.parse import quote

import requests

SEC_UA = os.environ.get('SEC_USER_AGENT') or 'FinDocs research contact@example.com'
DOC_EXT = ('.pdf', '.htm', '.html', '.txt', '.doc', '.docx', '.ppt', '.pptx')
THIS_YEAR = time.gmtime().tm_year
DEADLINE = None  # set by the run: discovery stops when it is reached


def late():
    return DEADLINE is not None and time.time() > DEADLINE

EX10 = r'EX-10'
EX99 = r'EX-99'
EX99C = r'EX-99\.?\(?C\)?'
EX99D = r'EX-99\.?\(?D\)?'
SEC_QUERIES = {
    'cim': [('"discussion materials"', EX99C), ('"presentation to the special committee"', EX99C),
            ('"preliminary discussion materials"', EX99C), ('"due diligence report"', EX99),
            ('"quality of earnings"', EX99C + '|' + EX99)],
    'deals': [('"letter of intent"', EX10 + '|' + EX99), ('"term sheet"', EX10 + '|' + EX99D + '|' + EX99),
              ('"non-disclosure agreement"', EX10 + '|' + EX99D), ('"confidentiality agreement"', EX99D + '|' + EX10),
              ('"indicative proposal"', EX99), ('"non-binding proposal"', EX99)],
    'letters': [('"dear limited partners"', EX99), ('"dear fellow shareholders"', EX99), ('"dear partners"', EX99),
                ('"letter to shareholders"', EX99), ('"dear fellow stockholders"', EX99), ('"dear unitholders"', EX99)],
    'memos': [('"investment committee memorandum"', ''), ('"investment memorandum"', EX99),
              ('"memorandum to the investment committee"', '')],
    'transcripts': [('"earnings call" operator "question-and-answer session"', EX99 + '|425'),
                    ('"earnings conference call" transcript operator', EX99 + '|425'),
                    ('"conference call transcript" earnings operator', EX99 + '|425')],
    'contracts': [('"employment agreement"', EX10), ('"credit agreement"', EX10), ('"supply agreement"', EX10),
                  ('"license agreement"', EX10), ('"consulting agreement"', EX10), ('"services agreement"', EX10),
                  ('"asset purchase agreement"', EX10), ('"lease agreement"', EX10), ('"loan agreement"', EX10)],
}
OPENALEX = {
    'equity': [('equity research', 'dissertation'), ('equity valuation', 'dissertation'), ('firm valuation', 'dissertation'),
               ('company valuation', 'dissertation'), ('investment thesis', None)],
    'research': [('industry analysis', 'report'), ('market analysis', 'report'), ('industry report', None),
                 ('sector analysis', 'report'), ('market research', 'report')],
}
WORLDBANK = {
    'research': [('industry analysis', None), ('sector assessment', None), ('market assessment', None),
                 ('value chain analysis', None)],
    'memos': [('investment', 'Project Appraisal Document'), ('financing', 'Project Appraisal Document')],
}
SOCRATA = {
    'payroll': ['employee payroll', 'employee salaries', 'payroll', 'employee compensation', 'salary'],
    'transactions': ['vendor payments', 'checkbook', 'expenditures', 'purchase card transactions', 'payments ledger',
                     'general ledger', 'accounts payable'],
}
GITHUB_DATA = {
    'transactions': ['quickbooks sample data', 'quickbooks transactions', 'stripe transactions dataset',
                     'synthetic financial transactions', 'paysim', 'bank transactions dataset', 'credit card transactions dataset',
                     'general ledger sample data', 'accounting transactions csv'],
    'payroll': ['payroll dataset', 'employee salary dataset', 'payroll sample data'],
}
DATA_FILE = re.compile(r'(transaction|payment|ledger|journal|invoice|charge|payout|payroll|salar|wage|bank|expense|'
                       r'purchase|receipt|account|quickbooks|stripe|paysim)', re.I)
GITHUB_NOTEBOOKS = ['dcf valuation', 'portfolio optimization', 'option pricing', 'financial modeling', 'quantitative finance',
                    'algorithmic trading backtest', 'credit risk model', 'value at risk', 'financial statement analysis',
                    'stock valuation', 'fixed income', 'black scholes', 'monte carlo finance', 'factor model',
                    'time series forecasting stock', 'risk management finance']
LICENSES = ['mit', 'apache-2.0', 'bsd-3-clause', 'bsd-2-clause', 'gpl-3.0', 'cc0-1.0', 'unlicense', 'cc-by-4.0', 'mpl-2.0']
OPEN_DATA_LICENSE = re.compile(r'public domain|creative commons|cc0|cc-by|odc|open data commons|open government|pddl', re.I)


def session():
    s = requests.Session()
    s.headers['User-Agent'] = SEC_UA
    return s


def _add(state, kind, cand):
    if cand['key'] in state['seen'] or cand['key'] in state['queued']:
        return False
    state['queue'].setdefault(kind, []).append(cand)
    state['queued'][cand['key']] = 1
    return True


# --- SEC EDGAR full-text search -----------------------------------------------------
def sec(state, kind, s, log, pages=10):
    """Full-text search, one year at a time (the API stops at 10,000 hits per query)."""
    added = 0
    for q, ftypes in SEC_QUERIES.get(kind, []):
        cur = state['cursors'].setdefault(f'sec:{kind}:{q}', {'year': THIS_YEAR, 'from': 0})
        if cur.get('done'):
            continue
        ft = re.compile(rf'^(?:{ftypes})', re.I) if ftypes else None
        for _ in range(pages):
            if late():
                return added
            if cur['year'] < 2001:
                cur['done'] = True
                break
            params = {'q': q, 'dateRange': 'custom', 'startdt': f'{cur["year"]}-01-01', 'enddt': f'{cur["year"]}-12-31',
                      'from': cur['from']}
            hits = None
            for attempt in range(2):
                try:
                    r = s.get('https://efts.sec.gov/LATEST/search-index', params=params, timeout=60)
                    time.sleep(0.15)
                    hits = r.json()['hits'] if r.ok else None
                except (requests.RequestException, ValueError, KeyError):
                    hits = None
                if hits is not None:
                    break
                time.sleep(3)
            if hits is None:
                log(f'  sec {kind} {q} {cur["year"]}: search failed')
                break
            for h in hits['hits']:
                src = h['_source']
                adsh, _, fn = h['_id'].partition(':')
                if not fn.lower().endswith(DOC_EXT):
                    continue
                if ft and not ft.match(src.get('file_type') or ''):
                    continue
                cik = (src.get('ciks') or ['0'])[0].lstrip('0') or '0'
                url = f'https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace("-", "")}/{fn}'
                if _add(state, kind, {'key': f'sec:{adsh}:{fn}', 'url': url, 'ext': fn.rsplit('.', 1)[-1].lower(),
                                      'orgs': src.get('display_names') or [], 'source': 'sec'}):
                    added += 1
            total = min(hits['total']['value'], 10000)
            cur['from'] += 100
            if cur['from'] >= total or not hits['hits']:
                cur['year'] -= 1
                cur['from'] = 0
    return added


# --- OpenAlex (open-access papers, theses and reports) ------------------------------
def openalex(state, kind, s, log, pages=3):
    added = 0
    for q, typ in OPENALEX.get(kind, []):
        cur = state['cursors'].setdefault(f'openalex:{kind}:{q}:{typ}', {'cursor': '*'})
        if cur.get('done'):
            continue
        filt = f'title.search:{q},is_oa:true,has_fulltext:true' + (f',type:{typ}' if typ else '')
        for _ in range(pages):
            if late():
                return added
            try:
                r = s.get('https://api.openalex.org/works', params={'filter': filt, 'per-page': 200, 'cursor': cur['cursor'],
                                                                    'select': 'id,best_oa_location,language'}, timeout=60)
                data = r.json() if r.ok else None
            except (requests.RequestException, ValueError):
                data = None
            if not data:
                log(f'  openalex {kind} {q}: failed')
                break
            for w in data.get('results', []):
                loc = w.get('best_oa_location') or {}
                url = loc.get('pdf_url')
                if not url or (w.get('language') not in (None, 'en')):
                    continue
                if _add(state, kind, {'key': f'openalex:{w["id"].rsplit("/", 1)[-1]}', 'url': url, 'ext': 'pdf',
                                      'orgs': [], 'source': 'openalex'}):
                    added += 1
            nxt = (data.get('meta') or {}).get('next_cursor')
            if not nxt or not data.get('results'):
                cur['done'] = True
                break
            cur['cursor'] = nxt
    return added


# --- World Bank documents -----------------------------------------------------------
def worldbank(state, kind, s, log, pages=3):
    added = 0
    for q, docty in WORLDBANK.get(kind, []):
        cur = state['cursors'].setdefault(f'wb:{kind}:{q}:{docty}', {'os': 0})
        if cur.get('done'):
            continue
        for _ in range(pages):
            if late():
                return added
            params = {'format': 'json', 'qterm': q, 'rows': 100, 'os': cur['os'], 'fl': 'pdfurl,docty,lang', 'lang_exact': 'English'}
            if docty:
                params['docty_exact'] = docty
            try:
                r = s.get('https://search.worldbank.org/api/v3/wds', params=params, timeout=60)
                data = r.json() if r.ok else None
            except (requests.RequestException, ValueError):
                data = None
            if not data:
                log(f'  worldbank {kind} {q}: failed')
                break
            docs = [v for k, v in (data.get('documents') or {}).items() if k != 'facets']
            for d in docs:
                url = d.get('pdfurl')
                if url and _add(state, kind, {'key': f'wb:{d.get("id")}', 'url': url.replace('http://', 'https://'), 'ext': 'pdf',
                                              'orgs': [], 'source': 'worldbank'}):
                    added += 1
            cur['os'] += 100
            if not docs or cur['os'] >= int(data.get('total') or 0):
                cur['done'] = True
                break
    return added


# --- Socrata government open data (payroll, vendor payments, checkbooks) ---------------
def socrata(state, kind, s, log, pages=2):
    added = 0
    for q in SOCRATA.get(kind, []):
        cur = state['cursors'].setdefault(f'socrata:{kind}:{q}', {'offset': 0})
        if cur.get('done'):
            continue
        for _ in range(pages):
            if late():
                return added
            try:
                r = s.get('https://api.us.socrata.com/api/catalog/v1', params={'q': q, 'only': 'datasets', 'limit': 100,
                                                                              'offset': cur['offset']}, timeout=60)
                data = r.json() if r.ok else None
            except (requests.RequestException, ValueError):
                data = None
            if not data:
                log(f'  socrata {kind} {q}: failed')
                break
            for d in data.get('results', []):
                meta, res = d.get('metadata', {}), d.get('resource', {})
                lic = meta.get('license') or ''
                if lic and not OPEN_DATA_LICENSE.search(lic):
                    continue
                if not lic and not re.search(r'\.gov$|\.gov/|\.us$', meta.get('domain', '')):
                    continue
                url = f'https://{meta["domain"]}/resource/{res["id"]}.csv?$limit=50000'
                if _add(state, kind, {'key': f'socrata:{meta["domain"]}:{res["id"]}', 'url': url, 'ext': 'csv',
                                      'orgs': [], 'source': 'socrata'}):
                    added += 1
            cur['offset'] += 100
            if cur['offset'] >= data.get('resultSetSize', 0):
                cur['done'] = True
                break
    return added


# --- GitHub (openly licensed repositories) -------------------------------------------------
def _gh(s):
    h = {'Accept': 'application/vnd.github+json', 'User-Agent': 'fin-docs'}
    if os.environ.get('GITHUB_TOKEN'):
        h['Authorization'] = f'Bearer {os.environ["GITHUB_TOKEN"]}'
    return h


def _repo_files(s, full, branch, pattern, max_size, limit):
    try:
        r = s.get(f'https://api.github.com/repos/{full}/git/trees/{quote(branch)}?recursive=1', headers=_gh(s), timeout=60)
        tree = r.json().get('tree', []) if r.ok else []
    except (requests.RequestException, ValueError):
        return []
    out = [t for t in tree if t.get('type') == 'blob' and pattern(t['path']) and 0 < t.get('size', 0) <= max_size]
    return out[:limit]


def github(state, kind, s, log, pages=2):
    """Notebooks (kind 'notebooks') or data files (transactions, payroll) from licensed repositories."""
    added = 0
    queries = GITHUB_NOTEBOOKS if kind == 'notebooks' else GITHUB_DATA.get(kind, [])
    for q in queries:
        for lic in LICENSES:
            cur = state['cursors'].setdefault(f'gh:{kind}:{q}:{lic}', {'page': 1})
            if cur.get('done'):
                continue
            for _ in range(pages):
                if late():
                    return added
                lang = ' language:"Jupyter Notebook"' if kind == 'notebooks' else ''
                try:
                    r = s.get('https://api.github.com/search/repositories', headers=_gh(s), timeout=60,
                              params={'q': f'{q} license:{lic}{lang}', 'per_page': 50, 'page': cur['page']})
                    if r.status_code == 403:
                        time.sleep(30)
                        break
                    items = r.json().get('items', []) if r.ok else None
                except (requests.RequestException, ValueError):
                    items = None
                if items is None:
                    break
                time.sleep(2)  # search API: 30 requests a minute
                for repo in items:
                    if late():
                        return added
                    full, branch = repo['full_name'], repo.get('default_branch') or 'main'
                    if f'ghrepo:{kind}:{full}' in state['seen']:
                        continue
                    state['seen'][f'ghrepo:{kind}:{full}'] = 1
                    if kind == 'notebooks':
                        files = _repo_files(s, full, branch, lambda p: p.endswith('.ipynb') and '.ipynb_checkpoints' not in p,
                                            5 * 2**20, 15)
                    else:
                        files = _repo_files(s, full, branch, lambda p: p.lower().endswith(('.csv', '.xlsx', '.json'))
                                            and DATA_FILE.search(p.rsplit('/', 1)[-1]), 40 * 2**20, 10)
                    for f in files:
                        url = f'https://raw.githubusercontent.com/{full}/{quote(branch)}/{quote(f["path"])}'
                        if _add(state, kind, {'key': f'gh:{full}:{f["path"]}'[:300], 'url': url,
                                              'ext': f['path'].rsplit('.', 1)[-1].lower(), 'orgs': [], 'source': 'github'}):
                            added += 1
                cur['page'] += 1
                if len(items) < 50 or cur['page'] > 10:
                    cur['done'] = True
                    break
    return added


# --- Zenodo (openly licensed datasets) ----------------------------------------------------
ZENODO = {
    'transactions': ['financial transactions', 'synthetic transactions', 'bank transactions', 'payment transactions',
                     'accounting journal entries', 'general ledger'],
    'payroll': ['payroll', 'employee salaries'],
}


def zenodo(state, kind, s, log, pages=2):
    added = 0
    for q in ZENODO.get(kind, []):
        cur = state['cursors'].setdefault(f'zenodo:{kind}:{q}', {'page': 1})
        if cur.get('done'):
            continue
        for _ in range(pages):
            if late():
                return added
            try:
                r = s.get('https://zenodo.org/api/records', timeout=60,
                          params={'q': f'"{q}"', 'type': 'dataset', 'size': 50, 'page': cur['page']})
                hits = r.json()['hits']['hits'] if r.ok else None
            except (requests.RequestException, ValueError, KeyError):
                hits = None
            if hits is None:
                break
            for h in hits:
                lic = ((h.get('metadata') or {}).get('license') or {}).get('id', '')
                if not re.match(r'cc|odc|pddl|mit|apache|bsd|gpl', lic or '', re.I):
                    continue
                for f in h.get('files', [])[:10]:
                    key = f.get('key', '')
                    if key.lower().endswith(('.csv', '.xlsx')) and 0 < f.get('size', 0) <= 40 * 2**20:
                        url = (f.get('links') or {}).get('self')
                        if url and _add(state, kind, {'key': f'zenodo:{h["id"]}:{key}', 'url': url, 'ext': key.rsplit('.', 1)[-1].lower(),
                                                      'orgs': [], 'source': 'zenodo'}):
                            added += 1
            cur['page'] += 1
            if len(hits) < 50:
                cur['done'] = True
                break
    return added


DISCOVER = {
    'cim': [sec], 'deals': [sec], 'letters': [sec], 'transcripts': [sec], 'contracts': [sec],
    'memos': [sec, worldbank], 'research': [worldbank, openalex], 'equity': [openalex],
    'notebooks': [github], 'transactions': [socrata, zenodo, github], 'payroll': [socrata, zenodo, github],
}
