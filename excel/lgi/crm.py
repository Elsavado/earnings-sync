"""CRM: partner companies (all fictional), their contacts, deals and sales activities, and lifecycle e-mail
campaigns to opted-in players (campaign results plus a recipient-level log)."""
import numpy as np
import pandas as pd

from . import names
from .config import END, GAMES, SEED, START

PREFIX = ('Blue Summit Silver Harbor Golden Arc Crimson Peak Northstar Brightwave Ironwood Maple Lane Redstone Clearview '
          'Highland Oakridge Starlight Riverbend Stonegate Evergreen Bluewater Sunfield Westbrook Lakeside Cobalt Amber Vista '
          'Pinecrest Granite Hollow Copperleaf Falcon Ridge').split()
SUFFIX = {'Brand partner': ['Beverages', 'Snacks', 'Apparel', 'Sportswear', 'Headphones', 'Mobile', 'Motors', 'Energy Drinks'],
          'Licensing': ['Pictures', 'Comics', 'Animation', 'Toys', 'Publishing'],
          'Media & creators': ['Media', 'Network', 'Creators Guild', 'Studios', 'Podcast Network'],
          'Esports': ['Esports', 'Gaming Club', 'League', 'Tournaments'],
          'Retail & distribution': ['Retail', 'Distribution', 'Game Stores', 'Merchandise'],
          'Ad network': ['Ad Exchange', 'Mediation', 'Ad Network'],
          'Technology partner': ['Analytics', 'Cloud Services', 'Anti-Cheat', 'Voice Chat', 'Payments']}
DEAL = {'Brand partner': ('In-game brand collaboration', 60_000, 900_000), 'Licensing': ('IP licence', 100_000, 2_500_000),
        'Media & creators': ('Creator sponsorship', 10_000, 250_000), 'Esports': ('Tournament sponsorship', 25_000, 600_000),
        'Retail & distribution': ('Physical edition / merchandise', 50_000, 1_200_000), 'Ad network': ('Ad revenue agreement', 30_000, 500_000),
        'Technology partner': ('Vendor contract', 20_000, 400_000)}
STAGES = ['Prospecting', 'Qualification', 'Proposal', 'Negotiation', 'Closed Won', 'Closed Lost']


def b2b(emp):
    rng = np.random.default_rng(SEED + 777)
    owners = emp[emp.department.isin(['Marketing & UA', 'Executive', 'Legal'])].employee_id.values
    accounts, contacts, opps, acts = [], [], [], []
    used = set()
    for i in range(320):
        seg = rng.choice(list(SUFFIX), p=[.22, .1, .2, .1, .12, .1, .16])
        while True:
            nm = f'{rng.choice(PREFIX)} {rng.choice(SUFFIX[seg])}'
            if nm not in used:
                used.add(nm)
                break
        aid = f'ACC{i + 1:05d}'
        dom = nm.lower().replace(' ', '') + '.example'
        created = START + pd.Timedelta(days=int(rng.integers(0, (END - START).days)))
        accounts.append({'account_id': aid, 'name': nm, 'segment': seg, 'country': rng.choice(['US', 'GB', 'DE', 'JP', 'FR', 'KR', 'BR', 'CA']),
                         'website': f'https://www.{dom}', 'owner_id': rng.choice(owners) if len(owners) else '', 'created': created,
                         'employees_band': rng.choice(['1-50', '51-200', '201-1000', '1000+'], p=[.25, .35, .25, .15])})
        f, la = names.people(rng, ['en'] * 3)
        for k in range(int(rng.integers(1, 4))):
            contacts.append({'contact_id': f'CON{len(contacts) + 1:06d}', 'account_id': aid, 'first_name': f[k], 'last_name': la[k],
                             'title': rng.choice(['Partnerships Manager', 'Marketing Director', 'Head of Business Development',
                                                  'Brand Manager', 'Licensing Executive', 'Account Executive', 'VP Marketing']),
                             'email': f'{f[k].lower()}.{la[k].lower()}@{dom}', 'phone': f'+1-555-{rng.integers(100, 999)}-{rng.integers(1000, 9999)}'})
        for k in range(int(rng.poisson(3)) + 1):
            kind, lo, hi = DEAL[seg]
            open_d = created + pd.Timedelta(days=int(rng.integers(0, 900)))
            if open_d > END:
                continue
            close = open_d + pd.Timedelta(days=int(rng.integers(20, 180)))
            stage = rng.choice(STAGES, p=[.04, .06, .08, .07, .45, .30]) if close <= END else rng.choice(STAGES[:4])
            g = rng.choice([x for x in GAMES if x['launch'] <= max(close, open_d) and x['accounts']] or GAMES[:1])
            amt = round(float(np.exp(rng.uniform(np.log(lo), np.log(hi)))), -3)
            oid = f'OPP{len(opps) + 1:06d}'
            opps.append({'opportunity_id': oid, 'account_id': aid, 'name': f'{nm} x {g["name"]}: {kind}', 'type': kind, 'game': g['code'],
                         'amount_usd': amt, 'stage': stage, 'probability_pct': {'Prospecting': 10, 'Qualification': 20, 'Proposal': 40,
                                                                                'Negotiation': 70, 'Closed Won': 100, 'Closed Lost': 0}[stage],
                         'created': open_d, 'close_date': close, 'owner_id': accounts[-1]['owner_id']})
            for _ in range(int(rng.integers(2, 9))):
                d = open_d + pd.Timedelta(days=int(rng.integers(0, max(1, (min(close, END) - open_d).days))))
                acts.append({'activity_id': f'ACT{len(acts) + 1:07d}', 'opportunity_id': oid, 'account_id': aid,
                             'type': rng.choice(['Call', 'Meeting', 'Email', 'Demo', 'Contract review'], p=[.3, .25, .3, .1, .05]),
                             'date': d, 'owner_id': accounts[-1]['owner_id'], 'outcome': rng.choice(['Completed', 'Follow-up needed', 'No answer'],
                                                                                                 p=[.7, .22, .08])})
    return pd.DataFrame(accounts), pd.DataFrame(contacts), pd.DataFrame(opps), pd.DataFrame(acts)


def email_campaigns(gi, g, players, rng, sample_share=.01):
    """Monthly newsletter and event e-mails to opted-in players who were active in the last 90 days."""
    camps, recips = [], []
    launch = pd.Period(g['launch'], 'M')
    signup, last = players.signup_day.values, players.last_active_day.values
    opt = players.marketing_opt_in.values & (players.status.values != 'Deleted (GDPR request)')
    for m in pd.period_range(launch, pd.Period(END, 'M'), freq='M'):
        d = (m.to_timestamp() + pd.Timedelta(days=int(rng.integers(2, 25))) - pd.Timestamp(START)).days
        if pd.Timestamp(START) + pd.Timedelta(days=d) > pd.Timestamp(END):
            continue
        aud = np.nonzero(opt & (signup <= d) & (last >= d - 90))[0]
        if not len(aud):
            continue
        for kind in (['Newsletter', 'Event announcement'] if g['kind'] == 'f2p' else ['Newsletter']):
            cid = f'EM-{g["code"]}-{m}-{"NL" if kind == "Newsletter" else "EV"}'
            op = rng.beta(22, 60)
            ck = op * rng.beta(8, 60)
            n = len(aud)
            bounce = rng.binomial(n, .006)
            unsub = rng.binomial(n, .0015)
            camps.append({'campaign_id': cid, 'game': g['code'], 'type': kind, 'send_date': (pd.Timestamp(START) + pd.Timedelta(days=d)).date(),
                          'subject': f'{g["name"]}: {"what is new this month" if kind == "Newsletter" else "a limited-time event starts now"}',
                          'recipients': n, 'delivered': n - bounce, 'opens': int((n - bounce) * op), 'clicks': int((n - bounce) * ck),
                          'unsubscribes': unsub, 'bounces': bounce})
            s = aud[rng.random(n) < sample_share]
            o = rng.random(len(s)) < op
            c = o & (rng.random(len(s)) < ck / max(op, 1e-9))
            recips.append(pd.DataFrame({'campaign_id': cid, 'player_id': players.player_id.values[s], 'email': players.email.values[s],
                                        'opened': o, 'clicked': c}))
    return pd.DataFrame(camps), (pd.concat(recips, ignore_index=True) if recips else pd.DataFrame())
