"""Industry benchmarks built from the collected data: genre economics, publisher league table, estimated Steam
revenue per game, and cost-structure benchmarks of the listed companies."""
import statistics

from .out import BENCH, Table, log

REVIEW_MULTIPLIER = 30   # owners per review (a common rule of thumb; ranges 20-60 by genre and era)
STORE_CUT = 0.30         # platform fee
REGIONAL_DISCOUNT = 0.75  # average price paid vs. US list price (regional pricing and sales)


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def benchmarks(out):
    cat = {r['appid']: r for r in out.state('catalog') or []}
    det = out.state('details') or []
    rows = []
    for d in det:
        c = cat.get(d['appid']) or {}
        reviews = (c.get('reviews_positive') or 0) + (c.get('reviews_negative') or 0)
        price = d.get('price_usd') or 0
        owners_est = reviews * REVIEW_MULTIPLIER
        rows.append({**d, 'reviews': reviews, 'pct_positive': round(100 * (c.get('reviews_positive') or 0) / reviews, 1) if reviews else None,
                     'owners_mid': c.get('owners_mid'), 'peak_ccu': c.get('peak_ccu_yesterday'),
                     'est_owners_from_reviews': owners_est,
                     'est_gross_revenue_usd': round(owners_est * price * REGIONAL_DISCOUNT) if price else 0,
                     'est_net_revenue_usd': round(owners_est * price * REGIONAL_DISCOUNT * (1 - STORE_CUT)) if price else 0})
    out.table(BENCH, 'steam_estimated_revenue_per_game', Table(
        'Estimated Steam revenue per game', [
            ('appid', 'Steam application id'), ('name', 'Game'), ('publishers', 'Publisher'), ('primary_genre', 'Genre'),
            ('release_date', 'Release date'), ('price_usd', 'US price'), ('is_free', 'Free to play'),
            ('has_in_app_purchases', 'Sells in-game items'), ('reviews', 'Total reviews'), ('pct_positive', 'Share positive, %'),
            ('owners_mid', 'Owners band midpoint'), ('peak_ccu', 'Peak concurrent players (yesterday)'),
            ('est_owners_from_reviews', f'Estimated buyers = reviews x {REVIEW_MULTIPLIER}'),
            ('est_gross_revenue_usd', f'Estimated gross sales = buyers x price x {REGIONAL_DISCOUNT} (regional prices, discounts)'),
            ('est_net_revenue_usd', f'Estimated developer revenue after the {int(STORE_CUT * 100)}% store fee')], rows,
        'Premium-sale estimate only; in-game purchases of free-to-play games are not included.'))

    genres = {}
    for r in rows:
        genres.setdefault(r.get('primary_genre') or 'Unknown', []).append(r)
    g_rows = []
    for g, rs in sorted(genres.items(), key=lambda kv: -len(kv[1])):
        g_rows.append({'genre': g, 'games': len(rs), 'share_free_pct': round(100 * sum(1 for r in rs if r['is_free']) / len(rs), 1),
                       'share_iap_pct': round(100 * sum(1 for r in rs if r['has_in_app_purchases']) / len(rs), 1),
                       'share_multiplayer_pct': round(100 * sum(1 for r in rs if r['multiplayer']) / len(rs), 1),
                       'median_price_paid_games': _med([r['price_usd'] for r in rs if (r['price_usd'] or 0) > 0]),
                       'median_reviews': _med([r['reviews'] for r in rs]), 'median_pct_positive': _med([r['pct_positive'] for r in rs]),
                       'median_owners_mid': _med([r['owners_mid'] for r in rs]),
                       'median_est_net_revenue_usd': _med([r['est_net_revenue_usd'] for r in rs if r['est_net_revenue_usd']]),
                       'total_est_net_revenue_usd': sum(r['est_net_revenue_usd'] for r in rs)})
    out.table(BENCH, 'genre_benchmarks', Table('Genre benchmarks', [
        ('genre', 'Primary genre'), ('games', 'Games in the sample'), ('share_free_pct', 'Free to play, %'),
        ('share_iap_pct', 'With in-game purchases, %'), ('share_multiplayer_pct', 'With multiplayer, %'),
        ('median_price_paid_games', 'Median US price of paid games'), ('median_reviews', 'Median reviews'),
        ('median_pct_positive', 'Median share positive, %'), ('median_owners_mid', 'Median owners (band midpoint)'),
        ('median_est_net_revenue_usd', 'Median estimated developer revenue, paid games'),
        ('total_est_net_revenue_usd', 'Total estimated developer revenue')], g_rows))

    pubs = {}
    for r in rows:
        for p in (r.get('publishers') or 'Unknown').split('; ')[:1]:
            pubs.setdefault(p, []).append(r)
    p_rows = [{'publisher': p, 'games': len(rs), 'total_reviews': sum(r['reviews'] for r in rs),
               'median_pct_positive': _med([r['pct_positive'] for r in rs]),
               'total_peak_ccu': sum(r['peak_ccu'] or 0 for r in rs),
               'total_est_net_revenue_usd': sum(r['est_net_revenue_usd'] for r in rs),
               'free_to_play_games': sum(1 for r in rs if r['is_free'])} for p, rs in pubs.items()]
    p_rows.sort(key=lambda r: -r['total_est_net_revenue_usd'])
    out.table(BENCH, 'publisher_league_table', Table('Publisher league table', [
        ('publisher', 'Publisher'), ('games', 'Games in the sample'), ('total_reviews', 'Reviews across its games'),
        ('median_pct_positive', 'Median share positive, %'), ('total_peak_ccu', 'Sum of peak concurrent players'),
        ('total_est_net_revenue_usd', 'Estimated developer revenue (premium sales)'),
        ('free_to_play_games', 'Free-to-play games')], p_rows))

    summ = out.state('company_summary') or []
    by_seg = {}
    for r in summ:
        by_seg.setdefault(r['segment'], []).append(r)
    s_rows = []
    for seg, rs in sorted(by_seg.items()):
        row = {'segment': seg, 'company_years': len(rs), 'companies': len({r['company'] for r in rs})}
        for k in ('gross_profit', 'rnd', 'sales_marketing', 'gna', 'operating_income', 'net_income', 'sbc'):
            row[f'median_{k}_pct_revenue'] = _med([r.get(f'{k}_pct_revenue') for r in rs])
        s_rows.append(row)
    out.table(BENCH, 'company_cost_structure_benchmarks', Table('Cost structure benchmarks by segment', [
        ('segment', 'Segment'), ('companies', 'Companies'), ('company_years', 'Company-years'),
        ('median_gross_profit_pct_revenue', 'Median gross margin, %'), ('median_rnd_pct_revenue', 'Median R&D, % of revenue'),
        ('median_sales_marketing_pct_revenue', 'Median sales & marketing, % of revenue'),
        ('median_gna_pct_revenue', 'Median G&A, % of revenue'), ('median_operating_income_pct_revenue', 'Median operating margin, %'),
        ('median_net_income_pct_revenue', 'Median net margin, %'), ('median_sbc_pct_revenue', 'Median share-based pay, % of revenue')],
        s_rows))
    log(f'  benchmarks: {len(rows)} games, {len(g_rows)} genres, {len(p_rows)} publishers, {len(s_rows)} segments')
