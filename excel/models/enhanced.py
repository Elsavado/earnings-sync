"""Enhanced models: rebuild SEC company models with model-specific logic (variants.py) and verify them.

    python -m models.enhanced test <kind> <sample size>     # random companies, verify only, print counts

kind: three (Excel Models), or an Enterprise kind (integrated, valuation, buyout, budget, credit, strategic).

Each model is recalculated in LibreOffice and must have no formula errors, all checks at zero, no
external links and no typed-in figures outside the input sheets - the same gate as main.Run.verify.
Logs carry counts only (the repository is public).
"""
import collections
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

import requests

from . import links, lo, three_x, unique
from .enterprise import references_ok
from .xl import INPUT_SHEETS
from .xlsxml import Package

SEC_UA = os.environ.get('SEC_USER_AGENT') or 'ExcelModels research contact@example.com'


def verify(wb, path, allowed=()):
    hard = [(ws.title, c.coordinate) for ws in wb.worksheets if ws.title not in INPUT_SHEETS and ws.title not in allowed
            for row in ws.iter_rows() for c in row if isinstance(c.value, (int, float)) and not isinstance(c.value, bool)]
    if hard:
        return None, 'hard-coded numbers outside inputs'
    wb.save(path)
    out = lo.convert([path], path.parent / 'recalc', 'xlsx').get(str(path))
    if not out:
        return None, 'recalculation failed'
    errors, formulas, values = lo.recalculated_errors(out)
    if errors:
        return None, 'formula errors'
    try:
        total = float(values.get('Checks!B3'))
    except (TypeError, ValueError):
        return None, 'checks not computed'
    if abs(total) > 0.01:
        return None, 'checks fail'
    empty = lo.empty_parts(out)
    if empty:
        return None, f'empty content: {empty[0]}'
    pkg = Package(out)
    links.clean(pkg)
    if links.has_external(pkg):
        return None, 'external link'
    if pkg.broken_parts():
        return None, 'invalid XML'
    pkg.save(out)
    return out, None


def finish(wb, key):
    mapping = unique.apply(wb, getattr(wb, 'profile', None) or unique.Profile(key))
    references_ok(wb)
    return {mapping.get(n, n) for n in INPUT_SHEETS}


ENT_KINDS = ('integrated', 'valuation', 'buyout', 'budget', 'credit', 'strategic')
_MARKET = []


def market():
    if not _MARKET:
        from .market import Market
        _MARKET.append(Market(lambda *a: None))
    return _MARKET[0]


def make(kind, facts, sector, sic, key):
    """(workbook, the variant behind it) or (None, None) when the company does not suit the model type."""
    if kind == 'three':
        wb = three_x.build(facts, sector, key, is_reit=str(sic) == '6798')
        return wb, getattr(wb, 'variant', None)
    from . import bankent, enterprise
    prof = unique.Profile(key)
    if kind in bankent.KINDS:
        wb = bankent.build(facts, sector, market(), sic, kind, 0, profile=prof)
    else:
        wb = enterprise.build(facts, sector, market(), sic, kind, 0, profile=prof)
    if wb is not None:
        wb.profile = prof
    return wb, getattr(wb, 'variant', None)


def is_bank(sic):
    try:
        return 6020 <= int(sic or 0) <= 6199
    except ValueError:
        return False


def company(s, cik, want=None):
    """want(sic) -> bool skips companies of other industries before their financial data is fetched."""
    sub = s.get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json', timeout=60)
    time.sleep(0.12)
    if want and sub.ok and not want(sub.json().get('sic')):
        return None
    facts = s.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json', timeout=120)
    time.sleep(0.12)
    if not (sub.ok and facts.ok):
        return None
    sub = sub.json()
    return facts.json(), (sub.get('sicDescription') or 'Unclassified').title(), sub.get('sic') or ''


def test_gov(kind, size):
    """Government models: random entities of the type (countries, US states and counties, projects)."""
    from . import govent
    s = requests.Session()
    s.headers['User-Agent'] = SEC_UA
    ents = govent.load(kind, s, lambda *a: None)
    random.Random(int(os.environ.get('SEED', '7'))).shuffle(ents)
    tally, methods, tmp = collections.Counter(), collections.Counter(), Path(tempfile.mkdtemp())
    keep = Path(os.environ.get('SAMPLES', 'samples'))
    keep.mkdir(exist_ok=True)
    for eid, ent in ents[:size]:
        key = f'gov:{eid}:{kind}'
        try:
            prof = unique.Profile(key)
            wb = govent.build(kind, ent, market(), profile=prof)
            wb.profile = prof
        except Exception as err:  # noqa: BLE001
            tally[f'build error {type(err).__name__}'] += 1
            print('BUILD', type(err).__name__, str(err)[:160], flush=True)
            continue
        tally['built'] += 1
        variant = wb.variant
        for b, m in variant.methods.items():
            methods[f'{b}={m}'] += 1
        work = tmp / f'm{tally["built"]}'
        work.mkdir()
        try:
            out, why = verify(wb, work / 'model.xlsx', finish(wb, key))
        except Exception as err:  # noqa: BLE001
            out, why = None, f'finish error {type(err).__name__}: {err}'[:120]
        if out:
            tally['PASSED'] += 1
            if tally['PASSED'] <= 3:
                shutil.copy(out, keep / f'sample_{tally["PASSED"]}.xlsx')
        else:
            tally[f'failed: {why}'] += 1
            print('FAIL', why, '|', ' '.join(f'{k}={v}' for k, v in variant.methods.items()), flush=True)
        shutil.rmtree(work, ignore_errors=True)
    print(chr(10).join(f'{k}: {v}' for k, v in sorted(tally.items())))
    print('methods used:', dict(sorted(methods.items())))
    return 0 if tally['PASSED'] == tally['built'] else 1


def test(kind, size):
    if kind.startswith('gov_'):
        return test_gov(kind, size)
    s = requests.Session()
    s.headers['User-Agent'] = SEC_UA
    tickers = s.get('https://www.sec.gov/files/company_tickers.json', timeout=60).json()
    ciks = sorted({v['cik_str'] for v in tickers.values()})
    random.Random(int(os.environ.get('SEED', '7'))).shuffle(ciks)
    tally, methods, tmp = collections.Counter(), collections.Counter(), Path(tempfile.mkdtemp())
    keep = Path(os.environ.get('SAMPLES', 'samples'))
    keep.mkdir(exist_ok=True)
    for cik in ciks:
        if tally['built'] >= size:
            break
        got = company(s, cik, is_bank if kind.startswith('bank_') else None)
        if not got:
            continue
        facts, sector, sic = got
        key = f'sec:{cik}:{kind}'
        try:
            wb, variant = make(kind, facts, sector, sic, key)
        except Exception as err:  # noqa: BLE001
            tally[f'build error {type(err).__name__}'] += 1
            print('BUILD', type(err).__name__, str(err)[:160], flush=True)
            continue
        if wb is None:
            tally['skipped (thin data)'] += 1
            continue
        tally['built'] += 1
        for b, m in variant.methods.items():
            methods[f'{b}={m}'] += 1
        work = tmp / f'm{tally["built"]}'
        work.mkdir()
        try:
            allowed = finish(wb, key)
            out, why = verify(wb, work / 'model.xlsx', allowed)
        except Exception as err:  # noqa: BLE001
            out, why = None, f'finish error {type(err).__name__}: {err}'[:120]
        if out:
            tally['PASSED'] += 1
            if tally['PASSED'] <= 3:
                shutil.copy(out, keep / f'sample_{tally["PASSED"]}.xlsx')
        else:
            tally[f'failed: {why}'] += 1
            # keep failing variants (methods only, no company) so they can be fixed
            print('FAIL', why, '|', ' '.join(f'{k}={v}' for k, v in variant.methods.items()), '|', ','.join(sorted(variant.modules)), flush=True)
        shutil.rmtree(work, ignore_errors=True)
    print('\n'.join(f'{k}: {v}' for k, v in sorted(tally.items())))
    print('methods used:', dict(sorted(methods.items())))
    return 0 if tally['PASSED'] == tally['built'] else 1


if __name__ == '__main__':
    if sys.argv[1] == 'test':
        sys.exit(test(sys.argv[2], int(sys.argv[3])))
