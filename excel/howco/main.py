"""One run of the "How Companies Work" collector for one source (SOURCE = enron | atlas | stocks | edu | sec).

Environment: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN (Drive), SHARED_DRIVE_ID,
SEC_USER_AGENT, RUN_MINUTES (budget), DRY_RUN=true (nothing published: a few samples and a leak report go to the
private folder instead), HOWCO_ANON=false (nothing anonymised: real people, companies and wording). Never exits with an error for a source problem (the user wants no failure e-mails):
problems are logged and the run ends normally; the state saved so far carries over to the next run.
"""
import importlib
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

import requests

from .anon import Anon, Plain
from .drive import Drive
from .people import key_material

START = time.time()
SOURCE = os.environ.get('SOURCE', '')
DRY = os.environ.get('DRY_RUN', '').lower() == 'true'
BUDGET = float(os.environ.get('RUN_MINUTES', '300')) * 60
PLAIN = os.environ.get('HOWCO_ANON', '').lower() == 'false'  # user, 2026-10-29: collect without anonymising
SEC_UA = os.environ.get('SEC_USER_AGENT') or 'research contact@example.com'
NEW_DATA_CAP = 1.25 * 2**40  # never more than ~1.25 TB of new data (user: keep 300 GB of the 2 TB pool free)
FREE_FLOOR = 300 * 2**30
FOLDERS = {'enron': 'Energy Trading Company Corpus', 'atlas': 'ATLAS Finance (simulated firms)',
           'stocks': 'Open Stock Reports', 'edu': 'Equity Research (.edu)', 'sec': 'Banker Board Decks (SEC)',
           'fcic': 'Financial Crisis Inquiry Commission', 'lehman': 'Investment Bank Bankruptcy Examiner',
           'senate': 'Senate Investigation Exhibits', 'antitrust': 'Antitrust Trial Exhibits'}


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


class Ctx:
    def __init__(self, source):
        self.source = source
        self.folder = FOLDERS[source]
        self.drive = Drive(source, DRY)
        self.dry = DRY
        self.state_name = f'state-{source}{"-dry" if DRY else ""}.json.gz'
        self.state = self.drive.load(self.state_name)
        self.work = Path(tempfile.mkdtemp(prefix=f'howco_{source}_'))
        self.anon = None
        self.samples = 0
        self.leak_report = []
        self.possible_report = []  # spaCy: people that may be left (dry runs)

    def left(self):
        return BUDGET - (time.time() - START)

    def save(self):
        self.state['bytes'] = self.state.get('bytes', 0) + self.drive.sent_bytes
        self.state['items'] = self.state.get('items', 0) + self.drive.sent_items
        by = self.state.setdefault('by_drive', {})
        by[self.drive.target] = by.get(self.drive.target, 0) + self.drive.sent_items
        self.drive.sent_bytes = self.drive.sent_items = 0
        self.drive.save(self.state_name, self.state)
        if self.anon:
            self.drive.save(f'names-{self.source}.json.gz', {'people': self.anon.pp.own, 'companies': self.anon.co.own,
                                                                    'tickers': self.anon.co.tick_own})

    def make_anon(self):
        """People and company maps of every source, so a name in use is never given to someone else."""
        pmaps, cmaps, tmaps, own = [], [], [], {'people': {}, 'companies': {}, 'tickers': {}}
        for n in self.drive.private_names():
            if n.startswith('names-') and n.endswith('.json.gz'):
                m = self.drive.load(n)
                if n == f'names-{self.source}.json.gz':
                    own = m
                else:
                    pmaps.append(m.get('people', {}))
                    cmaps.append(m.get('companies', {}))
                    tmaps.append(m.get('tickers', {}))
        s = requests.Session()
        s.headers['User-Agent'] = SEC_UA
        t = s.get('https://www.sec.gov/files/company_tickers.json', timeout=60).json()
        names = [v['title'] for v in t.values()]
        self.anon = Anon(pmaps, own.setdefault('people', {}), cmaps, own.setdefault('companies', {}), key_material(),
                         names, names[:1500], {v['ticker']: v['title'] for v in t.values()}, tmaps, own.setdefault('tickers', {}))
        self.anon.check_ner = self.dry
        if PLAIN:
            log('not anonymised (HOWCO_ANON=false): real names and wording are kept')
            plain, self.anon = Plain(self.anon), None  # no name maps to save
            return plain
        log(f'names: {len(self.anon.pp.map)} people and {len(self.anon.co.map)} companies known; '
            f'{len(self.anon.co.multi)} multi-word and {len(self.anon.co.single)} one-word company names to match')
        return self.anon

    def sample(self, local, name, leaks=()):
        """Dry run: keeps up to 40 processed files in the private folder for checking, with what leaked."""
        self.note(name, leaks)
        if not self.dry or self.samples >= 40:
            return
        self.samples += 1
        from googleapiclient.http import MediaFileUpload
        from models.store import _retry
        parent = self.drive.folder(self.drive.private, f'Dry run samples - {self.source}', create=True)
        media = MediaFileUpload(str(local), resumable=False)
        _retry(lambda: self.drive.drive.files().create(body={'name': name[:200], 'parents': [parent]},
                                                       media_body=media, fields='id').execute())

    def note(self, name, leaks, context=None):
        """Records what a file still contains: real names the rules replaced elsewhere, and possible people."""
        real = sorted({x for x in leaks if not x.startswith('possible')})
        poss = sorted({x[len('possible person: '):] for x in leaks if x.startswith('possible')})
        if real:
            self.leak_report.append(f'{name}: ' + (context(real) if context else ', '.join(real[:10])))
        if poss:
            self.possible_report.append(f'{name}: ' + ', '.join(poss[:12]))
        return bool(real)

    def finish(self):
        if self.dry:
            rep = self.work / 'leak-report.txt'
            rep.write_text('LEAKS (real names left)\n' + ('\n'.join(self.leak_report) or 'none')
                           + '\n\nPOSSIBLE PEOPLE (spaCy; check by hand)\n' + ('\n'.join(self.possible_report) or 'none'),
                           encoding='utf-8')
            self.samples = 0
            self.sample(rep, 'leak-report.txt')
        log(f'leak check: {len(self.leak_report)} file(s) with a real name left; '
            f'{len(self.possible_report)} file(s) with a possible person (dry runs)')


def main():
    if SOURCE not in FOLDERS:
        log(f'unknown source {SOURCE!r}')
        return
    if not DRY and os.environ.get('LIVE', '').lower() != 'true':
        log('HOWCO_LIVE is not true: nothing to do')
        return
    ctx = Ctx(SOURCE)
    # Items per Shared Drive and new data, over every source.
    counts, new_bytes = {}, 0
    for n in ctx.drive.private_names():
        if n.startswith('state-') and not n.endswith('-dry.json.gz'):
            st = ctx.state if n == ctx.state_name else ctx.drive.load(n)
            new_bytes += int(st.get('bytes', 0))
            for d, k in st.get('by_drive', {}).items():
                counts[d] = counts.get(d, 0) + int(k)
    free = ctx.drive.free_bytes()
    log(f'items per drive: {counts or "none yet"}; new data so far {new_bytes / 2**30:.1f} GB'
        + (f'; storage pool free {free / 2**30:.0f} GB' if free is not None else ''))
    if not DRY and (new_bytes >= NEW_DATA_CAP or (free is not None and free < FREE_FLOOR)):
        log('storage limit reached (1.25 TB of new data, or under 300 GB free): nothing collected this run')
        return
    if not ctx.drive.choose(counts):
        log(f'every drive is at its item cap and a new Shared Drive could not be made '
            f'({ctx.drive.overflow.get("denied")}): nothing collected this run')
        return
    if ctx.drive.target != ctx.drive.top:
        log(f'content goes to overflow drive {ctx.drive.target}')
    if PLAIN and not DRY and not ctx.state.get('plain'):
        # The first run without anonymising: this source's made-up-name files go to the trash (kept 30 days) and
        # it collects again from the start, so the two versions never sit side by side.
        n = ctx.drive.trash_folder(ctx.folder)
        keep = {k: ctx.state[k] for k in ('bytes', 'items', 'by_drive') if k in ctx.state}  # trash still counts
        ctx.state.clear()
        ctx.state.update(keep, plain=True)
        ctx.save()
        log(f'anonymised version moved to the trash ({n} folder(s)); collecting again without anonymising')
    try:
        importlib.import_module(f'howco.src_{SOURCE}').run(ctx, log)
    except Exception:  # noqa: BLE001 - logged; the saved state carries over
        log('problem:\n' + traceback.format_exc()[-3000:])
    finally:
        try:
            ctx.save()
            ctx.finish()
        except Exception:  # noqa: BLE001
            log('could not save the state:\n' + traceback.format_exc()[-1500:])
    log(f'done in {(time.time() - START) / 60:.0f} min; this source has {ctx.state.get("items", 0):,} items, '
        f'{ctx.state.get("bytes", 0) / 2**30:.2f} GB on the drive')


if __name__ == '__main__':
    sys.exit(main())
