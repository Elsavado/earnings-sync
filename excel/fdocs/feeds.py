"""Live discovery for the Workspace collectors: cursors that reopen, sources that take turns, per-source logs, and
the extra office sources (data.gov catalog, Socrata Discovery API, SEC EDGAR full-text search, web search).

Why (2026-10-29): after the finance-only rule (2026-10-27) every search cursor of the office and research collectors
was marked done for good, so each run found nothing and the queues stayed empty. Now:
- a finished cursor reopens after REOPEN_DAYS and reads only what was published or changed since it finished
  (newest first), so a query list can never run dry for good;
- each kind takes its sources in turn and moves on to the next query, source and cursor while its queue is short;
- every source logs what it found, and each run logs how many cursors are open, finished or waiting to reopen.

Content rules stay as they are: finance only (topic.py via office.about_finance), English US / Canadian content
(usca.py), one file per record, no repeated titles, and at most HOST_CAP files from one site or filer.
"""
import hashlib
import re
import time

import requests

from . import topic, usca, websearch
from .sources import THIS_YEAR, late

REOPEN_DAYS = 3
WEB_REOPEN_DAYS = 30
QUEUE_TARGET = 40  # a source stops adding once the kind's queue holds this many
HOST_CAP = 15  # at most this many files of one kind from one site, Socrata portal, data.gov publisher or SEC filer


# --- cursors ----------------------------------------------------------------------------------
def _iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(t))


def cursor(state, key, init, reopen_days=REOPEN_DAYS):
    """The cursor at key. A finished cursor reopens after reopen_days with 'since' (ISO time it finished): sources
    read newest first and stop at older records. Cursors finished before reopening existed get a finish time spread
    over the next reopen_days, so they do not all reopen at once."""
    cur = state['cursors'].setdefault(key, dict(init))
    if cur.get('done'):
        at = cur.get('done_at')
        if at is None:
            spread = int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % 1000 / 1000
            at = cur['done_at'] = time.time() - spread * reopen_days * 86400
        if time.time() - at >= reopen_days * 86400:
            n = cur.get('round', 0) + 1
            cur.clear()
            cur.update(dict(init), round=n, since=_iso(at))
    return cur


def finish(cur):
    cur['done'] = True
    cur['done_at'] = time.time()


def older(cur, stamp):
    """A reopened cursor reached records from before it last finished."""
    return bool(cur.get('since') and stamp and str(stamp)[:19] < cur['since'])


def rotate(state, key, items):
    """items starting one further on each call, so every query gets its turn first."""
    if not items:
        return []
    t = state['cursors'].setdefault(f'rot:{key}', {'n': 0})
    t['n'] = (t.get('n', 0) + 1) % len(items)
    return items[t['n']:] + items[:t['n']]


def full(state, kind):
    return len(state['queue'].get(kind, [])) >= QUEUE_TARGET


def status(state, prefixes, log, kind):
    """One line per run: how many search cursors of this kind are open, finished, or waiting to reopen."""
    cur = [v for k, v in state['cursors'].items() if k.startswith(prefixes) and isinstance(v, dict)]
    done = [c for c in cur if c.get('done')]
    log(f'  {kind}: {len(cur)} search cursors, {len(cur) - len(done)} open, {len(done)} finished (reopen after '
        f'{REOPEN_DAYS} days); web search: {websearch.provider() or "off"}'
        + (f', {websearch.remaining(state, kind)} queries left today' if websearch.provider() else ''))


def run(state, kind, s, log, fns):
    """Each source in turn (a different one leads every call) until the queue is full or time is up; logs what
    each source found."""
    turn = state['cursors'].setdefault(f'turn2:{kind}', {'n': 0})
    turn['n'] = (turn.get('n', 0) + 1) % len(fns)
    fns = fns[turn['n']:] + fns[:turn['n']]
    total, found = 0, []
    for fn in fns:
        if late() or full(state, kind):
            break
        t0 = time.time()
        try:
            n = fn(state, kind, s, log)
        except Exception as err:  # noqa: BLE001
            log(f'  {kind}: {fn.__name__} failed ({type(err).__name__}: {str(err)[:120]})')
            continue
        total += n
        found.append(f'{fn.__name__} {n} ({time.time() - t0:.0f}s)')
    if found:
        log(f'  {kind}: found ' + ', '.join(found))
    return total


def host_ok(state, kind, host):
    h = state.setdefault('office_hosts', {}).setdefault(kind, {})
    return h.get(host, 0) < HOST_CAP


def host_used(state, kind, host):
    h = state.setdefault('office_hosts', {}).setdefault(kind, {})
    h[host] = h.get(host, 0) + 1


def _host(url):
    return re.sub(r'^https?://([^/:?#]+).*$', r'\1', url or '').lower()


# --- query terms ------------------------------------------------------------------------------------
# Finance, accounting, hedge-fund and financial-analysis subjects only; each passes topic.finance itself.
FIN_TERMS = ['budget', 'financial statements', 'annual financial report', 'comprehensive annual financial report',
             'audit report', 'single audit', 'financial audit', 'expenditures', 'revenue', 'tax revenue', 'fiscal',
             'capital budget', 'operating budget', 'budget book', 'cash flow', 'balance sheet', 'income statement',
             'general ledger', 'accounts payable', 'accounts receivable', 'vendor payments', 'checkbook',
             'payroll', 'procurement spending', 'investment', 'investment portfolio', 'pension fund',
             'retirement fund investments', 'treasury', 'debt', 'bond issuance', 'municipal bonds', 'interest rates',
             'loans', 'mortgage', 'banking', 'credit union', 'insurance', 'actuarial valuation', 'financial condition',
             'financial performance', 'financial indicators', 'financial forecast', 'revenue forecast',
             'financial plan', 'grants expenditures', 'appropriations', 'fund balance', 'reconciliation',
             'disbursements', 'invoices', 'tax rates', 'property tax', 'sales tax', 'excise tax', 'tax expenditures',
             'economic indicators', 'consumer price', 'exchange rates', 'securities', 'stock market', 'trading',
             'hedge fund', 'private equity', 'venture capital', 'asset management', 'valuation', 'earnings',
             'dividends', 'cost analysis', 'cost estimate', 'financial literacy', 'public finance']
PRESENT_TERMS = ['budget presentation', 'financial presentation', 'finance committee presentation',
                 'budget briefing', 'investment presentation', 'treasury presentation', 'audit presentation',
                 'financial update presentation', 'revenue presentation', 'pension presentation', 'budget slides',
                 'financial overview presentation', 'debt presentation', 'tax presentation']
BOOK_TERMS = ['general ledger', 'journal entries', 'trial balance', 'check register', 'cash receipts',
              'accounts payable', 'accounts receivable', 'chart of accounts', 'fund balance', 'revenue ledger',
              'expenditure ledger', 'bank reconciliation', 'checkbook', 'vendor payments', 'disbursements',
              'payments ledger', 'purchase card transactions', 'expenditures detail', 'revenues detail',
              'budget to actual', 'warrant register', 'claims paid', 'treasurer report', 'cash disbursements']
PRESENT = re.compile(r'presentation|slides?\b|slide deck|briefing|\bdeck\b|webinar|overview|pptx?\b', re.I)
OPEN_LICENSE = re.compile(r'public ?domain|publicdomain|creative ?commons|creativecommons|cc0|cc-by|\bcc by\b|'
                          r'open ?data ?commons|opendatacommons|odc|pddl|open government|us-pd|usa\.gov', re.I)


# --- data.gov catalog (US federal, state and local open data) ----------------------------------------
DATAGOV = 'https://catalog.data.gov/search'
DG_EXT = {'gsheets': ('xlsx',), 'bookkeeping': ('xlsx', 'csv'), 'gdocs': ('docx',), 'slides': ('pptx',),
          'presentations': ('pdf',)}
DG_MAX = {'xlsx': 8 * 2**20}


def _dg_terms(kind):
    if kind == 'bookkeeping':
        return BOOK_TERMS
    if kind in ('presentations', 'slides'):
        return PRESENT_TERMS + FIN_TERMS
    return FIN_TERMS


def datagov(state, kind, s, log, pages=3):
    """catalog.data.gov: datasets whose files include this kind's format; one file per dataset."""
    from . import office
    added = 0
    for term in rotate(state, f'datagov:{kind}', _dg_terms(kind)):
        if late() or full(state, kind):
            break
        cur = cursor(state, f'office:datagov:{kind}:{term}', {'page': 0, 'after': None})
        if cur.get('done'):
            continue
        for _ in range(pages):
            if late() or full(state, kind):
                return added
            params = {'q': term, 'per_page': 100}
            if cur.get('after'):
                params['after'] = cur['after']
            why = ''
            try:
                r = s.get(DATAGOV, params=params, timeout=60)
                why = f'http {r.status_code}'
                data = r.json() if r.ok else None
            except (requests.RequestException, ValueError) as err:
                data, why = None, why or type(err).__name__
            time.sleep(1)  # the catalog limits bursts
            if data is None:
                log(f'  datagov {kind}: search failed ({why}); trying again next round')
                return added  # a failing catalog is left alone until the next discovery round
            results = data.get('results') or []
            for x in results:
                d = x.get('dcat') or {}
                title = (d.get('title') or x.get('title') or '').strip()
                ident = str(d.get('identifier') or x.get('identifier') or x.get('slug') or '')[:80]
                if not title or not ident or not usca.english_title(title):
                    continue
                langs = [str(v).lower() for v in (d.get('language') or [])] if isinstance(d.get('language'), list) else []
                if langs and not any(v.startswith('en') for v in langs):
                    continue
                lic = str(d.get('license') or '')
                org = x.get('organization') or {}
                if lic and not OPEN_LICENSE.search(lic) and 'Government' not in str(org.get('organization_type') or ''):
                    continue
                about = ' '.join(str(k) for k in (d.get('keyword') or [])) + ' ' + str(d.get('description') or '')[:3000]
                if not office.about_finance(title, about):
                    continue
                for dist in d.get('distribution') or []:
                    url = str(dist.get('downloadURL') or '').strip()
                    ext = url.lower().split('?')[0].rsplit('.', 1)[-1]
                    if ext not in DG_EXT[kind] or not url.startswith(('https://', 'http://')):
                        continue
                    if kind == 'presentations' and not PRESENT.search(f'{dist.get("title") or ""} {url} {title}'):
                        continue
                    host = _host(url)
                    publisher = 'dg:' + str(org.get('slug') or host)
                    if not host_ok(state, kind, publisher):
                        break
                    if office._add(state, kind, {'key': f'datagov:{ident}', 'url': url, 'ext': ext, 'orgs': [],
                                                 'source': 'datagov', 'topic': term, 'title': title[:200]},
                                   f'datagov:{ident}'):
                        added += 1
                        host_used(state, kind, publisher)
                    break  # one file per dataset
            cur['page'] += 1
            cur['after'] = data.get('after')
            if not results or not cur['after'] or cur['page'] >= (5 if cur.get('since') else 40):
                finish(cur)
                break
    return added


# --- Socrata Discovery API (every Socrata portal): finance datasets as spreadsheets ----------------
SOCRATA = 'https://api.us.socrata.com/api/catalog/v1'
# US and Canadian government portals only; training and demo sandboxes are not real publishers.
GOV_DOMAIN = re.compile(r'\.(?:gov|us|mil|ca)$|(?:city|county|state|gov|cityof|town|village)[a-z]*\.(?:org|com|net)$', re.I)
SANDBOX = re.compile(r'train|demo|test|sandbox|socrata\.com$|example', re.I)
SOCRATA_TERMS = FIN_TERMS + ['finance', 'spending', 'payments', 'audit', 'ledger', 'budget actuals', 'revenues and expenditures',
                             'contracts awarded', 'purchase orders', 'grants awarded', 'debt service', 'investments',
                             'pension', 'tax collections', 'financial transparency', 'open checkbook']
SHEET_ROWS = 20000  # a Google Sheet holds 10 million cells: the first rows of a large dataset


def socrata_sheets(state, kind, s, log, pages=3):
    """Finance datasets of US / Canadian government Socrata portals: for spreadsheets their first SHEET_ROWS rows,
    for bookkeeping (ledger terms) the whole dataset."""
    from . import office
    added = 0
    book = kind == 'bookkeeping'
    for term in rotate(state, f'socrata:{kind}', BOOK_TERMS if book else SOCRATA_TERMS):
        if late() or full(state, kind):
            break
        cur = cursor(state, f'office:socrata:{kind}:{term}', {'offset': 0})
        if cur.get('done'):
            continue
        for _ in range(pages):
            if late() or full(state, kind):
                return added
            try:
                r = s.get(SOCRATA, timeout=60, params={'q': term, 'only': 'dataset', 'limit': 100, 'offset': cur['offset'],
                                                       'order': 'updatedAt'})
                data = r.json() if r.ok else None
            except (requests.RequestException, ValueError):
                data = None
            if not data:
                log(f'  socrata {kind}: search failed; trying again next round')
                return added
            results = data.get('results') or []
            for d in results:
                meta, res, cls = d.get('metadata') or {}, d.get('resource') or {}, d.get('classification') or {}
                domain = str(meta.get('domain') or '')
                if not GOV_DOMAIN.search(domain) or SANDBOX.search(domain) or not res.get('id'):
                    continue
                lic = str(meta.get('license') or '')
                if lic and not OPEN_LICENSE.search(lic):
                    continue
                name = (res.get('name') or '').strip()
                if not name or not usca.english_title(name):
                    continue
                attribution = (res.get('attribution') or '').strip()
                about = ' '.join([str(res.get('description') or '')[:3000], str(cls.get('domain_category') or '')]
                                 + [str(t) for t in (cls.get('categories') or []) + (cls.get('tags') or [])
                                    + (cls.get('domain_tags') or [])])
                if not office.about_finance(name, about):
                    continue
                # The publisher tells same-named datasets of different governments apart ('Checkbook - City of X').
                title = name if not attribution or attribution.lower() in name.lower() else f'{name} - {attribution}'
                if not usca.english_title(title):
                    title = name
                if not host_ok(state, kind, 'socrata:' + domain):
                    continue
                url = (f'https://{domain}/api/views/{res["id"]}/rows.csv?accessType=DOWNLOAD' if book
                       else f'https://{domain}/resource/{res["id"]}.csv?$limit={SHEET_ROWS}')
                if office._add(state, kind, {'key': f'socrata:{domain}:{res["id"]}', 'url': url, 'ext': 'csv', 'orgs': [],
                                             'source': 'socrata', 'topic': term, 'title': title[:200]},
                               f'socrata:{domain}:{res["id"]}'):
                    added += 1
                    host_used(state, kind, 'socrata:' + domain)
            cur['offset'] += 100
            # A reopened cursor reads the most recently updated datasets only.
            if not results or cur['offset'] >= min(data.get('resultSetSize', 0), 300 if cur.get('since') else 10000):
                finish(cur)
                break
    return added


# --- SEC EDGAR full-text search: finance document exhibits as Google Docs -------------------------
# (query, exhibit types, forms, title). One document per title and industry (SIC code), so no filer or industry
# floods the folder; each title is a finance subject (topic.finance).
SEC_DOCS = [
    ('"reports fourth quarter" "financial results"', r'EX-99', '8-K', 'Quarterly earnings release'),
    ('"reports third quarter" "financial results"', r'EX-99', '8-K', 'Quarterly earnings release Q3'),
    ('"management\'s discussion and analysis" "financial condition"', r'EX-99', '6-K,40-F', 'Management discussion of financial results'),
    ('"letter to shareholders" "financial results"', r'EX-99', '8-K', 'Shareholder letter on financial results'),
    ('"annual report to shareholders" "financial statements"', r'EX-13', '10-K', 'Annual report financial section'),
    ('"audit committee charter"', r'EX-99', '', 'Audit committee charter'),
    ('"independent auditor\'s report" "balance sheets"', r'EX-99', '8-K,8-K/A', 'Acquired business financial statements'),
    ('"unaudited pro forma condensed combined financial"', r'EX-99', '8-K,8-K/A', 'Pro forma financial information'),
    ('"code of ethics" "senior financial officers"', r'EX-14', '', 'Code of ethics for financial officers'),
    ('"insider trading policy"', r'EX-19', '10-K', 'Insider trading policy'),
    ('"investment policy" "investment committee"', r'EX-99', '', 'Investment policy statement'),
    ('"dividend reinvestment" "plan"', r'EX-99', '', 'Dividend reinvestment plan'),
]
assert all(topic.finance(t) for *_, t in SEC_DOCS)
SEC_STATES = set('AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC '
                 'ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR A0 A1 A2 A3 A4 A5 A6 A7 A8 A9 B0'.split())  # A0-B0: Canada


def sec_docs(state, kind, s, log, pages=3):
    """Exhibits of US and Canadian filers (business address), HTML converted to a Word document by main.process."""
    from . import office
    added = 0
    rec = office._records(state)
    for q, ftypes, forms, title in rotate(state, f'secdocs:{kind}', SEC_DOCS):
        if late() or full(state, kind):
            break
        cur = cursor(state, f'office:sec:{kind}:{q}:{forms}', {'year': THIS_YEAR, 'from': 0})
        if cur.get('done'):
            continue
        ft = re.compile(rf'^(?:{ftypes})', re.I)
        for _ in range(pages):
            if late() or full(state, kind):
                return added
            if cur['year'] < (THIS_YEAR - 1 if cur.get('since') else 2001):
                finish(cur)
                break
            params = {'q': q, 'dateRange': 'custom', 'startdt': f'{cur["year"]}-01-01', 'enddt': f'{cur["year"]}-12-31',
                      'from': cur['from']}
            if forms:
                params['forms'] = forms
            try:
                r = s.get('https://efts.sec.gov/LATEST/search-index', params=params, timeout=60)
                time.sleep(0.2)
                hits = r.json()['hits'] if r.ok else None
            except (requests.RequestException, ValueError, KeyError):
                hits = None
            if hits is None:
                log(f'  sec {kind} {cur["year"]}: search failed; trying again next round')
                return added
            for h in hits['hits']:
                src = h['_source']
                adsh, _, fn = h['_id'].partition(':')
                if not fn.lower().endswith(('.htm', '.html')) or not ft.match(src.get('file_type') or ''):
                    continue
                states = set(src.get('biz_states') or [])
                if not states or not states <= SEC_STATES:
                    continue
                sic = (src.get('sics') or [''])[0] or 'none'
                cik = (src.get('ciks') or ['0'])[0].lstrip('0') or '0'
                record = f'sec:{title}:{sic}'
                if record in rec or not host_ok(state, kind, f'cik:{cik}'):
                    continue
                key = f'sec:{adsh}:{fn}'
                cand = {'key': key, 'url': f'https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace("-", "")}/{fn}',
                        'ext': 'htm', 'orgs': src.get('display_names') or [], 'source': 'sec', 'cik': cik,
                        'date': src.get('file_date') or '', 'topic': title, 'title': title, 'rules': office.RULES}
                from .sources import _add as _queue
                if _queue(state, kind, cand):
                    rec[record] = 1
                    host_used(state, kind, f'cik:{cik}')
                    added += 1
            total = min(hits['total']['value'], 10000)
            cur['from'] += 100
            if cur['from'] >= total or not hits['hits']:
                cur['year'] -= 1
                cur['from'] = 0
    return added


# --- web search (Google Programmable Search or Brave; skipped without keys) -------------------------
WEB_FT = {'gsheets': 'xlsx', 'gdocs': 'docx', 'slides': 'pptx', 'presentations': 'pdf', 'bookkeeping': 'xlsx'}
# Files published by organisations: US / Canadian government and university sites, and listed companies'
# investor-relations pages.
WEB_SITES = [('site:.gov', re.compile(r'\.(?:gov|mil)$')), ('site:.gc.ca', re.compile(r'\.gc\.ca$')),
             ('site:.edu', re.compile(r'\.edu$')), ('site:.ca', re.compile(r'\.ca$')),
             ('inurl:investor (NYSE OR NASDAQ OR TSX)', re.compile(r'\.(?:com|ca|us|net)$'))]
WEB_TERMS = {
    'gsheets': ['"financial statements"', 'budget', '"cash flow" forecast', '"capital budget"', '"revenue forecast"',
                '"financial model"', '"fund balance"', 'expenditures', '"debt service" schedule', '"investment portfolio"',
                '"financial indicators"', '"tax revenue"', 'valuation', '"pension fund"'],
    'gdocs': ['"financial policy"', '"investment policy"', '"budget narrative"', '"financial report"',
              '"audit report"', '"internal audit"', '"accounting policies"', '"financial procedures"', '"treasury"',
              '"debt management policy"', '"fiscal note"', '"management discussion and analysis"'],
    'slides': ['budget presentation', '"financial update"', '"investment committee"', '"finance committee"',
               '"budget overview"', '"financial results"', '"investor presentation"', '"earnings presentation"',
               '"treasury" presentation', '"pension" investment presentation', '"audit committee" presentation'],
    'presentations': ['"budget presentation"', '"investor presentation"', '"earnings presentation"',
                      '"financial update" presentation', '"finance committee" presentation', '"investment review" slides',
                      '"budget briefing"', '"treasury" presentation slides', '"pension fund" presentation'],
    'bookkeeping': ['"general ledger"', '"trial balance"', '"check register"', '"journal entries"', '"cash receipts"',
                    '"accounts payable" register', '"bank reconciliation"', '"warrant register"', '"chart of accounts"'],
}


def _web_title(t):
    t = re.sub(r'\s*[|–—-]\s*[^|–—-]{0,60}$', '', t or '').strip() or (t or '')  # ' - Site name'
    return re.sub(r'\.(?:xlsx|docx|pptx|pdf)$', '', t.strip(), flags=re.I).strip()


def web_queries(kind):
    ft = WEB_FT[kind]
    return [(f'{t} filetype:{ft} {site}', host) for t in WEB_TERMS[kind] for site, host in WEB_SITES]


def web(state, kind, s, log, calls=3):
    """A few web searches a call (the day's budget is shared out over the chained runs)."""
    from . import office
    if not websearch.provider() or websearch.remaining(state, kind) <= 0:
        return 0
    ext = WEB_FT[kind]
    added = used = 0
    for q, host_re in rotate(state, f'web:{kind}', web_queries(kind)):
        if late() or full(state, kind) or used >= calls:
            break
        cur = cursor(state, f'office:web:{kind}:{q}', {'page': 0}, WEB_REOPEN_DAYS)
        if cur.get('done'):
            continue
        res = websearch.search(state, kind, s, q, cur['page'])
        used += 1
        if res is None:
            break
        keep, raw = res
        for o in keep:
            url, host = o['url'], o['host']
            if not url.lower().split('?')[0].endswith('.' + ext) or not host_re.search(host):
                continue
            title = _web_title(o['title'])
            if not title or not usca.english_title(title) or not office.about_finance(title, o['snippet']):
                continue
            if not host_ok(state, kind, 'web:' + host):
                continue
            if office._add(state, kind, {'key': f'web:{url}'[:300], 'url': url, 'ext': ext, 'orgs': [], 'source': 'web',
                                         'topic': q.split(' filetype:')[0].strip('"'), 'title': title[:200]},
                           f'web:{host}:{usca.norm_title(title)}'):
                added += 1
                host_used(state, kind, 'web:' + host)
        cur['page'] += 1
        if raw == 0 or cur['page'] >= websearch.PAGES:
            finish(cur)
    return added
