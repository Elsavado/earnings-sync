"""Turns one downloaded spreadsheet into an accepted model file, or rejects it with a reason.

Pipeline: identify the real format -> convert legacy formats (.xls/.xlsb/templates) to .xlsx,
or .xlsm when there are macros -> break external links and drop web links -> reject broken
references -> classify -> rebuild hard-coded calculations as formulas -> require a real model
(enough formulas) -> anonymise -> recalculate in LibreOffice and reject #REF!/#NAME? or a
high error rate.
"""
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import classify, infer, links, lo, sheets
from .xl import REDACTED
from .xlsxml import Package

MIN_FORMULAS = 30
MIN_FORMULA_SHARE = 0.40
LARGE_MODEL_FORMULAS = 150  # full models with big input/data tables pass on formula count
MAX_ERROR_SHARE = 0.03
MAX_BYTES = 40 * 1024 * 1024


@dataclass
class Result:
    ok: bool
    reason: str = ''
    path: str = ''
    ext: str = ''
    category: str = ''
    title: str = ''
    stats: dict = field(default_factory=dict)


def sniff(path):
    """Returns (format, has_macros) with format in xls/xlsx/xlsm/xlsb/template, or (None, False)."""
    with open(path, 'rb') as f:
        head = f.read(8)
    if head.startswith(b'\xd0\xcf\x11\xe0'):
        import olefile
        try:
            ole = olefile.OleFileIO(path)
            names = ['/'.join(s) for s in ole.listdir()]
            ole.close()
        except Exception:  # noqa: BLE001
            return None, False
        if any('EncryptedPackage' in n for n in names):
            return None, False
        if not any(n in ('Workbook', 'Book') for n in names):
            return None, False
        return 'xls', any('_VBA_PROJECT_CUR' in n for n in names)
    if head.startswith(b'PK'):
        try:
            with zipfile.ZipFile(path) as z:
                ct = z.read('[Content_Types].xml').decode('utf-8', 'replace')
                names = z.namelist()
        except Exception:  # noqa: BLE001
            return None, False
        macros = 'xl/vbaProject.bin' in names
        if 'xl/workbook.bin' in names:
            return 'xlsb', macros
        if 'template.main' in ct or 'template.macroEnabled' in ct:
            return 'template', macros
        if 'sheet.macroEnabled.main' in ct:
            return 'xlsm', True
        if 'spreadsheetml.sheet.main' in ct:
            return 'xlsx', macros
    return None, False


def nice_title(stem, anonymizer, category):
    # A file named after a ticker ('$META', 'AAPL', '£BOKU') would identify the company.
    if re.fullmatch(r'[$£€]?[A-Za-z]{1,6}([._\- ]?[A-Za-z]{1,3})?', stem.strip()) or re.match(r'^[$£€]', stem.strip()):
        return category
    t = re.sub(r'[_\-.]+', ' ', stem)
    t = re.sub(r'\b(v|ver|version|rev)\s?\d+(\s?\d+)*\b|\b(final|copy|draft|new|old)\b|\(\d+\)', ' ', t, flags=re.I)
    t = re.sub(r'\b(19|20)\d{2}[01]\d[0-3]\d\b', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    t = anonymizer.text(t)
    t = re.sub(r'[\\/:*?"<>|#%]+', ' ', t).strip()
    if len(t) < 3 or not re.search(r'[A-Za-z]{3}', t):
        t = category
    if t.isupper() or t.islower():
        t = t.title().replace(REDACTED.title(), REDACTED)
    return t[:70].strip()


def process(src, filename, workdir, anonymizer):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if Path(src).stat().st_size > MAX_BYTES:
        return Result(False, 'too large')
    fmt, macros = sniff(src)
    if not fmt:
        return Result(False, 'not a readable Excel workbook (or encrypted)')
    ext = 'xlsm' if macros else 'xlsx'
    path = Path(src)
    if fmt in ('xls', 'xlsb', 'template'):
        conv = lo.convert([path], workdir / 'conv', ext, timeout=120).get(str(path))
        if not conv:
            return Result(False, f'{fmt} conversion failed')
        path = Path(conv)
        if ext == 'xlsm':
            with zipfile.ZipFile(path) as z:
                if 'xl/vbaProject.bin' not in z.namelist():
                    ext = 'xlsx'  # macros could not be carried over; save as a plain workbook
                    conv = lo.convert([path], workdir / 'conv2', 'xlsx', timeout=120).get(str(path))
                    if not conv:
                        return Result(False, 'conversion failed')
                    path = Path(conv)
    try:
        pkg = Package(path)
    except Exception as err:  # noqa: BLE001
        return Result(False, f'unreadable package ({type(err).__name__})')
    if not pkg.sheets:
        return Result(False, 'no worksheets')
    try:
        link_stats = links.clean(pkg)
    except links.Reject as err:
        return Result(False, f'broken or external references: {err}')
    # Every delivered tab must have content: blank and title-only placeholder tabs are removed.
    dropped = sheets.drop_empty(pkg)

    texts = pkg.texts()
    category, scores = classify.classify(Path(filename).stem, [n for n, _ in pkg.sheets], texts)
    if not category:
        return Result(False, 'not a financial model', stats={'scores': scores})

    added, n_formulas, n_constants = infer.infer(pkg)
    share = n_formulas / max(1, n_formulas + n_constants)
    stats = {'formulas': n_formulas, 'constants': n_constants, 'inferred': added, 'formula_share': round(share, 3),
             'empty_tabs_removed': dropped, **link_stats}
    if n_formulas < MIN_FORMULAS or (share < MIN_FORMULA_SHARE and n_formulas < LARGE_MODEL_FORMULAS):
        return Result(False, f'mostly hard-coded ({n_formulas} formulas, {share:.0%} of numbers)', stats=stats)

    anonymizer.package(pkg)
    if links.has_external(pkg):
        return Result(False, 'external references remain', stats=stats)
    broken = pkg.broken_parts()
    if broken:
        return Result(False, f'internal error: invalid XML in {broken[0]}', stats=stats)
    out = workdir / f'clean.{ext}'
    pkg.save(out)
    try:
        from openpyxl import load_workbook
        load_workbook(out, read_only=False, keep_vba=ext == 'xlsm').close()
    except Exception as err:  # noqa: BLE001
        return Result(False, f'cleaned file does not open ({type(err).__name__})', stats=stats)

    recalc = lo.convert([out], workdir / 'recalc', 'xlsx', timeout=120).get(str(out))
    if not recalc:
        return Result(False, 'LibreOffice could not open the cleaned file', stats=stats)
    errors, formulas_after, _ = lo.recalculated_errors(recalc)
    stats['errors'] = errors
    broken = sum(v for k, v in errors.items() if k.startswith('#REF') or k.startswith('#NAME') or k.startswith('Err:'))
    if broken:
        return Result(False, f'broken references after recalculation ({broken})', stats=stats)
    if sum(errors.values()) > MAX_ERROR_SHARE * max(1, formulas_after):
        return Result(False, f'too many formula errors ({sum(errors.values())})', stats=stats)
    return Result(True, path=str(out), ext=ext, category=category, title=nice_title(Path(filename).stem, anonymizer, category), stats=stats)
