"""ATLAS Finance (Hugging Face handshake-ai-research/ATLAS-Finance, CC BY 4.0): 13 simulated financial firms, each
with a data room, drive, inbox, chat, calendar and wiki, and 100 expert tasks (M&A, LBO, operating, project,
credit models). The firms and people are fictional already, so nothing is renamed.

  ATLAS Finance (simulated firms)/<Firm>/Documents/...            (unique files of the firm's drive and mail attachments)
  ATLAS Finance (simulated firms)/<Firm>/Tasks/<task>.md          (the brief a professional would be given)
  ATLAS Finance (simulated firms)/<Firm>/World data (inbox, chat, calendar, wiki).zip
  ATLAS Finance (simulated firms)/tasks.jsonl, About ATLAS Finance (licence).txt
"""
import hashlib
import json
import re
import shutil
import zipfile

import requests

REPO = 'handshake-ai-research/ATLAS-Finance'
BASE = f'https://huggingface.co/datasets/{REPO}/resolve/main'
DOCS = {'pdf', 'xlsx', 'xlsm', 'docx', 'pptx', 'csv', 'md', 'txt'}
LICENCE = ('Source: ATLAS Finance by Handshake AI Research (https://huggingface.co/datasets/handshake-ai-research/'
           'ATLAS-Finance), licensed CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Files are copied '
           'unchanged from the environment packs; the firms and people in them are fictional.\n')


def _get(url, dst):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dst, 'wb') as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def run(ctx, log):
    st = ctx.state
    st.setdefault('done', [])
    up = ctx.drive.uploaded()
    tree = requests.get(f'https://huggingface.co/api/datasets/{REPO}/tree/main/env-packs', timeout=60).json()
    packs = sorted(x['path'] for x in tree if x['path'].endswith('.zip'))
    for key, name, text in (('licence', 'About ATLAS Finance (licence).txt', LICENCE),):
        if key not in up:
            p = ctx.work / 'licence.txt'
            p.write_text(text, encoding='utf-8')
            ctx.drive.upload(str(p), ctx.folder, name, key)
    if 'tasks.jsonl' not in up:
        p = ctx.work / 'tasks.jsonl'
        _get(f'{BASE}/tasks.jsonl', p)
        ctx.drive.upload(str(p), ctx.folder, 'tasks.jsonl', 'tasks.jsonl')
    for path in packs:
        if path in st['done'] or ctx.left() < 900:
            continue
        m = re.match(r'env-packs/env(\d+)_(.+)\.zip$', path)
        firm = m.group(2).replace('-', ' ').title() if m else path
        rel = f'{ctx.folder}/{firm}'
        z = ctx.work / 'pack.zip'
        _get(f'{BASE}/{path}', z)
        seen, n_docs, n_tasks = set(), 0, 0
        with zipfile.ZipFile(z) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            # Documents: the firm's drive and mail attachments, each unique file once.
            for i in infos:
                parts = i.filename.split('/')
                ext = i.filename.rsplit('.', 1)[-1].lower()
                if ext not in DOCS or not re.search(r'/workspace/(?:drive/data|outlook/data/attachments)/', i.filename):
                    continue
                data = zf.read(i)
                h = hashlib.sha1(data).hexdigest()
                if h in seen:
                    continue
                seen.add(h)
                key = f'doc:{path}:{h[:16]}'
                if key not in up:
                    local = ctx.work / f'd.{ext}'
                    local.write_bytes(data)
                    ctx.drive.upload(str(local), f'{rel}/Documents', parts[-1], key)
                n_docs += 1
            # Task briefs.
            for i in infos:
                if i.filename.endswith('/instruction.md') and i.filename.count('/') == 1:
                    task = i.filename.split('/')[0]
                    key = f'task:{task}'
                    if key not in up:
                        local = ctx.work / 'task.md'
                        local.write_bytes(zf.read(i))
                        ctx.drive.upload(str(local), f'{rel}/Tasks', f'{task.split("__")[-1]}.md', key)
                    n_tasks += 1
            # The firm's world (inbox, chat, calendar, wiki...) from its first task, without the documents above.
            first = sorted({i.filename.split('/')[0] for i in infos})[0]
            wz = ctx.work / 'world.zip'
            with zipfile.ZipFile(wz, 'w', zipfile.ZIP_DEFLATED) as out:
                for i in infos:
                    f = i.filename
                    if f.startswith(f'{first}/environment/workspace/') and not re.search(
                            r'/workspace/(?:drive/data|outlook/data/attachments)/', f):
                        out.writestr(f.split('/environment/workspace/', 1)[1], zf.read(i))
            key = f'world:{path}'
            if key not in up:
                ctx.drive.upload(str(wz), rel, 'World data (inbox, chat, calendar, wiki).zip', key)
            wz.unlink()
        z.unlink()
        st['done'].append(path)
        ctx.save()
        log(f'{firm}: {n_docs} unique documents, {n_tasks} tasks')
        if ctx.dry:
            break
    if len(st['done']) >= len(packs):
        st['finished'] = True
    shutil.rmtree(ctx.work, ignore_errors=True)
    ctx.work.mkdir(parents=True, exist_ok=True)
