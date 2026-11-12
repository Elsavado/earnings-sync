"""Brave Search source for the shintiru office collector (user, 2026-11-12: "search the internet at large", option 3
approved). Topic phrases x file types ("statement of work" filetype:docx ...) through the Brave Search API; result
addresses that are Office files go to OUT_DIR/<type>/brave-*.tsv for the collector jobs.

Cost guard: at most BRAVE_MONTHLY_CAP searches a calendar month (repository variable; default 900, inside Brave's
monthly $5 credit). Usage and the position in the phrase list are kept in CURSORS_DIR/brave.json on the drive.
Does nothing when the secret BRAVE_API_KEY is not set.

  python -m fdocs.brave CURSORS_DIR OUT_DIR
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

from . import ccweb

API = 'https://api.search.brave.com/res/v1/web/search'
END = time.time() + float(os.environ.get('RUN_MINUTES', '45')) * 60
PAGES = 10  # Brave pages of 20 results (offset 0-9)

# finance, learning, operations and software / operational-tools delivery (the shintiru topics)
PHRASES = {
    'gdocs': [
        'statement of work', 'scope of work', 'project proposal', 'software requirements specification',
        'functional specification', 'technical design document', 'solution architecture', 'API documentation',
        'test plan', 'user acceptance testing', 'release notes', 'runbook', 'disaster recovery plan',
        'project status report', 'project charter', 'service level agreement', 'change request form',
        'data migration plan', 'go-live checklist', 'standard operating procedure', 'operations manual',
        'inventory management procedure', 'procurement policy', 'budget proposal', 'financial policy',
        'internal audit report', 'business case', 'course syllabus', 'lecture notes', 'lesson plan',
        'study guide', 'case study', 'training manual', 'onboarding guide', 'incident report template',
        'meeting minutes', 'quality management plan', 'risk register', 'cost benefit analysis',
        'vendor evaluation', 'request for proposal software', 'IT strategy', 'SaaS implementation plan',
    ],
    'gsheets': [
        'project budget', 'timesheet', 'resource plan', 'sprint backlog', 'bug tracker', 'issue log',
        'test cases', 'requirements traceability matrix', 'KPI dashboard', 'uptime report', 'risk register',
        'inventory tracker', 'staff roster', 'shift schedule', 'capacity plan', 'project schedule',
        'cash flow forecast', 'financial model', 'budget template', 'expense report', 'invoice tracker',
        'accounts receivable aging', 'balance sheet', 'income statement', 'payroll register', 'cost estimate',
        'gradebook', 'course schedule', 'attendance register', 'maintenance log', 'asset register',
        'purchase order log', 'vendor list', 'sales pipeline', 'OKR tracker', 'release plan', 'RACI matrix',
        'stakeholder register', 'billable hours', 'SLA report', 'OEE calculation', 'downtime log',
    ],
    'slides': [
        'case study', 'project kickoff', 'architecture review', 'product roadmap', 'quarterly business review',
        'board presentation', 'investor presentation', 'sprint review', 'lessons learned', 'project status update',
        'digital transformation', 'cloud migration', 'DevOps', 'agile training', 'data analytics',
        'operations dashboard', 'supply chain management', 'lean manufacturing', 'predictive maintenance',
        'financial statements analysis', 'budgeting', 'corporate finance', 'managerial accounting', 'audit',
        'lecture', 'course introduction', 'training', 'onboarding', 'strategy', 'business plan',
        'service overview', 'system integration', 'API integration', 'customer success', 'process improvement',
        'risk management', 'project management', 'change management', 'IT governance', 'cybersecurity awareness',
    ],
}
EXTS = {'gdocs': ['docx', 'doc'], 'gsheets': ['xlsx'], 'slides': ['pptx', 'ppt']}


def log(msg):
    print(time.strftime('[%H:%M:%S] ') + msg, flush=True)


def queries():
    """(query, kind, page) in order: every phrase's first page first, then the deeper pages."""
    base = [(f'"{p}" filetype:{e}', k) for k in PHRASES for p in PHRASES[k] for e in EXTS[k]]
    return [(q, k, page) for page in range(PAGES) for q, k in base]


def main(cursors, out):
    key = os.environ.get('BRAVE_API_KEY', '').strip()
    if not key:
        log('Brave search: off (no BRAVE_API_KEY secret)')
        return
    cap = int(os.environ.get('BRAVE_MONTHLY_CAP') or 900)
    cfile = Path(cursors) / 'brave.json'
    cfile.parent.mkdir(parents=True, exist_ok=True)
    cur = json.loads(cfile.read_text()) if cfile.exists() else {}
    month = time.strftime('%Y-%m')
    used = cur.get('used', {}).get(month, 0)
    qs = queries()
    i = cur.get('next', 0) % len(qs)
    out = Path(out)
    stamp = f'brave-0-{int(time.time())}.tsv'
    fh = {}
    for k in EXTS:
        (out / k).mkdir(parents=True, exist_ok=True)
        fh[k] = (out / k / stamp).open('w', encoding='utf-8')
    s = requests.Session()
    s.headers.update({'X-Subscription-Token': key, 'Accept': 'application/json'})
    found = calls = empty_pages = 0
    while used < cap and time.time() < END:
        q, kind, page = qs[i]
        try:
            r = s.get(API, params={'q': q, 'count': 20, 'offset': page, 'country': 'ALL', 'search_lang': 'en'},
                      timeout=30)
        except requests.RequestException:
            time.sleep(5)
            continue
        if r.status_code == 429:
            time.sleep(5)
            continue
        used += 1
        calls += 1
        if r.status_code != 200:
            log(f'  Brave: HTTP {r.status_code}; stopping this run')
            break
        res = (r.json().get('web') or {}).get('results') or []
        empty_pages += not res
        for item in res:
            url = item.get('url', '')
            hit = ccweb.EXT_KIND.get(os.path.splitext(url.split('?')[0].lower())[1])
            if hit:
                eng, open_host = ccweb.english_host(url.split('/')[2] if '//' in url else '')
                if eng or open_host:
                    fh[hit].write(f'{hit}\t{url}\t{os.path.splitext(url.split("?")[0].lower())[1][1:]}\n')
                    found += 1
        i = (i + 1) % len(qs)
        time.sleep(1.1)  # 1 search a second on the base plan
    for k, f in fh.items():
        f.close()
        if (out / k / stamp).stat().st_size == 0:
            (out / k / stamp).unlink()
    cur['next'] = i
    cur.setdefault('used', {})[month] = used
    cfile.write_text(json.dumps(cur))
    log(f'Brave search: {calls} searches this run, {used}/{cap} this month, {found} Office files found')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write(f'- Brave search: {calls} searches, {used}/{cap} this month, {found} files found\n')


if __name__ == '__main__':
    main(*sys.argv[1:3])
