"""Game-development material from openly licensed public sources, filed under "8 Game Development":

  code      open-source game and engine repositories (Godot, Unity, Unreal, engines) with their full commit history,
            stored as git bundles (`git clone <bundle>` restores every branch and tag) next to the licence text
  gdd       game design documents published in openly licensed repositories
  inputs    research datasets that pair gameplay video / frames with keyboard, mouse, controller or gaze input
  videos    gameplay videos and trailers from Wikimedia Commons (free licences, reviewed by Commons)
  telemetry player analytics, playtest telemetry, match data and support-ticket datasets
  assets    CC0 3D models, textures and materials (Poly Haven, ambientCG)

Every folder has a manifest.csv with each item's source, licence and collection date. Licence files and authorship
stay with the material (the licences require it). Content is unique: repositories sharing a root commit, files with a
checksum already collected and older versions of the same record are skipped. Logs carry counts only (public repo)."""
import base64
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

import requests

from . import pseudo
from .out import log

DEVF = '8 Game Development'
CODE, GDD, INPUTS, VIDEOS, TELEM, ASSETS = (f'{DEVF}/Game & Engine Code', f'{DEVF}/Design Documents',
                                           f'{DEVF}/Gameplay Recordings & Input Logs', f'{DEVF}/Gameplay Videos & Trailers',
                                           f'{DEVF}/Player Analytics & Telemetry', f'{DEVF}/3D Assets & Materials')
UA = 'GameDevPlanningCollector/1.1 (personal research; https://github.com/Elsavado/earnings-sync) python-requests'
S = requests.Session()
S.headers['User-Agent'] = UA
OSI = {'MIT', 'Apache-2.0', 'GPL-2.0', 'GPL-3.0', 'LGPL-2.1', 'LGPL-3.0', 'AGPL-3.0', 'BSD-2-Clause', 'BSD-3-Clause', 'MPL-2.0',
       'Zlib', 'ISC', 'Unlicense', 'BSL-1.0', 'EPL-2.0', 'CC0-1.0', 'CC-BY-4.0', 'CC-BY-SA-4.0', '0BSD', 'MIT-0', 'OFL-1.1'}
OPEN_DATA = re.compile(r'^(?:cc-by|cc0|cc-zero|mit|apache|bsd|gpl|lgpl|agpl|mpl|isc|unlicense|odc|pddl|cdla|openrail|other-open)', re.I)
T0 = time.time()


def today():
    return time.strftime('%Y-%m-%d', time.gmtime())


def late(margin=10):
    return time.time() - T0 > (float(os.environ.get('RUN_MINUTES', '300')) - margin) * 60


def get(url, params=None, gap=1.0, tries=5, **kw):
    for i in range(tries):
        time.sleep(gap)
        try:
            r = S.get(url, params=params, timeout=90, **kw)
        except requests.RequestException:
            time.sleep(10 * (i + 1))
            continue
        if r.status_code in (403, 429) and 'rate limit' in r.text.lower() or r.status_code == 429:
            reset = int(r.headers.get('X-RateLimit-Reset', time.time() + 60))
            time.sleep(min(900, max(5, reset - time.time() + 2)))
            continue
        if r.status_code >= 500:
            time.sleep(15 * (i + 1))
            continue
        return r
    return None


def js(r):
    try:
        return r.json() if r is not None and r.ok else None
    except ValueError:
        return None


def gh(url, params=None, gap=2.2):
    tok = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    h = {'Accept': 'application/vnd.github+json', **({'Authorization': f'Bearer {tok}'} if tok else {})}
    return js(get(url if url.startswith('http') else 'https://api.github.com' + url, params, gap=gap, headers=h))


def download(url, dest, limit, headers=None, gap=0.0):
    """Streams url to dest; None if it fails or exceeds limit bytes. Waits out 429/503 (Retry-After) and retries."""
    for i in range(5):
        time.sleep(gap)
        try:
            with S.get(url, stream=True, timeout=120, headers=headers or {}) as r:
                if r.status_code in (429, 503) or r.status_code >= 500:
                    try:
                        wait = float(r.headers.get('Retry-After', 0))
                    except ValueError:
                        wait = 0
                    time.sleep(min(600, max(wait, 30 * (i + 1))))
                    continue
                if not r.ok:
                    return None
                n = 0
                with open(dest, 'wb') as f:
                    for chunk in r.iter_content(4 * 2**20):
                        n += len(chunk)
                        if n > limit:
                            return None
                        f.write(chunk)
                return n
        except requests.RequestException:
            time.sleep(15 * (i + 1))
    return None


def safe(name, n=150):
    # Drive search queries quote names with ', so names use the typographic apostrophe
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', ' ', str(name)).replace("'", '’').strip(' .')
    name = re.sub(r'\s{2,}', ' ', name)
    return name[:n].rstrip(' .') or 'item'


class Budget:
    def __init__(self, dry, gb, items, dry_items=3):
        self.left = (0.15 if dry else gb) * 2**30
        self.items = dry_items if dry else items

    def take(self, size):
        if late() or self.items <= 0 or size > self.left:
            return False
        self.left -= size
        self.items -= 1
        return True

    def done(self):
        return late() or self.items <= 0 or self.left <= 0


KIND_FOLDERS = {'code': (CODE, True), 'gdd': (GDD, False), 'inputs': (INPUTS, True), 'telemetry': (TELEM, True),
                'videos': (VIDEOS, None), 'assets': (ASSETS, True)}  # None: the folder itself and its sub-folders
ROOTS_NOTE = re.compile(r'original root commit ([0-9a-f,]+)')


def norm(s):
    """Comparable form of a URL or item name (apostrophe style, spacing and case do not matter)."""
    return re.sub(r'\s+', ' ', str(s).replace('’', "'")).strip().lower()


def kind_folders(out, kind):
    base, subs = KIND_FOLDERS.get(kind, (None, False))
    if not base:
        return []
    return ([base] if subs is not True else []) + ([f'{base}/{x}' for x in out.children(base)] if subs is not False else [])


class Ctx:
    """State for one kind (its own state file, so parallel jobs never overwrite each other): seen ids and checksums,
    plus every item already listed in the kind's manifests on Drive (the durable record), counts and pending rows."""

    def __init__(self, out, kind):
        self.out, self.kind = out, kind
        st = out.state(f'devdata-{kind}')
        if st is None:  # first run with per-kind state: start from the shared file of earlier runs
            st = (out.state('devdata') or {}).get(kind) or {}
        self.st = st
        for k in ('seen', 'sums', 'roots'):
            self.st.setdefault(k, [])
        self.st.setdefault('cursor', {})
        self.seen, self.sums, self.roots = set(self.st['seen']), set(self.st['sums']), set(self.st['roots'])
        self.urls, self.items = set(), set()
        for folder in kind_folders(out, kind):
            for r in out.read_csv(f'{folder}/manifest.csv'):
                self.urls.add(norm(r.get('source_url', '')))
                self.items.add(norm(r.get('source_url', '')) + '|' + norm(r.get('item', '')))
                m = ROOTS_NOTE.search(r.get('notes', ''))
                if m:
                    self.roots.update(m.group(1).split(','))
        self.rows = {}
        self.n = {'added': 0, 'skipped': 0, 'failed': 0}
        self.last_save = time.time()

    def have(self, url, item=None):
        """True when the source (or this item of it) is already in a manifest."""
        return (norm(url) + '|' + norm(item)) in self.items if item is not None else norm(url) in self.urls

    def add(self, folder, row, ident=None, checksum=None, roots=()):
        row.setdefault('collected_date', today())
        row.setdefault('synthetic', 'no')
        self.rows.setdefault(folder, []).append(row)
        self.urls.add(norm(row.get('source_url', '')))
        self.items.add(norm(row.get('source_url', '')) + '|' + norm(row.get('item', '')))
        if ident:
            self.seen.add(ident)
        if checksum:
            self.sums.add(checksum)
        self.roots.update(roots)
        self.n['added'] += 1
        if time.time() - self.last_save > 600:
            self.save()

    def upload(self, path, data=None, local=None, mime='application/octet-stream'):
        """One upload; a failure is counted and skipped instead of stopping the kind."""
        try:
            if local is not None:
                self.out.put_file(path, local, mime)
            else:
                self.out.put(path, data, mime)
            return True
        except Exception:  # noqa: BLE001
            self.n['failed'] += 1
            return False

    def save(self):
        for folder, rows in self.rows.items():
            self.out.manifest(folder, rows)
        self.rows = {}
        self.st['seen'], self.st['sums'], self.st['roots'] = sorted(self.seen), sorted(self.sums), sorted(self.roots)
        if not self.out.dry:
            self.out.save_state(f'devdata-{self.kind}', self.st)
        self.last_save = time.time()

    def finish(self):
        self.save()
        log(f'  {self.kind}: ' + ', '.join(f'{k} {v}' for k, v in self.n.items()))
        if self.n['added'] == 0 and self.n['failed'] > 0:
            raise RuntimeError(f'{self.kind}: nothing collected, {self.n["failed"]} failures')


# ---------------------------------------------------------------- code with history
CODE_Q = [('Godot', 'topic:godot-game'), ('Godot', 'topic:godot4'), ('Godot', 'topic:godot language:GDScript'),
          ('Unity', 'topic:unity-game'), ('Unity', 'topic:unity3d-games'), ('Unity', 'topic:unity2d'),
          ('Unreal', 'topic:unreal-engine-game'), ('Unreal', 'topic:unreal-engine-5'), ('Unreal', 'topic:ue5'),
          ('Game Engines', 'topic:game-engine'), ('Game Engines', 'topic:game-engine language:C++'),
          ('Game Engines', 'topic:game-engine language:Rust'), ('Open-source Games', 'topic:open-source-game'),
          ('Open-source Games', 'topic:game language:C++'), ('Open-source Games', 'topic:game language:C#')]


def rmtree(path):
    """Removes a directory even when git left read-only pack files in it (Windows)."""
    import stat

    def unlock(fn, p, _):
        os.chmod(p, stat.S_IWRITE)
        fn(p)
    if Path(path).exists():
        shutil.rmtree(path, onerror=unlock)


def git(*a, cwd=None, timeout=1800):
    return subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_LFS_SKIP_SMUDGE': '1'})


PSEUDO_MARK = 'people as Contributor NNN'


def pseudo_bundle(work, bundle):
    """Pseudonymises the people in the clone's whole history (pseudo.py) and bundles every branch and tag."""
    names = pseudo.rewrite_repo(work)
    if git('bundle', 'create', str(bundle), '--all', cwd=work).returncode:
        raise RuntimeError('bundle')
    commits = git('rev-list', '--count', '--all', cwd=work).stdout.strip()
    lfs = 'filter=lfs' in git('show', 'HEAD:.gitattributes', cwd=work).stdout
    return names, commits, lfs


def repo_title(full_name, owner_type, names):
    """owner/repo with a personal owner account shown as its Contributor number (organisations keep their name)."""
    owner, _, repo = full_name.partition('/')
    if owner_type == 'Organization':
        return full_name
    return f'{names.get(owner)}/{repo}'


def code_notes(name, commits, size, lfs, roots, names):
    return (f'git bundle of every branch and tag; {commits} commits; {size / 2**20:.1f} MB; licence text in {name}.LICENSE.txt '
            f'(unchanged); {len(names.order)} {PSEUDO_MARK} in history, credits and headers (licence files untouched); '
            f'original root commit {",".join(sorted(roots)[:5])}' + (f' (+{len(roots) - 5} more)' if len(roots) > 5 else '') +('; large binary files are Git LFS pointers' if lfs else ''))


def code(out, dry):
    c = Ctx(out, 'code')
    bud = Budget(dry, 10, 60, 2)
    max_kb = 20_000 if dry else 600_000
    tmp = Path(tempfile.mkdtemp())
    for engine, q in CODE_Q:
        cur = c.st['cursor'].setdefault(q, 1)
        while cur <= 10 and not bud.done():
            res = gh('/search/repositories', {'q': f'{q} fork:false archived:false size:50..{max_kb}', 'sort': 'stars',
                                               'order': 'desc', 'per_page': 30, 'page': cur})
            items = (res or {}).get('items') or []
            for it in items:
                if bud.done():
                    break
                ident = f'gh:{it["id"]}'
                spdx = ((it.get('license') or {}).get('spdx_id') or '')
                if ident in c.seen or c.have(it['html_url']) or it.get('is_template') or spdx not in OSI:
                    c.n['skipped'] += 1
                    continue
                name = f'{it["owner"]["login"]}__{it["name"]}'
                work = tmp / f'{it["id"]}.git'
                try:
                    if git('clone', '--mirror', '--quiet', it['clone_url'], str(work)).returncode:
                        raise RuntimeError('clone')
                    roots = set(git('rev-list', '--max-parents=0', '--all', cwd=work).stdout.split())
                    if not roots or roots & c.roots:  # same project already collected (copy or re-upload)
                        c.seen.add(ident)
                        c.n['skipped'] += 1
                        continue
                    bundle = tmp / f'{name}.bundle'
                    names, commits, lfs = pseudo_bundle(work, bundle)
                    size = bundle.stat().st_size
                    if not bud.take(size):
                        bundle.unlink()
                        if bud.done():
                            break
                        continue
                    lic = gh(f'/repos/{it["full_name"]}/license') or {}
                    folder = f'{CODE}/{engine}'
                    out.put_file(f'{folder}/{name}.bundle', bundle, 'application/octet-stream')
                    if lic.get('content'):
                        out.put(f'{folder}/{name}.LICENSE.txt', base64.b64decode(lic['content']), 'text/plain')
                    c.add(folder, {'item': f'{name}.bundle', 'title': repo_title(it['full_name'], it['owner'].get('type'), names),
                                   'source_url': it['html_url'], 'licence': spdx,
                                   'notes': code_notes(name, commits, size, lfs, roots, names)}, ident, roots=roots)
                    bundle.unlink()
                except Exception:  # noqa: BLE001 - one repository never stops the run
                    c.n['failed'] += 1
                finally:
                    rmtree(work)
            if len(items) < 30:
                cur = 99
                break
            cur += 1
            c.st['cursor'][q] = cur
        c.st['cursor'][q] = cur
        if bud.done():
            break
    rmtree(tmp)
    c.finish()


# ---------------------------------------------------------------- design documents
GDD_Q = ['topic:game-design-document', 'topic:gdd', '"game design document" in:description,readme', '"GDD" game in:description']
GDD_FILE = re.compile(r'(?i)(?:^|/)[^/]*(?:\bgdd\b|game[-_ ]?design[-_ ]?doc|design[-_ ]?document)[^/]*\.(?:md|pdf|docx|txt)$')


def pseudo_doc(data, ext, names):
    """Bytes of a design document with its people as Contributor numbers (pseudo.document)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f'doc{ext.lower()}'
        p.write_bytes(data)
        try:
            pseudo.document(p, ext, names, handles=True)
        except Exception:  # noqa: BLE001 - an unreadable document is kept out rather than uploaded with names
            raise RuntimeError('document could not be pseudonymised')
        return p.read_bytes()


def gdd(out, dry):
    c = Ctx(out, 'gdd')
    bud = Budget(dry, 2, 300, 3)
    for q in GDD_Q:
        cur = c.st['cursor'].setdefault(q, 1)
        while cur <= 10 and not bud.done():
            items = ((gh('/search/repositories', {'q': f'{q} fork:false', 'sort': 'stars', 'per_page': 30, 'page': cur}) or {})
                     .get('items') or [])
            for it in items:
                if bud.done():
                    break
                spdx = ((it.get('license') or {}).get('spdx_id') or '')
                if f'gh:{it["id"]}' in c.seen or spdx not in OSI:
                    c.n['skipped'] += 1
                    continue
                tree = (gh(f'/repos/{it["full_name"]}/git/trees/{it["default_branch"]}', {'recursive': 1}) or {}).get('tree') or []
                docs = [t for t in tree if t.get('type') == 'blob' and GDD_FILE.search(t['path']) and 0 < t.get('size', 0) <= 20 * 2**20]
                got = 0
                names = pseudo.Names()  # one numbering per repository
                if it['owner'].get('type') != 'Organization':
                    names.get(it['owner']['login'])
                for t in docs[:5]:
                    if t['sha'] in c.sums or c.have(f'{it["html_url"]}/blob/{it["default_branch"]}/{t["path"]}') or not bud.take(t['size']):
                        continue
                    raw = get(f'https://raw.githubusercontent.com/{it["full_name"]}/{it["default_branch"]}/{t["path"]}', gap=0.3)
                    if raw is None or not raw.ok:
                        c.n['failed'] += 1
                        continue
                    name = safe(f'{it["owner"]["login"]}__{it["name"]}__{Path(t["path"]).name}')
                    try:
                        data = pseudo_doc(raw.content, Path(t['path']).suffix, names)
                    except RuntimeError:
                        c.n['failed'] += 1
                        continue
                    if not c.upload(f'{GDD}/{name}', data):
                        continue
                    c.add(GDD, {'item': name, 'title': f'{repo_title(it["full_name"], it["owner"].get("type"), names)}: {t["path"]}',
                                'source_url': f'{it["html_url"]}/blob/{it["default_branch"]}/{t["path"]}', 'licence': spdx,
                                'notes': f'{t["size"]:,} bytes; {PSEUDO_MARK}'}, checksum=t['sha'])
                    got += 1
                if got:
                    lic = gh(f'/repos/{it["full_name"]}/license') or {}
                    if lic.get('content'):
                        c.upload(f'{GDD}/{safe(it["owner"]["login"] + "__" + it["name"])}.LICENSE.txt', base64.b64decode(lic['content']),
                                 mime='text/plain')
                c.seen.add(f'gh:{it["id"]}')
            if len(items) < 30:
                cur = 99
                break
            cur += 1
        c.st['cursor'][q] = cur
    c.finish()


# ---------------------------------------------------------------- open datasets (Zenodo + Hugging Face)
def zenodo_records(q, page):
    r = js(get('https://zenodo.org/api/records', {'q': q, 'type': 'dataset', 'size': 25, 'page': page, 'sort': 'bestmatch'}, gap=2.5))
    return (r or {}).get('hits', {}).get('hits')


def hf_title(dataset_id):
    """owner/name with the uploading account as Contributor 001 (the source URL keeps the real id)."""
    owner, _, rest = dataset_id.partition('/')
    return f'Contributor 001/{rest}' if rest else dataset_id


def video_title(raw):
    """First descriptive line of a Commons description (no links or promotion lines)."""
    raw = re.sub(r'<[^>]+>', ' ', raw or '')
    return next((re.sub(r'\s+', ' ', ln).strip() for ln in raw.splitlines() if len(ln.strip()) > 3 and
                 not re.search(r'(?i)https?:|www\.|\.ly/|\.gg/|➡|subscribe|follow us|download', ln)), '')


def video_notes(size, artist):
    who = f'Contributor 001 (credit line on the source page)' if artist else 'see source page'
    return f'{size / 2**20:.1f} MB; author: {who}; {PSEUDO_MARK}'


def hf_datasets(term):
    return js(get('https://huggingface.co/api/datasets', {'search': term, 'full': 'true', 'limit': 100}, gap=1.5)) or []


def _hf_licence(d):
    for t in d.get('tags') or []:
        if t.startswith('license:'):
            return t.split(':', 1)[1]
    return ''


def datasets(out, dry, kind, folder, zq, hq, relevant, exts, file_cap_gb, run_gb, items):
    c = Ctx(out, kind)
    bud = Budget(dry, run_gb, items, 2)
    cap = (40 * 2**20) if dry else file_cap_gb * 2**30
    tmp = Path(tempfile.mkdtemp())
    for q in zq:
        page = c.st['cursor'].setdefault(f'z:{q}', 1)
        while page <= 20 and not bud.done():
            hits = zenodo_records(q, page)
            if hits is None:
                break
            for h in hits:
                if bud.done():
                    break
                md = h.get('metadata') or {}
                concept = f'zc:{h.get("conceptrecid") or h["id"]}'
                lic = (md.get('license') or {}).get('id', '') or ''
                text = f'{md.get("title", "")} {re.sub("<[^>]+>", " ", md.get("description") or "")} {" ".join(md.get("keywords") or [])}'
                if concept in c.seen or not relevant(text):
                    c.n['skipped'] += 1
                    continue
                if not OPEN_DATA.match(lic):
                    c.seen.add(concept)
                    c.n['rejected: licence'] = c.n.get('rejected: licence', 0) + 1
                    continue
                sub = f'{folder}/{safe(md.get("title") or h["id"], 90)}'
                files = [f for f in h.get('files', []) if f.get('key', '').lower().endswith(exts) and 0 < f.get('size', 0) <= cap]
                got = 0
                for f in files[:40]:
                    ck = f.get('checksum') or f.get('key')
                    rec = h.get('links', {}).get('self_html') or f'https://zenodo.org/records/{h["id"]}'
                    if ck in c.sums or c.have(rec, safe(f['key'])) or not bud.take(f['size']):
                        continue
                    dest = tmp / 'f'
                    if not download(f['links']['self'], dest, cap):
                        c.n['failed'] += 1
                        continue
                    ok = c.upload(f'{sub}/{safe(f["key"])}', local=dest)
                    dest.unlink()
                    if not ok:
                        continue
                    c.add(sub, {'item': safe(f['key']), 'title': pseudo.text(md.get('title', ''), pseudo.Names()), 'source_url': h.get('links', {}).get('self_html')
                                or f'https://zenodo.org/records/{h["id"]}', 'licence': lic,
                                'notes': f'{f["size"] / 2**20:.1f} MB; version {md.get("version") or "latest"}; DOI {h.get("doi", "")}'},
                          checksum=ck)
                    got += 1
                c.seen.add(concept)
            if len(hits) < 25:
                page = 99
                break
            page += 1
        c.st['cursor'][f'z:{q}'] = page
    for term in hq:
        if bud.done():
            break
        for d in hf_datasets(term):
            if bud.done():
                break
            ident = f'hf:{d["id"]}'
            lic = _hf_licence(d)
            text = f'{d["id"]} {(d.get("cardData") or {}).get("pretty_name", "")} {d.get("description") or ""} {" ".join(d.get("tags") or [])}'
            if ident in c.seen or d.get('private') or not relevant(text):
                c.n['skipped'] += 1
                continue
            if d.get('gated') or not OPEN_DATA.match(lic):  # gated sets need an account and their own terms
                c.seen.add(ident)
                c.n['rejected: licence or gated'] = c.n.get('rejected: licence or gated', 0) + 1
                continue
            tree = js(get(f'https://huggingface.co/api/datasets/{d["id"]}/tree/main', {'recursive': 'true'}, gap=1)) or []
            files = [t for t in tree if t.get('type') == 'file' and t['path'].lower().endswith(exts) and 0 < t.get('size', 0) <= cap]
            sub = f'{folder}/{safe(d["id"].replace("/", " - "), 90)}'
            for t in files[:40]:
                ck = (t.get('lfs') or {}).get('oid') or t.get('oid')
                if ck in c.sums or c.have(f'https://huggingface.co/datasets/{d["id"]}', safe(t['path'].replace('/', ' - '))) or not bud.take(t['size']):
                    continue
                dest = tmp / 'f'
                if not download(f'https://huggingface.co/datasets/{d["id"]}/resolve/main/{t["path"]}', dest, cap):
                    c.n['failed'] += 1
                    continue
                item = safe(t['path'].replace('/', ' - '))
                ok = c.upload(f'{sub}/{item}', local=dest)
                dest.unlink()
                if not ok:
                    continue
                c.add(sub, {'item': item, 'title': hf_title(d['id']), 'source_url': f'https://huggingface.co/datasets/{d["id"]}', 'licence': lic,
                            'notes': f'{t["size"] / 2**20:.1f} MB'}, checksum=ck)
            c.seen.add(ident)
    shutil.rmtree(tmp, ignore_errors=True)
    c.finish()


# video games specifically (a bare "game" also matches sports matches and gamified science tools)
GAME = re.compile(r'(?i)\b(?:gameplay|game ?play|video ?games?|computer games?|mobile games?|online games?|gamers?|gaming|playtest\w*|'
                  r'atari|minecraft|minerl|procgen|doom|vizdoom|mario|esports?|starcraft|dota|league of legends|counter-strike|'
                  r'cs:?go|overwatch|fortnite|steam|unity3?d?|unreal|godot|game engine|game telemetry|game analytics|'
                  r'video game)\b')
INPUT = re.compile(r'(?i)keyboard|mouse|controller|gamepad|joystick|input|action|demonstration|gaze|eye[- ]track|replay|trajector|button')
PLAYER = re.compile(r'(?i)player|playtest|telemetry|session|churn|retention|match|esport|behaviou?r|engagement|ticket|support|review')


def inputs(out, dry):
    datasets(out, dry, 'inputs', INPUTS,
             ['"Atari-HEAD"', 'gameplay keyboard mouse', 'gameplay "human demonstrations"', 'gameplay eye tracking dataset',
              'video game input actions dataset', 'minecraft human demonstrations', 'game controller input logs',
              'gameplay recordings dataset', 'esports replay dataset', 'MineRL', 'minecraft gameplay video dataset',
              '"video pretraining" minecraft', 'procgen recordings', 'gameplay video dataset', 'game playthrough video dataset'],
             ['atari', 'gameplay', 'minecraft', 'game demonstrations', 'video game actions', 'doom', 'minerl', 'procgen',
              'gameplay video', 'vpt'],
             lambda t: bool(GAME.search(t) and INPUT.search(t)),
             ('.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.mp4', '.webm', '.mkv', '.avi', '.csv', '.json', '.jsonl', '.parquet',
              '.hdf5', '.h5', '.npz', '.txt'), 3, 8, 200)


def telemetry(out, dry):
    datasets(out, dry, 'telemetry', TELEM,
             ['"game telemetry"', '"player behavior" game', 'playtest data game', '"game analytics"', 'esports match data',
              '"player churn" game', 'video game sessions dataset', '"customer support tickets"', 'game reviews dataset',
              'player engagement mobile game'],
             ['game telemetry', 'player behavior', 'esports', 'game analytics', 'customer support tickets', 'video game sales'],
             lambda t: bool((GAME.search(t) and PLAYER.search(t)) or re.search(r'(?i)support tickets?|help ?desk', t)),
             ('.csv', '.tsv', '.json', '.jsonl', '.parquet', '.xlsx', '.zip', '.gz', '.7z', '.tar', '.sqlite', '.db'), 1.5, 6, 300)


# ---------------------------------------------------------------- videos (Wikimedia Commons)
COMMONS = 'https://commons.wikimedia.org/w/api.php'
VIDEO_CATS = ['Category:Video game trailers', 'Category:Gameplay videos', 'Category:Videos of video games',
              'Category:Video game videos', 'Category:Free and open-source video games', 'Category:Let\'s Play videos']
FREE = re.compile(r'(?i)^(?:cc0|cc[- ]by(?:[- ]sa)?(?: [\d.]+)?|public domain|pd\b|attribution)')


def _members(cat, kinds):
    cont = {}
    while True:
        r = js(get(COMMONS, {'action': 'query', 'list': 'categorymembers', 'cmtitle': cat, 'cmtype': kinds, 'cmlimit': 500,
                             'format': 'json', **cont}, gap=0.5)) or {}
        yield from (m['title'] for m in r.get('query', {}).get('categorymembers', []))
        cont = r.get('continue') or {}
        if not cont:
            return


def _commons(c, bud, cap, tmp):
    """Wikimedia Commons: free licences only (Commons reviews every upload)."""
    cats, seen_cats, streak = list(VIDEO_CATS), set(), 0
    depth = {k: 0 for k in cats}
    while cats and not bud.done():
        cat = cats.pop(0)
        if cat in seen_cats:
            continue
        seen_cats.add(cat)
        if depth[cat] < 2:
            for sc in _members(cat, 'subcat'):
                if sc not in depth:
                    depth[sc] = depth[cat] + 1
                    cats.append(sc)
        titles = [t for t in _members(cat, 'file') if re.search(r'(?i)\.(?:webm|ogv|mp4|mpg|mpeg)$', t) and t not in c.seen]
        for k in range(0, len(titles), 40):
            if bud.done():
                break
            r = js(get(COMMONS, {'action': 'query', 'titles': '|'.join(titles[k:k + 40]), 'prop': 'imageinfo',
                                 'iiprop': 'url|size|mime|sha1|extmetadata', 'format': 'json'}, gap=0.5)) or {}
            for pg in (r.get('query') or {}).get('pages', {}).values():
                ii = (pg.get('imageinfo') or [{}])[0]
                em = ii.get('extmetadata') or {}
                lic = (em.get('LicenseShortName') or {}).get('value', '')
                if not ii.get('url') or ii.get('sha1') in c.sums or c.have(ii.get('descriptionurl', '')) or not FREE.match(lic) or (em.get('NonFree') or {}).get('value'):
                    c.n['skipped'] += 1
                    c.seen.add(pg['title'])
                    continue
                if ii.get('size', 0) > cap or not bud.take(ii.get('size', 0)):
                    continue
                dest = tmp / 'v'
                if not download(ii['url'], dest, cap, gap=3):
                    c.n['failed'] += 1
                    streak += 1
                    if streak >= 12:  # the media server is refusing us: stop for this run, try again next run
                        log('  videos: media downloads refused repeatedly; stopping this run')
                        bud.items = 0
                        break
                    continue
                streak = 0
                if not fresh(c, dest):
                    continue
                item = safe(pg['title'].split(':', 1)[1])
                ok = c.upload(f'{VIDEOS}/{item}', local=dest, mime=ii.get('mime') or 'video/webm')
                dest.unlink()
                if not ok:
                    continue
                artist = re.sub(r'<[^>]+>', '', (em.get('Artist') or {}).get('value', '')).strip()
                desc = video_title((em.get('ImageDescription') or {}).get('value', ''))
                vn = pseudo.Names()
                if artist_raw := re.sub(r'<[^>]+>', '', (em.get('Artist') or {}).get('value', '')).strip():
                    vn.get(artist_raw)
                desc = pseudo.text(desc, vn)
                c.add(VIDEOS, {'item': item, 'title': desc[:200] or item.rsplit('.', 1)[0], 'source_url': ii.get('descriptionurl', ''), 'licence': lic,
                               'notes': video_notes(ii.get('size', 0), artist)},
                      pg['title'], checksum=ii.get('sha1'))
                c.n['commons added'] = c.n.get('commons added', 0) + 1



def fresh(c, path):
    """Content dedupe across every video source: False (and the file removed) when this exact file is already collected."""
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(2**20), b''):
            h.update(b)
    d = f'sha256:{h.hexdigest()}'
    if d in c.sums:
        Path(path).unlink()
        c.n['duplicate content'] = c.n.get('duplicate content', 0) + 1
        return False
    c.sums.add(d)
    return True


def fetch(c, url, dest, cap, gap=1.0):
    """Downloads one video; a failed download is counted, a file already collected (same content) is dropped."""
    if not download(url, dest, cap, gap=gap):
        c.n['failed'] += 1
        Path(dest).unlink(missing_ok=True)
        return False
    return fresh(c, dest)


# Free and open-source games: footage of these is redistributable under the uploader's licence. Footage of other
# (commercial) games is only taken when the uploader shows it is their own game (devlog, "my game", made with ...).
OPEN_GAMES = ['supertuxkart', 'supertux', '0 a.d.', '0ad', 'xonotic', 'wesnoth', 'minetest', 'luanti', 'openttd', 'veloren',
              'mindustry', 'openra', 'freeciv', 'warzone 2100', 'red eclipse', 'hedgewars', 'teeworlds', 'ddnet', 'openarena',
              'nexuiz', 'speed dreams', 'stuntrally', 'stunt rally', 'mega glest', 'megaglest', 'glest', 'freeorion', 'unciv',
              'cataclysm dda', 'cataclysm: dark days ahead', 'shattered pixel dungeon', 'pixel dungeon', 'naev', 'endless sky',
              'flare', 'opensurge', 'open surge', 'pingus', 'frogatto', 'tux racer', 'extreme tux racer', 'supertux2',
              'armagetron', 'chromium b.s.u', 'assaultcube', 'urban terror', 'warsow', 'sauerbraten', 'cube 2', 'tremulous',
              'unvanquished', 'openmw', 'openrct2', 'openloco', 'opentyrian', 'mari0', 'lincity', 'simutrans', 'widelands',
              'the battle for wesnoth', 'battle for wesnoth', 'liquidwar', 'zero-k', 'zero k', 'beyond all reason',
              'spring engine', 'freedoom', 'blobby volley', 'oolite', 'vega strike', 'pioneer space sim', 'endless-sky',
              'keeperrl', 'dungeon crawl stone soup', 'crawl', 'nethack', 'angband', 'cdda', 'colobot', 'trigger rally',
              'yorg', 'yorg.io', 'shapez', 'luxtorpeda', 'godot demo', 'kenney']
OWN_GAME = re.compile(r'(?i)\bdev ?log\b|\bmy (?:first |new |indie )?game\b|\bour (?:new |indie )?game\b|\bmade (?:it )?(?:with|in) '
                      r'(?:godot|unity|unreal|bevy|love2d|pico-?8|gamemaker|defold|raylib|monogame)\b|\bgame ?jam\b|'
                      r'\bwork in progress\b|\bwip\b|\bindie ?dev\b|\bgamedev\b')
OPEN_GAME = re.compile(r'(?i)(?<![\w])(?:' + '|'.join(re.escape(g) for g in OPEN_GAMES) + r')(?![\w])')


def game_ok(text):
    """'open' (open-source game), 'own' (the uploader's own game) or None (other footage: skipped)."""
    if OPEN_GAME.search(text or ''):
        return 'open'
    if OWN_GAME.search(text or ''):
        return 'own'
    return None


PT_LICENCES = {1: 'CC BY 4.0', 2: 'CC BY-SA 4.0', 7: 'Public domain (CC0)'}  # PeerTube licence ids


def _peertube(c, bud, cap, tmp):
    """PeerTube (the federated index at sepiasearch.org): Gaming category, CC BY / CC BY-SA / public domain only."""
    folder = f'{VIDEOS}/PeerTube'
    for term in ['gameplay', 'trailer', 'devlog', 'let\'s play', 'speedrun', 'game', '']:
        start = c.st['cursor'].get(f'pt:{term}', 0)
        while start < 2000 and not bud.done():
            params = [('search', term), ('categoryOneOf', 7), ('count', 50), ('start', start), ('sort', '-publishedAt')]
            params += [('licenceOneOf', k) for k in PT_LICENCES]
            res = js(get('https://sepiasearch.org/api/v1/search/videos', params, gap=1)) or {}
            data = res.get('data') or []
            for v in data:
                if bud.done():
                    break
                ident = f'pt:{v.get("uuid")}'
                lic_id = (v.get('licence') or {}).get('id')
                if ident in c.seen or c.have(v.get('url', '')):
                    continue
                c.seen.add(ident)
                if lic_id not in PT_LICENCES:
                    c.n['rejected: licence'] = c.n.get('rejected: licence', 0) + 1
                    continue
                host = (v.get('account') or {}).get('host') or (v.get('channel') or {}).get('host')
                det = js(get(f'https://{host}/api/v1/videos/{v["uuid"]}', gap=0.5)) or {}
                text = ' '.join([det.get('name') or v.get('name') or '', det.get('description') or '', ' '.join(det.get('tags') or [])])
                kind = game_ok(text)
                if not kind:
                    c.n['rejected: footage of other games'] = c.n.get('rejected: footage of other games', 0) + 1
                    continue
                files = list(det.get('files') or []) + [f for sp in det.get('streamingPlaylists') or [] for f in sp.get('files') or []]
                files = [f for f in files if f.get('fileDownloadUrl') and 0 < f.get('size', 0) <= cap and (f.get('resolution') or {}).get('id', 0) <= 720]
                if not files:
                    c.n['skipped'] += 1
                    continue
                f = max(files, key=lambda f: (f.get('resolution') or {}).get('id', 0))
                if not bud.take(f['size']):
                    continue
                dest = tmp / 'v'
                if not fetch(c, f['fileDownloadUrl'], dest, cap):
                    continue
                item = safe(f'{v["uuid"]} - {det.get("name") or "video"}', 140) + '.mp4'
                ok = c.upload(f'{folder}/{item}', local=dest, mime='video/mp4')
                dest.unlink(missing_ok=True)
                if not ok:
                    continue
                vn = pseudo.Names()
                vn.get(((det.get('account') or {}).get('displayName')) or 'uploader')
                c.add(folder, {'item': item, 'title': pseudo.text(det.get('name') or '', vn), 'source_url': v.get('url', ''),
                               'licence': PT_LICENCES[lic_id], 'notes': f'{f["size"] / 2**20:.1f} MB; {(f.get("resolution") or {}).get("label", "")}; '
                               f'{"open-source game" if kind == "open" else "the uploader’s own game"}; author: Contributor 001 '
                               f'(credit line on the source page); {PSEUDO_MARK}'}, ident)
                c.n['peertube added'] = c.n.get('peertube added', 0) + 1
            if len(data) < 50:
                start = 10**6
                break
            start += 50
        c.st['cursor'][f'pt:{term}'] = start


IA_FREE = re.compile(r'(?i)creativecommons\.org/(?:licenses/(?:by|by-sa)/|publicdomain/(?:zero|mark)/)')


def _archive(c, bud, cap, tmp):
    """Internet Archive: explicit CC BY / CC BY-SA / public-domain licence AND footage of an open-source game (or the
    uploader's own game). Footage of commercial games is skipped whatever its stated licence."""
    folder = f'{VIDEOS}/Internet Archive'
    games = ' OR '.join(f'"{g}"' for g in OPEN_GAMES[:60])
    queries = [f'mediatype:movies AND licenseurl:*creativecommons* AND (title:({games}) OR subject:({games}))',
               'mediatype:movies AND licenseurl:*creativecommons* AND subject:(devlog OR "indie game" OR gamedev OR "game jam")']
    for qi, q in enumerate(queries):
        page = c.st['cursor'].get(f'ia:{qi}', 1)
        while page <= 40 and not bud.done():
            res = js(get('https://archive.org/advancedsearch.php', {'q': q, 'fl[]': ['identifier', 'licenseurl', 'title', 'subject'],
                                                                    'rows': 100, 'page': page, 'output': 'json'}, gap=1)) or {}
            docs = (res.get('response') or {}).get('docs') or []
            for d in docs:
                if bud.done():
                    break
                ident = f'ia:{d["identifier"]}'
                if ident in c.seen or c.have(f'https://archive.org/details/{d["identifier"]}'):
                    continue
                c.seen.add(ident)
                lic = d.get('licenseurl') or ''
                if not IA_FREE.search(lic):
                    c.n['rejected: licence'] = c.n.get('rejected: licence', 0) + 1
                    continue
                md = js(get(f'https://archive.org/metadata/{d["identifier"]}', gap=0.5)) or {}
                meta = md.get('metadata') or {}
                subj = meta.get('subject') or ''
                text = ' '.join([str(meta.get('title', '')), str(meta.get('description', ''))[:3000],
                                 ' '.join(subj) if isinstance(subj, list) else str(subj)])
                kind = game_ok(text)
                if not kind:
                    c.n['rejected: footage of other games'] = c.n.get('rejected: footage of other games', 0) + 1
                    continue
                vids = [f for f in md.get('files') or [] if re.search(r'(?i)\.(?:mp4|webm|ogv|mkv)$', f.get('name', ''))
                        and 0 < int(f.get('size') or 0) <= cap]
                if not vids:
                    c.n['skipped'] += 1
                    continue
                f = min(vids, key=lambda f: (f.get('source') != 'original', abs(int(f['size']) - 300 * 2**20)))
                ck = f'md5:{f.get("md5")}' if f.get('md5') else None
                if ck in c.sums or not bud.take(int(f['size'])):
                    continue
                dest = tmp / 'v'
                url = f'https://archive.org/download/{d["identifier"]}/{quote(f["name"])}'
                if not fetch(c, url, dest, cap):
                    continue
                item = safe(f'{d["identifier"]} - {Path(f["name"]).name}', 110)
                ok = c.upload(f'{folder}/{item}', local=dest, mime='video/mp4')
                dest.unlink(missing_ok=True)
                if not ok:
                    continue
                vn = pseudo.Names()
                vn.get(str(meta.get('creator') or meta.get('uploader') or 'uploader'))
                c.add(folder, {'item': item, 'title': pseudo.text(str(meta.get('title', ''))[:200], vn),
                               'source_url': f'https://archive.org/details/{d["identifier"]}', 'licence': lic,
                               'notes': f'{int(f["size"]) / 2**20:.1f} MB; {"open-source game" if kind == "open" else "the uploader’s own game"}; '
                                        f'author: Contributor 001 (credit line on the source page); {PSEUDO_MARK}'}, ident, checksum=ck)
                c.n['archive added'] = c.n.get('archive added', 0) + 1
            if len(docs) < 100:
                page = 10**6
                break
            page += 1
        c.st['cursor'][f'ia:{qi}'] = page


PROJECT_REPOS = ['supertuxkart/stk-code', 'SuperTux/supertux', '0ad/0ad', 'xonotic/xonotic', 'wesnoth/wesnoth', 'luanti-org/luanti',
                 'OpenTTD/OpenTTD', 'veloren/veloren', 'Anuken/Mindustry', 'OpenRA/OpenRA', 'freeciv/freeciv', 'Warzone2100/warzone2100',
                 'redeclipse/base', 'hedgewars/hw', 'teeworlds/teeworlds', 'ddnet/ddnet', 'Unciv/Unciv', 'CleverRaven/Cataclysm-DDA',
                 '00-Evan/shattered-pixel-dungeon', 'naev/naev', 'endless-sky/endless-sky', 'flareteam/flare-game', 'alemart/opensurge',
                 'OpenMW/openmw', 'OpenRCT2/OpenRCT2', 'widelands/widelands', 'Pingus/pingus', 'frogatto/frogatto', 'colobot/colobot',
                 'godotengine/godot-demo-projects', 'mrdoob/three.js', 'Zero-K-Game/Zero-K', 'beyond-all-reason/Beyond-All-Reason']
PROJECT_MEDIA = re.compile(r'(?i)\.(?:mp4|webm|ogv|mkv|mov)$')


def _projects(c, bud, cap, tmp):
    """Trailers and gameplay videos that open-source game projects publish themselves (in the repository or as release
    assets), under the project's licence. Video files in these repositories are part of the licensed work."""
    folder = f'{VIDEOS}/Open-source Game Projects'
    for full in PROJECT_REPOS:
        if bud.done():
            break
        info = gh(f'/repos/{full}') or {}
        spdx = ((info.get('license') or {}).get('spdx_id') or '')
        if not info or spdx not in OSI:
            c.n['rejected: licence'] = c.n.get('rejected: licence', 0) + (1 if info else 0)
            continue
        cands = []
        tree = (gh(f'/repos/{full}/git/trees/{info["default_branch"]}', {'recursive': 1}) or {}).get('tree') or []
        cands += [(t['path'], t['size'], f'https://raw.githubusercontent.com/{full}/{info["default_branch"]}/{t["path"]}', t['sha'])
                  for t in tree if t.get('type') == 'blob' and PROJECT_MEDIA.search(t['path']) and 0 < t.get('size', 0) <= cap]
        for rel in (gh(f'/repos/{full}/releases', {'per_page': 30}) or [])[:30]:
            cands += [(f'release {rel.get("tag_name")}/{a["name"]}', a['size'], a['browser_download_url'], f'asset:{a["id"]}')
                      for a in rel.get('assets') or [] if PROJECT_MEDIA.search(a['name']) and 0 < a['size'] <= cap]
        for path, size, url, ident in cands[:20]:
            if bud.done():
                break
            key = f'gh:{full}:{ident}'
            item = safe(f'{full.replace("/", "__")}__{path.replace("/", " - ")}', 110)
            if key in c.seen or c.have(f'https://github.com/{full}', item) or not bud.take(size):
                continue
            dest = tmp / 'v'
            if not fetch(c, url, dest, cap):
                c.seen.add(key)
                continue
            item = safe(f'{full.replace("/", "__")}__{path.replace("/", " - ")}', 110)
            ok = c.upload(f'{folder}/{item}', local=dest)
            dest.unlink(missing_ok=True)
            if not ok:
                continue
            c.add(folder, {'item': item, 'title': f'{full.split("/")[1]}: {path}', 'source_url': f'https://github.com/{full}',
                           'licence': spdx, 'notes': f'{size / 2**20:.1f} MB; published by the project ({"release asset" if path.startswith("release ") else "in the repository"}); '
                           f'some projects license media separately - see the repository; {PSEUDO_MARK}'}, key)
            c.n['project videos added'] = c.n.get('project videos added', 0) + 1


def videos(out, dry):
    """Openly licensed gameplay videos and trailers from four sources, each with its own share of the run budget."""
    c = Ctx(out, 'videos')
    cap = (40 * 2**20) if dry else int(1.5 * 2**30)
    tmp = Path(tempfile.mkdtemp())
    for fn, gb, items in ((_commons, 4, 100), (_peertube, 4, 100), (_archive, 4, 80), (_projects, 2, 60)):
        try:
            fn(c, Budget(dry, gb, items, 1), cap, tmp)
        except Exception:  # noqa: BLE001 - one source never stops the others
            c.n['failed'] += 1
    shutil.rmtree(tmp, ignore_errors=True)
    c.finish()


# ---------------------------------------------------------------- 3D assets (CC0)
def assets(out, dry):
    c = Ctx(out, 'assets')
    bud = Budget(dry, 5, 400, 3)
    tmp = Path(tempfile.mkdtemp())
    for t, sub in (('models', 'Poly Haven Models'), ('textures', 'Poly Haven Textures')):
        lst = js(get('https://api.polyhaven.com/assets', {'t': t}, gap=1)) or {}
        for aid, meta in sorted(lst.items(), key=lambda kv: -kv[1].get('date_published', 0)):
            if bud.done():
                break
            if f'ph:{aid}' in c.seen or c.have(f'https://polyhaven.com/a/{aid}'):
                continue
            files = js(get(f'https://api.polyhaven.com/files/{aid}', gap=0.5)) or {}
            g = ((files.get('gltf') or {}).get('1k') or {}).get('gltf')
            if not g:
                c.n['skipped'] += 1
                continue
            parts = [(Path(g['url']).name, g['url'], g.get('size', 0))] + [(p, i['url'], i.get('size', 0)) for p, i in (g.get('include') or {}).items()]
            size = sum(p[2] for p in parts)
            if not bud.take(size):
                continue
            z = tmp / f'{aid}.zip'
            try:
                with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for path, url, _ in parts:
                        r = get(url, gap=0.2)
                        if r is None or not r.ok:
                            raise RuntimeError('download')
                        zf.writestr(f'{aid}/{path}', r.content)
                    zf.writestr(f'{aid}/LICENSE.txt', 'CC0 1.0 Universal (public domain dedication) - https://polyhaven.com/license\n')
                out.put_file(f'{ASSETS}/{sub}/{aid}.zip', z, 'application/zip')
                c.add(f'{ASSETS}/{sub}', {'item': f'{aid}.zip', 'title': meta.get('name', aid), 'source_url': f'https://polyhaven.com/a/{aid}',
                                          'licence': 'CC0-1.0', 'notes': f'glTF at 1K resolution with textures; {size / 2**20:.1f} MB; '
                                          f'categories: {", ".join(meta.get("categories") or [])[:150]}'}, f'ph:{aid}')
            except Exception:  # noqa: BLE001
                c.n['failed'] += 1
            finally:
                z.unlink(missing_ok=True)
    off = c.st['cursor'].get('acg', 0)
    while not bud.done():
        r = js(get('https://ambientcg.com/api/v2/full_json', {'type': 'Material,3DModel', 'include': 'downloadData', 'limit': 100,
                                                              'offset': off, 'sort': 'Latest'}, gap=1)) or {}
        found = r.get('foundAssets') or []
        for a in found:
            if bud.done():
                break
            aid = a.get('assetId')
            if not aid or f'acg:{aid}' in c.seen or c.have(f'https://ambientcg.com/view?id={aid}'):
                continue
            downs = [d for cat in ((a.get('downloadFolders') or {}).get('default') or {}).get('downloadFiletypeCategories', {}).values()
                     for d in cat.get('downloads', [])]
            pick = sorted((d for d in downs if d.get('fullDownloadPath')),
                          key=lambda d: (not str(d.get('attribute', '')).startswith('1K'), d.get('size') or 1e12))
            if not pick or not bud.take(pick[0].get('size') or 0):
                c.n['skipped'] += 1
                continue
            d = pick[0]
            dest = tmp / 'a.zip'
            if not download(d['fullDownloadPath'], dest, 2**30):
                c.n['failed'] += 1
                continue
            item = safe(f'{aid}_{d.get("attribute", "")}.{d.get("filetype", "zip")}')
            ok = c.upload(f'{ASSETS}/ambientCG/{item}', local=dest)
            dest.unlink()
            if not ok:
                continue
            c.add(f'{ASSETS}/ambientCG', {'item': item, 'title': a.get('displayName') or aid, 'source_url': f'https://ambientcg.com/view?id={aid}',
                                          'licence': 'CC0-1.0', 'notes': f'{a.get("dataType", "")}; {d.get("attribute", "")}'}, f'acg:{aid}')
        if len(found) < 100:
            break
        off += 100
        c.st['cursor']['acg'] = off
    shutil.rmtree(tmp, ignore_errors=True)
    c.finish()


# ---------------------------------------------------------------- re-process items collected before pseudonyms
def pseudo_backfill(out, dry):
    """Rewrites the items already on Drive in place (same file names): code bundles, design documents, video and dataset
    manifests. Items whose manifest row already says PSEUDO_MARK are skipped, so the job can resume. A dry run reads
    Drive but writes to ./samples, for at most two bundles and three documents."""
    from .out import Out
    src = Out(False) if dry else out
    n = {'bundles': 0, 'documents': 0, 'manifest rows': 0, 'failed': 0}
    left = {'bundle': 2 if dry else 10**6, 'doc': 3 if dry else 10**6}
    tmp = Path(tempfile.mkdtemp())
    owner_type = {}

    def otype(owner):
        if owner not in owner_type:
            owner_type[owner] = (gh(f'/users/{owner}') or {}).get('type', 'User')
        return owner_type[owner]

    for eng in src.children(CODE):
        folder = f'{CODE}/{eng}'
        rows = src.read_csv(f'{folder}/manifest.csv')
        mb = lambda r: float((re.search(r'([\d.]+) MB', r['notes']) or [0, 0])[1])  # noqa: E731
        for r in sorted(rows, key=mb):  # smallest first
            if late() or left['bundle'] <= 0:
                break
            if not r['item'].endswith('.bundle') or PSEUDO_MARK in r['notes']:
                continue
            old, work, new = tmp / 'old.bundle', tmp / 'work.git', tmp / r['item']
            try:
                if not src.get_file(f'{folder}/{r["item"]}', old):
                    raise RuntimeError('missing')
                if git('clone', '--mirror', '--quiet', str(old), str(work)).returncode:
                    raise RuntimeError('clone from bundle')
                roots = set(git('rev-list', '--max-parents=0', '--all', cwd=work).stdout.split())  # original roots
                old.unlink()
                names, commits, lfs = pseudo_bundle(work, new)
                out.put_file(f'{folder}/{r["item"]}', new, 'application/octet-stream')
                name = r['item'][:-len('.bundle')]
                r['title'] = repo_title(r['title'], otype(r['title'].split('/')[0]), names)
                r['notes'] = code_notes(name, commits, new.stat().st_size, lfs, roots, names)
                out.manifest(folder, [r])
                n['bundles'] += 1
                left['bundle'] -= 1
            except Exception:  # noqa: BLE001
                n['failed'] += 1
            finally:
                rmtree(work)
                old.unlink(missing_ok=True)
                new.unlink(missing_ok=True)

    rows = src.read_csv(f'{GDD}/manifest.csv')
    per_repo = {}
    for r in rows:
        repo = r['title'].split(':', 1)[0]
        if repo not in per_repo:
            per_repo[repo] = pseudo.Names()
            owner = repo.split('/')[0]
            if not owner.startswith('Contributor ') and otype(owner) != 'Organization':
                per_repo[repo].get(owner)
    done_rows = []
    for r in rows:
        if late() or left['doc'] <= 0:
            break
        if PSEUDO_MARK in r['notes']:
            continue
        repo = r['title'].split(':', 1)[0]
        names = per_repo[repo]
        try:
            p = tmp / 'doc'
            if not src.get_file(f'{GDD}/{r["item"]}', p):
                raise RuntimeError('missing')
            data = pseudo_doc(p.read_bytes(), Path(r['item']).suffix, names)
            out.put(f'{GDD}/{r["item"]}', data)
            p.unlink()
            owner = repo.split('/')[0]
            kind = 'Organization' if owner.startswith('Contributor ') or otype(owner) == 'Organization' else 'User'
            r['title'] = repo_title(repo, kind, names) + ':' + r['title'].split(':', 1)[1]
            r['notes'] = f'{r["notes"]}; {PSEUDO_MARK}'
            done_rows.append(r)
            n['documents'] += 1
            left['doc'] -= 1
        except Exception:  # noqa: BLE001
            n['failed'] += 1
    out.manifest(GDD, done_rows)

    attrib = re.compile(r'attribution: [^;]*')
    folders = [VIDEOS] + [f'{INPUTS}/{x}' for x in src.children(INPUTS)] + [f'{TELEM}/{x}' for x in src.children(TELEM)]
    for folder in folders:
        rows, changed = src.read_csv(f'{folder}/manifest.csv'), []
        for r in rows:
            if PSEUDO_MARK in r['notes']:
                continue
            if folder == VIDEOS:
                m = attrib.search(r['notes'])
                vn = pseudo.Names()
                who = m.group(0)[len('attribution: '):].strip() if m else ''
                if who and who != 'see source page':
                    vn.get(who)
                r['title'] = pseudo.text(video_title(r['title']) or r['item'].rsplit('.', 1)[0], vn)
                r['notes'] = attrib.sub('author: ' + ('Contributor 001 (credit line on the source page)' if vn.order else 'see source page'),
                                        r['notes'])
            elif 'huggingface.co/datasets/' in r['source_url']:
                r['title'] = hf_title(r['source_url'].split('huggingface.co/datasets/', 1)[1])
            else:
                r['title'] = pseudo.text(r['title'], pseudo.Names())
            r['notes'] = f'{r["notes"]}; {PSEUDO_MARK}'
            changed.append(r)
        out.manifest(folder, changed)
        n['manifest rows'] += len(changed)
    rmtree(tmp)
    log('  pseudo_backfill: ' + ', '.join(f'{k} {v}' for k, v in n.items()))
    if n['failed']:
        raise RuntimeError(f'pseudo_backfill: {n["failed"]} item(s) failed; rerun to retry them')


def dedupe_dev(out, dry):
    """Removes copies collected twice (the same source and item listed in two manifest rows, e.g. after parallel jobs
    overwrote each other's state): keeps the copy named in the current style, moves the others to the Drive trash
    (restorable for 30 days) and drops their manifest rows; empty dataset folders go to the trash too. A dry run only
    counts."""
    from .out import Out
    src = Out(False) if dry else out
    n = {'duplicate items': 0, 'trashed': 0, 'emptied folders': 0, 'failed': 0}
    for kind in KIND_FOLDERS:
        groups = {}
        for folder in kind_folders(src, kind):
            for r in src.read_csv(f'{folder}/manifest.csv'):
                groups.setdefault(norm(r['source_url']) + '|' + norm(r['item']), []).append((folder, r['item']))
        drop = {}
        for copies in groups.values():
            if len(copies) < 2:
                continue
            current = [x for x in copies if x[1] == safe(x[1].replace("'", '’')) and x[0] == re.sub(r' {2,}', ' ', x[0])]
            keep = (current or copies)[0]
            for folder, item in copies:
                if (folder, item) != keep:
                    drop.setdefault(folder, []).append(item)
                    n['duplicate items'] += 1
        if dry:
            continue
        for folder, items in drop.items():
            try:
                for item in items:
                    out.trash(f'{folder}/{item}')
                    n['trashed'] += 1
                if out.remove_manifest_rows(folder, items) == 0 and folder.count('/') >= 2:
                    out.trash(folder, folder=True)
                    n['emptied folders'] += 1
            except Exception:  # noqa: BLE001
                n['failed'] += 1
    log('  dedupe_dev: ' + ', '.join(f'{k} {v}' for k, v in n.items()))
    if n['failed']:
        raise RuntimeError(f'dedupe_dev: {n["failed"]} folder(s) failed')

