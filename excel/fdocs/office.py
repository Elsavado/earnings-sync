"""Workspace office kinds: spreadsheets (uploaded as Google Sheets), documents (Google Docs), slide decks (Google
Slides), PDF presentations and bookkeeping records.

Sources are openly licensed only: Zenodo records under a Creative Commons, CC0 or open-source licence (searched by
file type), and government open-data portals (Socrata) for bookkeeping ledgers. People's names become
'Salvador Sekwa' (user, 2026-10-22), companies 'Redacted Company Name Inc'; e-mails, links, pictures and embedded
objects are removed as for the other types.
"""
import re
import time
from pathlib import Path

import requests

from . import anon as _anon
from . import sources
from . import tab as _tab
from .sources import _add, late

KINDS = ('gsheets', 'gdocs', 'slides', 'presentations', 'bookkeeping')
PERSON = 'Salvador Sekwa'
GOOGLE = {'gsheets': 'application/vnd.google-apps.spreadsheet', 'gdocs': 'application/vnd.google-apps.document',
          'slides': 'application/vnd.google-apps.presentation'}
ZENODO_LIC = re.compile(r'^(?:cc-by|cc0|cc-zero|mit|apache|bsd|gpl|lgpl|agpl|mpl|isc|unlicense|odc|pddl)', re.I)
# Topics rotate so the collection covers business, finance, public sector, education and science.
TOPICS = ['budget', 'financial', 'accounting', 'business plan', 'project management', 'marketing', 'sales', 'economics',
          'annual report', 'policy', 'education', 'training', 'workshop', 'health', 'engineering', 'energy', 'climate',
          'agriculture', 'transport', 'survey', 'statistics', 'data analysis', 'software', 'research methods', 'strategy',
          'governance', 'procurement', 'human resources', 'operations', 'supply chain', 'risk', 'audit', 'tourism',
          'water', 'urban planning', 'public health', 'innovation', 'entrepreneurship', 'sustainability', '']
ZFILE = {'gsheets': ('xlsx', None), 'gdocs': ('docx', None), 'slides': ('pptx', None), 'presentations': ('pdf', 'presentation'),
         'bookkeeping': ('xlsx', None)}
BOOK_Q = ['"general ledger"', 'bookkeeping', '"trial balance"', '"journal entries"', '"cash book"', '"accounts payable"',
          '"accounts receivable"', '"chart of accounts"', '"balance sheet"', '"income statement"', 'ledger', 'expenditure']
SOCRATA_BOOK = ['general ledger', 'journal entries', 'trial balance', 'check register', 'cash receipts', 'accounts receivable',
                'accounts payable', 'chart of accounts', 'fund balance', 'revenue ledger', 'expenditure ledger',
                'bank reconciliation', 'fixed assets', 'checkbook', 'vendor payments', 'disbursements', 'deposits']
LABEL = {'gsheets': 'Spreadsheet', 'gdocs': 'Document', 'slides': 'Slide deck', 'presentations': 'Presentation',
         'bookkeeping': 'Bookkeeping records'}
BOOK_COL = re.compile(r'debit|credit|ledger|journal|account|balance|fund|object|gl_?|posting|fiscal|period|voucher|'
                      r'check|cheque|receipt|deposit|invoice|payment|vendor|amount', re.I)


def zenodo_files(state, kind, s, log, pages=2):
    ext, rtype = ZFILE[kind]
    added = 0
    for topic in (BOOK_Q if kind == 'bookkeeping' else TOPICS):
        cur = state['cursors'].setdefault(f'office:zenodo:{kind}:{topic}', {'page': 1})
        if cur.get('done'):
            continue
        for _ in range(pages):
            if late():
                return added
            params = {'q': topic, 'file_type': ext, 'size': 25, 'page': cur['page'], 'sort': 'mostrecent'}
            if rtype:
                params['type'] = rtype
            try:
                r = s.get('https://zenodo.org/api/records', timeout=60, params=params)
                if r.status_code == 429:
                    time.sleep(60)
                    return added
                hits = r.json()['hits']['hits'] if r.ok else None
            except (requests.RequestException, ValueError, KeyError):
                hits = None
            if hits is None:
                break
            time.sleep(2.5)  # Zenodo allows about 30 searches a minute
            for h in hits:
                md = h.get('metadata') or {}
                if not ZENODO_LIC.match((md.get('license') or {}).get('id', '') or ''):
                    continue
                for f in h.get('files', [])[:20]:
                    key = f.get('key', '')
                    url = (f.get('links') or {}).get('self')
                    if key.lower().endswith('.' + ext) and url and 0 < f.get('size', 0) <= 40 * 2**20:
                        added += _add(state, kind, {'key': f'zenodo:{h["id"]}:{key}'[:300], 'url': url, 'ext': ext,
                                                    'orgs': [], 'source': 'zenodo', 'topic': topic.strip('"')})
            cur['page'] += 1
            if len(hits) < 25 or cur['page'] > 400:  # Zenodo serves at most 10,000 results per search
                cur['done'] = True
                break
    return added


def socrata_book(state, kind, s, log, pages=3):
    saved = sources.SOCRATA.get(kind)
    sources.SOCRATA[kind] = SOCRATA_BOOK
    try:
        return sources.socrata(state, kind, s, log, pages=pages)
    finally:
        if saved is None:
            sources.SOCRATA.pop(kind, None)


def office_sources(state, kind, s, log):
    if kind != 'bookkeeping':
        return zenodo_files(state, kind, s, log)
    turn = state['cursors'].setdefault('office:turn', {'n': 0})
    turn['n'] += 1
    added = 0
    for fn in ((socrata_book, zenodo_files) if turn['n'] % 2 else (zenodo_files, socrata_book)):
        if not late():
            added += fn(state, kind, s, log)
    return added


def _gate(kind, header, rows):
    """Table gate for the office kinds (replaces tab.gate's transaction/payroll checks)."""
    if kind == 'gsheets':
        if len(rows) < 10:
            return f'too few rows ({len(rows)})'
        if len([h for h in header if str(h).strip()]) < 3:
            return 'too few columns'
        return None
    if kind == 'bookkeeping':
        if len(rows) < 30:
            return f'too few rows ({len(rows)})'
        h = ' '.join(str(c) for c in header)
        if len(set(m.group(0).lower() for m in BOOK_COL.finditer(h))) < 2 or not _tab.MONEY_COL.search(h):
            return 'not bookkeeping records'
        return None
    return _ORIG_GATE(kind, header, rows)


_ORIG_GATE = _tab.gate
_tab.gate = _gate


def label(kind, cand):
    t = (cand.get('topic') or '').strip()
    return f'{LABEL[kind]} - {t.title()}' if t else LABEL[kind]


def setup(kind):
    """People become Salvador Sekwa in every office kind (documents, tables and file properties)."""
    _anon.PERSON = PERSON
    _tab.PERSON = PERSON


def slide_count(path):
    import zipfile
    with zipfile.ZipFile(path) as z:
        return sum(1 for n in z.namelist() if re.match(r'ppt/slides/slide\d+\.xml$', n))


def landscape_share(path):
    import fitz
    with fitz.open(path) as d:
        pages = [p.rect for p in d]
    return len(pages), (sum(r.width > r.height for r in pages) / len(pages) if pages else 0)


DISCOVER = {k: [office_sources] for k in KINDS}
