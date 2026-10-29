"""Pluggable web search for the Workspace collectors (office and research).

Provider, in order: the Google Programmable Search JSON API when GOOGLE_CSE_KEY and GOOGLE_CSE_CX are set, else the
Brave Search API when BRAVE_API_KEY is set, else none (every caller skips web search silently).

Calls are budgeted per job and per UTC day in the job's own state: the Google free tier is 100 queries a day for the
whole key and both collectors run one job per type, so each type gets a small share (DAILY below; WEB_SEARCH_DAILY
overrides it for every type). Brave's free plan is about 2,000 queries a month and one a second.

The queries name files published by organisations only (government, university and investor-relations sites); no
open-directory listings, no shared-document links and nothing marked confidential.
"""
import os
import re
import time

import requests

GOOGLE = 'https://www.googleapis.com/customsearch/v1'
BRAVE = 'https://api.search.brave.com/res/v1/web/search'
# Queries a day for each type's job. Google: 5 office types x 16 + figma 10 = 90 of the 100 free queries.
DAILY = {'google': {'gsheets': 16, 'gdocs': 16, 'slides': 16, 'presentations': 16, 'bookkeeping': 16, 'figma': 10},
         'brave': {'gsheets': 10, 'gdocs': 10, 'slides': 10, 'presentations': 10, 'bookkeeping': 10, 'figma': 5}}
PAGES = 10  # Google serves at most 100 results (10 pages of 10) per query; Brave 10 pages (offset 0-9)
# Private individuals' documents and file shares are never searched or kept (user rule).
PRIVATE_HOST = re.compile(r'(?:^|\.)(?:docs\.google\.com|drive\.google\.com|sites\.google\.com|dropbox\.com|'
                          r'dropboxusercontent\.com|box\.com|onedrive\.live\.com|1drv\.ms|sharepoint\.com|'
                          r'scribd\.com|slideshare\.net|issuu\.com|academia\.edu|coursehero\.com|studocu\.com)$', re.I)
PRIVATE_TEXT = re.compile(r'confidential|do not distribute|not for distribution|internal use only|index of /', re.I)


def provider():
    if os.environ.get('GOOGLE_CSE_KEY') and os.environ.get('GOOGLE_CSE_CX'):
        return 'google'
    if os.environ.get('BRAVE_API_KEY'):
        return 'brave'
    return None


def daily_cap(kind):
    p = provider()
    if not p:
        return 0
    if os.environ.get('WEB_SEARCH_DAILY', '').strip().isdigit():
        return int(os.environ['WEB_SEARCH_DAILY'])
    return DAILY[p].get(kind, 0)


def _budget(state, kind):
    b = state['cursors'].setdefault(f'web:budget:{kind}', {'day': '', 'used': 0})
    today = time.strftime('%Y-%m-%d', time.gmtime())
    if b.get('day') != today:
        b.update(day=today, used=0)
    return b


def remaining(state, kind):
    return max(0, daily_cap(kind) - _budget(state, kind)['used'])


def search(state, kind, s, query, page):
    """One page of results: (kept [{url, title, snippet, host}], number of raw results; 0 at the end), or None when
    it failed or no budget is left. Every call counts against the day's budget."""
    p = provider()
    if not p or remaining(state, kind) <= 0:
        return None
    _budget(state, kind)['used'] += 1
    try:
        if p == 'google':
            r = s.get(GOOGLE, timeout=30, params={'key': os.environ['GOOGLE_CSE_KEY'], 'cx': os.environ['GOOGLE_CSE_CX'],
                                                  'q': query, 'start': 1 + 10 * page, 'num': 10, 'safe': 'active'})
            if not r.ok:
                return None
            items = r.json().get('items') or []
            out = [{'url': i.get('link') or '', 'title': i.get('title') or '', 'snippet': i.get('snippet') or ''}
                   for i in items]
        else:
            time.sleep(1.1)  # one query a second on the free plan
            r = s.get(BRAVE, timeout=30, headers={'X-Subscription-Token': os.environ['BRAVE_API_KEY'],
                                                  'Accept': 'application/json'},
                      params={'q': query, 'count': 20, 'offset': page, 'safesearch': 'strict'})
            if not r.ok:
                return None
            items = (r.json().get('web') or {}).get('results') or []
            out = [{'url': i.get('url') or '', 'title': i.get('title') or '',
                    'snippet': re.sub(r'<[^>]+>', '', i.get('description') or '')} for i in items]
    except (requests.RequestException, ValueError):
        return None
    keep = []
    for o in out:
        host = re.sub(r'^https?://([^/:]+).*$', r'\1', o['url']).lower()
        if not o['url'].startswith('https://') and not o['url'].startswith('http://'):
            continue
        if PRIVATE_HOST.search(host) or PRIVATE_TEXT.search(o['title'] + ' ' + o['snippet']):
            continue
        o['host'] = host
        keep.append(o)
    return keep, len(out)
