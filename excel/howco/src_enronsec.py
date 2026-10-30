"""Enron Corp's own SEC filings (EDGAR, CIK 1024401, 1996-2005): annual and quarterly reports, current reports,
proxies, prospectuses and ownership filings. HTML filings are kept as Word documents.

  Energy Trading Company Corpus/SEC Filings (EDGAR)/<form type>/Folder K (Documents a-b)/<n> - <title>.<ext>
"""
import os

from . import docs

CIK = '1024401'
GROUPS = {'10-K': 'Annual reports (10-K)', '10-K405': 'Annual reports (10-K)', '10-Q': 'Quarterly reports (10-Q)',
          '8-K': 'Current reports (8-K)', 'DEF 14A': 'Proxy statements', 'PRE 14A': 'Proxy statements',
          'S-3': 'Registration statements & prospectuses', 'S-8': 'Registration statements & prospectuses',
          '424B2': 'Registration statements & prospectuses', '424B3': 'Registration statements & prospectuses',
          '424B5': 'Registration statements & prospectuses', '425': 'Merger communications'}


def discover(ctx, s, log):
    s.headers['User-Agent'] = os.environ.get('SEC_USER_AGENT') or 'HowCompaniesWork research collector admin@irtranscripts.com'
    d = s.get(f'https://data.sec.gov/submissions/CIK{CIK.zfill(10)}.json', timeout=60).json()
    r = d['filings']['recent']
    rows = list(zip(r['form'], r['filingDate'], r['accessionNumber'], r['primaryDocument'],
                    r.get('primaryDocDescription', [''] * len(r['form']))))
    log(f'{len(rows)} Enron filings listed')
    for form, date, acc, doc, desc in sorted(rows, key=lambda x: x[1]):
        folder = f'https://www.sec.gov/Archives/edgar/data/{CIK}/{acc.replace("-", "")}'
        # filings before 2001 list no primary document: the complete submission text holds them
        url = f'{folder}/{doc}' if doc else f'{folder}/{acc}.txt'
        ext = doc.rsplit('.', 1)[-1].lower() if doc and '.' in doc else 'txt'
        group = GROUPS.get(form) or ('Ownership filings (13D/13G)' if form.startswith('SC 13') else
                                     'Utility holding company filings (U-forms)' if form.startswith('U') else 'Other filings')
        yield {'url': url, 'group': group,
               'ext': ext, 'title': f'{date} {form} {(desc or "").strip()}'.strip()}


def run(ctx, log):
    docs.run(ctx, log, discover, min_text_per_page=50)
