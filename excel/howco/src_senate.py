"""US Senate Permanent Subcommittee on Investigations: hearing records with their exhibits and the staff reports
for Wall Street and the Financial Crisis (investment banks, Washington Mutual, rating agencies; 2010-11), the
JPMorgan Chase "whale trades" (2013) and HSBC money laundering (2012), from govinfo.gov (the Senate site refuses
automated visitors).

  Senate Investigation Exhibits/<inquiry>/Folder K (Documents a-b)/<n> - <title>.pdf
"""
import os
import re
import time

from . import docs

INQUIRIES = [('Wall Street and the Financial Crisis (2010-2011)', '"Wall Street and the Financial Crisis"',
              r'wall street and the financial crisis'),
             ('Bank derivatives trading losses (2013)', '"Whale Trades"', r'whale trades'),
             ('Global bank money laundering controls (2012)', '"HSBC Case History"', r'hsbc')]


def discover(ctx, s, log):
    key = os.environ.get('GOVINFO_API_KEY') or 'DEMO_KEY'
    for group, query, pattern in INQUIRIES:
        found, mark = [], '*'
        for _ in range(5):
            body = {'query': f'{query} AND (collection:CHRG OR collection:CPRT)', 'pageSize': 50, 'offsetMark': mark}
            try:
                d = s.post(f'https://api.govinfo.gov/search?api_key={key}', json=body, timeout=60).json()
            except Exception:  # noqa: BLE001
                log(f'{group}: search failed')
                break
            for res in d.get('results', []):
                pkg = res.get('packageId')
                if pkg and pkg not in found and re.search(pattern, res.get('title') or '', re.I):
                    found.append(pkg)
                    yield {'url': f'https://www.govinfo.gov/content/pkg/{pkg}/pdf/{pkg}.pdf', 'group': group,
                           'ext': 'pdf', 'title': f'{(res.get("title") or "")[:90]} ({(res.get("dateIssued") or "")[:4]})'}
            mark = d.get('offsetMark')
            if not mark or not d.get('results'):
                break
            time.sleep(2)
        log(f'{group}: {len(found)} hearing records and reports')


def run(ctx, log):
    docs.run(ctx, log, discover, min_text_per_page=100)
