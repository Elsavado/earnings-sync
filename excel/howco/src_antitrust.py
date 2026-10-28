"""Antitrust trial exhibits the US Department of Justice published: the search-engine monopoly case (filed 2020,
tried 2023; trial and remedies exhibits), the advertising-technology case (filed 2023, tried 2024; trial and
remedies exhibits) and the 1998-2002 operating-system and browser case (trial and remedies exhibits). Only
exhibits about business and money are kept; scanned pages without text are skipped. (Exhibits of FTC v. Meta and
Epic v. Apple were not found published as a public list, so they are not collected.)

  Antitrust Trial Exhibits/<case>/Folder K (Documents a-b)/<n> - <exhibit>.<ext>
"""
import re

from . import docs

CASES = [('Search engine monopoly case (2020-2025)',
          ['https://www.justice.gov/atr/us-and-plaintiff-states-v-google-llc-2020-trial-exhibits',
           'https://www.justice.gov/atr/us-and-plaintiff-states-v-google-llc-2020-remedies-hearing-exhibits']),
         ('Advertising technology case (2023-2025)',
          ['https://www.justice.gov/atr/us-and-plaintiff-states-v-google-llc-2023-trial-exhibits',
           'https://www.justice.gov/atr/us-and-plaintiff-states-v-google-llc-2023-remedies-hearing-exhibits']),
         ('Operating system and browser case (1998-2002)',
          ['https://www.justice.gov/atr/cases/ms_exhibits.htm', 'https://www.justice.gov/atr/cases/ms_remedyexhibits.htm'])]


def discover(ctx, s, log):
    for group, seeds in CASES:
        n = 0
        allow = '|'.join('^' + re.escape(u) + r'(?:\?page=\d+)?$' for u in seeds)
        for url, text, page in docs.crawl(s, seeds, allow, max_pages=400):
            if 'justice.gov' not in url:
                continue
            n += 1
            yield {'url': url, 'group': group, 'title': docs.title_of(url, text)}
        log(f'{group}: {n} exhibits listed')


def run(ctx, log):
    docs.run(ctx, log, discover, business_only=True)
