"""Data warehouse: a star schema (dimensions + facts) loaded from the operational systems, and its DDL."""
import numpy as np
import pandas as pd

from .config import COUNTRIES, END, GAMES, PLATFORMS, START
from .players import SALE, TODAY, daystr

RET_DAYS = [1, 3, 7, 14, 30, 60, 90, 180, 365]


def dim_date():
    d = pd.date_range(START, END, freq='D')
    idx = (d - pd.Timestamp(START)).days.values
    return pd.DataFrame({'date_key': d.strftime('%Y%m%d').astype(int), 'date': d.date, 'year': d.year, 'quarter': d.quarter,
                         'month': d.month, 'month_name': d.strftime('%B'), 'week_of_year': d.isocalendar().week.values,
                         'day_of_week': d.strftime('%A'), 'is_weekend': d.dayofweek >= 5, 'store_sale_period': SALE[idx] < 1})


def dim_game():
    return pd.DataFrame([{'game_key': i + 1, 'game_code': g['code'], 'name': g['name'], 'genre': g['genre'],
                          'business_model': 'Free to play' if g['kind'] == 'f2p' else 'Premium', 'launch_date': g['launch'],
                          'list_price_usd': g.get('price'), 'platforms': ', '.join(g['platforms']),
                          'status': 'Live' if g['launch'] <= END else 'In development'} for i, g in enumerate(GAMES)])


def dim_platform():
    return pd.DataFrame([{'platform_key': i + 1, 'platform': p, 'store_fee_pct': f * 100, 'payout_days': lag,
                          'device_class': 'Mobile' if p in ('iOS', 'Android') else 'Console' if p in ('PlayStation', 'Xbox', 'Nintendo Switch') else 'PC'}
                         for i, (p, (f, lag)) in enumerate(PLATFORMS.items())])


def dim_country():
    return pd.DataFrame([{'country_key': i + 1, 'country_code': c, 'monetisation_tier': t, 'currency': cur, 'language': lang}
                         for i, (c, _, t, cur, lang) in enumerate(COUNTRIES)])


def retention(players, g):
    """Share of each monthly sign-up cohort still playing N days later."""
    p = players[['platform', 'signup_day', 'lifetime_days']].copy()
    p['cohort'] = pd.Series(daystr(p.signup_day.values)).str[:7].values
    rows = []
    for (cohort, plat), grp in p.groupby(['cohort', 'platform']):
        row = {'cohort_month': cohort, 'game': g['code'], 'platform': plat, 'cohort_size': len(grp)}
        for n in RET_DAYS:
            eligible = grp[grp.signup_day + n <= TODAY]
            row[f'd{n}_retention_pct'] = round(100 * (eligible.lifetime_days >= n).mean(), 2) if len(eligible) else None
        rows.append(row)
    return pd.DataFrame(rows)


def finance_fact(gl):
    g = gl.copy()
    g['month'] = pd.to_datetime(g.date).dt.to_period('M').astype(str)
    return g.groupby(['month', 'account', 'account_name', 'game', 'platform', 'department'])[['debit', 'credit']].sum().round(2).reset_index()


def headcount_fact(emp, months):
    rows = []
    hire = pd.to_datetime(emp.hire_date)
    term = pd.to_datetime(emp.termination_date)
    for m in months:
        e = m.to_timestamp(how='end')
        act = emp[(hire <= e) & (term.isna() | (term > e))]
        for d, n in act.department.value_counts().items():
            rows.append({'month': str(m), 'department': d, 'headcount': int(n),
                         'hires': int(((hire.dt.to_period('M') == m) & (emp.department == d)).sum()),
                         'leavers': int(((term.dt.to_period('M') == m) & (emp.department == d)).sum())})
    return pd.DataFrame(rows)


DDL = """-- Little Games Incorporated data warehouse (fictional data). Star schema; keys are integers or business codes.
CREATE TABLE dim_date (date_key INT PRIMARY KEY, date DATE, year INT, quarter INT, month INT, month_name VARCHAR(12),
  week_of_year INT, day_of_week VARCHAR(10), is_weekend BOOLEAN, store_sale_period BOOLEAN);
CREATE TABLE dim_game (game_key INT PRIMARY KEY, game_code CHAR(2) UNIQUE, name VARCHAR(80), genre VARCHAR(40),
  business_model VARCHAR(20), launch_date DATE, list_price_usd DECIMAL(8,2), platforms VARCHAR(200), status VARCHAR(20));
CREATE TABLE dim_platform (platform_key INT PRIMARY KEY, platform VARCHAR(30) UNIQUE, store_fee_pct DECIMAL(5,2), payout_days INT, device_class VARCHAR(10));
CREATE TABLE dim_country (country_key INT PRIMARY KEY, country_code CHAR(2) UNIQUE, monetisation_tier INT, currency CHAR(3), language CHAR(2));
CREATE TABLE dim_player (player_id BIGINT PRIMARY KEY, game_code CHAR(2) REFERENCES dim_game(game_code), platform VARCHAR(30),
  country_code CHAR(2), signup_date DATE, last_active_date DATE, acquisition VARCHAR(10), segment VARCHAR(12), status VARCHAR(30), age_band VARCHAR(8));
CREATE TABLE dim_employee (employee_id VARCHAR(8) PRIMARY KEY, department VARCHAR(30), title VARCHAR(60), level VARCHAR(20),
  location VARCHAR(30), hire_date DATE, termination_date DATE, project VARCHAR(2));
CREATE TABLE dim_campaign (campaign_id VARCHAR(40) PRIMARY KEY, month CHAR(7), game CHAR(2), platform VARCHAR(30), country_tier INT, channel VARCHAR(40));
CREATE TABLE fact_daily_game_kpi (date DATE, game CHAR(2), platform VARCHAR(30), country CHAR(2), new_accounts INT, dau INT, sessions INT,
  minutes_played BIGINT, payers INT, gross_bookings_usd DECIMAL(14,2), refunds_usd DECIMAL(14,2), ad_revenue_usd DECIMAL(14,2),
  PRIMARY KEY (date, game, platform, country));
CREATE TABLE fact_purchase (txn_id VARCHAR(16) PRIMARY KEY, player_id BIGINT REFERENCES dim_player(player_id), purchased_at TIMESTAMP,
  game CHAR(2), platform VARCHAR(30), country CHAR(2), sku VARCHAR(20), item VARCHAR(80), kind VARCHAR(12), price_usd DECIMAL(10,2), status VARCHAR(12));
CREATE TABLE fact_retention_cohort (cohort_month CHAR(7), game CHAR(2), platform VARCHAR(30), cohort_size INT,
  d1_retention_pct DECIMAL(5,2), d3_retention_pct DECIMAL(5,2), d7_retention_pct DECIMAL(5,2), d14_retention_pct DECIMAL(5,2),
  d30_retention_pct DECIMAL(5,2), d60_retention_pct DECIMAL(5,2), d90_retention_pct DECIMAL(5,2), d180_retention_pct DECIMAL(5,2),
  d365_retention_pct DECIMAL(5,2), PRIMARY KEY (cohort_month, game, platform));
CREATE TABLE fact_ua_spend (campaign_id VARCHAR(40) REFERENCES dim_campaign(campaign_id), month CHAR(7), installs INT, spend_usd DECIMAL(14,2), cpi_usd DECIMAL(8,2));
CREATE TABLE fact_support_ticket (ticket_id VARCHAR(10) PRIMARY KEY, player_id BIGINT, created_at TIMESTAMP, solved_at TIMESTAMP, game CHAR(2),
  platform VARCHAR(30), country CHAR(2), category VARCHAR(40), channel VARCHAR(20), priority VARCHAR(10), status VARCHAR(10),
  first_response_minutes INT, resolution_hours DECIMAL(8,1), sla_breached BOOLEAN, csat_score INT, txn_id VARCHAR(16));
CREATE TABLE fact_finance_monthly (month CHAR(7), account INT, account_name VARCHAR(60), game CHAR(2), platform VARCHAR(30),
  department VARCHAR(30), debit DECIMAL(16,2), credit DECIMAL(16,2));
CREATE TABLE fact_headcount_monthly (month CHAR(7), department VARCHAR(30), headcount INT, hires INT, leavers INT);
"""
