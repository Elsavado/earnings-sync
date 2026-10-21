"""Little Games Incorporated: a fictional games company (2015 to date). Everything here is invented; the shapes
(prices, retention, payer conversion, ARPPU, platform fees, cost structure) follow public industry figures and are
refined from the collected public data when it is available (calibrate()).

To add to the company: add a game to GAMES (or extend END), and run the generator again. Every record is drawn from
seeded generators keyed by game and record number, so earlier history stays the same and only new records are added."""
from datetime import date

COMPANY = 'Little Games Incorporated'
SHORT = 'LGI'
DOMAIN = 'littlegames.example'          # reserved .example domain: no real mailbox can exist
PLAYER_DOMAINS = ['example.com', 'example.net', 'example.org', 'mail.example', 'inbox.test']
HQ = ('Austin', 'Texas', 'US')
START = date(2015, 1, 1)
END = date.today()
SEED = 20150101
SYNTHETIC_NOTE = 'Fictional data for Little Games Incorporated (a made-up company). Any resemblance to real people is coincidental.'

PLATFORMS = {  # store fee, payout lag days
    'iOS': (0.30, 45), 'Android': (0.30, 30), 'Steam': (0.30, 30), 'PlayStation': (0.30, 60),
    'Xbox': (0.30, 60), 'Nintendo Switch': (0.30, 60), 'Epic Games Store': (0.12, 30), 'Web Store': (0.035, 3)}

# country, weight, monetisation tier (1 high .. 3 low), currency, language
COUNTRIES = [
    ('US', 26, 1, 'USD', 'en'), ('GB', 6, 1, 'GBP', 'en'), ('DE', 6, 1, 'EUR', 'de'), ('FR', 4.5, 1, 'EUR', 'fr'),
    ('JP', 5, 1, 'JPY', 'ja'), ('KR', 3, 1, 'KRW', 'ko'), ('CA', 3.5, 1, 'CAD', 'en'), ('AU', 2.5, 1, 'AUD', 'en'),
    ('BR', 6, 2, 'BRL', 'pt'), ('MX', 4, 2, 'MXN', 'es'), ('ES', 2.5, 2, 'EUR', 'es'), ('IT', 2.5, 2, 'EUR', 'it'),
    ('PL', 2, 2, 'PLN', 'pl'), ('NL', 1.5, 1, 'EUR', 'nl'), ('SE', 1, 1, 'SEK', 'sv'), ('TR', 2.5, 3, 'TRY', 'tr'),
    ('IN', 5, 3, 'INR', 'en'), ('ID', 3, 3, 'IDR', 'id'), ('PH', 2, 3, 'PHP', 'en'), ('ZA', 1, 3, 'ZAR', 'en'),
    ('AR', 1.5, 3, 'ARS', 'es'), ('SA', 1.2, 2, 'SAR', 'ar'), ('TH', 1.5, 3, 'THB', 'th'), ('VN', 1.5, 3, 'VND', 'vi'),
    ('KE', 0.6, 3, 'KES', 'en')]
TIER_SPEND = {1: 1.0, 2: 0.45, 3: 0.2}

# Games. kind: f2p (in-app purchases, ads optional) or premium (unit price, DLC). accounts = lifetime accounts created.
# retention: (share still playing after day 1, decay exponent); payer: lifetime payer share; arppu: lifetime spend per
# payer (USD, tier 1); stick: DAU/MAU of retained players.
GAMES = [
    dict(code='PO', name='Pocket Orchard', genre='Casual / Farming', kind='f2p', launch=date(2015, 6, 18),
         platforms={'iOS': .5, 'Android': .5}, accounts=2_600_000, retention=(.38, .62), payer=.05, arppu=190, stick=.22,
         ads=True, preprod_months=10, peak_team=16),
    dict(code='IS', name='Ironclad Skies', genre='Action / Flight', kind='premium', launch=date(2016, 11, 8), price=29.99,
         platforms={'Steam': .55, 'PlayStation': .3, 'Xbox': .15}, accounts=1_600_000, retention=(.75, .45), payer=.22, arppu=24,
         stick=.25, dlc=[('Storm Front', 9.99, 240), ('Aces of the North', 14.99, 520)], preprod_months=20, peak_team=30),
    dict(code='TK', name='Tiny Kingdoms Online', genre='Strategy / MMO', kind='f2p', launch=date(2018, 3, 21),
         platforms={'Steam': .25, 'iOS': .35, 'Android': .4}, accounts=1_900_000, retention=(.42, .5), payer=.07, arppu=560,
         stick=.3, ads=False, preprod_months=22, peak_team=38),
    dict(code='PP', name='Puzzle Parade', genre='Puzzle / Match-3', kind='f2p', launch=date(2019, 8, 6),
         platforms={'iOS': .45, 'Android': .55}, accounts=2_400_000, retention=(.4, .6), payer=.045, arppu=150, stick=.24,
         ads=True, preprod_months=12, peak_team=18),
    dict(code='ND', name='Neon Drift Rally', genre='Racing', kind='premium', launch=date(2020, 10, 15), price=39.99,
         platforms={'Steam': .4, 'PlayStation': .3, 'Xbox': .2, 'Epic Games Store': .1}, accounts=1_400_000,
         retention=(.78, .42), payer=.3, arppu=21, stick=.24, dlc=[('Midnight Circuit', 12.99, 300), ('Desert Pack', 7.99, 640)],
         preprod_months=26, peak_team=40),
    dict(code='LA', name='Little Legends Arena', genre='Action / PvP', kind='f2p', launch=date(2022, 5, 12),
         platforms={'Steam': .35, 'PlayStation': .2, 'Xbox': .1, 'iOS': .15, 'Android': .2}, accounts=2_100_000,
         retention=(.45, .48), payer=.09, arppu=340, stick=.32, ads=False, battle_pass=9.99, preprod_months=30, peak_team=60),
    dict(code='HH', name='Harvest Hollow', genre='Simulation / Cozy', kind='premium', launch=date(2023, 9, 26), price=24.99,
         platforms={'Steam': .6, 'Nintendo Switch': .4}, accounts=1_800_000, retention=(.82, .4), payer=.18, arppu=16,
         stick=.28, dlc=[('Seaside Village', 9.99, 280)], preprod_months=24, peak_team=26),
    dict(code='ST', name='Starbound Tactics', genre='Strategy / Tactics', kind='premium', launch=date(2025, 4, 9), price=34.99,
         platforms={'Steam': .7, 'PlayStation': .15, 'Xbox': .15}, accounts=900_000, retention=(.76, .44), payer=.12, arppu=15,
         stick=.26, dlc=[], preprod_months=28, peak_team=34),
    dict(code='PE', name='Project Ember', genre='Action RPG', kind='premium', launch=date(2027, 10, 1), price=59.99,
         platforms={'Steam': .4, 'PlayStation': .35, 'Xbox': .25}, accounts=0, retention=(.8, .4), payer=0, arppu=0,
         stick=.3, dlc=[], preprod_months=34, peak_team=55),
]

ITEM_PRICES = [0.99, 1.99, 4.99, 9.99, 19.99, 49.99, 99.99]
ITEM_WEIGHTS = [.30, .14, .25, .17, .08, .04, .02]

FUNDING = [(date(2015, 1, 12), 'Seed', 5_000_000), (date(2016, 2, 24), 'Series A', 20_000_000),
           (date(2018, 11, 7), 'Series B', 45_000_000), (date(2021, 6, 22), 'Series C', 110_000_000)]

DEPARTMENTS = {  # share of headcount, annual base salary (USD, US level)
    'Engineering': (.30, 135_000), 'Art & Animation': (.16, 98_000), 'Game Design': (.10, 105_000),
    'Production': (.07, 115_000), 'Quality Assurance': (.08, 62_000), 'Live Operations': (.05, 95_000),
    'Data & Analytics': (.04, 128_000), 'Marketing & UA': (.06, 110_000), 'Player Support': (.06, 52_000),
    'Finance': (.025, 118_000), 'People & Talent': (.02, 96_000), 'Legal': (.01, 165_000), 'IT & Security': (.025, 112_000),
    'Executive': (.01, 240_000)}

# cost assumptions (refined by calibrate())
COSTS = dict(hosting_per_dau_day=0.0011, cpi={'iOS': 3.4, 'Android': 1.9, 'Steam': 2.6, 'PlayStation': 4.2, 'Xbox': 4.2,
                                               'Nintendo Switch': 3.8, 'Epic Games Store': 2.6, 'Web Store': 2.0},
             paid_share=.42, ecpm_tier={1: 11.0, 2: 4.5, 3: 1.6}, ad_impressions_per_dau=6.5, refund_rate=.012,
             chargeback_rate=.002, deferred_share=.2, deferral_months=6, engine_royalty=.05, benefits_load=.24,
             rent_per_head_month=950, software_per_head_month=310, travel_per_head_month=120, tax_rate=.21)


def calibrate(out=None):
    """Refines cost and price assumptions from the collected public data (Gaming Operations Data), when present."""
    if out is None:
        return {}
    notes = {}
    try:
        summ = out.state('company_summary') or []
        mob = [r for r in summ if r.get('segment') == 'Mobile' and r.get('sales_marketing_pct_revenue')]
        if mob:
            import statistics
            notes['mobile_sm_pct'] = statistics.median(r['sales_marketing_pct_revenue'] for r in mob)
    except Exception:  # noqa: BLE001 - defaults stay
        pass
    return notes
