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

import requests

from .out import log

DEVF = '8 Game Development'
CODE, GDD, INPUTS, VIDEOS, TELEM, ASSETS = (f'{DEVF}/Game & Engine Code', f'{DEVF}/Design Documents',
                                           f'{DEVF}/Gameplay Recordings & Input Logs', f'{DEVF}/Gameplay Videos & Trailers',
                                           f'{DEVF}/Player Analytics & Telemetry', f'{DEVF}/3D Assets & Materials')
UA = 'GameDevPlanningCollector/1.0 (personal research; python-requests)'
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


def download(url, dest, limit, headers=None):
    """Streams url to dest; None if it fails or exceeds limit bytes."""
    for i in range(3):
        try:
            with S.get(url, stream=True, timeout=120, headers=headers or {}) as r:
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
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', ' ', str(name)).strip(' .')
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


class Ctx:
    """Shared state for one kind: seen ids/checksums (unique content), counts, pending manifest rows per folder."""

    def __init__(self, out, kind):
        self.out, self.kind = out, kind
        st = out.state('devdata') or {}
        self.all = st
        self.st = st.setdefault(kind, {'seen': [], 'sums': [], 'roots': [], 'cursor': {}})
        for k in ('seen', 'sums', 'roots'):
            self.st.setdefault(k, [])
        self.st.setdefault('cursor', {})
        self.seen, self.sums, self.roots = set(self.st['seen']), set(self.st['sums']), set(self.st['roots'])
        self.rows = {}
        self.n = {'added': 0, 'skipped': 0, 'failed': 0}
        self.last_save = time.time()

    def add(self, folder, row, ident=None, checksum=None, roots=()):
        row.setdefault('collected_date', today())
        row.setdefault('synthetic', 'no')
        self.rows.setdefault(folder, []).append(row)
        if ident:
            self.seen.add(ident)
        if checksum:
            self.sums.add(checksum)
        self.roots.update(roots)
        self.n['added'] += 1
        if time.time() - self.last_save > 600:
            self.save()

    def save(self):
        for folder, rows in self.rows.items():
            self.out.manifest(folder, rows)
        self.rows = {}
        self.st['seen'], self.st['sums'], self.st['roots'] = sorted(self.seen), sorted(self.sums), sorted(self.roots)
        if not self.out.dry:
            self.out.save_state('devdata', self.all)
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
                if ident in c.seen or it.get('is_template') or spdx not in OSI:
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
                    if git('bundle', 'create', str(bundle), '--all', cwd=work).returncode:
                        raise RuntimeError('bundle')
                    size = bundle.stat().st_size
                    if not bud.take(size):
                        bundle.unlink()
                        if bud.done():
                            break
                        continue
                    commits = git('rev-list', '--count', '--all', cwd=work).stdout.strip()
                    lfs = 'filter=lfs' in git('show', 'HEAD:.gitattributes', cwd=work).stdout
                    lic = gh(f'/repos/{it["full_name"]}/license') or {}
                    folder = f'{CODE}/{engine}'
                    out.put_file(f'{folder}/{name}.bundle', bundle, 'application/octet-stream')
                    if lic.get('content'):
                        out.put(f'{folder}/{name}.LICENSE.txt', base64.b64decode(lic['content']), 'text/plain')
                    c.add(folder, {'item': f'{name}.bundle', 'title': it['full_name'], 'source_url': it['html_url'], 'licence': spdx,
                                   'notes': f'git bundle of every branch and tag; {commits} commits; {size / 2**20:.1f} MB; '
                                            f'licence text in {name}.LICENSE.txt' + ('; large binary files are Git LFS pointers' if lfs else '')},
                          ident, roots=roots)
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
GDD_FILE = re.compile(r'(?i)(?:^|/)[^/]*(?:\bgdd\b|game[-_ ]?design[-_ ]?doc|design[-_ ]?document)[^/]*\.(?:md|pdf|docx|odt|txt)$')


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
                for t in docs[:5]:
                    if t['sha'] in c.sums or not bud.take(t['size']):
                        continue
                    raw = get(f'https://raw.githubusercontent.com/{it["full_name"]}/{it["default_branch"]}/{t["path"]}', gap=0.3)
                    if raw is None or not raw.ok:
                        c.n['failed'] += 1
                        continue
                    name = safe(f'{it["owner"]["login"]}__{it["name"]}__{Path(t["path"]).name}')
                    out.put(f'{GDD}/{name}', raw.content)
                    c.add(GDD, {'item': name, 'title': f'{it["full_name"]}: {t["path"]}', 'source_url': f'{it["html_url"]}/blob/'
                                f'{it["default_branch"]}/{t["path"]}', 'licence': spdx, 'notes': f'{t["size"]:,} bytes'}, checksum=t['sha'])
                    got += 1
                if got:
                    lic = gh(f'/repos/{it["full_name"]}/license') or {}
                    if lic.get('content'):
                        out.put(f'{GDD}/{safe(it["owner"]["login"] + "__" + it["name"])}.LICENSE.txt', base64.b64decode(lic['content']), 'text/plain')
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
                if concept in c.seen or not OPEN_DATA.match(lic) or not relevant(text):
                    c.n['skipped'] += 1
                    continue
                sub = f'{folder}/{safe(md.get("title") or h["id"], 90)}'
                files = [f for f in h.get('files', []) if f.get('key', '').lower().endswith(exts) and 0 < f.get('size', 0) <= cap]
                got = 0
                for f in files[:40]:
                    ck = f.get('checksum') or f.get('key')
                    if ck in c.sums or not bud.take(f['size']):
                        continue
                    dest = tmp / 'f'
                    if not download(f['links']['self'], dest, cap):
                        c.n['failed'] += 1
                        continue
                    out.put_file(f'{sub}/{safe(f["key"])}', dest)
                    dest.unlink()
                    c.add(sub, {'item': safe(f['key']), 'title': md.get('title', ''), 'source_url': h.get('links', {}).get('self_html')
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
            if ident in c.seen or d.get('gated') or d.get('private') or not OPEN_DATA.match(lic) or not relevant(text):
                c.n['skipped'] += 1
                continue
            tree = js(get(f'https://huggingface.co/api/datasets/{d["id"]}/tree/main', {'recursive': 'true'}, gap=1)) or []
            files = [t for t in tree if t.get('type') == 'file' and t['path'].lower().endswith(exts) and 0 < t.get('size', 0) <= cap]
            sub = f'{folder}/{safe(d["id"].replace("/", " - "), 90)}'
            for t in files[:40]:
                ck = (t.get('lfs') or {}).get('oid') or t.get('oid')
                if ck in c.sums or not bud.take(t['size']):
                    continue
                dest = tmp / 'f'
                if not download(f'https://huggingface.co/datasets/{d["id"]}/resolve/main/{t["path"]}', dest, cap):
                    c.n['failed'] += 1
                    continue
                item = safe(t['path'].replace('/', ' - '))
                out.put_file(f'{sub}/{item}', dest)
                dest.unlink()
                c.add(sub, {'item': item, 'title': d['id'], 'source_url': f'https://huggingface.co/datasets/{d["id"]}', 'licence': lic,
                            'notes': f'{t["size"] / 2**20:.1f} MB'}, checksum=ck)
            c.seen.add(ident)
    shutil.rmtree(tmp, ignore_errors=True)
    c.finish()


GAME = re.compile(r'(?i)\b(?:game|gameplay|games|gaming|atari|minecraft|doom|mario|esports?|video ?game|starcraft|dota|league of legends)\b')
INPUT = re.compile(r'(?i)keyboard|mouse|controller|gamepad|joystick|input|action|demonstration|gaze|eye[- ]track|replay|trajector|button')
PLAYER = re.compile(r'(?i)player|playtest|telemetry|session|churn|retention|match|esport|behaviou?r|engagement|ticket|support|review')


def inputs(out, dry):
    datasets(out, dry, 'inputs', INPUTS,
             ['"Atari-HEAD"', 'gameplay keyboard mouse', 'gameplay "human demonstrations"', 'gameplay eye tracking dataset',
              'video game input actions dataset', 'minecraft human demonstrations', 'game controller input logs',
              'gameplay recordings dataset', 'esports replay dataset'],
             ['atari', 'gameplay', 'minecraft', 'game demonstrations', 'video game actions', 'doom'],
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


def videos(out, dry):
    c = Ctx(out, 'videos')
    bud = Budget(dry, 6, 150, 2)
    cap = (40 * 2**20) if dry else int(1.5 * 2**30)
    tmp = Path(tempfile.mkdtemp())
    cats, seen_cats = list(VIDEO_CATS), set()
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
                if not ii.get('url') or ii.get('sha1') in c.sums or not FREE.match(lic) or (em.get('NonFree') or {}).get('value'):
                    c.n['skipped'] += 1
                    c.seen.add(pg['title'])
                    continue
                if ii.get('size', 0) > cap or not bud.take(ii.get('size', 0)):
                    continue
                dest = tmp / 'v'
                if not download(ii['url'], dest, cap):
                    c.n['failed'] += 1
                    continue
                item = safe(pg['title'].split(':', 1)[1])
                out.put_file(f'{VIDEOS}/{item}', dest, ii.get('mime') or 'video/webm')
                dest.unlink()
                artist = re.sub(r'<[^>]+>', '', (em.get('Artist') or {}).get('value', '')).strip()
                desc = re.sub(r'https?://\S+|<[^>]+>', ' ', (em.get('ImageDescription') or {}).get('value', ''))
                desc = next((ln.strip() for ln in desc.splitlines() if len(ln.strip()) > 3), '')
                c.add(VIDEOS, {'item': item, 'title': desc[:200] or item.rsplit('.', 1)[0], 'source_url': ii.get('descriptionurl', ''), 'licence': lic,
                               'notes': f'{ii.get("size", 0) / 2**20:.1f} MB; attribution: {artist[:200] or "see source page"}'},
                      pg['title'], checksum=ii.get('sha1'))
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
            if f'ph:{aid}' in c.seen:
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
            if not aid or f'acg:{aid}' in c.seen:
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
            out.put_file(f'{ASSETS}/ambientCG/{item}', dest)
            dest.unlink()
            c.add(f'{ASSETS}/ambientCG', {'item': item, 'title': a.get('displayName') or aid, 'source_url': f'https://ambientcg.com/view?id={aid}',
                                          'licence': 'CC0-1.0', 'notes': f'{a.get("dataType", "")}; {d.get("attribute", "")}'}, f'acg:{aid}')
        if len(found) < 100:
            break
        off += 100
        c.st['cursor']['acg'] = off
    shutil.rmtree(tmp, ignore_errors=True)
    c.finish()

