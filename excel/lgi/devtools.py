"""Little Games Incorporated (fictional): the studio's tool exports and test data, built from the same staff roster,
projects, sprints and issues as the rest of the company's records (pm.py, finance.staff), so ids and dates agree.

  7 Tool Exports/Jira            issue-tracker export per project (Jira CSV columns and Jira REST-style JSON)
  7 Tool Exports/Slack           workspace export (users.json, channels.json, <channel>/<YYYY-MM-DD>.json), zipped
  7 Tool Exports/Discord         community server, one JSON file per channel (DiscordChatExporter layout)
  7 Tool Exports/Perforce        changelist history of the Unreal projects (`p4 describe -s` text and CSV)
  7 Tool Exports/Engine Projects project layouts per game (Unity, Unreal Engine or Godot) with script stubs
  8 Playtest & Analytics         playtest sessions, session events and surveys per milestone build; a sampled player
                                 analytics event stream for the live games

Everything is invented (see config.SYNTHETIC_NOTE); every folder's manifest.csv marks its files synthetic."""
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from gaming.out import log
from . import finance, names, pm
from .config import COMPANY, DOMAIN, END, FUNDING, GAMES, SEED, SYNTHETIC_NOTE

ROOT = f'{COMPANY}/7 Tool Exports'
JIRA, SLACK, DISCORD, P4, ENGINE = (f'{ROOT}/Jira', f'{ROOT}/Slack', f'{ROOT}/Discord', f'{ROOT}/Perforce', f'{ROOT}/Engine Projects')
PLAY = f'{COMPANY}/8 Playtest & Analytics'
ENGINES = {'PO': 'Unity', 'IS': 'Unreal', 'TK': 'Unity', 'PP': 'Unity', 'ND': 'Unreal', 'LA': 'Unreal', 'HH': 'Unity', 'ST': 'Godot',
           'PE': 'Unreal'}
ENGINE_VERSION = {'Unity': '2022.3.47f1', 'Unreal': '5.4', 'Godot': '4.3'}
EPOCH_DISCORD = 1420070400000


def sid(*a):
    """Stable numeric id (the same on every run)."""
    return int(hashlib.sha1(repr((SEED,) + a).encode()).hexdigest()[:15], 16)


def _manifest(out, folder, items, about):
    out.manifest(folder, [{'item': i, 'title': about, 'source_url': '', 'licence': 'Fictional data (generated)', 'synthetic': 'yes',
                           'collected_date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                           'notes': SYNTHETIC_NOTE} for i in items])


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for path, data in files.items():
            z.writestr(path, data if isinstance(data, (bytes, str)) else json.dumps(data, indent=1))
    return buf.getvalue()


def _ts(d, rng, h0=9, h1=18):
    return pd.Timestamp(d) + pd.Timedelta(seconds=int(rng.integers(h0 * 3600, h1 * 3600)))


# ---------------------------------------------------------------- Jira
def jira(out, emp, projects, versions, sprints, issues):
    who = emp.set_index('employee_id')
    nm = lambda e: f'{who.at[e, "first_name"]} {who.at[e, "last_name"]}' if e in who.index else ''  # noqa: E731
    mail = lambda e: who.at[e, 'email'] if e in who.index else ''  # noqa: E731
    jd = lambda d: '' if d is None or pd.isna(d) else pd.Timestamp(d).strftime('%d/%b/%y 9:00 AM')  # noqa: E731
    sp = sprints.set_index('sprint_id').name.to_dict()
    pname = projects.set_index('project_key').name.to_dict()
    items = []
    for key, grp in issues.groupby('project_key'):
        ids = {k: 10000 + i for i, k in enumerate(grp.issue_key)}
        csv = pd.DataFrame({
            'Summary': grp.summary, 'Issue key': grp.issue_key, 'Issue id': grp.issue_key.map(ids), 'Issue Type': grp.type,
            'Status': grp.status, 'Project key': key, 'Project name': pname.get(key, key), 'Priority': grp.priority,
            'Resolution': np.where(grp.status == 'Done', 'Done', 'Unresolved'), 'Assignee': grp.assignee_id.map(nm),
            'Reporter': grp.reporter_id.map(nm), 'Created': grp.created.map(jd), 'Resolved': grp.resolved.map(jd),
            'Fix Version/s': grp.fix_version, 'Component/s': grp.component, 'Sprint': grp.sprint_id.map(lambda s: sp.get(s, '')),
            'Custom field (Story Points)': grp.story_points, 'Custom field (Epic Link)': grp.epic_key})
        out.put(f'{JIRA}/{key} - Jira export.csv', csv.to_csv(index=False).encode('utf-8'), 'text/csv')
        rest = {'expand': 'names,schema', 'startAt': 0, 'maxResults': len(grp), 'total': len(grp), 'issues': [
            {'id': str(ids[r.issue_key]), 'key': r.issue_key, 'fields': {
                'summary': r.summary, 'issuetype': {'name': r.type}, 'status': {'name': r.status}, 'priority': {'name': r.priority},
                'project': {'key': key, 'name': pname.get(key, key)}, 'components': [{'name': r.component}],
                'assignee': {'displayName': nm(r.assignee_id), 'emailAddress': mail(r.assignee_id)} if r.assignee_id else None,
                'reporter': {'displayName': nm(r.reporter_id), 'emailAddress': mail(r.reporter_id)} if r.reporter_id else None,
                'created': f'{r.created}T09:00:00.000+0000', 'resolutiondate': f'{r.resolved}T17:00:00.000+0000' if r.resolved else None,
                'fixVersions': [{'name': r.fix_version}] if r.fix_version else [],
                'customfield_10016': None if pd.isna(r.story_points) else float(r.story_points),
                'customfield_10014': r.epic_key or None, 'customfield_10020': [{'name': sp.get(r.sprint_id, '')}] if r.sprint_id else []}}
            for r in grp.itertuples()]}
        out.put(f'{JIRA}/{key} - Jira REST export.json', json.dumps(rest).encode('utf-8'), 'application/json')
        items += [f'{key} - Jira export.csv', f'{key} - Jira REST export.json']
    _manifest(out, JIRA, items, 'Issue-tracker export (Jira formats)')
    log(f'  jira: {len(issues):,} issues in {len(items) // 2} projects')


# ---------------------------------------------------------------- Slack
def slack(out, emp, projects, versions, sprints, issues, rng, since):
    uid = {e: f'U{sid(e):012X}'[:11] for e in emp.employee_id}
    who = emp.set_index('employee_id')
    users = [{'id': uid[e.employee_id], 'name': f'{e.first_name.lower()}.{e.last_name.lower()}', 'real_name': f'{e.first_name} {e.last_name}',
              'deleted': bool(pd.notna(e.termination_date) and e.termination_date), 'profile': {'title': e.title, 'real_name': f'{e.first_name} {e.last_name}',
                                                               'display_name': e.first_name, 'email': e.email}, 'tz': 'America/Chicago'}
             for e in emp.itertuples()]
    msgs = {}

    def say(ch, when, emp_id, text, thread=None):
        if not since <= pd.Timestamp(when).date() < END or emp_id not in uid:
            return None
        ts = f'{pd.Timestamp(when).timestamp():.6f}'
        m = {'type': 'message', 'user': uid[emp_id], 'text': text, 'ts': ts,
             'user_profile': {'real_name': f'{who.at[emp_id, "first_name"]} {who.at[emp_id, "last_name"]}', 'display_name': who.at[emp_id, 'first_name']}}
        if thread:
            m['thread_ts'] = thread
        msgs.setdefault(ch, []).append(m)
        return ts
    ceo = emp.employee_id.iloc[0]
    hr = emp[emp.department == 'People & Talent'].employee_id
    hr = hr.iloc[0] if len(hr) else ceo
    for e in emp.itertuples():
        say('general', _ts(e.hire_date, rng, 9, 11), hr, f'Please welcome <@{uid[e.employee_id]}>, joining {e.department} as {e.title} '
            f'({e.location}) :wave:')
    for when, rnd, amt in FUNDING:
        say('general', _ts(when, rng, 11, 12), ceo, f'Big news: we closed our {rnd} (USD {amt / 1e6:,.0f}M). All-hands at 3pm to talk about what it means for us.')
    leads = projects.set_index('project_key').lead_id.to_dict()
    names_ = {g['code']: g['name'] for g in GAMES}
    done = issues[(issues.status == 'Done') & (issues.type != 'Epic')]
    by_fix = done.groupby(['project_key', 'fix_version']).summary.apply(list).to_dict()
    for v in versions.itertuples():
        lead = leads.get(v.project_key)
        notes = by_fix.get((v.project_key, v.version), [])[:6]
        say('releases', _ts(v.release_date, rng, 14, 17), lead, f'*{names_.get(v.project_key)} {v.version}* is out ({v.kind}). Highlights:\n' +
            '\n'.join(f'• {s}' for s in notes) if notes else f'*{names_.get(v.project_key)} {v.version}* is out ({v.kind}).')
    by_sprint = dict(tuple(issues[issues.type != 'Epic'].groupby('sprint_id')))
    empty = issues.iloc[:0]
    for s in sprints.itertuples():
        ch = f'{s.project_key.lower()}-dev'
        lead = leads.get(s.project_key)
        its = by_sprint.get(s.sprint_id, empty)
        goals = its[its.type == 'Story'].summary.head(3).tolist()
        t = say(ch, _ts(s.start_date, rng, 9, 10), lead, f'{s.name} starts today ({s.team_size} people). Goals: ' + '; '.join(goals or ['carry-over work']))
        if t and len(its):
            for r in its.sample(min(len(its), 8), random_state=int(rng.integers(1 << 30))).itertuples():
                if r.status == 'Done' and r.resolved and r.assignee_id:
                    say(ch, _ts(r.resolved, rng), r.assignee_id, rng.choice([
                        f'Merged: {r.summary} ({r.issue_key}). Ready for QA.', f'{r.issue_key} is done - {r.summary.lower()}. PR needs one more review.',
                        f'Closed {r.issue_key} ({r.summary}). Notes are on the ticket.']))
                elif r.type == 'Bug' and r.reporter_id:
                    say('qa', _ts(r.created, rng), r.reporter_id, f'New {r.priority.lower()} bug in {names_.get(s.project_key)}: {r.summary} ({r.issue_key})')
    for g in GAMES:
        launch = pd.Timestamp(g['launch'])
        lead = leads.get(g['code'])
        day = max(launch, pd.Timestamp(since)) + pd.Timedelta(days=int(rng.integers(5, 40)))
        while day.date() <= END and lead:
            t = say('incidents', day, lead, f':rotating_light: {g["name"]}: {rng.choice(["login errors spiking", "store purchases failing on one platform", "matchmaking queue times up 4x", "crash rate up after the hotfix", "leaderboard service timing out"])}. Investigating.')
            if t:
                say('incidents', day + pd.Timedelta(minutes=int(rng.integers(20, 180))), lead,
                    rng.choice(['Mitigated: rolled back the config change. Post-mortem doc to follow.', 'Resolved - the upstream provider fixed it. Monitoring.',
                                'Fixed with a server-side patch; no client update needed.']), t)
            day += pd.Timedelta(days=int(rng.integers(20, 75)))
    files = {'users.json': users}
    chans = []
    for ch, ms in msgs.items():
        ms.sort(key=lambda m: float(m['ts']))
        created = int(float(ms[0]['ts']))
        chans.append({'id': f'C{sid(ch):012X}'[:11], 'name': ch, 'created': created, 'creator': ms[0]['user'],
                      'is_archived': False, 'is_general': ch == 'general', 'members': sorted({m['user'] for m in ms}),
                      'topic': {'value': '', 'creator': '', 'last_set': 0}, 'purpose': {'value': f'#{ch}', 'creator': '', 'last_set': 0}})
        for day, grp in pd.Series(ms).groupby([datetime.fromtimestamp(float(m['ts']), timezone.utc).strftime('%Y-%m-%d') for m in ms]):
            files[f'{ch}/{day}.json'] = list(grp)
    files['channels.json'] = chans
    out.put(f'{SLACK}/Little Games Inc Slack export.zip', _zip(files), 'application/zip')
    _manifest(out, SLACK, ['Little Games Inc Slack export.zip'], 'Workspace export in Slack\'s export layout')
    log(f'  slack: {sum(len(v) for v in msgs.values()):,} messages in {len(chans)} channels')


# ---------------------------------------------------------------- Discord
def discord(out, emp, versions, issues, rng, since):
    community = emp[emp.department.isin(['Live Operations', 'Marketing & UA', 'Player Support'])]
    mods = community.employee_id.tolist() or emp.employee_id.tolist()[:3]
    who = emp.set_index('employee_id')
    players = names.usernames(rng, np.arange(1, 4001))
    seq = [0]

    def snow(when):
        seq[0] += 1
        return str(((int(pd.Timestamp(when).timestamp() * 1000) - EPOCH_DISCORD) << 22) | (seq[0] % 4096))

    def author(staff=None, player=None):
        if staff:
            return {'id': str(sid(staff) % 10**18), 'name': f'{who.at[staff, "first_name"]}_LGI', 'discriminator': '0000',
                    'nickname': f'{who.at[staff, "first_name"]} | Little Games', 'isBot': False, 'roles': [{'name': 'Staff'}]}
        return {'id': str(sid(player) % 10**18), 'name': player.lower(), 'discriminator': '0000', 'nickname': player,
                'isBot': False, 'roles': [{'name': 'Player'}]}
    guild = {'id': str(sid('guild') % 10**18), 'name': 'Little Games Community'}
    chans = {}

    def post(ch, cat, when, content, staff=None, player=None):
        if not since <= pd.Timestamp(when).date() < END:
            return
        chans.setdefault((ch, cat), []).append({'id': snow(when), 'type': 'Default', 'timestamp': pd.Timestamp(when).tz_localize('UTC').isoformat(),
                                                'timestampEdited': None, 'isPinned': False, 'content': content, 'author': author(staff, player),
                                                'attachments': [], 'embeds': [], 'reactions': [], 'mentions': []})
    done = issues[(issues.status == 'Done') & (issues.type.isin(['Story', 'Bug']))]
    by_fix = done.groupby(['project_key', 'fix_version']).summary.apply(list).to_dict()
    for g in GAMES:
        if g['launch'] > END:
            continue
        code = g['code'].lower()
        for v in versions[versions.project_key == g['code']].itertuples():
            if pd.Timestamp(v.release_date).date() > END:
                continue
            notes = by_fix.get((g['code'], v.version), [])[:8]
            post(f'{code}-patch-notes', g['name'], _ts(v.release_date, rng, 15, 18), f'**{g["name"]} {v.version}**\n' +
                 '\n'.join(f'- {s}' for s in notes) if notes else f'**{g["name"]} {v.version}** is live.', staff=mods[int(rng.integers(len(mods)))])
        bugs = issues[(issues.project_key == g['code']) & (issues.type == 'Bug')]
        bugs = bugs[pd.to_datetime(bugs.created) >= pd.Timestamp(g['launch'])]
        for r in bugs.sample(min(len(bugs), 600), random_state=int(rng.integers(1 << 30))).itertuples():
            p = players[int(rng.integers(len(players)))]
            t = _ts(r.created, rng, 0, 24)
            post(f'{code}-bug-reports', g['name'], t, rng.choice([f'anyone else seeing this? {r.summary.lower()} is broken since the update',
                                                                  f'bug: {r.summary.lower()} - happens every time for me', f'{r.summary.lower()} not working pls fix']), player=p)
            post(f'{code}-bug-reports', g['name'], t + pd.Timedelta(hours=int(rng.integers(1, 30))),
                 rng.choice(['Thanks for the report! We can reproduce it and the team is on it.', 'Logged for the dev team - a fix is planned for the next patch.',
                             'Thanks! Could you DM us your player ID and device so we can look closer?']), staff=mods[int(rng.integers(len(mods)))])
        day = max(pd.Timestamp(g['launch']), pd.Timestamp(since))
        while day.date() <= END:
            for _ in range(int(rng.poisson(3))):
                post(f'{code}-general', g['name'], _ts(day, rng, 0, 24), rng.choice([
                    'gg everyone', 'what is the best build right now?', 'event rewards look great this week', 'lfg, anyone up for a match?',
                    'new player here, any tips?', 'the last update is so good', 'servers lagging for anyone else?', 'just finished the season pass!']),
                    player=players[int(rng.integers(len(players)))])
            day += pd.Timedelta(days=1)
    items = []
    for (ch, cat), ms in chans.items():
        ms.sort(key=lambda m: m['timestamp'])
        doc = {'guild': guild, 'channel': {'id': str(sid('discord', ch) % 10**18), 'type': 'GuildTextChat', 'categoryId': '',
                                          'category': cat, 'name': ch, 'topic': None},
               'dateRange': {'after': None, 'before': None}, 'exportedAt': datetime.now(timezone.utc).isoformat(), 'messages': ms,
               'messageCount': len(ms)}
        name = f'Little Games Community - {cat} - {ch}.json'
        out.put(f'{DISCORD}/{name}', json.dumps(doc).encode('utf-8'), 'application/json')
        items.append(name)
    _manifest(out, DISCORD, items, 'Community server export (DiscordChatExporter JSON layout)')
    log(f'  discord: {sum(len(v) for v in chans.values()):,} messages in {len(items)} channels')


# ---------------------------------------------------------------- Perforce
P4_PATHS = {'Gameplay': ['Source/{G}/Gameplay/{F}.cpp', 'Source/{G}/Gameplay/{F}.h', 'Content/Blueprints/BP_{F}.uasset'],
            'UI/UX': ['Content/UI/WBP_{F}.uasset', 'Source/{G}/UI/{F}Widget.cpp'], 'Backend': ['Source/{G}Online/{F}Service.cpp', 'Source/{G}Online/{F}Service.h'],
            'Art': ['Content/Art/{F}/SM_{F}.uasset', 'Content/Art/{F}/T_{F}_D.uasset', 'Content/Art/{F}/M_{F}.uasset'],
            'Audio': ['Content/Audio/{F}/SC_{F}.uasset', 'Content/Audio/{F}/{F}_01.wav'], 'Monetisation': ['Source/{G}/Store/{F}.cpp', 'Config/DefaultStore.ini'],
            'LiveOps': ['Content/Events/DA_{F}.uasset', 'Config/LiveOps/{F}.json'], 'Performance': ['Config/DefaultEngine.ini', 'Source/{G}/Core/{F}Profiler.cpp'],
            'Localization': ['Content/Localization/Game/en/Game.po', 'Content/Localization/Game/fr/Game.po']}


def perforce(out, emp, issues, logs, rng):
    who = emp.set_index('employee_id')
    items, cl = [], 100000
    rows_all = logs.merge(issues[['issue_key', 'project_key', 'component', 'summary', 'type']], on='issue_key')
    rows_all = rows_all[(rows_all.project_key.map(ENGINES) == 'Unreal') & (pd.to_datetime(rows_all.date) < pd.Timestamp(END))]
    rows_all = rows_all.sort_values(['date', 'issue_key'])
    revs, text, table = {}, {}, {}
    gname = {g['code']: ''.join(w for w in g['name'].title().split() if w.isalnum()) for g in GAMES}
    for r in rows_all.itertuples():  # one server: change numbers rise with time across every depot
        if rng.random() < .3 or r.employee_id not in who.index:
            continue
        key, G = r.project_key, gname[r.project_key]
        cl += int(rng.integers(1, 9))
        e = who.loc[r.employee_id]
        user = f'{e.first_name[0].lower()}{e.last_name.lower()}'
        feat = ''.join(w.capitalize() for w in r.summary.split()[1:])[:40] or 'Misc'
        paths = [f'//depot/{G}/Main/' + p.format(G=G, F=feat) for p in P4_PATHS.get(r.component, P4_PATHS['Gameplay'])]
        paths = paths[:int(rng.integers(1, len(paths) + 1))]
        when = _ts(r.date, rng)
        acts = []
        for p in paths:
            revs[p] = revs.get(p, 0) + 1
            acts.append((p, revs[p], 'add' if revs[p] == 1 else 'edit'))
        desc = f'{r.issue_key}: {r.summary}' + (' (fix)' if r.type == 'Bug' else '')
        text.setdefault(key, []).append(f'Change {cl} by {user}@{user}-{key.lower()}-ws on {when:%Y/%m/%d %H:%M:%S}\n\n\t{desc}\n\n'
                                        'Affected files ...\n\n' + '\n'.join(f'... {p}#{n} {a}' for p, n, a in acts) + '\n')
        table.setdefault(key, []).append({'change': cl, 'date': when, 'user': user, 'client': f'{user}-{key.lower()}-ws', 'status': 'submitted',
                                          'description': desc, 'issue_key': r.issue_key, 'files': len(acts),
                                          'paths': ' | '.join(p for p, _, _ in acts)})
    for key in sorted(table):
        out.put(f'{P4}/{key} - p4 describe.txt', '\n'.join(reversed(text[key])).encode('utf-8'), 'text/plain')  # p4 lists newest first
        out.put(f'{P4}/{key} - changelists.csv', pd.DataFrame(table[key]).to_csv(index=False).encode('utf-8'), 'text/csv')
        items += [f'{key} - p4 describe.txt', f'{key} - changelists.csv']
        log(f'  perforce {key}: {len(table[key]):,} changelists')
    _manifest(out, P4, items, 'Perforce changelist history (p4 describe -s format)')


# ---------------------------------------------------------------- engine project layouts
def _feature_names():
    return {comp: [''.join(w.capitalize() for w in f.split()) for f in feats] for comp, feats in pm.FEATURES.items()}


def engine_projects(out):
    feats = _feature_names()
    items = []
    for g in GAMES:
        eng = ENGINES[g['code']]
        G = ''.join(w for w in g['name'].title().split() if w.isalnum())
        f = {'README.md': f'# {g["name"]}\n\n{eng} {ENGINE_VERSION[eng]} project layout of {COMPANY} (fictional). {SYNTHETIC_NOTE}\n'}
        if eng == 'Unity':
            f['ProjectSettings/ProjectVersion.txt'] = f'm_EditorVersion: {ENGINE_VERSION[eng]}\n'
            f['ProjectSettings/ProjectSettings.asset'] = f'%YAML 1.1\n--- !u!129 &1\nPlayerSettings:\n  companyName: {COMPANY}\n  productName: {g["name"]}\n'
            f['Packages/manifest.json'] = {'dependencies': {'com.unity.inputsystem': '1.7.0', 'com.unity.addressables': '1.21.21',
                                                            'com.unity.purchasing': '4.12.2', 'com.unity.render-pipelines.universal': '14.0.11'}}
            f['.gitignore'] = '/[Ll]ibrary/\n/[Tt]emp/\n/[Oo]bj/\n/[Bb]uild/\n/[Ll]ogs/\n/[Uu]ser[Ss]ettings/\n*.csproj\n*.sln\n'
            f['Assets/Scenes/Main.unity'] = '%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n'
            for comp, names_ in feats.items():
                for n in names_[:3]:
                    f[f'Assets/Scripts/{comp.replace("/", "")}/{n}.cs'] = (
                        f'using UnityEngine;\n\nnamespace LittleGames.{G}.{comp.replace("/", "")}\n{{\n    /// <summary>{n} ({g["name"]}).</summary>\n'
                        f'    public class {n} : MonoBehaviour\n    {{\n        void Start() {{ }}\n\n        void Update() {{ }}\n    }}\n}}\n')
        elif eng == 'Unreal':
            f[f'{G}.uproject'] = {'FileVersion': 3, 'EngineAssociation': ENGINE_VERSION[eng], 'Category': '', 'Description': g['name'],
                                  'Modules': [{'Name': G, 'Type': 'Runtime', 'LoadingPhase': 'Default'},
                                              {'Name': f'{G}Online', 'Type': 'Runtime', 'LoadingPhase': 'Default'}],
                                  'Plugins': [{'Name': 'EnhancedInput', 'Enabled': True}, {'Name': 'OnlineSubsystemSteam', 'Enabled': True}]}
            f['Config/DefaultEngine.ini'] = f'[/Script/EngineSettings.GameMapsSettings]\nGameDefaultMap=/Game/Maps/MainMenu\n\n[/Script/Engine.RendererSettings]\nr.DefaultFeature.AntiAliasing=4\n'
            f['Config/DefaultGame.ini'] = f'[/Script/EngineSettings.GeneralProjectSettings]\nProjectName={g["name"]}\nCompanyName={COMPANY}\n'
            f['.p4ignore'] = 'Binaries/\nDerivedDataCache/\nIntermediate/\nSaved/\n*.sln\n.vs/\n'
            f[f'Source/{G}.Target.cs'] = f'using UnrealBuildTool;\n\npublic class {G}Target : TargetRules\n{{\n    public {G}Target(TargetInfo Target) : base(Target)\n    {{\n        Type = TargetType.Game;\n        ExtraModuleNames.Add("{G}");\n    }}\n}}\n'
            f[f'Source/{G}/{G}.Build.cs'] = f'using UnrealBuildTool;\n\npublic class {G} : ModuleRules\n{{\n    public {G}(ReadOnlyTargetRules Target) : base(Target)\n    {{\n        PublicDependencyModuleNames.AddRange(new[] {{ "Core", "CoreUObject", "Engine", "InputCore", "EnhancedInput" }});\n    }}\n}}\n'
            for comp, names_ in feats.items():
                for n in names_[:3]:
                    f[f'Source/{G}/{comp.replace("/", "")}/{n}.h'] = (f'#pragma once\n\n#include "CoreMinimal.h"\n#include "GameFramework/Actor.h"\n#include "{n}.generated.h"\n\n'
                                                                    f'UCLASS()\nclass {G.upper()}_API A{n} : public AActor\n{{\n    GENERATED_BODY()\npublic:\n    A{n}();\n}};\n')
                    f[f'Source/{G}/{comp.replace("/", "")}/{n}.cpp'] = f'#include "{n}.h"\n\nA{n}::A{n}()\n{{\n    PrimaryActorTick.bCanEverTick = true;\n}}\n'
        else:
            f['project.godot'] = (f'config_version=5\n\n[application]\n\nconfig/name="{g["name"]}"\nrun/main_scene="res://scenes/main.tscn"\n'
                                  f'config/features=PackedStringArray("{ENGINE_VERSION[eng]}", "Forward Plus")\n')
            f['scenes/main.tscn'] = '[gd_scene format=3]\n\n[node name="Main" type="Node2D"]\n'
            f['export_presets.cfg'] = '[preset.0]\n\nname="Windows Desktop"\nplatform="Windows Desktop"\n'
            for comp, names_ in feats.items():
                for n in names_[:3]:
                    f[f'scripts/{comp.replace("/", "_").lower()}/{n.lower()}.gd'] = f'extends Node\nclass_name {n}\n\n## {n} ({g["name"]}).\n\nfunc _ready() -> void:\n\tpass\n'
        name = f'{g["code"]} - {g["name"]} ({eng} project layout).zip'
        out.put(f'{ENGINE}/{name}', _zip(f), 'application/zip')
        items.append(name)
    _manifest(out, ENGINE, items, 'Engine project layouts with script stubs')
    log(f'  engine projects: {len(items)}')


# ---------------------------------------------------------------- playtests and analytics
def playtests(out, versions, rng, dry):
    sess, ev, surv = [], [], []
    for g in GAMES:
        for v in versions[(versions.project_key == g['code']) & versions.kind.eq('Milestone')].itertuples():
            if v.version == '1.0 Launch' or pd.Timestamp(v.release_date).date() > END:
                continue
            testers = int(rng.integers(30, 60 if dry else 400))
            build = f'{v.version.split()[0].lower()}-{pd.Timestamp(v.release_date):%Y%m%d}.{int(rng.integers(100, 999))}'
            quality = {'Prototype': .4, 'Vertical': .55, 'Alpha': .65, 'Beta': .8}.get(v.version.split()[0], .7)
            for t in range(testers):
                tid = f'PT-{g["code"]}-{t + 1:05d}'
                for s in range(int(rng.integers(1, 5))):
                    start = pd.Timestamp(v.release_date) - pd.Timedelta(days=int(rng.integers(1, 14))) + pd.Timedelta(seconds=int(rng.integers(36000, 79200)))
                    dur = float(np.round(rng.gamma(2.2, 18), 1))
                    crash = rng.random() > quality + .25
                    sid = f'{tid}-S{s + 1}'
                    sess.append({'session_id': sid, 'tester_id': tid, 'game': g['code'], 'build': build, 'milestone': v.version,
                                 'platform': rng.choice(list(g['platforms'])), 'started_at': start, 'duration_min': dur,
                                 'level_reached': int(1 + rng.poisson(dur / 9)), 'deaths': int(rng.poisson(dur / (6 + 10 * quality))),
                                 'crashed': crash, 'avg_fps': float(np.round(rng.normal(30 + 35 * quality, 6), 1)),
                                 'input_device': rng.choice(['Keyboard & mouse', 'Controller', 'Touch'] if 'iOS' in g['platforms'] else ['Keyboard & mouse', 'Controller'])})
                    tt = 0.0
                    for _ in range(int(min(60, 4 + dur / 2))):
                        tt += float(rng.exponential(dur * 60 / max(1, 4 + dur / 2)))
                        ev.append({'session_id': sid, 'ts': start + pd.Timedelta(seconds=tt), 'event': rng.choice(
                            ['level_start', 'checkpoint', 'death', 'menu_open', 'item_pickup', 'objective_complete'], p=[.15, .25, .2, .1, .2, .1]),
                                   'level': int(1 + tt / 540), 'x': float(np.round(rng.uniform(-500, 500), 1)), 'y': float(np.round(rng.uniform(-500, 500), 1)),
                                   'z': float(np.round(rng.uniform(0, 60), 1))})
                    if crash:
                        ev.append({'session_id': sid, 'ts': start + pd.Timedelta(minutes=dur), 'event': 'crash', 'level': int(1 + tt / 540),
                                   'x': None, 'y': None, 'z': None})
                fun = int(np.clip(round(rng.normal(2.2 + 3 * quality, .8)), 1, 5))
                surv.append({'tester_id': tid, 'game': g['code'], 'build': build, 'milestone': v.version, 'fun_1_5': fun,
                             'difficulty_1_5': int(np.clip(round(rng.normal(3, .9)), 1, 5)), 'clarity_1_5': int(np.clip(round(rng.normal(2 + 2.5 * quality, .9)), 1, 5)),
                             'would_recommend_0_10': int(np.clip(round(rng.normal(3 + 6 * quality, 1.8)), 0, 10)),
                             'comment': rng.choice(['Controls felt great once I got used to them.', 'The tutorial was too long.', 'Loved the art style.',
                                                    'I got lost in the second area.', 'Performance dropped in big fights.', 'Want more variety in enemies.',
                                                    'Menus were confusing.', 'Would play again!'])})
    frames = {'playtest_sessions': pd.DataFrame(sess), 'playtest_events': pd.DataFrame(ev), 'playtest_surveys': pd.DataFrame(surv)}
    for k, df in frames.items():
        out.put(f'{PLAY}/{k}.csv', df.to_csv(index=False).encode('utf-8'), 'text/csv')
    log(f'  playtests: {len(sess):,} sessions, {len(ev):,} events, {len(surv):,} surveys')
    return [f'{k}.csv' for k in frames]


EVENTS = ['session_start', 'tutorial_step', 'level_start', 'level_complete', 'level_fail', 'store_open', 'purchase', 'ad_impression',
          'social_share', 'push_open', 'session_end']


def analytics(out, rng, dry):
    end = pd.Timestamp(END)
    rows = []
    n_players = 100 if dry else 1500
    for g in GAMES:
        if g['launch'] > END or g['accounts'] == 0:
            continue
        for i in range(n_players):
            pid = f'A-{g["code"]}-{i + 1:06d}'
            plat = rng.choice(list(g['platforms']), p=np.array(list(g['platforms'].values())) / sum(g['platforms'].values()))
            active_days = sorted(set(rng.integers(0, 60, int(rng.integers(1, 40)))))
            payer = rng.random() < g['payer'] * 3
            for d in active_days:
                t = end - pd.Timedelta(days=int(60 - d)) + pd.Timedelta(seconds=int(rng.integers(0, 86400)))
                sid = f'{pid}-{d}'
                rows.append((t, pid, sid, g['code'], plat, 'session_start', ''))
                for _ in range(int(rng.integers(2, 9))):
                    t += pd.Timedelta(seconds=int(rng.exponential(120)))
                    e = rng.choice(EVENTS[1:-1], p=[.05, .3, .25, .12, .1, .02 if payer else .0, .1, .03, .03 + (.0 if payer else .02)])
                    props = {'level_start': {'level': int(rng.integers(1, 200))}, 'level_complete': {'stars': int(rng.integers(1, 4))},
                             'purchase': {'sku': f'{g["code"]}-{rng.choice(["GEMS_S", "GEMS_M", "BUNDLE", "PASS"])}',
                                          'price_usd': float(rng.choice([0.99, 4.99, 9.99, 19.99]))},
                             'ad_impression': {'placement': rng.choice(['rewarded', 'interstitial'])}}.get(e, {})
                    rows.append((t, pid, sid, g['code'], plat, e, json.dumps(props) if props else ''))
                rows.append((t + pd.Timedelta(seconds=int(rng.exponential(200))), pid, sid, g['code'], plat, 'session_end', ''))
    df = pd.DataFrame(rows, columns=['event_time', 'player_id', 'session_id', 'game', 'platform', 'event', 'properties'])
    name = 'player_analytics_events_last_60_days_sample.csv'
    out.put(f'{PLAY}/{name}', df.to_csv(index=False).encode('utf-8'), 'text/csv')
    log(f'  analytics: {len(df):,} events from {df.player_id.nunique():,} sampled players')
    return [name]


def build(out, dry=False):
    rng = np.random.default_rng(SEED + 7070)
    emp = finance.staff(np.random.default_rng(SEED + 99))
    projects, versions, sprints, issues, logs = pm.build(emp, END)
    since = (pd.Timestamp(END) - pd.Timedelta(days=120)).date() if dry else pd.Timestamp('2015-01-01').date()
    if dry:
        keep = issues.project_key.isin(['ND', 'PP'])
        issues, sprints = issues[keep], sprints[sprints.project_key.isin(['ND', 'PP'])]
        logs = logs[logs.issue_key.isin(issues.issue_key)]
    jira(out, emp, projects, versions, sprints, issues)
    slack(out, emp, projects, versions, sprints, issues, rng, since)
    discord(out, emp, versions, issues, rng, since)
    perforce(out, emp, issues, logs, rng)
    engine_projects(out)
    items = playtests(out, versions, rng, dry) + analytics(out, rng, dry)
    _manifest(out, PLAY, items, 'Playtest telemetry and sampled player analytics events')
    out.put(f'{PLAY}/README.txt', (f'{SYNTHETIC_NOTE}\nPlayer support tickets are in "{COMPANY}/3 Customer Support"; '
                                   f'daily KPIs and cohorts are in "{COMPANY}/5 Data Warehouse".\n').encode('utf-8'), 'text/plain')
