"""YouTube sources (yt-dlp). Three kinds share this module:

  ytpublic   public finance bodies: SEC, standard setters (FASB, GASB, IFRS/IASB, PCAOB, AICPA), pension funds
             (CalPERS, CalSTRS, NYSTRS, Ontario Teachers'), treasurers and budget committees
             -> Public Finance Meetings/<organisation>/
  ytcompany  company investor days, capital markets days and finance webinars
             -> Company Webinars and Investor Days/<channel>/   licence "publicly posted (copyright of owner)"
  ytcc       videos under YouTube's Creative Commons licence (CC BY 3.0) found with the CC search filter
             -> Creative Commons Uploads/YouTube/

Transcript: captions uploaded with the video, else YouTube auto-captions, else ASR. GitHub runner addresses are
often refused by YouTube ("Sign in to confirm you're not a bot"): that is detected, counted and reported, and the
source stops for the run once every download so far was refused. A cookies file (secret YT_COOKIES) is used when
present.
"""
import re
from urllib.parse import quote_plus

from . import media, topics

CC_FILTER = 'EgIwAQ%253D%253D'  # YouTube search filter "Creative Commons"
FED_PD = 'Public domain (US federal government work)'
PUB = 'Public record (government meeting recording)'
OWNER = 'publicly posted (copyright of owner)'

# (address, organisation, licence, country)
CHANNELS = [
    ('https://www.youtube.com/user/SECViews/videos', 'U.S. Securities and Exchange Commission', FED_PD, 'US'),
    ('https://www.youtube.com/playlist?list=PLIKoYJoLyluIPk7gLPyYqQw-UycQuBMHc', 'CalPERS', PUB, 'US'),
    ('https://www.youtube.com/@CalPERS/videos', 'CalPERS', PUB, 'US'),
    ('https://www.youtube.com/@CalSTRS/videos', 'CalSTRS', PUB, 'US'),
    ('https://www.youtube.com/@NYSTRS/videos', 'NYSTRS', PUB, 'US'),
    ('https://www.youtube.com/@IFRSFoundation/videos', 'IFRS Foundation', OWNER, 'International'),
    ('https://www.youtube.com/@FASBorg/videos', 'FASB', OWNER, 'US'),
    ('https://www.youtube.com/@GASBorg/videos', 'GASB', OWNER, 'US'),
    ('https://www.youtube.com/@PCAOB/videos', 'PCAOB', OWNER, 'US'),
    ('https://www.youtube.com/@AICPA/videos', 'AICPA', OWNER, 'US'),
    ('https://www.youtube.com/@OntarioTeachers/videos', "Ontario Teachers' Pension Plan", OWNER, 'Canada'),
]
# searches for public bodies; a result is kept only when its channel looks like the body (OFFICIAL)
PUBLIC_SEARCHES = [
    'SEC open meeting', 'SEC investor advisory committee meeting', 'FASB board meeting', 'GASB board meeting',
    'IASB board meeting', 'IFRS Interpretations Committee meeting', 'ISSB meeting', 'PCAOB board meeting',
    'PCAOB standing advisory group', 'AICPA webcast', 'CalPERS board meeting', 'CalPERS investment committee',
    'CalSTRS investment committee meeting', 'CalSTRS board meeting', 'NYSTRS board meeting',
    'state treasurer investment board meeting', 'state investment board meeting', 'pension board of trustees meeting',
    'retirement system board meeting', 'city council budget committee meeting', 'county board of supervisors budget hearing',
    'city finance committee meeting', 'legislature appropriations committee hearing', 'ways and means committee hearing budget',
    'Bank of Canada press conference', 'Ontario budget committee', 'Toronto budget committee meeting',
    'municipal finance officers webinar', 'GFOA webinar',
]
OFFICIAL = re.compile(r'\b(?:SEC|Securities and Exchange|FASB|Financial Accounting|GASB|Governmental Accounting|IFRS|'
                      r'IASB|PCAOB|AICPA|CalPERS|CalSTRS|NYSTRS|Teachers|Pension|Retirement|Treasur\w*|City|County|'
                      r'State|Council|Government|Legislat\w*|Senate|Assembly|House|Gov|TV|Channel \d+|Bank of Canada|'
                      r'Ontario|Toronto|Board|Commission|Department|GFOA|Municipal|Public)\b', re.I)
COMPANY_SEARCHES = [
    'investor day 2026', 'investor day 2025', 'investor day 2024', 'capital markets day 2025', 'capital markets day 2024',
    'analyst day 2025', 'analyst and investor day', 'investor day full webcast', 'investor update webcast',
    'Dbriefs webcast financial reporting', 'financial reporting webcast accounting update', 'IFRS webinar',
    'CFO webinar finance', 'audit committee webinar', 'hedge fund webinar', 'asset management webinar outlook',
    'private equity webinar', 'treasury management webinar', 'FP&A webinar', 'financial modeling webinar',
]
COMPANY_TITLE = re.compile(r'\b(?:investor day|capital markets? day|analyst day|investor (?:update|meeting|event|'
                           r'conference)|webinar|webcast|dbriefs|virtual (?:event|session)|live event)\b', re.I)
CC_SEARCHES = [
    'accounting webinar', 'finance webinar', 'financial reporting webinar', 'IFRS webinar', 'GAAP update webinar',
    'audit webinar', 'investment committee meeting', 'budget committee meeting', 'finance committee meeting',
    'city council budget hearing', 'budget workshop meeting', 'pension board meeting', 'board of finance meeting',
    'school board finance committee meeting', 'treasurer meeting', 'hedge fund panel', 'financial analysis webinar',
    'investing webinar', 'economic outlook webinar', 'municipal budget meeting', 'retirement board meeting',
    'capital budget meeting', 'audit committee meeting', 'tax webinar', 'personal finance webinar',
]
MIN_SECS = {'public': 600, 'company': 900, 'cc': 600}


def _date(info):
    d = info.get('upload_date') or info.get('release_date') or ''
    return f'{d[:4]}-{d[4:6]}-{d[6:8]}' if len(d) == 8 else ''


def _check(kind):
    def check(info):
        title = info.get('title') or ''
        if info.get('live_status') in ('is_live', 'is_upcoming', 'post_live'):
            raise media.Skip('live or upcoming')
        if info.get('duration') and info['duration'] < MIN_SECS[kind]:
            raise media.Skip('too short')
        if not topics.english(title, info.get('language')):
            raise media.Skip('not English')
        if kind == 'cc' and 'creative commons' not in (info.get('license') or '').lower():
            raise media.Skip(f'not Creative Commons ({info.get("license")})')
    return check


def _from_info(kind, org=None):
    def upd(info):
        out = {'title': info.get('title'), 'date': _date(info),
               'youtube_id': info.get('id'), 'youtube_channel': info.get('channel') or info.get('uploader'),
               'youtube_channel_url': info.get('channel_url'), 'youtube_license': info.get('license')}
        if kind != 'public' or not org:
            out['organisation'] = info.get('channel') or info.get('uploader')
        if kind == 'cc':
            out['licence'] = 'CC BY 3.0 (YouTube Creative Commons Attribution licence)'
            out['licence_url'] = 'https://creativecommons.org/licenses/by/3.0/'
        return out
    return upd


def _item(kind, e, org, licence, country, group):
    vid = e.get('id')
    url = f'https://www.youtube.com/watch?v={vid}'
    return {'id': f'yt:{vid}', 'type': kind, 'org': org, 'group': group, 'title': e.get('title'), 'date': '',
            'url': url, 'licence': licence, 'media': [('ytdlp', url)], 'check': _check(kind),
            'from_info': _from_info(kind, org), 'youtube_only': True,
            'meta': {'country': country, 'youtube_id': vid}}


def _listing(url, log, limit=150):
    try:
        return media.listing(url, limit)
    except Exception as e:  # noqa: BLE001
        log(f'  could not list {url}: {type(e).__name__}: {str(e)[:200]}')
        return []


def _wanted(kind, e):
    title = e.get('title') or ''
    if e.get('duration') and e['duration'] < MIN_SECS[kind]:
        return False
    if not e.get('id') or not topics.english(title):
        return False
    if kind == 'public':
        return topics.meeting(title) or topics.finance(title)
    if kind == 'company':
        return bool(COMPANY_TITLE.search(title)) and topics.finance(title)
    return topics.finance(title) and topics.meeting(title)


def items(ctx, log, kind):
    seen = set()

    def fresh(e):
        if e.get('id') in seen or media.have(ctx, f'yt:{e.get("id")}'):
            return False
        seen.add(e.get('id'))
        return _wanted(kind, e)

    if kind == 'public':
        for url, org, lic, country in CHANNELS:
            entries = _listing(url, log)
            log(f'{org}: {len(entries)} videos listed')
            for e in entries:
                if fresh(e) and (topics.meeting(e.get('title')) or org in ('U.S. Securities and Exchange Commission',)):
                    yield _item('public', e, org, lic, country, org)
        for q in PUBLIC_SEARCHES:
            for e in _listing(f'ytsearch40:{q}', log, 40):
                ch = e.get('channel') or e.get('uploader') or ''
                if ch and OFFICIAL.search(ch) and fresh(e) and topics.finance(e.get('title'), q):
                    lic = FED_PD if re.search(r'Securities and Exchange|\bSEC\b', ch) else \
                        (OWNER if re.search(r'FASB|GASB|IFRS|IASB|PCAOB|AICPA|Teachers', ch, re.I) else PUB)
                    country = 'Canada' if re.search(r'Canada|Ontario|Toronto', ch + q) else 'US'
                    yield _item('public', e, ch, lic, country, ch)
    elif kind == 'company':
        for q in COMPANY_SEARCHES:
            for e in _listing(f'ytsearch40:{q}', log, 40):
                if fresh(e):
                    ch = e.get('channel') or e.get('uploader') or 'Unknown channel'
                    yield _item('company', e, ch, OWNER, '', ch)
    else:
        for q in CC_SEARCHES:
            for e in _listing(f'https://www.youtube.com/results?search_query={quote_plus(q)}&sp={CC_FILTER}', log, 60):
                if fresh(e):
                    yield _item('cc', e, e.get('channel') or e.get('uploader') or 'YouTube', 'CC BY 3.0 (YouTube)',
                                '', 'YouTube')
