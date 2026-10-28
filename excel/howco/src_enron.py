"""Energy-trading company e-mail corpus: the EDRM v2 mailboxes as PST files (Hugging Face
intellekthq/enron-ferc-pst, CC BY 3.0 US, privacy-cleaned by its publisher; 171 files, 1.2 M messages, 454 k
attachments). One PST at a time: download, unpack with readpst, give every person and company a made-up name,
then upload

  Energy Trading Company Corpus/<made-up mailbox owner>/Emails part NNN.zip      (one .eml per message, by folder)
  Energy Trading Company Corpus/<made-up mailbox owner>/Attachments/<Type> part K.zip
                                                       (unique office documents, PDFs and text files; up to 500 a zip)

Attachments are unique across the whole corpus (content hash). Zips keep the Shared Drive far below its item cap.
"""
import email
import email.policy
import hashlib
import re
import shutil
import subprocess
import time
import zipfile
from collections import Counter
from email.message import EmailMessage
from email.utils import getaddresses
from pathlib import Path

import requests

from .anon import LEGACY, convert_legacy

REPO = 'intellekthq/enron-ferc-pst'
KEEP = {'xls', 'xlsx', 'xlsm', 'doc', 'docx', 'ppt', 'pptx', 'pdf', 'csv', 'txt', 'rtf'}
TYPES = {'xls': 'Spreadsheets', 'xlsx': 'Spreadsheets', 'xlsm': 'Spreadsheets', 'csv': 'Spreadsheets',
         'doc': 'Documents', 'docx': 'Documents', 'rtf': 'Documents', 'txt': 'Documents',
         'ppt': 'Presentations', 'pptx': 'Presentations', 'pdf': 'PDFs'}
ADDR_HEADERS = ('From', 'To', 'Cc', 'Bcc', 'Reply-To', 'Sender')
KEEP_HEADERS = ('Date', 'Subject', 'Importance', 'Content-Language')
PER_ZIP = 500
LICENCE = ('Source: EDRM Enron Email Data Set v2 as PST (Hugging Face intellekthq/enron-ferc-pst), produced by ZL '
           'Technologies, Inc., licensed CC BY 3.0 US (https://creativecommons.org/licenses/by/3.0/us/), modified '
           'by its publisher to reduce privacy risk. Modified again here: every person and company has a made-up '
           'name. No endorsement by ZL Technologies, EDRM or the correspondents is implied.\n')


def pst_files():
    r = requests.get(f'https://huggingface.co/api/datasets/{REPO}/tree/main/data', timeout=60)
    return sorted((x['path'], x['size']) for x in r.json() if x['path'].endswith('.pst'))


def run(ctx, log):
    st = ctx.state
    st.setdefault('done', [])
    st.setdefault('hashes', [])
    st.setdefault('owners', {})
    st.setdefault('att_parts', {})
    A = ctx.make_anon()
    hashes = set(st['hashes'])
    uploaded = ctx.drive.uploaded()
    files = pst_files()
    log(f'{len(files)} PST files, {len(st["done"])} done')
    if not ctx.dry and 'licence' not in uploaded:
        p = ctx.work / 'licence.txt'
        p.write_text(LICENCE, encoding='utf-8')
        ctx.drive.upload(str(p), ctx.folder, 'About this corpus (licence).txt', 'licence')
    for path, size in files:
        if path in st['done']:
            continue
        need = 1200 + size / 2**20 * 3  # seconds: a rough cost per MB of PST
        if ctx.left() < need:
            log(f'{path.rsplit("/", 1)[-1]}: not enough time left in this run')
            break
        t0 = time.time()
        try:
            stats = one(ctx, A, path, hashes, uploaded, log)
        except Exception as e:  # noqa: BLE001
            log(f'{path}: problem {type(e).__name__}: {str(e)[:300]}')
            shutil.rmtree(ctx.work / 'pst', ignore_errors=True)
            continue
        st['hashes'] = sorted(hashes)
        st['done'].append(path)
        ctx.save()
        log(f'{path.rsplit("/", 1)[-1]}: {stats} in {(time.time() - t0) / 60:.0f} min')
        if ctx.dry:
            break  # one PST is enough to check


def _participants(A, msg):
    out, seen = [], set()
    for h in ADDR_HEADERS:
        for disp, addr in getaddresses([str(v) for v in msg.get_all(h, [])]):
            who = A.pp.from_display(disp) or A.pp.from_display(addr.split('@')[0]) if (disp or addr) else None
            if who and (who[0].lower(), who[1].lower()) not in seen:
                seen.add((who[0].lower(), who[1].lower()))
                out.append(who)
    return out


def _addr_list(A, value):
    out = []
    for disp, addr in getaddresses([value]):
        if addr and '@' in addr:
            new_addr = A.pp.address(addr, disp)
        elif addr:
            new_addr = A.text(addr)
        else:
            new_addr = ''
        new_disp = A.text(disp) if disp else ''
        out.append(f'"{new_disp}" <{new_addr}>' if new_disp and new_addr else (new_addr or new_disp))
    return ', '.join(x for x in out if x)


def _body(msg):
    """Plain text of a message (HTML turned into text when there is no plain part)."""
    plain, html = [], []
    for part in msg.walk():
        if part.is_multipart() or part.get_filename() or part.get_content_disposition() == 'attachment':
            continue
        ct = part.get_content_type()
        try:
            payload = part.get_payload(decode=True) or b''
        except Exception:  # noqa: BLE001
            continue
        cs = part.get_content_charset() or 'cp1252'
        try:
            text = payload.decode(cs, 'replace')
        except LookupError:
            text = payload.decode('cp1252', 'replace')
        if ct == 'text/plain':
            plain.append(text)
        elif ct == 'text/html':
            html.append(text)
    if plain:
        return '\n'.join(plain)
    t = '\n'.join(html)
    t = re.sub(r'(?is)<(script|style).*?</\1>', '', t)
    t = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>', '\n', t)
    t = re.sub(r'<[^>]+>', '', t)
    from html import unescape
    return unescape(t)


def _attachments(msg):
    for part in msg.walk():
        fn = part.get_filename()
        if not fn or part.is_multipart():
            continue
        ext = fn.rsplit('.', 1)[-1].lower() if '.' in fn else ''
        if ext not in KEEP:
            continue
        try:
            data = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            data = None
        if data:
            yield fn, ext, data


def one(ctx, A, path, hashes, uploaded, log):
    name = path.rsplit('/', 1)[-1]
    m = re.match(r'zl_(.+?)_(\d+)\.pst$', name)
    mailbox, part = (m.group(1), m.group(2)) if m else (name[:-4], '000')
    work = ctx.work / 'pst'
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    pst = work / name
    with requests.get(f'https://huggingface.co/datasets/{REPO}/resolve/main/{path}', stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(pst, 'wb') as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    out = work / 'out'
    out.mkdir()
    subprocess.run(['readpst', '-e', '-b', '-q', '-D', '-j', '4', '-o', str(out), str(pst)], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=7200)
    pst.unlink()
    files = sorted(p for p in out.rglob('*') if p.is_file())
    log(f'{name}: {len(files)} messages unpacked')

    # Pass 1: who is in this mailbox (so names are known before any body is rewritten) and whose mailbox it is.
    msgs, senders = [], Counter()
    for p in files:
        try:
            msg = email.message_from_bytes(p.read_bytes(), policy=email.policy.compat32)
        except Exception:  # noqa: BLE001
            continue
        who = _participants(A, msg)
        for w in who:
            A.pp.pseudo(*w)
        frm = A.pp.from_display(str(msg.get('From', '')).split('<')[0]) or None
        if frm and re.search(r'sent', str(p.parent), re.I):
            senders[(frm[0].lower(), frm[1].lower())] += 1
        msgs.append((p, who))
    owner = ctx.state['owners'].get(mailbox)
    if not owner:
        last, _, init = mailbox.partition('-')
        cands = [w for w in senders if w[1] == last and (not init or w[0].startswith(init[:1]))]
        owner = list(max(cands, key=lambda w: senders[w]) if cands else
                     (senders.most_common(1)[0][0] if senders else ('mailbox', mailbox.replace('-', ''))))
        ctx.state['owners'][mailbox] = owner
    owner_name = A.pp.pseudo(*owner)
    rel = f'{ctx.folder}/{owner_name}'

    # Pass 2: rewrite every message; collect new attachments.
    stats = Counter()
    zpath = work / f'Emails part {part}.zip'
    att_dir = work / 'att'
    att_dir.mkdir()
    new_att = []
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for i, (p, who) in enumerate(msgs):
            A.start()
            try:
                msg = email.message_from_bytes(p.read_bytes(), policy=email.policy.compat32)
                body = A.text(_body(msg), who)
                new = EmailMessage()
                for h in ADDR_HEADERS:
                    v = msg.get_all(h)
                    if v:
                        new[h] = re.sub(r'[

]+\s*', ' ', _addr_list(A, ', '.join(str(x) for x in v)))
                for h in KEEP_HEADERS:
                    if msg.get(h):
                        val = A.text(str(msg.get(h)), who) if h == 'Subject' else str(msg.get(h))
                        new[h] = re.sub(r'[

]+\s*', ' ', val)
                names = []
                for fn, ext, data in _attachments(msg):
                    fn_new = A.text(fn, who)
                    names.append(fn_new)
                    h = hashlib.sha1(data).hexdigest()[:20]
                    if h in hashes:
                        stats['duplicate attachments'] += 1
                        continue
                    hashes.add(h)
                    local = att_dir / f'{len(new_att) + 1}.{ext}'
                    local.write_bytes(data)
                    new_att.append((local, ext, fn_new, who, h))
                if names:
                    new['X-Attachments'] = re.sub(r'[
]+\s*', ' ', '; '.join(names))[:900]
                new.set_content(body or '')
                raw = bytes(new)
                folder = '/'.join(A.text(seg, who) for seg in p.parent.relative_to(out).parts)
                z.writestr(f'{folder}/{i + 1}.eml', raw)
                stats['messages'] += 1
                lk = A.leaks(raw.decode('utf-8', 'replace'), who)
                if lk:
                    stats['messages with a name left'] += 1
                    ctx.leak_report.append(f'{name} message {i + 1}: {", ".join(sorted(set(lk))[:8])}')
                if ctx.dry and stats['messages'] <= 15:
                    s = work / f'sample {i + 1}.eml'
                    s.write_bytes(raw)
                    ctx.sample(s, f'{owner_name} - {i + 1}.eml')
            except Exception as e:  # noqa: BLE001
                stats['unreadable messages'] += 1
                if stats['unreadable messages'] <= 3:
                    log(f'  message {i + 1}: {type(e).__name__}: {str(e)[:150]}')
    shutil.rmtree(out, ignore_errors=True)
    key = f'emails:{mailbox}:{part}'
    if key not in uploaded:
        ctx.drive.upload(str(zpath), rel, f'Emails part {part}.zip', key)
        stats['uploads'] += 1
    zpath.unlink()

    # Attachments: legacy formats to OOXML, made-up names inside, then zipped by type.
    legacy = [str(a[0]) for a in new_att if a[1] in LEGACY]
    conv = convert_legacy(legacy, att_dir / 'conv') if legacy else {}
    by_type = {}
    for local, ext, fn_new, who, h in new_att:
        src, e = str(local), ext
        if ext in LEGACY:
            src = conv.get(str(local))
            if not src:
                stats['attachments not converted'] += 1
                continue
            e = LEGACY[ext]
        dst = att_dir / f'anon-{local.stem}.{e}'
        A.start()
        try:
            ok, text = A.file(src, dst, e, who)
        except Exception:  # noqa: BLE001
            ok, text = False, ''
        if not ok:
            stats['attachments unreadable'] += 1
            continue
        lk = A.leaks(text, who)
        if lk:
            stats['attachments with a name left'] += 1
            ctx.leak_report.append(f'{name} attachment {local.name}: {", ".join(sorted(set(lk))[:8])}')
        stem = re.sub(r'[\\/:*?"<>|]+', ' ', fn_new.rsplit('.', 1)[0]).strip()[:80] or 'attachment'
        by_type.setdefault(TYPES[ext], []).append((dst, f'{stem}.{e}'))
        stats['attachments'] += 1
        if ctx.dry and stats['attachments'] <= 10:
            ctx.sample(dst, f'{owner_name} - attachment {stats["attachments"]} - {stem}.{e}')
    parts = ctx.state['att_parts'].setdefault(mailbox, {})
    for typ, items in by_type.items():
        for i in range(0, len(items), PER_ZIP):
            k = parts.get(typ, 0) + 1
            zp = work / f'{typ} part {k}.zip'
            used = set()
            with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
                for dst, nm in items[i:i + PER_ZIP]:
                    base, n = nm, 2
                    while nm.lower() in used:
                        nm = re.sub(r'(\.[^.]+)$', f' ({n})\\1', base)
                        n += 1
                    used.add(nm.lower())
                    z.write(dst, nm)
            akey = f'att:{mailbox}:{part}:{typ}:{i // PER_ZIP}'
            if akey not in uploaded:
                ctx.drive.upload(str(zp), f'{rel}/Attachments', f'{typ} part {k}.zip', akey)
                stats['uploads'] += 1
            parts[typ] = k
            zp.unlink()
    shutil.rmtree(work, ignore_errors=True)
    return dict(stats)
