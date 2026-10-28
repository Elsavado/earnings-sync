"""Financial Crisis Inquiry Commission records (public domain): the NARA release of the Commission's records as
hosted by Stanford Law (interview memos, business meeting agendas, response letters, agreements; 506 files) and the
documents of the Stanford FCIC resource library (fcic.law.stanford.edu). Audio interviews are left out: spoken
names cannot be replaced.

  Financial Crisis Inquiry Commission/<series>/Folder K (Documents a-b)/<n> - <title>.<ext>
"""
import re
from urllib.parse import unquote, urlparse

from . import docs

NARA = 'https://fcic-static.law.stanford.edu/NARA.FCIC.2016-03-11/'
LIBRARY = ['https://fcic.law.stanford.edu/resource', 'https://fcic.law.stanford.edu/hearings',
           'https://fcic.law.stanford.edu/report']
SERIES = {'SCREENED Interviews': 'Interviews', 'BusMtgsAgnds_SCREENED': 'Business meetings and agendas',
          'Response Letters SCREENED': 'Response letters', 'ConfidAgrmts (NonGov)': 'Agreements (non-government)',
          'ConfidAgrmts (Gov)': 'Agreements (government)'}


def discover(ctx, s, log):
    n = 0
    for url, text, page in docs.crawl(s, [NARA], r'^https://fcic-static\.law\.stanford\.edu/NARA\.FCIC\.2016-03-11/'):
        part = unquote(url[len(NARA):]).split('/')[0] if url.startswith(NARA) else ''
        n += 1
        yield {'url': url, 'group': SERIES.get(part, 'Commission records'), 'title': docs.title_of(url)}
    log(f'NARA release: {n} documents listed')
    n = 0
    for url, text, page in docs.crawl(s, LIBRARY, r'^https?://fcic\.law\.stanford\.edu/(?:resource|hearings|report|'
                                      r'interviews|documents)', max_pages=4000):
        if not re.search(r'(?:^|\.)stanford\.edu$', urlparse(url).netloc):
            continue
        n += 1
        yield {'url': url, 'group': 'Resource library', 'title': docs.title_of(url, text)}
    log(f'resource library: {n} documents listed')


def run(ctx, log):
    docs.run(ctx, log, discover)
