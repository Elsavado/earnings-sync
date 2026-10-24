"""Steam: catalogue, game details, DLC, reviews over time, update timelines, regional prices, concurrent players and
the hardware survey. Only public endpoints; requests are paced and retried."""
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

from .out import BENCH, DEV, MARKETING, MONEY, PLATFORMS, PLAYERS, Table, log, person_free  # noqa: F401

S = requests.Session()
S.headers['User-Agent'] = 'Mozilla/5.0 (research data collection)'
COUNTRIES = ['us', 'gb', 'de', 'fr', 'br', 'jp', 'kr', 'cn', 'in', 'au', 'ca', 'mx', 'pl', 'za', 'id', 'tr']
IAP, MULTI, COOP, PVP, ONLINE_PVP, ONLINE_COOP, MMO_GENRE, F2P_GENRE, EA_GENRE = 35, 1, 9, 49, 36, 38, '29', '37', '70'
LAST = {}


def get(url, params=None, gap=0.0, key='default', tries=6):
    """GET with a minimum gap between calls of the same key and back-off on 429/5xx."""
    for i in range(tries):
        wait = LAST.get(key, 0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        LAST[key] = time.time()
        try:
            r = S.get(url, params=params, timeout=60)
        except requests.RequestException:
            time.sleep(5 * (i + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(300, 30 * (i + 1)))
            continue
        return r
    return None


def js(r):
    """The JSON body of a response, or None when the call failed or the body is not JSON."""
    try:
        return r.json() if r is not None and r.ok else None
    except ValueError:
        return None


def today():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _owners(rng):
    nums = [int(x.replace(',', '').strip()) for x in re.findall(r'[\d,]+', rng or '')]
    return (nums[0], nums[1]) if len(nums) == 2 else (None, None)


# ---------------------------------------------------------------- catalogue
def catalog(out, limit_pages=None):
    apps, page = [], 0
    while limit_pages is None or page < limit_pages:
        r = get('https://steamspy.com/api.php', {'request': 'all', 'page': page}, gap=61, key='steamspy')
        if r is None or not r.ok:
            break
        try:
            data = r.json()
        except ValueError:  # past the last page SteamSpy answers with an empty, non-JSON body
            break
        if not data:
            break
        apps += list(data.values())
        log(f'  steamspy page {page}: {len(apps)} apps')
        page += 1
    d = today()
    rows = []
    for a in apps:
        lo, hi = _owners(a.get('owners'))
        rows.append({
            'appid': a['appid'], 'name': a.get('name'), 'developer': person_free(a.get('developer')),
            'publisher': person_free(a.get('publisher')), 'owners_range': a.get('owners'), 'owners_low': lo, 'owners_high': hi,
            'owners_mid': (lo + hi) // 2 if lo is not None else None,
            'price_usd': int(a.get('price') or 0) / 100, 'initial_price_usd': int(a.get('initialprice') or 0) / 100,
            'discount_pct': int(a.get('discount') or 0), 'reviews_positive': a.get('positive'), 'reviews_negative': a.get('negative'),
            'peak_ccu_yesterday': a.get('ccu'), 'avg_playtime_forever_h': round((a.get('average_forever') or 0) / 60, 2),
            'avg_playtime_2w_h': round((a.get('average_2weeks') or 0) / 60, 2),
            'median_playtime_forever_h': round((a.get('median_forever') or 0) / 60, 2),
            'median_playtime_2w_h': round((a.get('median_2weeks') or 0) / 60, 2), 'snapshot_date': d})
    if not rows:
        raise RuntimeError('SteamSpy returned nothing')
    rows.sort(key=lambda r: -((r['reviews_positive'] or 0) + (r['reviews_negative'] or 0)))
    ident = [('appid', 'Steam application id'), ('name', 'Game name'), ('developer', 'Developer'), ('publisher', 'Publisher'),
             ('price_usd', 'Current US price, USD'), ('initial_price_usd', 'Undiscounted US price, USD'),
             ('discount_pct', 'Discount on the snapshot date, %'), ('snapshot_date', 'Date of the snapshot (UTC)')]
    out.table(f'{PLATFORMS}/Steam Catalogue', 'steam_catalogue', Table(
        'Steam catalogue', ident + [('owners_range', 'Estimated owners band'), ('reviews_positive', 'Positive reviews'),
                                    ('reviews_negative', 'Negative reviews')], rows,
        'Every Steam application with an owners estimate, ordered by number of reviews.'))
    eng = [('appid', 'Steam application id'), ('name', 'Game name'), ('owners_low', 'Owners band, low end'),
           ('owners_high', 'Owners band, high end'), ('owners_mid', 'Midpoint of the owners band'),
           ('peak_ccu_yesterday', 'Peak concurrent players on the day before the snapshot'),
           ('avg_playtime_forever_h', 'Average lifetime playtime per owner, hours'),
           ('median_playtime_forever_h', 'Median lifetime playtime per owner, hours'),
           ('avg_playtime_2w_h', 'Average playtime in the last two weeks, hours'),
           ('median_playtime_2w_h', 'Median playtime in the last two weeks, hours'), ('snapshot_date', 'Snapshot date (UTC)')]
    out.table(f'{PLAYERS}/Steam Owners & Playtime', f'steam_owners_playtime_{d}', Table(
        'Steam owners and playtime', eng, rows, 'Engagement snapshot per game; one file per snapshot builds the history.'))
    out.save_state('catalog', [{k: r[k] for k in ('appid', 'name', 'reviews_positive', 'reviews_negative', 'peak_ccu_yesterday',
                                                  'price_usd', 'owners_mid')} for r in rows])
    return rows


def top(out, n, by='reviews'):
    cat = out.state('catalog')
    if not cat:
        raise RuntimeError('no catalogue yet: run the catalog job first')
    if by == 'ccu':
        cat = sorted(cat, key=lambda r: -(r['peak_ccu_yesterday'] or 0))
    return cat[:n]


# ---------------------------------------------------------------- game details and DLC
def details(out, n=5000):
    games, dlc_parent = [], {}
    for i, app in enumerate(top(out, n)):
        r = get('https://store.steampowered.com/api/appdetails', {'appids': app['appid'], 'cc': 'us', 'l': 'english'},
                gap=1.5, key='store')
        if r is None or not r.ok:
            continue
        d = (js(r) or {}).get(str(app['appid'])) or {}
        if not d.get('success'):
            continue
        d = d['data']
        cats = {c['id'] for c in d.get('categories') or []}
        genres = [g['description'] for g in d.get('genres') or []]
        gids = {str(g['id']) for g in d.get('genres') or []}
        price = d.get('price_overview') or {}
        langs = re.sub(r'<[^>]+>', '', d.get('supported_languages') or '')
        for x in d.get('dlc') or []:
            dlc_parent[x] = (app['appid'], d.get('name'))
        games.append({
            'appid': app['appid'], 'name': d.get('name'), 'type': d.get('type'), 'is_free': d.get('is_free'),
            'release_date': (d.get('release_date') or {}).get('date'), 'coming_soon': (d.get('release_date') or {}).get('coming_soon'),
            'developers': person_free('; '.join(d.get('developers') or [])), 'publishers': person_free('; '.join(d.get('publishers') or [])),
            'primary_genre': genres[0] if genres else None, 'genres': '; '.join(genres),
            'categories': '; '.join(c['description'] for c in d.get('categories') or []),
            'windows': (d.get('platforms') or {}).get('windows'), 'mac': (d.get('platforms') or {}).get('mac'),
            'linux': (d.get('platforms') or {}).get('linux'), 'metacritic': (d.get('metacritic') or {}).get('score'),
            'required_age': d.get('required_age'), 'controller_support': d.get('controller_support'),
            'languages': len([x for x in langs.split(',') if x.strip()]), 'achievements': (d.get('achievements') or {}).get('total'),
            'recommendations': (d.get('recommendations') or {}).get('total'), 'dlc_count': len(d.get('dlc') or []),
            'price_usd': (price.get('final') or 0) / 100 if price else (0 if d.get('is_free') else None),
            'initial_price_usd': (price.get('initial') or 0) / 100 if price else None,
            'has_in_app_purchases': IAP in cats, 'multiplayer': bool(cats & {MULTI, PVP, ONLINE_PVP, COOP, ONLINE_COOP}),
            'online_pvp': ONLINE_PVP in cats, 'online_coop': ONLINE_COOP in cats, 'mmo': MMO_GENRE in gids,
            'free_to_play_genre': F2P_GENRE in gids, 'early_access': EA_GENRE in gids})
        if i % 250 == 0:
            log(f'  details {i}/{n}')
    cols = [(k, v) for k, v in [
        ('appid', 'Steam application id'), ('name', 'Game name'), ('type', 'Store item type'), ('is_free', 'Free to play'),
        ('release_date', 'Release date as shown on the store'), ('coming_soon', 'Not released yet'), ('developers', 'Developers'),
        ('publishers', 'Publishers'), ('primary_genre', 'First listed genre'), ('genres', 'All genres'), ('categories', 'Store features'),
        ('windows', 'Runs on Windows'), ('mac', 'Runs on macOS'), ('linux', 'Runs on Linux / Steam Deck OS'),
        ('metacritic', 'Metacritic score'), ('required_age', 'Minimum age'), ('controller_support', 'Controller support'),
        ('languages', 'Number of supported languages'), ('achievements', 'Number of achievements'),
        ('recommendations', 'Total user recommendations'), ('dlc_count', 'Number of DLC items'), ('price_usd', 'Current US price'),
        ('initial_price_usd', 'Undiscounted US price'), ('has_in_app_purchases', 'Sells in-game items'),
        ('multiplayer', 'Has any multiplayer mode'), ('online_pvp', 'Online player-versus-player'), ('online_coop', 'Online co-op'),
        ('mmo', 'Massively multiplayer'), ('free_to_play_genre', 'Tagged free to play'), ('early_access', 'In early access')]]
    out.table(f'{PLATFORMS}/Steam Game Details', 'steam_game_details', Table(
        'Steam game details', cols, games, f'Store details of the {len(games):,} most-reviewed games.'))
    out.save_state('details', [{k: g[k] for k in ('appid', 'name', 'primary_genre', 'is_free', 'has_in_app_purchases',
                                                  'multiplayer', 'release_date', 'price_usd', 'publishers')} for g in games])
    # DLC prices (batched)
    ids = list(dlc_parent)
    rows = []
    for k in range(0, len(ids), 100):
        batch = ids[k:k + 100]
        r = get('https://store.steampowered.com/api/appdetails', {'appids': ','.join(map(str, batch)), 'cc': 'us',
                                                                   'filters': 'price_overview'}, gap=1.5, key='store')
        js_ = js(r) or {}
        for x in batch:
            p = ((js_.get(str(x)) or {}).get('data') or {})
            p = p.get('price_overview') if isinstance(p, dict) else None
            rows.append({'dlc_appid': x, 'parent_appid': dlc_parent[x][0], 'parent_name': dlc_parent[x][1],
                         'price_usd': (p or {}).get('final', 0) / 100 if p else None,
                         'initial_price_usd': (p or {}).get('initial', 0) / 100 if p else None,
                         'discount_pct': (p or {}).get('discount_percent') if p else None, 'snapshot_date': today()})
    out.table(f'{MONEY}/Steam DLC Catalogue', 'steam_dlc_prices', Table(
        'Steam DLC and prices', [('dlc_appid', 'DLC application id'), ('parent_appid', 'Base game id'), ('parent_name', 'Base game'),
                                 ('price_usd', 'Current US price'), ('initial_price_usd', 'Undiscounted US price'),
                                 ('discount_pct', 'Discount %'), ('snapshot_date', 'Snapshot date')], rows,
        'Paid and free add-ons of the most-reviewed games.'))


# ---------------------------------------------------------------- reviews
def reviews(out, n=5000):
    totals, monthly = [], []
    for i, app in enumerate(top(out, n)):
        a = app['appid']
        r = get(f'https://store.steampowered.com/appreviews/{a}', {'json': 1, 'filter': 'all', 'language': 'all',
                                                                    'num_per_page': 0, 'purchase_type': 'all'}, gap=1.2, key='store')
        if r is not None and r.ok:
            q = (js(r) or {}).get('query_summary') or {}
            totals.append({'appid': a, 'name': app['name'], 'review_score_desc': q.get('review_score_desc'),
                           'total_positive': q.get('total_positive'), 'total_negative': q.get('total_negative'),
                           'total_reviews': q.get('total_reviews'),
                           'pct_positive': round(100 * q['total_positive'] / q['total_reviews'], 1) if q.get('total_reviews') else None,
                           'snapshot_date': today()})
        r = get(f'https://store.steampowered.com/appreviewhistogram/{a}', {'l': 'english', 'review_score_preference': 0},
                gap=1.2, key='store')
        if r is not None and r.ok:
            res = (js(r) or {}).get('results') or {}
            for x in res.get('rollups') or []:
                up, down = x.get('recommendations_up', 0), x.get('recommendations_down', 0)
                monthly.append({'appid': a, 'name': app['name'],
                                'period_start': datetime.fromtimestamp(x['date'], timezone.utc).strftime('%Y-%m-%d'),
                                'period': res.get('rollup_type'), 'positive': up, 'negative': down, 'total': up + down,
                                'pct_positive': round(100 * up / (up + down), 1) if up + down else None})
        if i % 250 == 0:
            log(f'  reviews {i}/{n}')
    out.table(f'{MARKETING}/Steam Review Totals', 'steam_review_totals', Table(
        'Steam review totals', [('appid', 'Steam application id'), ('name', 'Game'), ('review_score_desc', 'Store rating label'),
                                ('total_positive', 'Positive reviews'), ('total_negative', 'Negative reviews'),
                                ('total_reviews', 'All reviews'), ('pct_positive', 'Share positive, %'),
                                ('snapshot_date', 'Snapshot date')], totals))
    out.table(f'{MARKETING}/Steam Review Volume Over Time', 'steam_review_volume', Table(
        'Steam review volume over time', [('appid', 'Steam application id'), ('name', 'Game'),
                                          ('period_start', 'Start of the period'), ('period', 'Period length (month or week)'),
                                          ('positive', 'Positive reviews in the period'), ('negative', 'Negative reviews in the period'),
                                          ('total', 'Reviews in the period'), ('pct_positive', 'Share positive, %')], monthly,
        'Reviews per period since release: a proxy for sales and player activity over a game\'s life.'))


# ---------------------------------------------------------------- update timelines
def news(out, n=5000):
    items, cadence = [], []
    for i, app in enumerate(top(out, n)):
        r = get('https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/', {'appid': app['appid'], 'count': 1000, 'maxlength': 1},
                gap=0.3, key='api')
        if r is None or not r.ok:
            continue
        ni = [x for x in ((js(r) or {}).get('appnews') or {}).get('newsitems') or [] if x.get('feed_type') == 1]
        dates = sorted(x['date'] for x in ni)
        for x in ni:
            tags = x.get('tags') or []
            items.append({'appid': app['appid'], 'name': app['name'],
                          'date': datetime.fromtimestamp(x['date'], timezone.utc).strftime('%Y-%m-%d'),
                          'title': person_free(x.get('title')), 'patch_notes': 'patchnotes' in tags, 'url': x.get('url')})
        now = time.time()
        gaps = [(b - a) / 86400 for a, b in zip(dates, dates[1:])]
        cadence.append({'appid': app['appid'], 'name': app['name'], 'updates_total': len(dates),
                        'updates_last_365d': sum(1 for t in dates if now - t < 365 * 86400),
                        'patch_notes_last_365d': sum(1 for x in ni if 'patchnotes' in (x.get('tags') or []) and now - x['date'] < 365 * 86400),
                        'median_days_between_updates': round(statistics.median(gaps), 1) if gaps else None,
                        'first_update': datetime.fromtimestamp(dates[0], timezone.utc).strftime('%Y-%m-%d') if dates else None,
                        'last_update': datetime.fromtimestamp(dates[-1], timezone.utc).strftime('%Y-%m-%d') if dates else None})
        if i % 500 == 0:
            log(f'  news {i}/{n}')
    out.table(f'{DEV}/Steam Update Timeline', 'steam_update_timeline', Table(
        'Steam update and announcement timeline', [('appid', 'Steam application id'), ('name', 'Game'), ('date', 'Posted (UTC)'),
                                                  ('title', 'Announcement title'), ('patch_notes', 'Tagged as patch notes'),
                                                  ('url', 'Link')], items, 'Developer announcements posted on Steam.'))
    out.table(f'{DEV}/Steam Update Cadence', 'steam_update_cadence', Table(
        'Steam update cadence', [('appid', 'Steam application id'), ('name', 'Game'), ('updates_total', 'Announcements in all'),
                                 ('updates_last_365d', 'Announcements in the last 365 days'),
                                 ('patch_notes_last_365d', 'Patch notes in the last 365 days'),
                                 ('median_days_between_updates', 'Median days between announcements'),
                                 ('first_update', 'First announcement'), ('last_update', 'Latest announcement')], cadence))


# ---------------------------------------------------------------- regional prices (daily)
def prices(out, n=5000):
    apps = [a for a in top(out, n) if (a.get('price_usd') or 0) > 0]
    d = today()
    rows = []
    for cc in COUNTRIES:
        for k in range(0, len(apps), 100):
            batch = apps[k:k + 100]
            r = get('https://store.steampowered.com/api/appdetails', {'appids': ','.join(str(a['appid']) for a in batch),
                                                                       'cc': cc, 'filters': 'price_overview'}, gap=1.3, key='store')
            js_ = js(r) or {}
            for a in batch:
                p = ((js_.get(str(a['appid'])) or {}).get('data') or {})
                p = p.get('price_overview') if isinstance(p, dict) else None
                if p:
                    rows.append({'date': d, 'country': cc.upper(), 'appid': a['appid'], 'name': a['name'], 'currency': p.get('currency'),
                                 'initial_price': p.get('initial', 0) / 100, 'final_price': p.get('final', 0) / 100,
                                 'discount_pct': p.get('discount_percent')})
        log(f'  prices {cc}: {len(rows)} rows')
    out.table(f'{MONEY}/Steam Regional Prices/{d[:7]}', f'steam_prices_{d}', Table(
        'Steam regional prices', [('date', 'Snapshot date (UTC)'), ('country', 'Store country'), ('appid', 'Steam application id'),
                                  ('name', 'Game'), ('currency', 'Local currency'), ('initial_price', 'Undiscounted local price'),
                                  ('final_price', 'Price paid on the day'), ('discount_pct', 'Discount %')], rows,
        'Daily prices of paid games in 16 store regions; together the daily files give price and discount history.'), xlsx=False)


# ---------------------------------------------------------------- concurrent players (hourly)
def players(out, n=2000):
    apps = top(out, n, by='ccu')
    now = datetime.now(timezone.utc)
    stamp = now.strftime('%Y-%m-%d %H:00')

    def one(a):
        r = get('https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/', {'appid': a['appid']}, key=f'c{a["appid"]}')
        if r is None or not r.ok:
            return None
        c = ((js(r) or {}).get('response') or {}).get('player_count')
        return None if c is None else f'{stamp},{a["appid"]},"{(a["name"] or "").replace(chr(34), "")}",{c}\n'
    with ThreadPoolExecutor(8) as ex:
        lines = [x for x in ex.map(one, apps) if x]
    path = f'{PLAYERS}/Steam Concurrent Players/{now:%Y-%m}/steam_players_{now:%Y-%m-%d}.csv'
    old = out.get(path)
    body = (old.decode('utf-8') if old else 'hour_utc,appid,name,players\n') + ''.join(lines)
    out.put(path, body.encode('utf-8'), 'text/csv')
    log(f'  players: {len(lines)} games at {stamp}')


def players_daily(out, day):
    """Daily peak and average per game for one day, appended to the month's summary."""
    path = f'{PLAYERS}/Steam Concurrent Players/{day[:7]}/steam_players_{day}.csv'
    rows = out.read_csv(path)
    if not rows:
        return
    per = {}
    for r in rows:
        per.setdefault((r['appid'], r['name']), []).append(int(r['players']))
    summ = f'{PLAYERS}/Steam Concurrent Players/steam_players_daily_{day[:7]}.csv'
    old = out.read_csv(summ)
    old = [r for r in old if r['date'] != day]
    for (a, nme), v in per.items():
        old.append({'date': day, 'appid': a, 'name': nme, 'peak_players': max(v), 'avg_players': round(sum(v) / len(v)),
                    'hours_sampled': len(v)})
    out.table(f'{PLAYERS}/Steam Concurrent Players', f'steam_players_daily_{day[:7]}', Table(
        'Steam concurrent players, daily', [('date', 'Day (UTC)'), ('appid', 'Steam application id'), ('name', 'Game'),
                                            ('peak_players', 'Highest hourly count'), ('avg_players', 'Average of hourly counts'),
                                            ('hours_sampled', 'Hours sampled')], old,
        'Hourly samples of the 2,000 most-played games, summarised per day.'))


# ---------------------------------------------------------------- hardware survey
def _survey_rows(html, month):
    html = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    heads = list(re.finditer(r'id="(\w+)_stats_row"[^>]*>.*?<div class="stats_col_left">([^<]+)</div>', html, re.S))
    rows = []
    for k, m in enumerate(heads):
        label = m.group(2).strip()
        block = html[m.end():heads[k + 1].start() if k + 1 < len(heads) else len(html)]
        det = block.find('_details"')
        if det < 0:
            continue
        for it in re.finditer(r'<div class="stats_col_mid[^"]*"[^>]*>(.*?)</div>\s*<div class="stats_col_right(?!2)[^"]*"[^>]*>'
                              r'\s*(?:<[^>]+>\s*)*([\d.]+)\s*%', block[det:], re.S):
            item = re.sub(r'<[^>]+>|&nbsp;', ' ', it.group(1)).strip()
            if item:
                rows.append({'month': month, 'category': label, 'item': re.sub(r'\s+', ' ', item), 'share_pct': float(it.group(2))})
    return rows


def hardware(out, backfill=True):
    rows = []
    url = 'https://store.steampowered.com/hwsurvey/Steam-Hardware-Software-Survey-Welcome-to-Steam'
    r = get(url)
    if r is not None and r.ok:
        m = re.search(r'id="main_stats_header">\s*([A-Za-z]+ \d{4})', r.text)
        month = datetime.strptime(m.group(1), '%B %Y').strftime('%Y-%m') if m else today()[:7]
        rows += _survey_rows(r.text, month)
    old = out.read_csv(f'{PLATFORMS}/Steam Hardware Survey/steam_hardware_survey.csv')
    have = {r['month'] for r in old} | {r['month'] for r in rows}
    if backfill:
        cdx = get('https://web.archive.org/cdx/search/cdx', {'url': 'store.steampowered.com/hwsurvey', 'output': 'json',
                                                              'from': '2008', 'collapse': 'timestamp:6', 'filter': 'statuscode:200'})
        snaps = (js(cdx) or [])[1:]
        for s in snaps:
            ts = s[1]
            page = get(f'https://web.archive.org/web/{ts}id_/{s[2]}', gap=2, key='wayback')
            if page is None or not page.ok:
                continue
            m = re.search(r'id="main_stats_header">\s*([A-Za-z]+ \d{4})', page.text)
            if not m:
                continue
            month = datetime.strptime(m.group(1), '%B %Y').strftime('%Y-%m')
            if month in have:
                continue
            got = _survey_rows(page.text, month)
            if got:
                rows += got
                have.add(month)
        log(f'  hardware survey: {len(have)} months')
    allrows = sorted([*old, *rows], key=lambda r: (r['month'], r['category'], -float(r['share_pct'])))
    seen, uniq = set(), []
    for r in allrows:
        k = (r['month'], r['category'], r['item'])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    out.table(f'{PLATFORMS}/Steam Hardware Survey', 'steam_hardware_survey', Table(
        'Steam hardware and software survey', [('month', 'Survey month'), ('category', 'Category (OS, CPU, GPU, RAM, ...)'),
                                               ('item', 'Item'), ('share_pct', 'Share of surveyed users, %')], uniq,
        'Monthly survey results, combined platforms, as far back as available.'))
