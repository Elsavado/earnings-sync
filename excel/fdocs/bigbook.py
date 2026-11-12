"""Large workbooks on Kaggle (user, 2026-11-12: "yes set kaggle notebooks").

The office collectors skip spreadsheets a GitHub runner cannot handle (over 8 MB, gigabytes once unpacked, or too
slow / out of memory in the 3 GB worker) and remember them in their state as state['big'] (main.Run.handle). This
pass sends them to a private Kaggle notebook (about 30 GB of memory, 12-hour sessions), which downloads, checks and
anonymises each one with the same code (main.process) and returns the finished files as notebook output; back on
the GitHub runner they are numbered and uploaded by the collector itself (main.Run.handle -> publish), so numbering,
duplicates and state stay in one place. Kaggle never holds any Drive sign-in.

  python -m fdocs.bigbook sync                   (GitHub, first step of a collector run) bring back the finished
                                                  Kaggle job and upload its files; send the next PER_JOB workbooks
  python -m fdocs.bigbook kernel JOB.json OUT    (Kaggle) process them into OUT/ (+ OUT/results.json)
Needs KAGGLE_API_TOKEN and KAGGLE_USERNAME; without them the step does nothing.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LIMITS = {'xlsx_mb': 150, 'unpacked_gb': 6, 'seconds': 1800}


def log(msg):
    print(time.strftime('[%H:%M:%S] ') + msg, flush=True)


def kernel(job_path, out):
    """On Kaggle: big limits, then main.process for each workbook, one at a time (all memory for one file)."""
    os.environ['BIG_PASS'] = '1'
    from . import main, office, tab
    office.MAX_SIZE['xlsx'] = LIMITS['xlsx_mb'] * 2**20
    tab.UNPACKED_MAX = LIMITS['unpacked_gb'] * 2**30
    main.DOWNLOAD_SECONDS['data'] = LIMITS['seconds']
    main.make_anon()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cands = json.loads(Path(job_path).read_text(encoding='utf-8'))['cands']
    results = []
    for i, cand in enumerate(cands):
        work = Path(tempfile.mkdtemp(prefix='big_'))
        t0 = time.time()
        try:
            res = main.process(cand, cand['kind'], str(work))
        except MemoryError:
            res = {'ok': False, 'reason': 'MemoryError even with 30 GB'}
        except Exception as err:  # noqa: BLE001
            res = {'ok': False, 'reason': f'error {type(err).__name__}: {str(err)[:80]}'}
        row = {'key': cand['key'], 'ok': bool(res.get('ok')), 'reason': res.get('reason'), 'raw': res.get('raw'),
               'label': res.get('label'), 'ext': res.get('ext'), 'sample': res.get('sample', ''),
               'subject': cand.get('subject')}
        if res.get('ok'):
            name = f'{i:04d}.{res["ext"]}'
            shutil.copy(res['path'], out / name)
            row['file'] = name
        results.append(row)
        log(f'{i + 1}/{len(cands)}: {"ok" if row["ok"] else row["reason"]} ({time.time() - t0:.0f}s)')
        shutil.rmtree(work, ignore_errors=True)
        (out / 'results.json').write_text(json.dumps(results), encoding='utf-8')


KAGGLE = [sys.executable, '-m', 'kaggle']
PER_JOB = 60


def _kaggle(*args, check=True):
    r = subprocess.run(KAGGLE + list(args), capture_output=True, text=True, timeout=600)
    if check and r.returncode:
        raise RuntimeError(f'kaggle {args[0]} {args[1]} failed: {(r.stderr or r.stdout)[-300:]}')
    return (r.stdout or '') + (r.stderr or '')


def _slug(main):
    app = os.environ.get('FD_APP', 'fin-docs')
    return f"big-workbooks-{app}-{main.STATE_NAME.replace('.json.gz', '')}".lower().replace('_', '-')[:50]


def _script(cands):
    env = {k: os.environ[k] for k in ('OFFICE_PROFILE', 'SEC_USER_AGENT', 'KINDS') if os.environ.get(k)}
    return f"""import json, os, subprocess, sys
JOB = json.loads({json.dumps(json.dumps({'cands': cands}))})
os.environ.update(json.loads({json.dumps(json.dumps(env))}))
subprocess.run(['git', 'clone', '-q', '--depth', '1', '{REPO}', '/tmp/es'], check=True)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', '/tmp/es/excel/requirements.txt'], check=True)
os.chdir('/tmp/es/excel')
sys.path.insert(0, '/tmp/es/excel')
open('/tmp/job.json', 'w').write(json.dumps(JOB))
from fdocs import bigbook
bigbook.kernel('/tmp/job.json', '/kaggle/working/out')
"""


REPO = 'https://github.com/Elsavado/earnings-sync'


def sync():
    """In a collector run, before collecting: bring back a finished Kaggle job, then send the next one."""
    if not os.environ.get('KAGGLE_API_TOKEN') or not os.environ.get('KAGGLE_USERNAME'):
        log('large workbooks: no Kaggle sign-in; skipped')
        return
    from . import main
    run = main.Run()
    st = run.state
    big, done = st.setdefault('big', {}), st.setdefault('big_done', {})
    ref = f"{os.environ['KAGGLE_USERNAME']}/{_slug(main)}"
    job = st.get('big_job')
    if job:
        status = _kaggle('kernels', 'status', ref, check=False).lower()
        if 'running' in status or 'queued' in status:
            log('large workbooks: Kaggle job still running')
            return
        if 'complete' in status:
            out = Path(tempfile.mkdtemp(prefix='bigout_'))
            _kaggle('kernels', 'output', ref, '-p', str(out), check=False)
            made = _import(run, {k: big[k] for k in job['keys'] if k in big}, out)
            log(f'large workbooks: {len(job["keys"])} back from Kaggle, {made} uploaded')
        else:
            log(f'large workbooks: Kaggle job ended without results ({status.strip()[-80:]}); its files are skipped')
        for k in job['keys']:
            done[k] = 1
        st.pop('big_job', None)
        run.save(force=True)
    todo = [c for k, c in big.items() if k not in done][:PER_JOB]
    if not todo:
        log(f'large workbooks: none waiting ({len(done)} done)')
        return
    d = Path(tempfile.mkdtemp(prefix='kernel_'))
    (d / 'script.py').write_text(_script(todo), encoding='utf-8')
    (d / 'kernel-metadata.json').write_text(json.dumps({
        'id': ref, 'title': _slug(main), 'code_file': 'script.py', 'language': 'python', 'kernel_type': 'script',
        'is_private': True, 'enable_gpu': False, 'enable_internet': True, 'dataset_sources': [],
        'competition_sources': [], 'kernel_sources': []}), encoding='utf-8')
    _kaggle('kernels', 'push', '-p', str(d))
    st['big_job'] = {'keys': [c['key'] for c in todo], 'at': time.time()}
    run.save(force=True)
    log(f'large workbooks: {len(todo)} sent to Kaggle ({len(big) - len(done) - len(todo)} more waiting)')


def _import(run, cands, out):
    res_file = next(Path(out).rglob('results.json'), None)
    if res_file is None:
        return 0
    base = res_file.parent
    made = 0
    for r in json.loads(res_file.read_text(encoding='utf-8')):
        cand = cands.get(r['key'])
        if not cand:
            continue
        cand = dict(cand)
        if r.get('subject'):
            cand['subject'] = r['subject']
        if r['ok']:
            r = dict(r, path=str(base / r['file']))
        before = sum(run.made.values())
        run.handle(cand['kind'], cand, r)
        made += sum(run.made.values()) - before
    return made


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'kernel':
        kernel(sys.argv[2], sys.argv[3])
    elif cmd == 'sync':
        try:
            sync()
        except Exception as err:  # noqa: BLE001  never stops the collector run
            log(f'large workbooks: {type(err).__name__}: {str(err)[:200]}')
    sys.stdout.flush()
    os._exit(0)
