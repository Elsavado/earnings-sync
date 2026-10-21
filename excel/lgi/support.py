"""Customer support (help-desk export): tickets driven by daily active players, a ticket for every refund and
chargeback (linked to its transaction), conversation messages, agents, satisfaction surveys and SLA results."""
import numpy as np
import pandas as pd

from . import names
from .config import SEED
from .players import TODAY, to_date

CATS = [('Purchase not received', 'Billing', .11), ('Refund request', 'Billing', .0), ('Account access', 'Account', .16),
        ('Bug report', 'Technical', .19), ('Crash or performance', 'Technical', .12), ('Gameplay question', 'Gameplay', .14),
        ('Ban appeal', 'Trust & Safety', .05), ('Harassment report', 'Trust & Safety', .04), ('Feedback or suggestion', 'Feedback', .09),
        ('Data or privacy request', 'Privacy', .02), ('Progress lost', 'Technical', .08)]
CHANNELS = (['In-game form', 'Email', 'Web form', 'Social media', 'Platform store'], [.42, .28, .2, .06, .04])
PLAYER_LINES = {
    'Purchase not received': ['I bought {item} but it never showed up in my account.', 'Paid for {item} and got nothing. Please help.'],
    'Refund request': ['I would like a refund for {item}, it was bought by mistake.', 'Please refund {item}, it was not what I expected.'],
    'Account access': ["I can't log in to my account anymore.", 'My account was linked to an old email and I am locked out.'],
    'Bug report': ['There is a bug in {game}: the {thing} does not work after the last update.', 'Found a bug with the {thing} in {game}.'],
    'Crash or performance': ['{game} crashes every time I open the {thing}.', 'The game freezes on my device during the {thing}.'],
    'Gameplay question': ['How do I unlock the {thing} in {game}?', 'What is the best way to get more rewards from the {thing}?'],
    'Ban appeal': ['My account was banned and I do not know why. I never cheated.', 'Please review my suspension, I think it is a mistake.'],
    'Harassment report': ['A player keeps sending abusive messages in chat.', 'I want to report a player for harassment.'],
    'Feedback or suggestion': ['Love {game}! It would be great to have more {thing} options.', 'Suggestion: please rebalance the {thing}.'],
    'Data or privacy request': ['Please send me a copy of my personal data.', 'I want my account and data deleted.'],
    'Progress lost': ['I lost all my progress after changing devices.', 'My save is gone after the update, I had hours of progress.'],
}
AGENT_LINES = ['Thanks for reaching out, {first}. I have looked into your account and {fix}.',
               'Hi {first}, sorry for the trouble. {fix_cap}. Let us know if anything else comes up.',
               'Hello {first}, thank you for your patience. {fix_cap}.']
FIXES = {'Billing': 'restored the missing purchase to your account', 'Account': 'reset the login link and sent it to your email',
         'Technical': 'passed the details to our development team, and a fix is planned for the next update',
         'Gameplay': 'shared a guide that explains the steps', 'Trust & Safety': 'reviewed the case and taken the appropriate action',
         'Feedback': 'shared your suggestion with the design team', 'Privacy': 'completed your request as required by law'}
THINGS = ['shop', 'daily rewards', 'leaderboard', 'season pass', 'tutorial', 'garage', 'inventory', 'map', 'guild screen', 'settings menu']


def agents(emp, rng):
    staff = emp[emp.department == 'Player Support'][['employee_id', 'first_name', 'last_name', 'email', 'hire_date', 'termination_date']].copy()
    staff['team'] = 'Tier 2 (in-house)'
    f, la = names.people(rng, ['en'] * 60 + ['es'] * 30 + ['pt'] * 10)
    bpo = pd.DataFrame({'employee_id': [f'BPO{i:04d}' for i in range(1, 101)], 'first_name': f, 'last_name': la,
                        'email': [f'{a.lower()}.{b.lower()}@helpdeskharbor.example' for a, b in zip(f, la)],
                        'hire_date': pd.Timestamp('2016-06-01').date(), 'termination_date': None, 'team': 'Tier 1 (outsourced)'})
    return pd.concat([staff, bpo], ignore_index=True)


def tickets(gi, g, players, txn, kpis, agent_df, start_no):
    rng = np.random.default_rng(SEED + 1000 * gi + 11)
    daily = kpis.groupby('date').dau.sum()
    days = (pd.to_datetime(daily.index) - pd.Timestamp('2015-01-01')).days.values
    rate = .0006 if g['kind'] == 'f2p' else .0009
    n_day = rng.poisson(daily.values * rate)
    tday = np.repeat(days, n_day)
    signup, last = players.signup_day.values, players.last_active_day.values
    who = np.full(len(tday), -1)
    todo = np.arange(len(tday))
    for _ in range(12):
        if not len(todo):
            break
        hi = np.searchsorted(signup, tday[todo], side='right')
        pick = (rng.random(len(todo)) * np.maximum(hi, 1)).astype(int)
        ok = (hi > 0) & (last[pick] >= tday[todo])
        who[todo[ok]] = pick[ok]
        todo = todo[~ok]
    keep = who >= 0
    tday, who = tday[keep], who[keep]
    w = np.array([c[2] for c in CATS])
    cat = rng.choice(len(CATS), len(tday), p=w / w.sum())
    t = pd.DataFrame({'day': tday, 'pidx': who, 'category': np.asarray([c[0] for c in CATS], dtype=object)[cat], 'txn_id': ''})
    rf = txn[txn.status != 'completed']
    if len(rf):
        pidx = (rf.player_id.values - players.player_id.values[0])
        r = pd.DataFrame({'day': np.minimum(rf.day.values + rng.integers(0, 4, len(rf)), TODAY), 'pidx': pidx,
                          'category': np.where(rf.status.values == 'chargeback', 'Purchase not received', 'Refund request'),
                          'txn_id': rf.txn_id.values})
        t = pd.concat([t, r], ignore_index=True)
    t = t.sort_values('day', kind='stable').reset_index(drop=True)
    n = len(t)
    cat_group = dict((c[0], c[1]) for c in CATS)
    t['group'] = t.category.map(cat_group)
    t['ticket_id'] = [f'T{start_no + i:08d}' for i in range(1, n + 1)]
    p = players.iloc[t.pidx.values]
    t['player_id'] = p.player_id.values
    t['game'] = g['code']
    t['platform'] = p.platform.values
    t['country'] = p.country.values
    t['channel'] = rng.choice(CHANNELS[0], n, p=CHANNELS[1])
    t['priority'] = np.where(t.group.isin(['Billing', 'Trust & Safety', 'Privacy']), 'High', rng.choice(['Normal', 'Low', 'Urgent'], n, p=[.75, .2, .05]))
    sec = rng.integers(0, 86400, n)
    t['created_at'] = (to_date(t.day.values) + sec.astype('timedelta64[s]')).astype('datetime64[s]')
    frm = np.round(rng.lognormal(np.log(np.where(t.priority == 'Urgent', 25, np.where(t.priority == 'High', 90, 240))), .8))
    res = np.round(rng.lognormal(np.log(np.where(t.group == 'Technical', 52, 14)), .9), 1)
    t['first_response_minutes'] = frm.astype(int)
    t['resolution_hours'] = res
    t['solved_at'] = (t.created_at.values + (res * 3600).astype('timedelta64[s]')).astype('datetime64[s]')
    open_ = t.solved_at.values > np.datetime64(pd.Timestamp.now().floor('s'))
    t['status'] = np.where(open_, rng.choice(['Open', 'Pending'], n), 'Solved')
    t.loc[open_, 'solved_at'] = pd.NaT
    t.loc[open_, 'resolution_hours'] = np.nan
    t['sla_breached'] = (frm > np.where(t.priority == 'Urgent', 60, np.where(t.priority == 'High', 240, 1440)))
    tier1 = agent_df[agent_df.team.str.startswith('Tier 1')].employee_id.values
    tier2 = agent_df[agent_df.team.str.startswith('Tier 2')].employee_id.values
    esc = t.group.isin(['Trust & Safety', 'Privacy']) | (rng.random(n) < .15)
    t['escalated'] = esc
    t['assignee_id'] = np.where(esc & (len(tier2) > 0), tier2[rng.integers(0, max(1, len(tier2)), n)] if len(tier2) else '',
                                tier1[rng.integers(0, len(tier1), n)])
    sat = rng.random(n) < .32
    score = np.clip(np.round(rng.normal(np.where(res > 72, 3.0, 4.3), .9)), 1, 5)
    t['csat_score'] = np.where(sat & (t.status == 'Solved'), score, np.nan)
    t['first_name'] = p.first_name.values
    t['email'] = p.email.values
    t['item'] = ''
    if len(rf):
        m = t.txn_id != ''
        t.loc[m, 'item'] = t.loc[m, 'txn_id'].map(txn.set_index('txn_id').item)
    return t.drop(columns=['pidx', 'day'])


def messages(t, g, rng):
    rows = []
    for r in t.itertuples():
        thing = THINGS[hash(r.ticket_id) % len(THINGS)]
        item = r.item or 'a gem pack'
        rows.append({'ticket_id': r.ticket_id, 'seq': 1, 'author': 'player', 'author_id': r.player_id, 'created_at': r.created_at,
                     'body': rng.choice(PLAYER_LINES[r.category]).format(item=item, game=g['name'], thing=thing)})
        fix = FIXES[r.group] if r.category != 'Refund request' else 'processed a refund to your original payment method'
        reply_at = r.created_at + pd.Timedelta(minutes=int(r.first_response_minutes))
        rows.append({'ticket_id': r.ticket_id, 'seq': 2, 'author': 'agent', 'author_id': r.assignee_id, 'created_at': reply_at,
                     'body': rng.choice(AGENT_LINES).format(first=r.first_name, fix=fix, fix_cap=fix[0].upper() + fix[1:])})
        if r.escalated:
            rows.append({'ticket_id': r.ticket_id, 'seq': 3, 'author': 'player', 'author_id': r.player_id,
                         'created_at': reply_at + pd.Timedelta(hours=3), 'body': 'Thanks, any update on this?'})
    return pd.DataFrame(rows)
