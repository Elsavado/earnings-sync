"""The Lehman Brothers bankruptcy examiner's report (Valukas, 2010; filed in the U.S. Bankruptcy Court, S.D.N.Y.):
the volumes and appendices, from the public copy at web.stanford.edu/~jbulow/lehmandocs/ (the law firm's own site
refuses automated visitors, so it is not used).

  Investment Bank Bankruptcy Examiner/Report volumes and appendices/Folder K (Documents a-b)/<n> - <title>.pdf
"""
from . import docs

SEEDS = ['https://web.stanford.edu/~jbulow/lehmandocs/']


def discover(ctx, s, log):
    n = 0
    for url, text, page in docs.crawl(s, SEEDS, r'^https://web\.stanford\.edu/~jbulow/lehmandocs/', max_pages=50):
        n += 1
        yield {'url': url, 'group': 'Report volumes and appendices', 'title': docs.title_of(url, text)}
    log(f'{n} documents listed')


def run(ctx, log):
    docs.run(ctx, log, discover)
