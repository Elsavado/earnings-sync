"""Internet Archive items under a Creative Commons licence (or public domain mark) that are recordings of meetings,
webinars, hearings or conferences about finance, budgets, accounting or investing, in English.

  Creative Commons Uploads/Internet Archive/<date> <title>/
Audio: the item's MP3/M4A/OGG, else its smallest video file (audio extracted). Transcript: the item's own
SRT/VTT when it has one, else ASR.
"""
import re
import time
from urllib.parse import quote

from . import media, topics

SEARCH = 'https://archive.org/advancedsearch.php'
QUERY = ('mediatype:(movies OR audio) AND licenseurl:*creativecommons.org* AND '
         'title:(meeting OR webinar OR webcast OR hearing OR "town hall" OR panel OR conference OR committee OR '
         'board OR session OR roundtable OR forum OR briefing OR symposium) AND '
         'title:(budget OR finance OR financial OR accounting OR audit OR investment OR investing OR pension OR '
         'retirement OR treasury OR treasurer OR fiscal OR revenue OR appropriations OR bond OR bonds OR banking OR '
         'economic OR economics OR "hedge fund" OR securities OR tax OR taxation OR capital OR FASB OR GASB OR IFRS)')
AUDIO = ('VBR MP3', '128Kbps MP3', '64Kbps MP3', 'MP3', 'M4A', 'Ogg Vorbis', 'Flac', 'WAVE')
VIDEO = ('h.264', 'h.264 IA', '512Kb MPEG4', 'MPEG4', 'Ogg Video', 'Cinepack', 'QuickTime', 'MPEG2', 'Matroska')


def _search(ctx, page, rows=200):
    params = {'q': QUERY, 'fl[]': ['identifier', 'title', 'licenseurl', 'language', 'date', 'creator'],
              'rows': rows, 'page': page, 'output': 'json', 'sort[]': 'addeddate desc'}
    for i in range(3):
        try:
            r = ctx.http.get(SEARCH, params=params, timeout=120)
            if r.ok:
                return r.json()['response']
        except Exception:  # noqa: BLE001
            pass
        time.sleep(10 * (i + 1))
    return {'docs': [], 'numFound': 0}


def _files(ctx, ident):
    r = ctx.http.get(f'https://archive.org/metadata/{ident}', timeout=120)
    r.raise_for_status()
    return r.json()


def _one(v):
    return (v[0] if isinstance(v, list) and v else v) or ''


def items(ctx, log):
    page, total = 1, None
    while True:
        res = _search(ctx, page)
        docs = res.get('docs', [])
        if total is None:
            total = res.get('numFound', 0)
            log(f'Internet Archive: {total} candidate items')
        if not docs:
            return
        for d in docs:
            ident, title = d.get('identifier'), _one(d.get('title'))
            lang = _one(d.get('language'))
            if not topics.english(title, lang or None) or not topics.finance(title) or not topics.meeting(title):
                continue
            if media.have(ctx, ident):
                continue
            yield _item(ctx, ident, title, d)
        page += 1


def _item(ctx, ident, title, d):
    lic = _one(d.get('licenseurl'))
    it = {'id': ident, 'type': 'cc', 'group': 'Internet Archive', 'org': _one(d.get('creator')) or 'Internet Archive',
          'title': title, 'date': _one(d.get('date'))[:10], 'url': f'https://archive.org/details/{ident}',
          'licence': topics.licence_name(lic) or lic, 'licence_url': lic, 'media': [],
          'meta': {'archive_identifier': ident, 'uploader_creator': _one(d.get('creator'))}}
    try:
        meta = _files(ctx, ident)
    except Exception as e:  # noqa: BLE001
        it['media'] = [('direct', f'https://archive.org/download/{ident}/__missing__')]
        it['meta']['problem'] = str(e)[:100]
        return it
    files = meta.get('files', [])
    au = sorted((f for f in files if f.get('format') in AUDIO), key=lambda f: (AUDIO.index(f['format']),))
    vi = sorted((f for f in files if f.get('format') in VIDEO), key=lambda f: int(f.get('size') or 0))
    pick = (au or vi)[:2]
    it['media'] = [('direct', f"https://archive.org/download/{ident}/{quote(f['name'])}") for f in pick]
    subs = [f for f in files if f['name'].lower().endswith(('.srt', '.vtt'))]
    subs.sort(key=lambda f: ('asr' in f['name'].lower(), f['name']))
    if subs:
        it['captions_url'] = f"https://archive.org/download/{ident}/{quote(subs[0]['name'])}"
        it['captions_how'] = 'captions file of the Internet Archive item' + \
            (' (archive.org automatic speech recognition)' if 'asr' in subs[0]['name'].lower() else '')
    md = meta.get('metadata', {})
    desc = re.sub(r'<[^>]+>', ' ', _one(md.get('description')))[:500]
    it['meta'].update({'description': desc.strip(), 'collection': md.get('collection')})
    return it
