"""Zips a batch of 50 files per document category and file type from the Workspace folder "Financial Documents"
(IR Transcripts Shared Drive) into a separate folder; the originals are never moved or changed (user, 2026-11-01:
"zip a batch of 50 files per file type, do not zip them all", then "by document type ... the way they are in the
folders, as term sheets etc, each in their own zips of 50"):

  Financial Documents - Zipped/Term Sheets, LOIs & NDAs - PDF - 50 files.zip, Jupyter Notebooks - IPYNB - 50 files.zip, ...

The 50 files are spread evenly over the group's sorted file list. A group with fewer files is zipped whole. Files are stored (not recompressed) and keep their folder path.
Anything else in the zip folder (zips of earlier plans) is removed first.

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
SKIP = {'CSV'}  # user, 2026-11-01: "do not add csv"


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
        if ext in SKIP:
            continue
        by_type.setdefault(f"{f['Path'].split('/', 1)[0]} - {ext}", []).append(f)
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
