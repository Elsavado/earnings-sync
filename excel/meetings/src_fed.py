"""Federal Reserve Board: FOMC Chair press conferences (2011 on) and open Board meetings (2017 on). The video is the
Board's own Brightcove player (not YouTube); the Board's official transcript PDF goes alongside when it exists.

  Public Finance Meetings/Federal Reserve Board/<date> FOMC press conference/
  Public Finance Meetings/Federal Reserve Board/<date> Open Board meeting/
Licence: works of the US federal government (public domain).
"""
import re
import time

from . import media

BASE = 'https://www.federalreserve.gov'
PLAYER = 'https://players.brightcove.net/{acct}/default_default/index.html?videoId={vid}'
LIC = 'Public domain (US federal government work)'


def _get(ctx, url):
    for i in range(3):
        try:
            r = ctx.http.get(url, timeout=60)
            if r.status_code == 404:
                return ''
            if r.ok:
                return r.text
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5 * (i + 1))
    return ''


def _item(ctx, page, kind, date):
    text = _get(ctx, BASE + page)
    vid = re.search(r'video-id="(\d+)"', text)
    if not vid:
        return None
    acct = re.search(r'data-account="(\d+)"', text)
    pdf = re.search(r'href="([^"]*(?:FOMCpresconf\d+|open-board-meeting-transcript-\d+)\.pdf)"', text, re.I)
    d = f'{date[:4]}-{date[4:6]}-{date[6:8]}'
    it = {'id': f'fed:{page}', 'type': 'public', 'org': 'Federal Reserve Board', 'title': kind, 'date': d,
          'url': BASE + page, 'licence': LIC,
          'media': [('ytdlp', PLAYER.format(acct=acct.group(1) if acct else '66043936001', vid=vid.group(1)))],
          'meta': {'country': 'US', 'brightcove_video_id': vid.group(1)}}
    if pdf:
        it['extra_files'] = [('official-transcript.pdf', BASE + pdf.group(1) if pdf.group(1).startswith('/') else pdf.group(1))]
        it['meta']['official_transcript'] = 'official-transcript.pdf (the Board\'s transcript, no timings)'
    return it


def items(ctx, log):
    pages = set()
    for url in [BASE + '/monetarypolicy/fomccalendars.htm'] + \
               [f'{BASE}/monetarypolicy/fomchistorical{y}.htm' for y in range(2011, time.gmtime().tm_year)]:
        pages |= {(p, 'FOMC press conference', p[-12:-4]) for p in re.findall(r'(/monetarypolicy/fomcpresconf\d{8}\.htm)',
                                                                             _get(ctx, url))}
    for y in range(2017, time.gmtime().tm_year + 1):
        for page in (f'{y}-board-meetings', f'{y}-board-meeting', f'{y}-boardmeeting'):
            t = _get(ctx, f'{BASE}/aboutthefed/boardmeetings/{page}.htm')
            if t:
                pages |= {(p, 'Open Board meeting', re.search(r'(\d{8})', p).group(1))
                          for p in re.findall(r'(/aboutthefed/boardmeetings/\d{8}open\.htm)', t)}
                break
    log(f'Federal Reserve: {len(pages)} press conference and open meeting pages')
    for page, kind, date in sorted(pages, key=lambda x: x[2], reverse=True):  # newest first
        if media.have(ctx, f'fed:{page}'):
            continue
        it = _item(ctx, page, kind, date)
        if it:
            yield it
