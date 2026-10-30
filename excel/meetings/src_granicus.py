"""City, county and state budget / finance / audit / pension committee meetings on Granicus (the archive most US
local governments use). Each site's on-demand views are read (ViewPublisher pages; the podcast feed for the newest
clips); only meetings whose committee or title is about finance are kept. Audio is Granicus's own MP3 (else the
MP4 or the stream); the transcript is the meeting's closed captions (videos/<clip>/captions.vtt), else ASR.

  Public Finance Meetings/<government>/<date> <committee meeting>/
Licence: public record (government meeting recording).
"""
import datetime
import html
import re
import time

from . import topics

SITES = ['sanfrancisco', 'lacity', 'oakland', 'phoenix', 'sacramento', 'sandiego', 'sanjose', 'seattle', 'houston',
         'denver', 'lacounty', 'boston', 'dc', 'detroit', 'atlanta', 'miamidade', 'nashville', 'pittsburgh',
         'columbus', 'cincinnati', 'stpaul', 'minneapolis', 'baltimore', 'austin', 'cityofmadison', 'longbeach',
         'fresno', 'santaclara', 'sanmateocounty', 'alamedacounty', 'sonoma', 'pasadena', 'berkeley',
         'santamonica', 'tampa', 'orlando', 'charlotte', 'raleigh', 'richmond', 'norfolk', 'kcmo', 'stlouis',
         'milwaukee', 'louisville', 'memphis', 'okc', 'tulsa', 'albuquerque', 'tucson', 'mesa', 'elpaso',
         'sanantonio', 'fortworth', 'arlington', 'portland', 'spokane', 'tacoma', 'boise', 'saltlakecity', 'reno',
         'lasvegas', 'clarkcounty', 'honolulu', 'anchorage', 'hartford', 'providence', 'newark', 'jerseycity',
         'buffalo', 'rochester', 'syracuse', 'albany', 'nyassembly', 'ilga', 'mnsenate', 'wisconsin']
MAX_VIEW = 40
FIN_NAME = re.compile(r'\b(?:budget|financ\w*|audit|pension|retirement|investment|treasur\w*|fiscal|revenue|'
                      r'appropriations?|ways and means|taxation|controller|comptroller|bond)\b', re.I)
LIC = 'Public record (government meeting recording)'


def _get(ctx, url, tries=2):
    for i in range(tries):
        try:
            r = ctx.http.get(url, timeout=60, allow_redirects=False)
            return r.status_code, r.text
        except Exception:  # noqa: BLE001
            time.sleep(3 * (i + 1))
    return 0, ''


def _strip(s):
    return re.sub(r'\s+', ' ', html.unescape(html.unescape(re.sub(r'<[^>]+>', ' ', s)))).strip()


def _view_title(page):
    for pat in (r'<h3[^>]*>(.*?)</h3>', r'<h1 style="color:#fff;">(.*?)</h1>', r'<h2[^>]*>(.*?)</h2>',
                r'<title>(.*?)</title>'):
        m = re.search(pat, page, re.S | re.I)
        if m and _strip(m.group(1)):
            return _strip(m.group(1))
    return ''


def _rows(page):
    """(clip id, name, date, mp3, mp4) of a ViewPublisher page."""
    out = []
    for chunk in re.split(r'<tr\b', page)[1:]:
        clip = re.search(r'clip_id=(\d+)', chunk)
        if not clip:
            continue
        name = ''
        m = re.search(r'<td[^>]*headers="[^"]*Name[^"]*"[^>]*>(.*?)</td>', chunk, re.S | re.I)
        if m:
            name = _strip(m.group(1))
        if not name:
            m = re.search(r'headers="Date ([^"]+)"', chunk)
            if m:
                name = re.sub(r'-+', ' ', m.group(1)).strip()
        if not name:
            cells = [_strip(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', chunk, re.S)]
            name = next((c for c in cells if c and not re.match(r'^[\d/:\s\-APMhm&;nbsp]+$', c)), '')
        date = ''
        m = re.search(r'<span style="display:none;">(\d{9,11})</span>', chunk)
        if m:
            date = datetime.datetime.fromtimestamp(int(m.group(1)), datetime.timezone.utc).strftime('%Y-%m-%d')
        else:
            m = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', _strip(chunk))
            if m:
                y = int(m.group(3))
                date = f'{y + 2000 if y < 100 else y:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}'
        mp3 = re.search(r'(https?://archive-video\.granicus\.com/[^"\'\s]+\.mp3)', chunk)
        mp4 = re.search(r'(https?://archive-video\.granicus\.com/[^"\'\s]+\.mp4)', chunk)
        out.append((clip.group(1), name, date, mp3.group(1) if mp3 else None, mp4.group(1) if mp4 else None))
    return out


def _feed(ctx, site, view):
    """Podcast feed of a view: newest clips with their full titles."""
    code, xml = _get(ctx, f'https://{site}.granicus.com/Podcast.php?view_id={view}')
    out = []
    for it in re.findall(r'<item>(.*?)</item>', xml or '', re.S):
        clip = re.search(r'clip_id=(\d+)', it)
        title = re.search(r'<title>(.*?)</title>', it, re.S)
        enc = re.search(r"<enclosure url=['\"]([^'\"]+)", it)
        d = re.search(r"yr='(\d+)' mo='(\d+)' day='(\d+)'", it)
        if clip:
            url = enc.group(1) if enc else None
            out.append((clip.group(1), _strip(title.group(1)) if title else '',
                        f'{int(d.group(1)):04d}-{int(d.group(2)):02d}-{int(d.group(3)):02d}' if d else '',
                        url if url and url.endswith('.mp3') else None, url if url and url.endswith('.mp4') else None))
    return out


def _discover(ctx, log):
    """{site: {'name', 'views': {view id: title}}}, cached in the state for 30 days."""
    cache = ctx.state.setdefault('granicus', {})
    if cache.get('when', 0) > time.time() - 30 * 86400 and cache.get('sites'):
        return cache['sites']
    sites = {}
    for site in SITES:
        code, _ = _get(ctx, f'https://{site}.granicus.com/ViewPublisher.php?view_id=1', tries=1)
        if code in (0, 301, 302):
            continue  # no such Granicus site
        views, misses, gov, any_clips = {}, 0, '', False
        for v in range(1, MAX_VIEW + 1):
            code, page = _get(ctx, f'https://{site}.granicus.com/ViewPublisher.php?view_id={v}')
            if code != 200 or 'clip_id=' not in page:
                misses += 1
                if misses >= (8 if any_clips else 12):
                    break
                continue
            misses, any_clips = 0, True
            title = _view_title(page)
            gm = re.search(r'<title>(.*?)</title>', page, re.S)
            gov = gov or (_strip(gm.group(1)) if gm else site)
            rows = _rows(page)
            if FIN_NAME.search(title) or any(FIN_NAME.search(r[1]) for r in rows):
                views[str(v)] = title
        if views:
            sites[site] = {'name': gov, 'views': views}
            log(f'Granicus {site} ({gov}): finance views {views}')
    cache.update(when=time.time(), sites=sites)
    return sites


def items(ctx, log):
    sites = _discover(ctx, log)
    log(f'Granicus: {len(sites)} sites with finance meetings')
    seen = set()
    # newest clips of every site first (podcast feeds), then the full archives
    for full in (False, True):
        for site, info in sites.items():
            for view, vtitle in info['views'].items():
                if full:
                    code, page = _get(ctx, f'https://{site}.granicus.com/ViewPublisher.php?view_id={view}')
                    rows = _rows(page) if code == 200 else []
                else:
                    rows = _feed(ctx, site, view)
                for clip, name, date, mp3, mp4 in rows:
                    if clip in seen:
                        continue
                    title = name or vtitle
                    if not (FIN_NAME.search(title) or FIN_NAME.search(vtitle)) or not topics.english(title):
                        continue
                    if not mp3 and not mp4:
                        continue
                    seen.add(clip)
                    base = (mp3 or mp4).rsplit('/', 1)[-1].rsplit('.', 1)[0]
                    mediae = [('direct', mp3)] if mp3 else []
                    mediae += [('direct', mp4 or mp3[:-4] + '.mp4'),
                               ('stream', f'https://archive-stream.granicus.com/OnDemand/_definst_/mp4:archive/{site}/'
                                          f'{base}.mp4/playlist.m3u8')]
                    yield {'id': f'{site}:{clip}', 'type': 'public', 'org': info['name'],
                           'title': re.sub(r'\s*-\s*[A-Z][a-z]{2} \d{1,2}, \d{4}$', '', title), 'date': date,
                           'url': f'https://{site}.granicus.com/MediaPlayer.php?view_id={view}&clip_id={clip}',
                           'licence': LIC, 'media': mediae,
                           'captions_url': f'https://{site}.granicus.com/videos/{clip}/captions.vtt',
                           'captions_how': 'closed captions published with the meeting video (Granicus)',
                           'meta': {'country': 'US', 'committee': vtitle, 'granicus_site': site,
                                    'agenda_url': f'https://{site}.granicus.com/AgendaViewer.php?view_id={view}&clip_id={clip}'}}
