"""Monthly aggregates handed from the player simulation to accounting (and the data warehouse)."""
import pandas as pd

from .config import COUNTRIES
from .players import to_date

TIER = {c[0]: c[2] for c in COUNTRIES}


def month_of(days):
    return pd.Series(to_date(days)).dt.to_period('M').astype(str).values


def game_aggregates(players, txn, kpis, scale=1.0):
    k = kpis.assign(month=pd.to_datetime(kpis.date).dt.to_period('M').astype(str))
    km = k.groupby(['month', 'game', 'platform']).dau.sum().rename('dau_days').reset_index()
    t = txn.assign(month=month_of(txn.day.values))
    tm = t.groupby(['month', 'game', 'platform', 'kind', 'status']).price_usd.sum().rename('amount').reset_index()
    ads = k.groupby(['month', 'game', 'platform']).ad_revenue_usd.sum().rename('amount').reset_index()
    ads = ads[ads.amount > 0].assign(kind='ads', status='completed')
    p = players[players.acquisition == 'Paid']
    p = p.assign(month=month_of(p.signup_day.values), tier=p.country.map(TIER))
    pi = p.groupby(['month', 'game', 'platform', 'tier']).size().rename('installs').reset_index()
    km['dau_days'] /= scale
    tm = pd.concat([tm, ads], ignore_index=True)
    tm['amount'] /= scale
    pi['installs'] /= scale
    return km, tm, pi
