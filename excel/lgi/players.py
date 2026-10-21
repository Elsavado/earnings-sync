"""Players and purchases, simulated bottom-up per game: every account has a sign-up day, platform, country, lifetime
and spending; purchases are individual transactions; daily KPIs (new accounts, DAU, sessions, payers, bookings, ad
revenue) are aggregated from them, so every system built on top reconciles."""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import names
from .config import (COSTS, COUNTRIES, END, GAMES, ITEM_PRICES, ITEM_WEIGHTS, PLATFORMS, SEED, START, TIER_SPEND)

PLAT = list(PLATFORMS)
CC = [c[0] for c in COUNTRIES]
CW = np.array([c[1] for c in COUNTRIES], float)
TIER = np.array([c[2] for c in COUNTRIES])
LANG = np.array([c[4] for c in COUNTRIES], dtype=object)
TODAY = (END - START).days
HORIZON = 12 * 365
EPOCH = np.datetime64(START.isoformat())


def day_index(d):
    return (d - START).days


def to_date(idx):
    return EPOCH + np.asarray(idx).astype('timedelta64[D]')


def sale_days():
    """Seasonal store sales (summer, autumn, winter) as day indexes -> discount multiplier."""
    m = np.ones(day_index(date(2040, 1, 1)))
    for y in range(2015, 2040):
        for a, b, disc in ((date(y, 6, 24), date(y, 7, 8), .55), (date(y, 11, 24), date(y, 12, 1), .65), (date(y, 12, 19), date(y + 1, 1, 3), .5)):
            m[day_index(a):day_index(b)] = disc
    return m


SALE = sale_days()


def _signup_curve(g, rng):
    t = np.arange(HORIZON, dtype=float)
    if g['kind'] == 'premium':
        w = 30 * np.exp(-t / 9) + 6 * np.exp(-t / 120) + 0.9 * np.exp(-t / 1400)
    else:
        w = 4 * np.exp(-t / 20) + 3 * np.exp(-t / 300) + 1.2 * np.exp(-t / 1600)
        w *= np.minimum(1, (t + 30) / 120)  # soft launch ramp
    start = day_index(g['launch'])
    doy = (start + t) % 365
    w *= 1 + .22 * np.cos(2 * np.pi * (doy - 358) / 365)  # holidays
    for k in range(int(HORIZON / 95)):  # content updates
        s = int(rng.integers(60, 120)) + k * 95
        if s < HORIZON:
            w[s:s + 25] *= 1 + rng.uniform(.2, .6) * np.exp(-np.arange(min(25, HORIZON - s)) / 7)
    if g['kind'] == 'premium':
        w *= np.where(SALE[start:start + HORIZON] < 1, 2.6, 1)  # sales lift unit sales
    return w / w.sum()


def simulate_game(gi, g, scale=1.0):
    rng = np.random.default_rng(SEED + 1000 * gi)
    n = int(g['accounts'] * scale)
    if n == 0:
        return None
    start = day_index(g['launch'])
    signup = start + rng.choice(HORIZON, n, p=_signup_curve(g, rng))
    order = np.argsort(signup, kind='stable')
    signup = signup[order]
    plats = list(g['platforms'])
    plat = rng.choice(len(plats), n, p=np.array(list(g['platforms'].values())) / sum(g['platforms'].values()))
    cw = CW.copy()
    if g['kind'] == 'premium':
        cw = cw * np.where(TIER == 1, 1.5, np.where(TIER == 2, 1.0, .55))
    country = rng.choice(len(CC), n, p=cw / cw.sum())
    r1, b = g['retention']
    u = rng.random(n)
    lifetime = np.where(u > r1, 0, np.minimum((np.maximum(u, 1e-9) / r1) ** (-1 / b), 6000)).astype(int)
    keep = signup <= TODAY
    signup, plat, country, lifetime = signup[keep], plat[keep], country[keep], lifetime[keep]
    m = len(signup)
    pid = gi * 100_000_000 + np.arange(1, m + 1)
    last = np.minimum(signup + lifetime, TODAY)
    tier = TIER[country]
    paid = rng.random(m) < COSTS['paid_share'] * np.where(g['kind'] == 'premium', .6, 1.0)

    # --- purchases ---------------------------------------------------------------------------------
    txn = []
    reg = np.array([1.0, .72, .5])[tier - 1]
    if g['kind'] == 'premium':
        disc = SALE[signup]
        txn.append(pd.DataFrame({'player_id': pid, 'day': signup, 'sku': f'{g["code"]}-BASE', 'item': f'{g["name"]} (full game)',
                                 'price_usd': np.round(g['price'] * reg * disc, 2), 'kind': 'game'}))
        for j, (dname, dprice, offset) in enumerate(g.get('dlc', [])):
            rel = start + offset
            alive_at = (signup + lifetime >= rel) | (rng.random(m) < .15)
            buy = alive_at & (rng.random(m) < g['payer'] * 1.6) & (rel <= TODAY)
            idx = np.nonzero(buy)[0]
            d = np.maximum(rel, signup[idx]) + (rng.exponential(60, len(idx))).astype(int)
            ok = d <= TODAY
            txn.append(pd.DataFrame({'player_id': pid[idx][ok], 'day': d[ok], 'sku': f'{g["code"]}-DLC{j + 1}',
                                     'item': f'{g["name"]}: {dname}', 'price_usd': np.round(dprice * reg[idx][ok] * SALE[d[ok]], 2),
                                     'kind': 'dlc'}))
    payer_p = g['payer'] * np.minimum(1, (lifetime + 1) / 45) ** .6
    payer_p *= g['payer'] / max(payer_p.mean(), 1e-9)
    payer = rng.random(m) < payer_p * np.array([1.25, .95, .6])[tier - 1]
    if g['kind'] == 'f2p':
        idx = np.nonzero(payer)[0]
        spend = rng.lognormal(np.log(g['arppu'] * TIER_SPEND[1]) - .98, 1.4, len(idx)) * np.array([TIER_SPEND[t] for t in (1, 2, 3)])[tier[idx] - 1]
        spend *= np.minimum(1, (lifetime[idx] + 7) / 120) ** .15
        k = np.maximum(1, np.round(spend / 9.4)).astype(int)
        who = np.repeat(idx, k)
        d = signup[who] + (rng.beta(1, 1.8, len(who)) * (lifetime[who] + 1)).astype(int)
        price = np.asarray(ITEM_PRICES)[rng.choice(len(ITEM_PRICES), len(who), p=ITEM_WEIGHTS)]
        ok = d <= TODAY
        txn.append(pd.DataFrame({'player_id': pid[who][ok], 'day': d[ok], 'sku': [f'{g["code"]}-GEM{int(p * 100)}' for p in price[ok]],
                                 'item': [f'Gem pack {p:.2f}' for p in price[ok]], 'price_usd': price[ok], 'kind': 'in_app'}))
        if g.get('battle_pass'):
            seasons = (lifetime[idx] // 70) * (rng.random(len(idx)) < .6)
            who = np.repeat(idx, seasons)
            nth = np.concatenate([np.arange(s) for s in seasons]) if len(seasons) else np.array([], int)
            d = signup[who] + nth * 70 + rng.integers(0, 10, len(who))
            ok = d <= TODAY
            txn.append(pd.DataFrame({'player_id': pid[who][ok], 'day': d[ok], 'sku': f'{g["code"]}-PASS', 'item': 'Season pass',
                                     'price_usd': g['battle_pass'], 'kind': 'season_pass'}))
    t = pd.concat(txn, ignore_index=True) if txn else pd.DataFrame(columns=['player_id', 'day', 'sku', 'item', 'price_usd', 'kind'])
    t = t.sort_values(['day', 'player_id'], kind='stable').reset_index(drop=True)
    pos = pid - pid[0]
    t['platform'] = np.asarray(plats, dtype=object)[plat[t.player_id.values - pid[0]]]
    t['country'] = np.asarray(CC, dtype=object)[country[t.player_id.values - pid[0]]]
    r = rng.random(len(t))
    t['status'] = np.where(r < COSTS['chargeback_rate'], 'chargeback', np.where(r < COSTS['chargeback_rate'] + COSTS['refund_rate'], 'refunded', 'completed'))
    t['seconds'] = rng.integers(0, 86400, len(t))
    t['game'] = g['code']
    t['txn_id'] = [f'{g["code"]}-T{i:09d}' for i in range(1, len(t) + 1)]

    spend_sum = np.bincount(t.player_id.values - pid[0], weights=np.where(t.status.values == 'completed', t.price_usd.values, 0), minlength=m)
    cnt = np.bincount(t.player_id.values - pid[0], minlength=m)
    firstbuy = np.full(m, -1)
    if len(t):
        fb = t.groupby('player_id').day.min()
        firstbuy[fb.index.values - pid[0]] = fb.values

    # --- accounts --------------------------------------------------------------------------------------
    lrng = np.random.default_rng(SEED + 1000 * gi + 7)
    first, lastn = names.people(lrng, LANG[country])
    seg = np.where(spend_sum >= 1000, 'Whale', np.where(spend_sum >= 100, 'Dolphin', np.where(spend_sum > 0, 'Minnow', 'Non-payer')))
    status = np.where(last >= TODAY - 30, 'Active', np.where(last >= TODAY - 90, 'Lapsed', 'Churned'))
    status = np.where(lrng.random(m) < .004, 'Banned', np.where(lrng.random(m) < .01, 'Deleted (GDPR request)', status))
    players = pd.DataFrame({
        'player_id': pid, 'account_number': [f'{g["code"]}{x % 100_000_000:09d}' for x in pid], 'game': g['code'],
        'platform': np.asarray(plats, dtype=object)[plat], 'country': np.asarray(CC, dtype=object)[country], 'language': LANG[country],
        'first_name': first, 'last_name': lastn, 'signup_day': signup, 'last_active_day': last, 'lifetime_days': last - signup,
        'acquisition': np.where(paid, 'Paid', 'Organic'), 'lifetime_spend_usd': np.round(spend_sum, 2), 'purchases': cnt,
        'first_purchase_day': firstbuy, 'segment': seg, 'status': status,
        'marketing_opt_in': lrng.random(m) < .38, 'age_band': lrng.choice(['13-17', '18-24', '25-34', '35-44', '45-54', '55+'], m,
                                                                       p=[.08, .27, .31, .18, .1, .06])})
    players['email'] = names.player_emails(lrng, first, lastn, pid)
    players['username'] = names.usernames(lrng, pid)
    del pos
    return players, t


def daily_kpis(gi, g, players, txn):
    """game x platform x country x day."""
    rng = np.random.default_rng(SEED + 1000 * gi + 3)
    plats, D = list(g['platforms']), TODAY + 1
    pidx = pd.Categorical(players.platform, categories=plats).codes
    cidx = pd.Categorical(players.country, categories=CC).codes
    grp = pidx * len(CC) + cidx
    G = len(plats) * len(CC)
    new = np.zeros((G, D))
    np.add.at(new, (grp, players.signup_day.values), 1)
    alive = np.zeros((G, D + 1))
    np.add.at(alive, (grp, players.signup_day.values), 1)
    np.add.at(alive, (grp, players.last_active_day.values + 1), -1)
    alive = np.cumsum(alive, axis=1)[:, :D]
    wk = 1 + .12 * np.isin((np.arange(D) + START.weekday()) % 7, [5, 6])
    p = np.clip(g['stick'] * wk * rng.normal(1, .04, D), 0, 1)
    dau = rng.binomial(alive.astype(np.int64), p) + new
    tt = txn[txn.status == 'completed']
    tg = pd.Categorical(tt.platform, categories=plats).codes * len(CC) + pd.Categorical(tt.country, categories=CC).codes
    book = np.zeros((G, D))
    np.add.at(book, (tg, tt.day.values), tt.price_usd.values)
    payers = np.zeros((G, D))
    first_of_day = ~tt.duplicated(['player_id', 'day'])
    np.add.at(payers, (tg[first_of_day.values], tt.day.values[first_of_day.values]), 1)
    rf = txn[txn.status != 'completed']
    rg = pd.Categorical(rf.platform, categories=plats).codes * len(CC) + pd.Categorical(rf.country, categories=CC).codes
    refunds = np.zeros((G, D))
    np.add.at(refunds, (rg, rf.day.values), rf.price_usd.values)
    ads = np.zeros((G, D))
    if g.get('ads'):
        ecpm = np.array([COSTS['ecpm_tier'][t] for t in TIER])
        ads = (dau - payers) * COSTS['ad_impressions_per_dau'] * np.tile(ecpm, len(plats))[:, None] / 1000 * rng.normal(1, .08, (G, D))
    sessions = np.round(dau * rng.normal(2.4 if g['kind'] == 'f2p' else 1.3, .1, (G, D)))
    minutes = np.round(sessions * rng.normal(14 if g['kind'] == 'f2p' else 52, 3, (G, D)))
    gi_, di = np.nonzero((dau > 0) | (new > 0) | (book > 0))
    return pd.DataFrame({
        'date': to_date(di), 'game': g['code'], 'platform': np.asarray(plats, dtype=object)[gi_ // len(CC)],
        'country': np.asarray(CC, dtype=object)[gi_ % len(CC)], 'new_accounts': new[gi_, di].astype(int), 'dau': dau[gi_, di].astype(int),
        'sessions': sessions[gi_, di].astype(int), 'minutes_played': minutes[gi_, di].astype(int), 'payers': payers[gi_, di].astype(int),
        'gross_bookings_usd': np.round(book[gi_, di], 2), 'refunds_usd': np.round(refunds[gi_, di], 2),
        'ad_revenue_usd': np.round(np.maximum(ads[gi_, di], 0), 2)})


def ts(day, seconds):
    return (to_date(day) + np.asarray(seconds).astype('timedelta64[s]')).astype('datetime64[s]')


def daystr(d):
    return np.where(np.asarray(d) < 0, '', np.datetime_as_string(to_date(np.maximum(d, 0)), unit='D'))


def plus_days(d, n):
    return d + timedelta(days=int(n))
