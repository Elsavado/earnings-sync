"""Congressional hearings and reports on Enron's collapse (2001-2006) from govinfo.gov: Senate and House hearings,
committee prints and the Joint Committee on Taxation's investigation of Enron's tax and compensation practices.

  Energy Trading Company Corpus/Congressional Hearings & Reports/<Hearings|Reports>/Folder K (Documents a-b)/<n> - <title>.pdf
"""
import os
import re
import time

from . import docs


def discover(ctx, s, log):
    key = os.environ.get('GOVINFO_API_KEY') or 'DEMO_KEY'
    found, mark = set(), '*'
    for _ in range(40):
        body = {'query': 'enron AND (collection:CHRG OR collection:CPRT OR collection:CRPT)', 'pageSize': 100,
                'offsetMark': mark}
        try:
            d = s.post(f'https://api.govinfo.gov/search?api_key={key}', json=body, timeout=60).json()
        except Exception:  # noqa: BLE001
            log('search failed')
            break
        for res in d.get('results', []):
            pkg, title = res.get('packageId'), res.get('title') or ''
            if not pkg or pkg in found or not re.search(r'\benron\b', title, re.I):
                continue
            found.add(pkg)
            group = 'Hearings' if pkg.startswith('CHRG') else 'Reports'
            yield {'url': f'https://www.govinfo.gov/content/pkg/{pkg}/pdf/{pkg}.pdf', 'group': group, 'ext': 'pdf',
                   'title': f'{title[:100]} ({(res.get("dateIssued") or "")[:4]})'}
        mark = d.get('offsetMark')
        if not mark or not d.get('results'):
            break
        time.sleep(2)
    log(f'{len(found)} Enron hearings and reports')


def run(ctx, log):
    docs.run(ctx, log, discover, min_text_per_page=100)
