"""Accounting (ERP) for Little Games Incorporated: staff and payroll, vendors and payables, store payouts and
receivables, user acquisition, fixed assets, capitalised development, deferred revenue, stock-based pay, funding, and
a double-entry general ledger from which the trial balance and the financial statements are built."""
from datetime import date

import numpy as np
import pandas as pd

from . import names
from .config import (COMPANY, COSTS, DEPARTMENTS, END, FUNDING, GAMES, PLATFORMS, SEED, START)

MONTHS = pd.period_range(START, END, freq='M')
DEV = ['Engineering', 'Art & Animation', 'Game Design', 'Production', 'Quality Assurance', 'Live Operations', 'Data & Analytics']
OVERHEAD = [d for d in DEPARTMENTS if d not in DEV]
STORE = {'iOS': 'App Store', 'Android': 'Google Play', 'Steam': 'Steam', 'PlayStation': 'PlayStation Store', 'Xbox': 'Microsoft Store',
         'Nintendo Switch': 'Nintendo eShop', 'Epic Games Store': 'Epic Games Store', 'Web Store': 'LGI Web Store (payment processor)'}
COA = [
    (1000, 'Cash and cash equivalents', 'Asset', 'Balance sheet'), (1100, 'Accounts receivable - stores', 'Asset', 'Balance sheet'),
    (1150, 'Accounts receivable - ad partners', 'Asset', 'Balance sheet'), (1200, 'Prepaid expenses', 'Asset', 'Balance sheet'),
    (1500, 'Property and equipment', 'Asset', 'Balance sheet'), (1550, 'Accumulated depreciation', 'Asset', 'Balance sheet'),
    (1600, 'Capitalised software development', 'Asset', 'Balance sheet'), (1650, 'Accumulated amortisation - software', 'Asset', 'Balance sheet'),
    (2000, 'Accounts payable', 'Liability', 'Balance sheet'), (2100, 'Accrued payroll taxes', 'Liability', 'Balance sheet'),
    (2200, 'Deferred revenue', 'Liability', 'Balance sheet'), (2300, 'Income tax payable', 'Liability', 'Balance sheet'),
    (3000, 'Preferred stock and paid-in capital', 'Equity', 'Balance sheet'), (3100, 'Paid-in capital - stock compensation', 'Equity', 'Balance sheet'),
    (4000, 'Game sales', 'Revenue', 'Revenue'), (4010, 'In-game purchases', 'Revenue', 'Revenue'), (4020, 'Season passes', 'Revenue', 'Revenue'),
    (4030, 'Downloadable content', 'Revenue', 'Revenue'), (4100, 'Advertising revenue', 'Revenue', 'Revenue'),
    (4900, 'Refunds and chargebacks', 'Revenue', 'Revenue'),
    (5000, 'Platform fees', 'Expense', 'Cost of revenue'), (5100, 'Hosting and infrastructure', 'Expense', 'Cost of revenue'),
    (5200, 'Engine royalties', 'Expense', 'Cost of revenue'), (5300, 'Amortisation of capitalised software', 'Expense', 'Cost of revenue'),
    (5400, 'Player support', 'Expense', 'Cost of revenue'), (5500, 'Payment processing', 'Expense', 'Cost of revenue'),
    (6000, 'R&D salaries and benefits', 'Expense', 'Research and development'),
    (6050, 'R&D contractors and outsourcing', 'Expense', 'Research and development'),
    (6100, 'Sales and marketing salaries', 'Expense', 'Sales and marketing'), (6150, 'User acquisition', 'Expense', 'Sales and marketing'),
    (6160, 'Brand and community marketing', 'Expense', 'Sales and marketing'), (6200, 'G&A salaries and benefits', 'Expense', 'General and administrative'),
    (6250, 'Rent and facilities', 'Expense', 'General and administrative'), (6260, 'Software and tools', 'Expense', 'General and administrative'),
    (6270, 'Professional fees', 'Expense', 'General and administrative'), (6280, 'Travel', 'Expense', 'General and administrative'),
    (6290, 'Recruiting', 'Expense', 'General and administrative'), (6300, 'Insurance', 'Expense', 'General and administrative'),
    (6400, 'Depreciation', 'Expense', 'General and administrative'), (6500, 'Stock-based compensation', 'Expense', 'Stock-based compensation'),
    (7000, 'Interest income', 'Revenue', 'Other income'), (8000, 'Income tax expense', 'Expense', 'Income tax')]
ACC = {a: n for a, n, _, _ in COA}
REV_ACC = {'game': 4000, 'in_app': 4010, 'season_pass': 4020, 'dlc': 4030}
VENDORS = [  # name, category, expense account, payment terms
    ('Northwind Cloud Hosting', 'Cloud hosting', 5100, 30), ('Forgelight Engine Licensing', 'Engine royalties', 5200, 45),
    ('Socialite Ads', 'User acquisition', 6150, 30), ('SearchPoint Ads', 'User acquisition', 6150, 30),
    ('ShortClip Ads', 'User acquisition', 6150, 30), ('PlayNet Exchange', 'User acquisition', 6150, 30),
    ('Creator Collective', 'Influencer marketing', 6160, 30), ('Brightline Brand Studio', 'Brand marketing', 6160, 30),
    ('Pixelhaven Art Outsourcing', 'Art outsourcing', 6050, 45), ('Tessellate Co-Dev', 'Co-development', 6050, 45),
    ('Lingua Loc Services', 'Localisation', 6050, 30), ('BugSweep QA Partners', 'Outsourced QA', 6050, 30),
    ('Helpdesk Harbor BPO', 'Player support outsourcing', 5400, 30), ('Soundforge Music Licensing', 'Music licensing', 6050, 30),
    ('Riverside Office Properties', 'Office rent', 6250, 0), ('Stackwise Software', 'Software subscriptions', 6260, 30),
    ('Hollis & Grant LLP', 'Legal', 6270, 30), ('Meridian Audit Partners', 'Audit and tax', 6270, 30),
    ('Talentbridge Recruiting', 'Recruiting', 6290, 30), ('Shieldmark Insurance', 'Insurance', 6300, 0),
    ('Kestrel Hardware Supply', 'Computer equipment', 1500, 30), ('Waypoint Travel', 'Travel', 6280, 15),
    ('Paygate Processing', 'Payment processing', 5500, 0)]
UA_VENDORS = ['Socialite Ads', 'SearchPoint Ads', 'ShortClip Ads', 'PlayNet Exchange']
RATE = {2015: .004, 2016: .006, 2017: .01, 2018: .018, 2019: .02, 2020: .005, 2021: .002, 2022: .02, 2023: .048, 2024: .05, 2025: .042, 2026: .037}


class Ledger:
    def __init__(self):
        self.lines, self.n = [], 0

    def je(self, day, memo, source, lines, ref=''):
        """lines: [(account, debit, credit, dims dict)]"""
        lines = [(a, round(d, 2), round(c, 2), dims) for a, d, c, dims in lines if round(d, 2) or round(c, 2)]
        if not lines:
            return
        diff = round(sum(d for _, d, _, _ in lines) - sum(c for _, _, c, _ in lines), 2)
        if diff:  # rounding
            a, d, c, dims = lines[-1]
            lines[-1] = (a, d, round(c + diff, 2), dims) if c else (a, round(d - diff, 2), c, dims)
        self.n += 1
        jid = f'JE{self.n:07d}'
        for i, (a, d, c, dims) in enumerate(lines, 1):
            self.lines.append({'journal_id': jid, 'line': i, 'date': day, 'account': a, 'account_name': ACC[a], 'debit': d, 'credit': c,
                               'memo': memo, 'source': source, 'reference': ref, 'game': dims.get('game', ''),
                               'platform': dims.get('platform', ''), 'department': dims.get('department', ''),
                               'vendor': dims.get('vendor', ''), 'customer': dims.get('customer', '')})

    def frame(self):
        return pd.DataFrame(self.lines)


def team_size(g, month):
    launch = pd.Period(g['launch'], 'M')
    start = launch - g['preprod_months']
    if month < start:
        return 0.0
    if month < launch:
        return g['peak_team'] * (.2 + .8 * (month - start).n / g['preprod_months'])
    k = (month - launch).n
    if g['kind'] == 'f2p':
        return g['peak_team'] * max(.55, 1 - .45 * k / 12)
    dlc = any(0 <= k - off // 30 <= 4 for _, _, off in g.get('dlc', []))
    return g['peak_team'] * (.3 if k < 18 else .12) * (1.8 if dlc else 1)


def staff(rng):
    """Monthly roster: founders, then hiring to the plan (game teams plus overhead) with attrition."""
    target = {}
    for m in MONTHS:
        dev = sum(team_size(g, m) for g in GAMES) * .62
        tot = max(4, dev / .76)
        target[m] = tot
    dshare = np.array([DEPARTMENTS[d][0] for d in DEPARTMENTS])
    emp, active, nid = [], [], 0
    founders = [('Executive', 'Chief Executive Officer'), ('Engineering', 'Chief Technology Officer'),
                ('Game Design', 'Creative Director'), ('Art & Animation', 'Art Director')]

    def hire(m, dept, title=None):
        nonlocal nid
        nid += 1
        loc = rng.choice(['Austin, US', 'Remote, US', 'Montreal, CA', 'Warsaw, PL', 'Manchester, GB'], p=[.55, .2, .1, .1, .05])
        f, la = names.people(rng, ['pl' if 'PL' in loc else 'fr' if 'CA' in loc and rng.random() < .5 else 'en'])
        level = title or rng.choice(['Associate', 'Mid-level', 'Senior', 'Lead', 'Principal', 'Manager', 'Director'],
                                    p=[.2, .3, .25, .1, .04, .08, .03])
        base = DEPARTMENTS[dept][1] * {'Associate': .72, 'Mid-level': .9, 'Senior': 1.12, 'Lead': 1.3, 'Principal': 1.45,
                                       'Manager': 1.35, 'Director': 1.75}.get(level, 2.0)
        base *= {'Austin, US': 1, 'Remote, US': .97, 'Montreal, CA': .78, 'Warsaw, PL': .55, 'Manchester, GB': .8}[loc]
        day = m.to_timestamp() + pd.Timedelta(days=int(rng.integers(0, 27)))
        e = {'employee_id': f'E{nid:05d}', 'first_name': f[0], 'last_name': la[0], 'department': dept,
             'title': title or f'{level} {dept.split(" &")[0].rstrip("s")}', 'level': level if not title else 'Executive',
             'location': loc, 'hire_date': day.date(), 'termination_date': None, 'termination_reason': None,
             'salary_usd': round(base * rng.normal(1, .06), -2), 'project': None}
        e['email'] = names.staff_email(e['first_name'], e['last_name'], nid)
        emp.append(e)
        active.append(e)
        return e
    for dept, title in founders:
        hire(MONTHS[0], dept, title)
    for m in MONTHS[1:]:
        for e in list(active):
            if e['level'] != 'Executive' and rng.random() < .011:
                e['termination_date'] = (m.to_timestamp() + pd.Timedelta(days=int(rng.integers(0, 27)))).date()
                e['termination_reason'] = rng.choice(['Resigned', 'Resigned', 'Resigned', 'Performance', 'Restructuring'])
                active.remove(e)
        if m.month == 4:
            for e in active:
                e['salary_usd'] = round(e['salary_usd'] * rng.normal(1.04, .015), -2)
        need = int(round(target[m])) - len(active)
        for _ in range(max(0, min(need, 25))):
            hire(m, rng.choice(list(DEPARTMENTS), p=dshare / dshare.sum()))
        if need < -8 and m.year in (2019, 2023):  # restructuring
            for e in rng.choice(active, size=min(-need, len(active) - 4), replace=False):
                if e['level'] != 'Executive':
                    e['termination_date'] = (m.to_timestamp() + pd.Timedelta(days=14)).date()
                    e['termination_reason'] = 'Restructuring'
                    active.remove(e)
        live = [g for g in GAMES if team_size(g, m) > 0]
        for e in active:
            if e['department'] in DEV and (e['project'] is None or not any(g['code'] == e['project'] for g in live)) and live:
                w = np.array([team_size(g, m) for g in live])
                e['project'] = live[int(rng.choice(len(live), p=w / w.sum()))]['code']
    return pd.DataFrame(emp)


def build(kpis_monthly, txn_monthly, paid_installs, tickets_monthly, emp=None):
    """kpis_monthly: month x game x platform -> dau_days; txn_monthly: month x game x platform x kind x status -> amount;
    paid_installs: month x game x platform x tier -> installs; tickets_monthly: month -> tickets."""
    rng = np.random.default_rng(SEED + 99)
    emp = staff(rng) if emp is None else emp
    L = Ledger()
    payroll, ap, pos, assets, ua, ar = [], [], [], [], [], []
    vend = {v[0]: v for v in VENDORS}
    inv_n = [0]

    def invoice(m, vendor, amount, memo, dims, account=None, po=None):
        if amount <= 0:
            return
        inv_n[0] += 1
        v = vend[vendor]
        day = (m.to_timestamp(how='end')).date()
        due = pd.Timestamp(day) + pd.Timedelta(days=v[3])
        paid = max(pd.Timestamp(day), due + pd.Timedelta(days=int(rng.integers(-3, 9))))
        paid = paid.date() if paid <= pd.Timestamp(END) else None
        acc = account or v[2]
        ref = f'INV-{inv_n[0]:07d}'
        ap.append({'invoice_id': ref, 'vendor': vendor, 'category': v[1], 'invoice_date': day, 'due_date': due.date(),
                   'amount_usd': round(amount, 2), 'account': acc, 'description': memo, 'po_number': po or '',
                   'paid_date': paid, 'status': 'Paid' if paid else 'Open', **{k: dims.get(k, '') for k in ('game', 'department')}})
        L.je(day, memo, 'AP', [(acc, amount, 0, {**dims, 'vendor': vendor}), (2000, 0, amount, {'vendor': vendor})], ref)
        if ap[-1]['paid_date']:
            L.je(ap[-1]['paid_date'], f'Payment {ref}: {memo}', 'AP payment', [(2000, amount, 0, {'vendor': vendor}), (1000, 0, amount, {'vendor': vendor})], ref)

    cash_bal, cap_by_game, def_sched = 0.0, {}, {}
    for when, rnd, amt in FUNDING:
        if when <= END:
            L.je(when, f'{rnd} financing', 'Equity', [(1000, amt, 0, {}), (3000, 0, amt, {})], rnd)
    for m in MONTHS:
        mend = m.to_timestamp(how='end').date()
        if mend > END:
            mend = END
        y = m.year
        # ---- payroll ----
        act = emp[(pd.to_datetime(emp.hire_date) <= m.to_timestamp(how='end')) &
                  (emp.termination_date.isna() | (pd.to_datetime(emp.termination_date) >= m.to_timestamp()))]
        dept_cost = {}
        for e in act.itertuples():
            gross = e.salary_usd / 12
            tax = gross * .0765
            ben = gross * (COSTS['benefits_load'] - .0765)
            payroll.append({'period': str(m), 'employee_id': e.employee_id, 'department': e.department, 'gross_pay_usd': round(gross, 2),
                            'employer_taxes_usd': round(tax, 2), 'benefits_usd': round(ben, 2), 'project': e.project or ''})
            k = (e.department, e.project or '')
            dept_cost[k] = dept_cost.get(k, 0) + gross + tax + ben
        for (dept, proj), cost in dept_cost.items():
            acc = 6000 if dept in DEV else 6100 if dept == 'Marketing & UA' else 5400 if dept == 'Player Support' else 6200
            L.je(mend, f'Payroll {m} {dept}', 'Payroll', [(acc, cost, 0, {'department': dept, 'game': proj}),
                                                           (1000, 0, cost * .9, {'department': dept}), (2100, 0, cost * .1, {'department': dept})], f'PR-{m}')
            L.je(mend + pd.Timedelta(days=10) if mend + pd.Timedelta(days=10) <= END else mend, f'Payroll taxes remitted {m} {dept}', 'Payroll',
                 [(2100, cost * .1, 0, {'department': dept}), (1000, 0, cost * .1, {'department': dept})], f'PR-{m}')
        # stock-based compensation
        sbc = sum(dept_cost.values()) * (.04 if y < 2019 else .07)
        L.je(mend, f'Stock compensation {m}', 'Equity', [(6500, sbc, 0, {}), (3100, 0, sbc, {})])
        # capitalised development: premium games in the 12 months before launch
        for g in GAMES:
            launch = pd.Period(g['launch'], 'M')
            if g['kind'] == 'premium' and 0 < (launch - m).n <= 12:
                c = sum(v for (d, p), v in dept_cost.items() if p == g['code'] and d in DEV) * .45
                cap_by_game[g['code']] = cap_by_game.get(g['code'], 0) + c
                L.je(mend, f'Capitalise development {g["name"]} {m}', 'Capitalisation', [(1600, c, 0, {'game': g['code']}),
                                                                                         (6000, 0, c, {'game': g['code']})])
            if g['kind'] == 'premium' and 0 <= (m - launch).n < 24 and cap_by_game.get(g['code']):
                a = cap_by_game[g['code']] / 24
                L.je(mend, f'Amortise {g["name"]} {m}', 'Amortisation', [(5300, a, 0, {'game': g['code']}), (1650, 0, a, {'game': g['code']})])
        # ---- revenue, fees, receivables ----
        tm = txn_monthly[txn_monthly.month == str(m)]
        for (gc, plat), grp in tm[tm.kind != 'ads'].groupby(['game', 'platform']):
            fee = PLATFORMS[plat][0]
            cust = STORE[plat]
            comp = grp[grp.status == 'completed']
            gross = comp.amount.sum()
            refunds = grp[grp.status != 'completed'].amount.sum()
            lines, deferred = [], 0
            for kind, amt in comp.groupby('kind').amount.sum().items():
                d = amt * COSTS['deferred_share'] if kind in ('in_app', 'season_pass') else 0
                deferred += d
                lines.append((REV_ACC[kind], 0, amt - d, {'game': gc, 'platform': plat, 'customer': cust}))
            net = gross * (1 - fee)
            lag = PLATFORMS[plat][1]
            ref = f'AR-{gc}-{plat[:3].upper()}-{m}'
            L.je(mend, f'{cust} sales {gc} {m}', 'Store statement', [(1100, net, 0, {'game': gc, 'platform': plat, 'customer': cust}),
                                                                     (5000, gross * fee, 0, {'game': gc, 'platform': plat, 'customer': cust})] + lines +
                 [(2200, 0, deferred, {'game': gc, 'platform': plat})], ref)
            if refunds:
                L.je(mend, f'{cust} refunds and chargebacks {gc} {m}', 'Store statement',
                     [(4900, refunds * (1 - fee), 0, {'game': gc, 'platform': plat, 'customer': cust}),
                      (1100, 0, refunds * (1 - fee), {'game': gc, 'platform': plat, 'customer': cust})], ref)
            if deferred:
                for k in range(1, COSTS['deferral_months'] + 1):
                    def_sched[(m + k, gc, plat)] = def_sched.get((m + k, gc, plat), 0) + deferred / COSTS['deferral_months']
            pay = pd.Timestamp(mend) + pd.Timedelta(days=lag)
            amount_due = net - refunds * (1 - fee)
            ar.append({'statement_id': ref, 'customer': cust, 'game': gc, 'platform': plat, 'period': str(m), 'gross_sales_usd': round(gross, 2),
                       'refunds_usd': round(refunds, 2), 'platform_fee_usd': round(gross * fee, 2), 'net_due_usd': round(amount_due, 2),
                       'statement_date': mend, 'expected_payment': pay.date(), 'received_date': pay.date() if pay <= pd.Timestamp(END) else None})
            if pay <= pd.Timestamp(END):
                L.je(pay.date(), f'Payout {ref}', 'Cash receipt', [(1000, amount_due, 0, {'customer': cust}), (1100, 0, amount_due, {'customer': cust})], ref)
            if plat == 'Web Store':
                invoice(m, 'Paygate Processing', gross * .029, f'Card processing {m}', {'game': gc})
            g = next(x for x in GAMES if x['code'] == gc)
            if g['kind'] == 'premium':
                invoice(m, 'Forgelight Engine Licensing', max(0, gross * (1 - fee)) * COSTS['engine_royalty'], f'Engine royalty {gc} {m}', {'game': gc})
        for (gc, plat), amt in [(k[1:], v) for k, v in def_sched.items() if k[0] == m]:
            kind_acc = 4010
            L.je(mend, f'Deferred revenue released {gc} {m}', 'Revenue recognition',
                 [(2200, amt, 0, {'game': gc, 'platform': plat}), (kind_acc, 0, amt, {'game': gc, 'platform': plat})])
        ads = tm[tm.kind == 'ads'].amount.sum()
        if ads:
            L.je(mend, f'Ad mediation revenue {m}', 'Ad partners', [(1150, ads, 0, {'customer': 'Ad mediation partners'}),
                                                                     (4100, 0, ads, {'customer': 'Ad mediation partners'})], f'ADS-{m}')
            pay = pd.Timestamp(mend) + pd.Timedelta(days=45)
            if pay <= pd.Timestamp(END):
                L.je(pay.date(), f'Ad partner payout {m}', 'Cash receipt', [(1000, ads, 0, {}), (1150, 0, ads, {})], f'ADS-{m}')
        # ---- operating costs through payables ----
        km = kpis_monthly[kpis_monthly.month == str(m)]
        for gc, dd in km.groupby('game').dau_days.sum().items():
            invoice(m, 'Northwind Cloud Hosting', dd * COSTS['hosting_per_dau_day'] * rng.normal(1, .05), f'Hosting {gc} {m}', {'game': gc})
        pi = paid_installs[paid_installs.month == str(m)]
        for r in pi.itertuples():
            cpi = COSTS['cpi'][r.platform] * {1: 1.0, 2: .55, 3: .3}[r.tier] * (1 + .03 * (y - 2015))
            spend = r.installs * cpi
            vendor = UA_VENDORS[hash((r.game, r.platform, r.tier)) % len(UA_VENDORS)]
            camp = f'UA-{r.game}-{r.platform[:3].upper()}-T{r.tier}-{m}'
            ua.append({'campaign_id': camp, 'month': str(m), 'game': r.game, 'platform': r.platform, 'country_tier': r.tier, 'channel': vendor,
                       'installs': int(r.installs), 'spend_usd': round(spend, 2), 'cpi_usd': round(cpi, 2)})
            invoice(m, vendor, spend, f'User acquisition {camp}', {'game': r.game, 'department': 'Marketing & UA'})
        heads = len(act)
        invoice(m, 'Riverside Office Properties', heads * COSTS['rent_per_head_month'], f'Rent {m}', {'department': 'People & Talent'})
        invoice(m, 'Stackwise Software', heads * COSTS['software_per_head_month'], f'Software {m}', {'department': 'IT & Security'})
        invoice(m, 'Waypoint Travel', heads * COSTS['travel_per_head_month'] * rng.uniform(.5, 1.5), f'Travel {m}', {})
        hires = emp[pd.to_datetime(emp.hire_date).dt.to_period('M') == m]
        if len(hires):
            invoice(m, 'Talentbridge Recruiting', hires.salary_usd.sum() * .18 * .35, f'Recruiting fees {m} ({len(hires)} hires)', {'department': 'People & Talent'})
            po = f'PO-{m}-HW'
            cost = len(hires) * 2600
            pos.append({'po_number': po, 'vendor': 'Kestrel Hardware Supply', 'date': mend, 'description': f'Laptops and peripherals for {len(hires)} new hires',
                        'amount_usd': cost, 'status': 'Received'})
            invoice(m, 'Kestrel Hardware Supply', cost, f'Equipment {m}', {}, po=po)
            assets.append({'asset_id': f'FA-{m}-HW', 'description': f'Workstations ({len(hires)})', 'in_service': mend, 'cost_usd': cost, 'life_months': 36})
        if m.month == 1:
            invoice(m, 'Shieldmark Insurance', 18_000 + heads * 900, f'Insurance {y}', {})
            invoice(m, 'Meridian Audit Partners', 0 if y < 2017 else 60_000 + heads * 400, f'Audit and tax {y - 1}', {'department': 'Finance'})
            if heads > 20:
                po = f'PO-{y}-SRV'
                cost = heads * 1800
                pos.append({'po_number': po, 'vendor': 'Kestrel Hardware Supply', 'date': mend, 'description': 'Build servers and devkits',
                            'amount_usd': cost, 'status': 'Received'})
                invoice(m, 'Kestrel Hardware Supply', cost, f'Servers and devkits {y}', {}, po=po)
                assets.append({'asset_id': f'FA-{y}-SRV', 'description': 'Build servers and development kits', 'in_service': mend, 'cost_usd': cost, 'life_months': 36})
        invoice(m, 'Hollis & Grant LLP', rng.uniform(6_000, 18_000) + heads * 60, f'Legal services {m}', {'department': 'Legal'})
        invoice(m, 'Helpdesk Harbor BPO', tickets_monthly.get(str(m), 0) * .55 * 4.2, f'Outsourced support {m}', {'department': 'Player Support'})
        for g in GAMES:
            launch = pd.Period(g['launch'], 'M')
            k = (launch - m).n
            if 0 <= k <= 3:
                invoice(m, 'Brightline Brand Studio', g['peak_team'] * 9_000, f'Launch campaign {g["name"]}', {'game': g['code'], 'department': 'Marketing & UA'})
                invoice(m, 'Creator Collective', g['peak_team'] * 4_000, f'Creator programme {g["name"]}', {'game': g['code'], 'department': 'Marketing & UA'})
            if 1 <= k <= 6:
                invoice(m, 'Lingua Loc Services', g['peak_team'] * 2_500, f'Localisation {g["name"]}', {'game': g['code']})
                invoice(m, 'BugSweep QA Partners', g['peak_team'] * 3_000, f'Compatibility QA {g["name"]}', {'game': g['code']})
            if 1 <= k <= g['preprod_months'] and g['kind'] == 'premium':
                invoice(m, 'Pixelhaven Art Outsourcing', g['peak_team'] * 2_200, f'Art outsourcing {g["name"]}', {'game': g['code']})
                if k % 3 == 0:
                    invoice(m, 'Soundforge Music Licensing', 15_000, f'Music licences {g["name"]}', {'game': g['code']})
            if g['kind'] == 'f2p' and m >= launch and m.month % 2 == 0:
                invoice(m, 'Tessellate Co-Dev', g['peak_team'] * 1_500, f'Live content co-development {g["name"]}', {'game': g['code']})
        # depreciation
        dep = sum(a['cost_usd'] / a['life_months'] for a in assets
                  if pd.Period(a['in_service'], 'M') < m <= pd.Period(a['in_service'], 'M') + a['life_months'])
        L.je(mend, f'Depreciation {m}', 'Depreciation', [(6400, dep, 0, {}), (1550, 0, dep, {})])
        # interest on cash
        gl = L.frame() if m.month == 12 or m == MONTHS[-1] else None
        if gl is not None:
            cash_bal = gl[gl.account == 1000].eval('debit - credit').sum()
            intr = max(0, cash_bal) * RATE.get(y, .03) * (12 if m.month == 12 else m.month) / 12
            L.je(mend, f'Interest income {y}', 'Treasury', [(1000, intr, 0, {}), (7000, 0, intr, {})])
            pre = gl[(gl.account >= 4000) & (gl.account != 8000)].eval('credit - debit').sum() + intr
            prior = gl[gl.account == 8000].eval('debit - credit').sum()
            due = max(0, pre * COSTS['tax_rate'] - prior)  # losses carried forward
            if due and m.month == 12:
                L.je(mend, f'Income tax {y}', 'Tax', [(8000, due, 0, {}), (2300, 0, due, {})])
                pay = date(y + 1, 4, 15)
                if pay <= END:
                    L.je(pay, f'Income tax paid {y}', 'Tax', [(2300, due, 0, {}), (1000, 0, due, {})])
    gl = L.frame()
    return emp, pd.DataFrame(payroll), gl, pd.DataFrame(ap), pd.DataFrame(pos), pd.DataFrame(assets), pd.DataFrame(ua), pd.DataFrame(ar)


def statements(gl):
    gl = gl.copy()
    gl['month'] = pd.to_datetime(gl.date).dt.to_period('M').astype(str)
    gl['year'] = gl.month.str[:4]
    cls = {a: (t, sec) for a, _, t, sec in COA}
    gl['type'] = gl.account.map(lambda a: cls[a][0])
    gl['section'] = gl.account.map(lambda a: cls[a][1])
    tb = gl.groupby(['month', 'account', 'account_name', 'type'])[['debit', 'credit']].sum().reset_index()
    tb['net'] = tb.debit - tb.credit
    pl = gl[gl.account >= 4000].copy()
    pl['amount'] = pl.credit - pl.debit
    order = ['Revenue', 'Cost of revenue', 'Research and development', 'Sales and marketing', 'General and administrative',
             'Stock-based compensation', 'Other income', 'Income tax']

    def income(by):
        t = pl.pivot_table(index=['section', 'account_name'], columns=by, values='amount', aggfunc='sum', fill_value=0)
        rows = []
        for sec in order:
            if sec not in t.index.get_level_values(0):
                continue
            for (s, a), v in t.loc[[sec]].iterrows():
                rows.append({'section': s, 'line': a, **v.round(2).to_dict()})
            rows.append({'section': sec, 'line': f'Total {sec.lower()}', **t.loc[sec].sum().round(2).to_dict()})
            if sec == 'Cost of revenue':
                rows.append({'section': 'Gross profit', 'line': 'Gross profit', **(t.loc['Revenue'].sum() + t.loc['Cost of revenue'].sum()).round(2).to_dict()})
            if sec == 'Stock-based compensation':
                op = t.loc[[s for s in order[:6] if s in t.index.get_level_values(0)]].sum()
                rows.append({'section': 'Operating income', 'line': 'Operating income (loss)', **op.round(2).to_dict()})
        rows.append({'section': 'Net income', 'line': 'Net income (loss)', **t.sum().round(2).to_dict()})
        return pd.DataFrame(rows)
    is_m, is_y = income('month'), income('year')
    # balance sheet: cumulative balances at month end
    bs_acc = gl[gl.account < 4000].groupby(['month', 'account', 'account_name', 'type']).apply(lambda x: (x.debit - x.credit).sum()).unstack(['account', 'account_name', 'type']).fillna(0).cumsum()
    ni = pl.groupby('month').amount.sum().reindex(bs_acc.index, fill_value=0).cumsum()
    rows = []
    for (a, n, t) in bs_acc.columns:
        sign = 1 if t == 'Asset' else -1
        rows.append({'section': t, 'line': n, **(bs_acc[(a, n, t)] * sign).round(2).to_dict()})
    rows.append({'section': 'Equity', 'line': 'Accumulated deficit / retained earnings', **ni.round(2).to_dict()})
    bs = pd.DataFrame(rows)
    assets = bs[bs.section == 'Asset'].iloc[:, 2:].sum()
    le = bs[bs.section != 'Asset'].iloc[:, 2:].sum()
    check = (assets - le).abs().max()
    bs = pd.concat([bs, pd.DataFrame([{'section': 'Check', 'line': 'Total assets', **assets.round(2).to_dict()},
                                      {'section': 'Check', 'line': 'Total liabilities and equity', **le.round(2).to_dict()}])])
    # cash flow (direct, by source) per year
    cash = gl[gl.account == 1000].copy()
    cash['amount'] = cash.debit - cash.credit
    cash['activity'] = cash.source.map(lambda s: 'Financing' if s == 'Equity' else 'Investing' if s == 'Capex' else 'Operating')
    cash.loc[cash.memo.str.contains('Equipment|Servers and devkits', regex=True) & (cash.source == 'AP payment'), 'activity'] = 'Investing'
    cf = cash.pivot_table(index=['activity', 'source'], columns='year', values='amount', aggfunc='sum', fill_value=0).round(2).reset_index()
    return tb, is_m, is_y, bs, cf, check
