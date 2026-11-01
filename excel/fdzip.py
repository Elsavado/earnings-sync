"""Zips one category of the Workspace folder "Financial Documents" (IR Transcripts Shared Drive) into parts of at
most ~495 MB, in a separate folder; the originals are never moved or changed (user, 2026-11-01):

  Financial Documents - Zipped/<Category>/<Category> - Part 01 of 07.zip

Files are stored (not recompressed) and keep their folder path inside the category. Parts are planned from the
sorted file list, so a rerun skips the parts already uploaded and makes only the missing ones.

  python fdzip.py "<Category>"        (rclone remote "ws:" must point at the IR Transcripts Shared Drive)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

SRC = 'ws:Financial Documents'
DST = 'ws:Financial Documents - Zipped'
MAX = 495_000_000


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def rclone(*args, capture=False):
    r = subprocess.run(['rclone', *args], capture_output=capture, text=True)
    if r.returncode:
        raise RuntimeError(f'rclone {args[0]} failed ({r.returncode}): {(r.stderr or "")[-500:]}')
    return r.stdout


def plan(cat):
    files = json.loads(rclone('lsjson', '-R', '--files-only', f'{SRC}/{cat}', capture=True))
    files.sort(key=lambda f: f['Path'])
    parts, cur, size = [], [], 0
    for f in files:
        if cur and size + f['Size'] > MAX:
            parts.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += f['Size']
    if cur:
        parts.append(cur)
    return files, parts


def main():
    cat = sys.argv[1]
    files, parts = plan(cat)
    n = len(parts)
    log(f'{cat}: {len(files)} files, {sum(f["Size"] for f in files) / 2**30:.2f} GB -> {n} zip part(s)')
    try:
        done = set(rclone('lsf', '--files-only', f'{DST}/{cat}', capture=True).splitlines())
    except RuntimeError:
        done = set()
    work = tempfile.mkdtemp(prefix='fdzip_')
    for i, part in enumerate(parts, 1):
        name = f'{cat} - Part {i:0{max(2, len(str(n)))}d} of {n:0{max(2, len(str(n)))}d}.zip'
        if name in done:
            log(f'  {name}: already uploaded')
            continue
        src = os.path.join(work, 'files')
        lst = os.path.join(work, 'list.txt')
        with open(lst, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(f['Path'] for f in part) + '\n')
        rclone('copy', f'{SRC}/{cat}', src, '--files-from-raw', lst, '--transfers', '16', '--checkers', '16')
        out = os.path.join(work, name)
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
            for f in part:
                p = os.path.join(src, f['Path'])
                if os.path.exists(p):
                    z.write(p, f['Path'])
        rclone('copyto', out, f'{DST}/{cat}/{name}', '--drive-chunk-size', '128M')
        log(f'  {name}: {len(part)} files, {os.path.getsize(out) / 2**20:.0f} MB uploaded')
        shutil.rmtree(src, ignore_errors=True)
        os.remove(out)
    log(f'{cat}: done')


if __name__ == '__main__':
    main()
