"""Apple App Store games: daily top-grossing / top-free / top-paid charts in 16 countries, and a growing catalogue of
every game that has appeared in them (price, ratings, release and update dates, size, seller)."""
from datetime import datetime, timezone

from .out import MONEY, PLATFORMS, Table, log, person_free
from .steam import get, js, today

COUNTRIES = ['us', 'gb', 'de', 'fr', 'jp', 'kr', 'cn', 'br', 'in', 'ca', 'au', 'mx', 'id', 'tr', 'sa', 'it']
CHARTS = {'top_grossing': 'topgrossingapplications', 'top_free': 'topfreeapplications', 'top_paid': 'toppaidapplications'}


def mobile(out):
    d = today()
    ranks, ids, home = [], set(), {}
    for cc in COUNTRIES:
        for chart, feed in CHARTS.items():
            r = get(f'https://itunes.apple.com/{cc}/rss/{feed}/limit=200/genre=6014/json', gap=1, key='itunes')
            if r is None or not r.ok:
                continue
            for i, e in enumerate(((js(r) or {}).get('feed') or {}).get('entry') or [], 1):
                aid = e['id']['attributes']['im:id']
                ids.add(aid)
                home.setdefault(aid, cc)
                ranks.append({'date': d, 'country': cc.upper(), 'chart': chart, 'rank': i, 'app_id': aid,
                              'name': e['im:name']['label'], 'seller': person_free(e['im:artist']['label']),
                              'price': float(e['im:price']['attributes'].get('amount') or 0),
                              'currency': e['im:price']['attributes'].get('currency'),
                              'sub_genre': (e.get('category') or {}).get('attributes', {}).get('label')})
    log(f'  app store charts: {len(ranks)} rows, {len(ids)} apps')
    out.table(f'{MONEY}/App Store Game Charts/{d[:7]}', f'appstore_game_charts_{d}', Table(
        'App Store game charts', [('date', 'Chart date (UTC)'), ('country', 'Store country'),
                                  ('chart', 'Chart: top_grossing (revenue rank), top_free, top_paid'), ('rank', 'Position 1-200'),
                                  ('app_id', 'App Store id'), ('name', 'Game'), ('seller', 'Seller'), ('price', 'Download price'),
                                  ('currency', 'Currency'), ('sub_genre', 'Store category')], ranks,
        'Daily top 200 games per chart and country; the top-grossing rank is the public signal of in-app revenue.'), xlsx=False)

    old = {r['app_id']: r for r in out.read_csv(f'{PLATFORMS}/App Store Game Catalogue/appstore_game_catalogue.csv')}
    def lookup(batch, cc):
        r = get('https://itunes.apple.com/lookup', {'id': ','.join(batch), 'country': cc}, gap=1, key='itunes')
        return ((js(r) or {}).get('results') or []) if r is not None and r.ok else []
    ids = list(ids)
    found = []
    for k in range(0, len(ids), 150):
        found += lookup(ids[k:k + 150], 'us')
    missing = set(ids) - {str(a['trackId']) for a in found}
    by_cc = {}
    for aid in missing:
        by_cc.setdefault(home[aid], []).append(aid)
    for cc, lst in by_cc.items():  # games sold only outside the US: looked up in the store where they charted
        for k in range(0, len(lst), 150):
            found += lookup(lst[k:k + 150], cc)
    for a in found:
        if True:
            prev = old.get(str(a['trackId'])) or {}
            old[str(a['trackId'])] = {
                'app_id': a['trackId'], 'name': a.get('trackName'), 'seller': person_free(a.get('sellerName')),
                'developer_id': a.get('artistId'), 'primary_genre': a.get('primaryGenreName'), 'genres': '; '.join(a.get('genres') or []),
                'price': a.get('price'), 'currency': a.get('currency'), 'average_rating': a.get('averageUserRating'), 'rating_count': a.get('userRatingCount'),
                'content_rating': a.get('contentAdvisoryRating'), 'release_date': (a.get('releaseDate') or '')[:10],
                'last_update': (a.get('currentVersionReleaseDate') or '')[:10], 'version': a.get('version'),
                'size_mb': round(int(a.get('fileSizeBytes') or 0) / 2**20, 1), 'minimum_os': a.get('minimumOsVersion'),
                'languages': len(a.get('languageCodesISO2A') or []), 'first_seen_in_charts': prev.get('first_seen_in_charts') or d,
                'last_seen_in_charts': d}
    rows = sorted(old.values(), key=lambda r: -int(r.get('rating_count') or 0))
    out.table(f'{PLATFORMS}/App Store Game Catalogue', 'appstore_game_catalogue', Table(
        'App Store game catalogue', [('app_id', 'App Store id'), ('name', 'Game'), ('seller', 'Seller'), ('developer_id', 'Developer id'),
                                     ('primary_genre', 'Primary category'), ('genres', 'All categories'), ('price', 'Price in the store looked up'), ('currency', 'Currency'),
                                     ('average_rating', 'Average rating (1-5)'), ('rating_count', 'Number of ratings'),
                                     ('content_rating', 'Age rating'), ('release_date', 'First release'),
                                     ('last_update', 'Latest version released'), ('version', 'Current version'),
                                     ('size_mb', 'Download size, MB'), ('minimum_os', 'Minimum iOS'),
                                     ('languages', 'Languages'), ('first_seen_in_charts', 'First day seen in a chart'),
                                     ('last_seen_in_charts', 'Latest day seen in a chart')], rows,
        'Every game that has appeared in a top-200 chart in any of the 16 countries.'))
