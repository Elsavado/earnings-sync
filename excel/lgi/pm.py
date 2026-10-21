"""Project management (issue-tracker export): projects, releases, sprints, issues and work logs. Teams are the
employees assigned to each game in the staff roster; issue volume follows team size, and releases follow the launch
and content schedule."""
import numpy as np
import pandas as pd

from .config import GAMES, SEED
from .finance import DEV, MONTHS, team_size

FEATURES = {
    'Gameplay': ['combat feel', 'enemy behaviour', 'quest chain', 'boss encounter', 'progression curve', 'crafting', 'matchmaking rules'],
    'UI/UX': ['shop screen', 'settings menu', 'onboarding flow', 'inventory grid', 'HUD layout', 'accessibility options'],
    'Backend': ['login service', 'leaderboard API', 'save sync', 'inventory service', 'anti-cheat checks', 'event scheduler'],
    'Art': ['character skins', 'environment props', 'VFX pass', 'lighting pass', 'animation set', 'UI icons'],
    'Audio': ['music stems', 'ambient loops', 'UI sounds', 'voice lines'],
    'Monetisation': ['offer wall', 'season pass track', 'starter bundle', 'price localisation', 'store rotation'],
    'LiveOps': ['holiday event', 'weekend tournament', 'limited-time mode', 'daily missions', 'login calendar'],
    'Performance': ['load times', 'memory budget', 'frame pacing', 'shader compile stutter', 'battery drain'],
    'Localization': ['string export', 'font coverage', 'text overflow fixes', 'voice-over integration'],
}
VERBS = {'Story': ['Implement', 'Design', 'Build', 'Add'], 'Task': ['Update', 'Set up', 'Refactor', 'Document', 'Review'],
         'Bug': ['Fix', 'Investigate', 'Resolve'], 'Spike': ['Prototype', 'Evaluate', 'Research']}


def build(emp, today):
    rng = np.random.default_rng(SEED + 555)
    projects, versions, sprints, issues, logs = [], [], [], [], []
    dev = emp[emp.department.isin(DEV)]
    for g in GAMES:
        launch = pd.Period(g['launch'], 'M')
        start = launch - g['preprod_months']
        if start > MONTHS[-1]:
            continue
        key = g['code']
        lead = dev[dev.project == key].employee_id.values
        projects.append({'project_key': key, 'name': g['name'], 'type': 'Game', 'lead_id': lead[0] if len(lead) else '',
                         'start_date': start.to_timestamp().date(), 'status': 'Live' if launch <= MONTHS[-1] else 'In development'})
        ms = [('Prototype', start + 2), ('Vertical slice', start + g['preprod_months'] // 3), ('Alpha', launch - g['preprod_months'] // 3),
              ('Beta', launch - 3), ('1.0 Launch', launch)]
        v = 1
        for name, when in ms:
            versions.append({'project_key': key, 'version': name, 'release_date': when.to_timestamp().date(), 'kind': 'Milestone'})
        m = launch + 1
        while m <= MONTHS[-1]:
            v += 1
            versions.append({'project_key': key, 'version': f'1.{v}', 'release_date': (m.to_timestamp() + pd.Timedelta(days=int(rng.integers(0, 20)))).date(),
                             'kind': 'Content update' if g['kind'] == 'f2p' else 'Patch'})
            m += 2 if g['kind'] == 'f2p' else 4
        for dname, _, off in g.get('dlc', []):
            versions.append({'project_key': key, 'version': f'DLC: {dname}', 'release_date': (g['launch'] + pd.Timedelta(days=off)),
                             'kind': 'DLC'})
        vers = pd.DataFrame([x for x in versions if x['project_key'] == key]).sort_values('release_date')
        day = start.to_timestamp()
        sn = 0
        epics = {}
        while day.date() <= today:
            sn += 1
            end = day + pd.Timedelta(days=13)
            m = pd.Period(day, 'M')
            team = dev[(dev.project == key) & (pd.to_datetime(dev.hire_date) <= day) &
                       (dev.termination_date.isna() | (pd.to_datetime(dev.termination_date) >= day))]
            heads = len(team) or max(1, int(round(team_size(g, m) * .62)))
            sid = f'{key}-S{sn:03d}'
            state = 'Closed' if end.date() < today else 'Active'
            sprints.append({'sprint_id': sid, 'project_key': key, 'name': f'{key} Sprint {sn}', 'start_date': day.date(),
                            'end_date': end.date(), 'state': state, 'team_size': heads})
            fix = vers[vers.release_date >= end.date()]
            fixv = fix.version.iloc[0] if len(fix) else ''
            n = rng.poisson(heads * 3.2)
            live = m >= launch
            types = rng.choice(['Story', 'Task', 'Bug', 'Spike'], n, p=[.38, .3, .27, .05] if live else [.5, .33, .12, .05])
            comps = rng.choice(list(FEATURES), n)
            for k in range(n):
                comp = comps[k]
                if comp not in epics:
                    epics[comp] = f'{key}-E{len(epics) + 1}'
                    issues.append({'issue_key': epics[comp], 'project_key': key, 'type': 'Epic', 'summary': f'{comp} for {g["name"]}',
                                   'component': comp, 'status': 'Done' if live else 'In Progress', 'priority': 'High', 'story_points': None,
                                   'assignee_id': lead[0] if len(lead) else '', 'reporter_id': lead[0] if len(lead) else '',
                                   'created': day.date(), 'resolved': None, 'sprint_id': '', 'epic_key': '', 'fix_version': ''})
                ty = types[k]
                who = team.employee_id.values[rng.integers(0, len(team))] if len(team) else ''
                created = day - pd.Timedelta(days=int(rng.integers(0, 30)))
                done = state == 'Closed' or rng.random() < .4
                status = 'Done' if done else rng.choice(['To Do', 'In Progress', 'In Review'])
                pts = int(rng.choice([1, 2, 3, 5, 8, 13], p=[.15, .25, .27, .2, .1, .03])) if ty in ('Story', 'Spike') else None
                ik = f'{key}-{len(issues) + 1}'
                issues.append({'issue_key': ik, 'project_key': key, 'type': ty,
                               'summary': f'{rng.choice(VERBS[ty])} {rng.choice(FEATURES[comp])}', 'component': comp, 'status': status,
                               'priority': rng.choice(['Low', 'Medium', 'High', 'Highest'], p=[.2, .55, .2, .05]), 'story_points': pts,
                               'assignee_id': who, 'reporter_id': lead[rng.integers(0, len(lead))] if len(lead) else who,
                               'created': created.date(), 'resolved': (day + pd.Timedelta(days=int(rng.integers(1, 14)))).date() if done else None,
                               'sprint_id': sid, 'epic_key': epics[comp], 'fix_version': fixv})
                if done and who:
                    for _ in range(int(rng.integers(1, 4))):
                        logs.append({'issue_key': ik, 'employee_id': who, 'date': (day + pd.Timedelta(days=int(rng.integers(0, 13)))).date(),
                                     'hours': float(rng.choice([.5, 1, 2, 3, 4, 6, 8]))})
            day = end + pd.Timedelta(days=1)
    return (pd.DataFrame(projects), pd.DataFrame(versions), pd.DataFrame(sprints), pd.DataFrame(issues), pd.DataFrame(logs))
