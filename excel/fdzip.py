"""Zips a batch of 50 files per file type from the Workspace folder "Financial Documents" (IR Transcripts Shared
Drive) into a separate folder; the originals are never moved or changed (user, 2026-11-01: "zip a batch of 50 files
per file type, do not zip them all"):

  Financial Documents - Zipped/PDF - 50 files.zip, IPYNB - 50 files.zip, CSV - 50 files.zip, ...

The 50 files of a type are spread evenly over its sorted file list, so every category of that type is represented.
A type with fewer files is zipped whole. Files are stored (not recompressed) and keep their folder path.
Anything else in the zip folder (category zips from the earlier whole-folder plan) is removed first.

  python fdzip.py        (rclone remote "ws:" must point at the IR Transcripts Shared Drive)
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile

SRC = 'ws:Financial Documents'
DST = 'ws:Financial Documents - Zipped'
PER_TYPE = 50


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def rclone(*args, capture=False, check=True):
    r = subprocess.run(['rclone', *args], capture_output=capture, text=True)
    if r.returncode and check:
        raise RuntimeError(f'rclone {args[0]} failed ({r.returncode}): {(r.stderr or "")[-500:]}')
    return r.stdout


def main():
    files = json.loads(rclone('lsjson', '-R', '--files-only', SRC, capture=True))
    by_type = {}
    for f in sorted(files, key=lambda f: f['Path']):
        ext = f['Name'].rsplit('.', 1)[-1].upper() if '.' in f['Name'] else 'OTHER'
        by_type.setdefault(ext, []).append(f)
    log(f'{len(files)} files: ' + ', '.join(f'{t} {len(v)}' for t, v in sorted(by_type.items())))
    names = {f'{t} - {min(PER_TYPE, len(v))} files.zip' for t, v in by_type.items()}
    old = [p for p in rclone('lsf', '-R', DST, capture=True, check=False).splitlines() if p not in names]
    for p in old:  # category folders first, then loose files
        if p.endswith('/') and '/' not in p.rstrip('/'):
            rclone('purge', f'{DST}/{p.rstrip("/")}', check=False)
        elif not p.endswith('/') and '/' not in p:
            rclone('deletefile', f'{DST}/{p}', check=False)
    if old:
        log(f'removed {len(old)} earlier item(s) from the zip folder')
    work = tempfile.mkdtemp(prefix='fdzip_')
    for t, fs in sorted(by_type.items()):
        step = len(fs) / min(PER_TYPE, len(fs))
        pick = [fs[int(i * step)] for i in range(min(PER_TYPE, len(fs)))]
        name = f'{t} - {len(pick)} files.zip'
        src = os.path.join(work, 'files')
        lst = os.path.join(work, 'list.txt')
        with open(lst, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(f['Path'] for f in pick) + '\n')
        rclone('copy', SRC, src, '--files-from-raw', lst, '--transfers', '16')
        out = os.path.join(work, name)
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
            for f in pick:
                p = os.path.join(src, f['Path'])
                if os.path.exists(p):
                    z.write(p, f['Path'])
        rclone('copyto', out, f'{DST}/{name}', '--drive-chunk-size', '128M')
        log(f'{name}: {os.path.getsize(out) / 2**20:.0f} MB uploaded')
        shutil.rmtree(src, ignore_errors=True)
        os.remove(out)
    log('done')


if __name__ == '__main__':
    main()
