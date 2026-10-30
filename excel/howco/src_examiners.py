"""Court-appointed examiner and trustee investigation reports from corporate bankruptcies (what went wrong inside
the company, with the evidence). Known reports by direct address, plus the CourtListener RECAP archive when the
COURTLISTENER_TOKEN secret is set (free account at courtlistener.com).

  Bankruptcy Examiner & Trustee Reports/<case>/Folder K (Documents a-b)/<n> - <title>.pdf
"""
import os
import re
import time

from . import docs

KNOWN = [
    ('FTX Trading (2022)', 'Examiner final report - phase II (2024)',
     'https://storage.courtlistener.com/recap/gov.uscourts.deb.188450/gov.uscourts.deb.188450.25679.0.pdf'),
]
QUERIES = ['"report of the examiner"', '"examiner\'s report"', '"final report of the examiner"',
           '"report of the trustee" investigation', '"trustee\'s report" investigation',
           '"report of investigation" trustee', '"examiner\'s final report"']
API = 'https://www.courtlistener.com/api/rest/v4/search/'


def discover(ctx, s, log):
    for case, title, url in KNOWN:
        yield {'url': url, 'group': case, 'ext': 'pdf', 'title': title}
    token = os.environ.get('COURTLISTENER_TOKEN')
    if not token:
        log('COURTLISTENER_TOKEN not set: only the known reports')
        return
    h = {'Authorization': f'Token {token}'}
    n = 0
    for q in QUERIES:
        url, params = API, {'type': 'rd', 'q': q, 'available_only': 'on', 'order_by': 'score desc'}
        for _ in range(20):
            try:
                d = s.get(url, params=params, headers=h, timeout=60).json()
            except Exception:  # noqa: BLE001
                break
            for r in d.get('results', []):
                path = r.get('filepath_local')
                desc = (r.get('description') or r.get('short_description') or '').strip()
                if not path or (r.get('page_count') or 0) < 20 or not re.search(r'examiner|trustee', desc, re.I) \
                        or not re.search(r'report', desc, re.I):
                    continue
                n += 1
                case = re.sub(r'\s+', ' ', r.get('caseName') or 'Unknown case')[:80]
                year = (r.get('dateFiled') or r.get('entry_date_filed') or '')[:4]
                yield {'url': f'https://storage.courtlistener.com/{path}', 'group': f'{case} ({year})' if year else case,
                       'ext': 'pdf', 'title': desc[:110]}
            url, params = d.get('next'), None
            if not url:
                break
            time.sleep(1.5)
    log(f'{n} examiner and trustee report documents listed')


def run(ctx, log):
    docs.run(ctx, log, discover, min_text_per_page=100)
