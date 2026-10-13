"""One collection run: refresh sources, process scraped spreadsheets, build SEC company models,
verify every file, number it and upload it to Drive in folders of twenty.

Environment: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN (Drive),
SEC_USER_AGENT (SEC fair-access contact), GITHUB_TOKEN (GitHub API), RUN_MINUTES (budget),
DRY_RUN=true (build and verify, no uploads), LOCAL_COPY_DIR (copies of models 1-100).
"""
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

import requests
from openpyxl.workbook import Workbook  # noqa: F401  (import check)

from . import bank, dcf, fpa, lbo, links, lo, sources, three
from .anonymize import Anonymizer
from .market import Market
from .process import process
from .store import Store, folder_name
from .xl import INPUT_SHEETS
from .xlsxml import Package

START = time.time()
BUDGET = float(os.environ.get('RUN_MINUTES', '50')) * 60
DRY = os.environ.get('DRY_RUN', '').lower() == 'true'
LOCAL = os.environ.get('LOCAL_COPY_DIR', 'first100')
SEC_UA = os.environ.get('SEC_USER_AGENT') or 'ExcelModels research contact@example.com'
BANK_SIC = set(range(6020, 6037)) | {6111, 6141, 6153, 6159, 6162, 6172, 6199}
TYPE_LABEL = {'three': 'Three-statement model', 'reit': 'Industry-specific model - REIT', 'bank': 'Industry-specific model - Bank',
              'dcf': 'DCF valuation model', 'lbo': 'LBO model', 'fpa': 'Operating & FP&A model'}


FILE_SECONDS = 180  # hard limit for processing one downloaded spreadsheet
ANON = None  # set before the worker pool forks, so workers inherit the loaded name lists


def _process_one(args):
    src, name, work = args
    res = process(src, name, work, ANON)
    return res.__dict__


class Worker:
    """Runs process() in a child process so a pathological file can be killed."""

    def __init__(self):
        self.pool = multiprocessing.get_context('fork').Pool(1)

    def run(self, args):
        try:
            return self.pool.apply_async(_process_one, (args,)).get(timeout=FILE_SECONDS)
        except multiprocessing.TimeoutError:
            self.pool.terminate()
            os.system('pkill -9 -f soffice >/dev/null 2>&1')
            self.pool = multiprocessing.get_context('fork').Pool(1)
            return {'ok': False, 'reason': f'processing took longer than {FILE_SECONDS}s'}

    def close(self):
        self.pool.terminate()


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def left():
    return BUDGET - (time.time() - START)


def clean_label(s, limit=90):
    s = re.sub(r'[\\/:*?"<>|]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:limit].strip().rstrip('.').strip()


class Run:
    def __init__(self):
        self.store = None if DRY and not os.environ.get('GOOGLE_REFRESH_TOKEN') else Store(dry_run=DRY)
        self.state = (self.store.load_state() if self.store else {}) or {}
        st = self.state
        for k, v in {'next': 1, 'seen': {}, 'queued': {}, 'queue': [], 'hashes': {}, 'sec': {'i': 0, 'done': {}}, 'counts': {}}.items():
            st.setdefault(k, v)
        if self.store and not DRY:
            st['next'] = max(st['next'], self.store.max_number() + 1)
        self.tmp = Path(tempfile.mkdtemp(prefix='xm_'))
        self.made = 0
        self.last_save = time.time()

    def save(self, force=False):
        if self.store and (force or time.time() - self.last_save > 300):
            self.store.save_state(self.state)
            self.last_save = time.time()

    def publish(self, path, label, ext, key, category, source):
        """Numbers, uploads and records one verified model file."""
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if digest in self.state['hashes']:
            self.state['seen'][key] = 'rej:duplicate'
            return None
        n = self.state['next']
        name = self.store.upload(str(path), n, clean_label(label), ext, key, category) if self.store else f'{n} - {label}.{ext}'
        self.state['next'] = n + 1
        self.state['hashes'][digest] = n
        self.state['seen'][key] = f'ok:{n}'
        c = self.state['counts']
        c[category] = c.get(category, 0) + 1
        c[f'source:{source}'] = c.get(f'source:{source}', 0) + 1
        self.made += 1
        if n <= 100:
            dest = Path(LOCAL) / folder_name(n)
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy(path, dest / name)
        log(f'  #{n} {name}')
        self.save()
        return n

    # --- scraped spreadsheets ------------------------------------------------------
    def scraped(self, until):
        s = sources.session()
        q = self.state['queue']
        done = 0
        worker = Worker()
        while q and time.time() < until:
            cand = q.pop(0)
            self.state['queued'].pop(cand['key'], None)
            if cand['key'] in self.state['seen']:
                continue
            work = self.tmp / f'c{done}'
            work.mkdir()
            try:
                r = s.get(cand['url'], timeout=90, stream=True)
                if not r.ok:
                    self.state['seen'][cand['key']] = f'rej:http {r.status_code}'
                    continue
                src = work / 'download.bin'
                size = 0
                t0 = time.time()
                with open(src, 'wb') as f:
                    for chunk in r.iter_content(1 << 16):
                        size += len(chunk)
                        if size > 40 * 1024 * 1024 or time.time() - t0 > 90:
                            break
                        f.write(chunk)
                r.close()
                raw_hash = hashlib.sha256(src.read_bytes()).hexdigest()
                if f'raw:{raw_hash}' in self.state['seen']:
                    self.state['seen'][cand['key']] = 'rej:duplicate download'
                    continue
                self.state['seen'][f'raw:{raw_hash}'] = 1
                res = worker.run((str(src), cand['name'], str(work)))
                if not res.get('ok'):
                    self.state['seen'][cand['key']] = f'rej:{res.get("reason")}'[:120]
                    log(f'  - {cand["source"]}: {cand["name"][:60]}: {res.get("reason")}')
                    continue
                title, cat = res['title'], res['category']
                self.publish(res['path'], f'{cat} - {title}' if title != cat else cat, res['ext'], cand['key'], cat, cand['source'])
            except Exception as err:  # noqa: BLE001
                self.state['seen'][cand['key']] = f'rej:error {type(err).__name__}'
                log(f'  ! {cand["name"][:60]}: {type(err).__name__}: {err}')
            finally:
                shutil.rmtree(work, ignore_errors=True)
                done += 1
        worker.close()
        log(f'scraped: processed {done}, {len(q)} still queued')

    # --- SEC company models ------------------------------------------------------------
    def verify(self, wb, path):
        """Saves, recalculates in LibreOffice and checks a generated model. Returns the recalculated file or None."""
        hard = [(ws.title, c.coordinate) for ws in wb.worksheets if ws.title not in INPUT_SHEETS
                for row in ws.iter_rows() for c in row if isinstance(c.value, (int, float)) and not isinstance(c.value, bool)]
        if hard:
            return None, f'hard-coded numbers outside inputs: {hard[:3]}'
        wb.save(path)
        out = lo.convert([path], path.parent / 'recalc', 'xlsx').get(str(path))
        if not out:
            return None, 'recalculation failed'
        errors, formulas, values = lo.recalculated_errors(out)
        if errors:
            return None, f'formula errors {errors}'
        try:
            total = float(values.get('Checks!B3'))
        except (TypeError, ValueError):
            return None, 'checks not computed'
        if abs(total) > 0.01:
            return None, f'checks fail ({total})'
        # Safety net: nothing in a delivered model may point outside the workbook.
        pkg = Package(out)
        links.clean(pkg)
        if links.has_external(pkg):
            return None, 'external link could not be removed'
        if pkg.broken_parts():
            return None, f'invalid XML in {pkg.broken_parts()[0]}'
        pkg.save(out)
        from openpyxl import load_workbook
        try:
            load_workbook(out).close()
        except Exception as err:  # noqa: BLE001
            return None, f'file does not open ({type(err).__name__})'
        return out, None

    def sec(self, until):
        s = requests.Session()
        s.headers['User-Agent'] = SEC_UA
        st = self.state['sec']
        if 'companies' not in st or st.get('listed_at', 0) < time.time() - 7 * 86400 and st['i'] >= len(st['companies']):
            data = s.get('https://www.sec.gov/files/company_tickers.json', timeout=60).json()
            ciks, seen = [], set()
            for v in data.values():
                if v['cik_str'] not in seen:
                    seen.add(v['cik_str'])
                    ciks.append(v['cik_str'])
            st['companies'], st['i'], st['listed_at'] = ciks, 0, time.time()
        while st['i'] < len(st['companies']) and time.time() < until:
            cik = st['companies'][st['i']]
            st['i'] += 1
            done = set(st['done'].get(str(cik), []))
            try:
                sub = s.get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json', timeout=60)
                time.sleep(0.12)
                facts = s.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json', timeout=120)
                time.sleep(0.12)
                if not (sub.ok and facts.ok):
                    continue
                sub, facts = sub.json(), facts.json()
            except (requests.RequestException, ValueError):
                continue
            sic = sub.get('sic') or ''
            sector = (sub.get('sicDescription') or 'Unclassified').title()
            try:
                sic_i = int(sic)
            except ValueError:
                sic_i = 0
            plan = []
            if sic_i in BANK_SIC:
                plan.append(('bank', lambda: bank.build(facts, sector, self.market, sic)))
            else:
                plan.append(('reit' if sic_i == 6798 else 'three', lambda: three.build(facts, sector, is_reit=sic_i == 6798)))
            plan += [('dcf', lambda: dcf.build(facts, sector, self.market, sic)),
                     ('lbo', lambda: lbo.build(facts, sector, self.market, sic)),
                     ('fpa', lambda: fpa.build(facts, sector))]
            for kind, make in plan:
                if kind in done or time.time() > until:
                    continue
                key = f'sec:{cik}:{kind}'
                try:
                    wb = make()
                except Exception as err:  # noqa: BLE001
                    log(f'  ! CIK {cik} {kind}: {type(err).__name__}: {err}')
                    traceback.print_exc(limit=2)
                    wb = None
                done.add(kind)
                if wb is None:
                    continue
                work = self.tmp / f'sec_{cik}_{kind}'
                work.mkdir()
                try:
                    out, why = self.verify(wb, work / 'model.xlsx')
                    if not out:
                        self.state['seen'][key] = f'rej:{why}'[:160]
                        log(f'  - CIK {cik} {kind}: {why}')
                        continue
                    self.publish(out, f'{TYPE_LABEL[kind]} - {sector}', 'xlsx', key, TYPE_LABEL[kind].split(' - ')[0], 'sec')
                finally:
                    shutil.rmtree(work, ignore_errors=True)
            st['done'][str(cik)] = sorted(done)
        log(f'sec: company {st["i"]}/{len(st["companies"])}')

    def go(self):
        log(f'start: next model number {self.state["next"]}, {len(self.state["queue"])} candidates queued')
        if self.store:
            used, limit = self.store.quota()
            log(f'Drive: {used / 2**30:.1f} GB used of {limit / 2**30:.1f} GB')
            if limit and limit - used < 2 * 2**30:
                log('Drive has less than 2 GB free; stopping')
                return
        self.market = Market(log)
        log(f'market: rf {self.market.rf:.2%}, ERP {self.market.erp:.2%}, SOFR {self.market.sofr:.2%}, {len(self.market.betas)} industry betas')
        tickers = requests.get('https://www.sec.gov/files/company_tickers.json', headers={'User-Agent': SEC_UA}, timeout=60).json()
        names = [v['title'] for v in tickers.values()]
        companies_json = None
        cj = Path(__file__).resolve().parents[2] / 'companies.json'
        if cj.exists():
            companies_json = json.loads(cj.read_text(encoding='utf-8'))
            for c in companies_json.get('companies', []):
                names += [c.get('name', '')] + list(c.get('aliases') or [])
        try:
            import spacy
            nlp = spacy.load('en_core_web_sm', exclude=['parser', 'lemmatizer', 'attribute_ruler', 'tagger', 'senter'])
        except Exception:  # noqa: BLE001
            nlp = None
        global ANON
        self.anonymizer = ANON = Anonymizer(names, [v['title'] for v in list(tickers.values())[:1500]], nlp)
        log(f'anonymizer: {len(self.anonymizer.multi)} multi-word and {len(self.anonymizer.single)} one-word company names')

        s = sources.session()
        refresh_until = time.time() + min(0.3 * left(), 16 * 60)
        for name, fn in [('github', lambda: sources.github(self.state, s, log)),
                         ('damodaran', lambda: sources.damodaran(self.state, s, log)),
                         ('zenodo', lambda: sources.zenodo(self.state, s, log, max_pages=6)),
                         ('websites', lambda: sources.websites(self.state, s, log, companies_json,
                                                               minutes=max(1, (refresh_until - time.time()) / 60)))]:
            if time.time() > refresh_until:
                break
            try:
                fn()
            except Exception as err:  # noqa: BLE001
                log(f'{name}: failed ({type(err).__name__}: {err})')
        self.save(force=True)
        # Split the rest of the run between scraped files and SEC models.
        self.scraped(time.time() + 0.45 * left())
        self.save(force=True)
        self.sec(time.time() + left() - 60)
        self.save(force=True)
        c = self.state['counts']
        log(f'done: {self.made} models this run; next number {self.state["next"]}; totals {json.dumps(c, sort_keys=True)}')
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a', encoding='utf-8') as f:
                f.write(f'## Excel models\n\n{self.made} models this run, {self.state["next"] - 1} in total.\n\n| Category / source | Count |\n|---|---|\n')
                for k in sorted(c):
                    f.write(f'| {k} | {c[k]} |\n')


if __name__ == '__main__':
    code = 0
    try:
        if os.environ.get('RESET', '').lower() == 'true':
            Store().reset(log)
        Run().go()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)  # do not wait for website-crawler threads still finishing a request
