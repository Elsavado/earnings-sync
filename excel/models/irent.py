"""IR-enhanced enterprise models: a company's own investor-relations workbook (financial supplement, KPI book,
segment data, fact sheet) turned into a working forecast model that keeps the company's unique line items.

1. The workbook is converted, cleaned (external links, pictures, empty tabs), hard-coded totals are rebuilt as
   formulas (infer.py) and names are anonymised (company -> Redacted Company Name Inc, people -> Salvador Sekwa).
2. Every time-series block is found: a header row of periods (years, fiscal years, quarters or period-end dates, in
   either order) and the line items under it.
3. For each sheet with a series block, a forecast sheet links every historical value and projects it:
   - lines that are formulas in the company's own workbook (totals, margins, ratios) keep the same formula, so the
     company's structure carries into the forecast;
   - level lines grow at their own historical rate (capped, floored, fading to a long-term rate, plus the live
     scenario); quarterly lines grow on the same quarter of the previous year, keeping seasonality;
   - ratio lines (percentages, margins, per-share figures) hold their recent average.
4. Driver analysis, scenario manager, dashboard and checks are added. The company's own sheets are the input sheets.
"""
import datetime as dt
import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter, column_index_from_string
from openpyxl.worksheet.datavalidation import DataValidation

from . import classify, enterprise, images, infer, links, lo, sheets
from .process import MAX_BYTES, nice_title, sniff
from .xl import (BOLD, FC_FILL, BLUE_FILL, HEAD, INPUT, INPUT_FILL, NAVY, NOTE, NUM, PCT, Inputs, checks, cover)
from .xlsxml import Package

KINDS = {
    'ir_enhanced': 'IR-enhanced operating model',
}
KIND, LABEL = 'ir_enhanced', KINDS['ir_enhanced']
enterprise.KINDS.setdefault(KIND, LABEL)
MAX_SHEETS, MAX_ROWS, MAX_COLS = 6, 400, 80
FINANCIAL = re.compile(r'revenue|sales|income|ebitda|ebit\b|margin|assets|liabilit|equity|cash flow|segment|operating|'
                       r'earnings|expenses|volume|units|customers|subscribers|backlog|bookings|production|deposits|loans|premium',
                       re.I)
RATIO_LABEL = re.compile(r'%|margin|ratio|rate\b|yield|growth|per share|\bEPS\b|\bx\b|multiple|days|turnover|average price|'
                         r'per unit|per customer|\bARPU\b|basis points|bps', re.I)


# --- periods --------------------------------------------------------------------------------------------------------
def parse_period(v):
    """(year, quarter 0 for annual) or None."""
    if isinstance(v, (dt.datetime, dt.date)):
        return (v.year, 0)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (int(v), 0) if float(v).is_integer() and 1980 <= v <= 2040 else None
    if not isinstance(v, str):
        return None
    s = v.strip()
    if len(s) > 24 or re.search(r'\b(E|est|estimate|budget|plan|forecast|guidance|target)\b', s, re.I):
        return None
    m = re.fullmatch(r"(?:FY|CY|F)?\s*'?((?:19|20)\d{2})\s*(?:A|Actual|\(A\))?", s, re.I)
    if m:
        return (int(m.group(1)), 0)
    m = re.fullmatch(r"(?:FY|F)\s*'?(\d{2})\s*(?:A)?", s, re.I)
    if m:
        return (2000 + int(m.group(1)), 0)
    m = re.fullmatch(r"Q([1-4])\s*[-' ]?\s*(?:FY|CY|F)?\s*'?((?:19|20)?\d{2})", s, re.I) or \
        re.fullmatch(r"([1-4])Q\s*[-' ]?\s*(?:FY|CY)?\s*'?((?:19|20)?\d{2})", s, re.I)
    if m:
        y = int(m.group(2))
        return (y + 2000 if y < 100 else y, int(m.group(1)))
    m = re.fullmatch(r"(?:FY|CY)?\s*((?:19|20)\d{2})\s*[-/ ]?\s*Q([1-4])", s, re.I)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return None


def _order(p):
    return p[0] * 4 + max(p[1], 1) - 1 if p[1] else p[0]


def find_block(ws):
    """The largest period-header row and its series: (header row, [(col, period)], [series rows], frequency)."""
    best = None
    rows = min(ws.max_row, MAX_ROWS)
    cols = min(ws.max_column, MAX_COLS)
    grid = {}
    for row in ws.iter_rows(min_row=1, max_row=rows, max_col=cols):
        for c in row:
            if c.value is not None:
                grid[(c.row, c.column)] = c.value
    for r in range(1, rows + 1):
        found = [(cidx, parse_period(grid.get((r, cidx)))) for cidx in range(1, cols + 1)]
        found = [(cidx, p) for cidx, p in found if p]
        if len(found) < 3:
            continue
        freq = {bool(p[1]) for _, p in found}
        if len(freq) != 1:
            found = [x for x in found if bool(x[1][1]) == (sum(bool(p[1]) for _, p in found) * 2 > len(found))]
        keys = [_order(p) for _, p in found]
        if len(set(keys)) != len(keys) or len(found) < 3:
            continue
        if not (keys == sorted(keys) or keys == sorted(keys, reverse=True)):
            continue
        first_col = min(cidx for cidx, _ in found)
        series = []
        for rr in range(r + 1, rows + 1):
            if any(parse_period(grid.get((rr, cidx))) for cidx, _ in found[:3]):
                break  # next header row
            label = next((grid[(rr, cc)] for cc in range(1, first_col) if isinstance(grid.get((rr, cc)), str)
                          and grid[(rr, cc)].strip()), None)
            vals = [grid.get((rr, cidx)) for cidx, _ in found]
            num = [v for v in vals if (isinstance(v, (int, float)) and not isinstance(v, bool)) or
                   (isinstance(v, str) and v.startswith('='))]
            if label and len(num) >= 3:
                series.append(rr)
        if series and (not best or len(series) * len(found) > len(best[2]) * len(best[1])):
            best = (r, found, series, 'Q' if found[0][1][1] else 'A')
    return best


# --- formulas -------------------------------------------------------------------------------------------------------
REF = re.compile(r"(?<![A-Za-z_!'\]])(\$?)([A-Z]{1,3})(\$?)(\d+)(?![\d(])")
SAFE_FUNCS = {'SUM', 'AVERAGE', 'IFERROR', 'ROUND', 'MIN', 'MAX', 'ABS', 'IF', 'SUBTOTAL'}


def translate(formula, src_col, row_map, dst_col):
    """The company's same-column formula (totals, ratios) rewritten for a forecast column, or None."""
    body = formula[1:]
    if '!' in body or '[' in body or '"' in body:
        return None
    funcs = set(re.findall(r'([A-Z][A-Z0-9.]*)\(', body))
    if funcs - SAFE_FUNCS:
        return None
    out, pos = [], 0
    for m in REF.finditer(body):
        if m.group(2) != src_col:
            return None
        row = int(m.group(4))
        if row not in row_map:
            return None
        out.append(body[pos:m.start()] + f'{dst_col}{row_map[row]}')
        pos = m.end()
    if not out:
        return None
    return '=' + ''.join(out) + body[pos:]


# --- build ------------------------------------------------------------------------------------------------------------
def _short(name, used):
    base = re.sub(r"[\\/*?:\[\]']", '', name)[:24].strip() or 'Sheet'
    t, k = f'F - {base}', 2
    while t in used:
        t, k = f'F - {base[:21]} {k}', k + 1
    used.add(t)
    return t


def _period_label(p, freq):
    return f'Q{p[1]} {p[0]}' if freq == 'Q' else f'FY{p[0]}'


def _next(p, freq, k):
    if freq == 'Q':
        idx = p[0] * 4 + p[1] - 1 + k
        return (idx // 4, idx % 4 + 1)
    return (p[0] + k, 0)


def scrub_sources(wb):
    """Source notes in the company's own sheets ("Source: Form 10-K") are blanked or their source words removed."""
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and not v.startswith('=') and enterprise.SOURCE_WORDS.search(v):
                    if re.match(r'\s*(source|note|\*|\(\d\)|\d\))', v, re.I) or len(v) > 60:
                        c.value = None
                    else:
                        c.value = re.sub(r'\s{2,}', ' ', enterprise.SOURCE_WORDS.sub('', v)).strip() or None
            if ws.title and enterprise.SOURCE_WORDS.search(ws.title):
                pass
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.comment is not None and enterprise.SOURCE_WORDS.search(c.comment.text or ''):
                    c.comment = None


def enhance(wb, category, title):
    originals = [ws.title for ws in wb.worksheets]
    blocks = []
    for ws in wb.worksheets:
        b = find_block(ws)
        if b and len(b[2]) >= 3:
            blocks.append((ws, b))
    blocks.sort(key=lambda x: -len(x[1][2]) * len(x[1][1]))
    blocks = blocks[:MAX_SHEETS]
    if sum(len(b[2]) for _, b in blocks) < 8:
        return None, 'fewer than 8 time series'
    si = Inputs(wb, 'Scenario Inputs', 'Forecast settings and scenarios')
    si.add('cap', 'Maximum starting growth per year', 0.30, PCT)
    si.add('floor', 'Minimum starting growth per year', -0.20, PCT)
    si.add('lt', 'Long-term growth reached by the final forecast period', 0.03, PCT)
    ws = si.ws
    r = si.next_row + 1
    ws.cell(row=r, column=1, value='Active scenario (1 = Base, 2 = Upside, 3 = Downside)').font = BOLD
    sel = ws.cell(row=r, column=2, value=1)
    sel.font, sel.fill, sel.number_format = INPUT, INPUT_FILL, '0'
    dv = DataValidation(type='list', formula1='"1,2,3"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(sel.coordinate)
    sel_ref = f"'Scenario Inputs'!$B${r}"
    ws.cell(row=r + 1, column=1, value='Active scenario name')
    ws.cell(row=r + 1, column=2, value=f'=CHOOSE({sel_ref},"Base","Upside","Downside")').font = BOLD
    for k, (lab, v) in enumerate((('Growth adjustment - Base', 0.0), ('Growth adjustment - Upside', 0.02),
                                  ('Growth adjustment - Downside', -0.03))):
        ws.cell(row=r + 3 + k, column=1, value=lab)
        c = ws.cell(row=r + 3 + k, column=2, value=v)
        c.font, c.fill, c.number_format = INPUT, INPUT_FILL, PCT
    ws.cell(row=r + 6, column=1, value='Live growth adjustment').font = BOLD
    ws.cell(row=r + 6, column=2, value=f'=CHOOSE({sel_ref},B{r + 3},B{r + 4},B{r + 5})').number_format = PCT
    adj, name_ref = f"'Scenario Inputs'!$B${r + 6}", f"'Scenario Inputs'!$B${r + 1}"
    cap, floor, lt = si.ref('cap'), si.ref('floor'), si.ref('lt')

    da = wb.create_sheet('Driver Analysis')
    da['A1'] = 'Growth drivers by line item (from each line\'s own history, with the live scenario)'
    da['A1'].font = Font(bold=True, size=13, color=NAVY)
    for k, h in enumerate(['Forecast sheet', 'Line item', 'Last actual', 'Historical growth', 'Starting driver', 'Method']):
        c = da.cell(row=3, column=1 + k, value=h)
        c.font, c.fill = HEAD, BLUE_FILL
    for letter, w in zip('ABCDEF', (24, 46, 14, 16, 14, 34)):
        da.column_dimensions[letter].width = w
    drow = 4
    used, sections, dash = set(originals) | {'Scenario Inputs', 'Driver Analysis'}, [], []
    struct_n = growth_n = ratio_n = 0
    for src, (hr, found, series, freq) in blocks:
        chron = sorted(found, key=lambda x: _order(x[1]))
        horizon = 8 if freq == 'Q' else 5
        fc_name = _short(src.title, used)
        fs = wb.create_sheet(fc_name)
        fs.sheet_view.showGridLines = False
        fs['A1'] = f'Forecast of {src.title}'
        fs['A1'].font = Font(bold=True, size=13, color=NAVY)
        fs['A2'] = 'Historical columns link to the company sheet; forecast columns are formulas (live scenario).'
        fs['A2'].font = NOTE
        fs.column_dimensions['A'].width = 50
        nh = len(chron)
        periods = [_period_label(p, freq) for _, p in chron] + [_period_label(_next(chron[-1][1], freq, k), freq)
                                                                for k in range(1, horizon + 1)]
        for j, p in enumerate(periods):
            c = fs.cell(row=3, column=2 + j, value=p)
            c.font, c.fill = HEAD, (FC_FILL if j >= nh else BLUE_FILL)
            fs.column_dimensions[get_column_letter(2 + j)].width = 13
        fs.freeze_panes = 'B4'
        first = series[0]
        row_map = {sr: 4 + sr - first for sr in range(first, series[-1] + 1)}
        last_src_col = get_column_letter(chron[-1][0])
        q = f"'{src.title}'"
        for sr in range(first, series[-1] + 1):
            fr = row_map[sr]
            first_col = min(cidx for cidx, _ in found)
            label = next((src.cell(row=sr, column=cc) for cc in range(1, first_col)
                          if isinstance(src.cell(row=sr, column=cc).value, str) and src.cell(row=sr, column=cc).value.strip()), None)
            if label is not None:
                fs.cell(row=fr, column=1, value=f"={q}!{label.coordinate}")
            if sr not in series:
                continue
            raw = [src.cell(row=sr, column=cidx).value for cidx, _ in chron]
            for j, (cidx, _) in enumerate(chron):
                if raw[j] is not None and not isinstance(raw[j], str) or (isinstance(raw[j], str) and raw[j].startswith('=')):
                    c = fs.cell(row=fr, column=2 + j, value=f"={q}!{get_column_letter(cidx)}{sr}")
                    c.number_format = src.cell(row=sr, column=cidx).number_format or NUM
            fmt = src.cell(row=sr, column=chron[-1][0]).number_format or NUM
            consts = [v for v in raw if isinstance(v, (int, float)) and not isinstance(v, bool)]
            is_ratio = ('%' in fmt) or (consts and all(abs(v) <= 1.5 for v in consts) and RATIO_LABEL.search(str(label.value if label else '')))
            last_val = src.cell(row=sr, column=chron[-1][0]).value
            hist = [get_column_letter(2 + j) for j in range(nh)]
            filled = [h for h, v in zip(hist, raw) if v is not None]
            struct = translate(last_val, last_src_col, row_map, 'X') if isinstance(last_val, str) and last_val.startswith('=') else None
            if struct:
                method = "Company formula carried forward"
                struct_n += 1
            elif is_ratio:
                method = 'Held at the recent average'
                ratio_n += 1
            else:
                method = 'Own growth rate' + (', same quarter last year' if freq == 'Q' else '')
                growth_n += 1
            da.cell(row=drow, column=1, value=fc_name)
            da.cell(row=drow, column=2, value=f"='{fc_name}'!A{fr}")
            lc = f"'{fc_name}'!{hist[-1]}{fr}"
            da.cell(row=drow, column=3, value=f'=N({lc})').number_format = fmt
            if not struct and not is_ratio:
                if freq == 'Q' and nh >= 8:
                    a, b = f"'{fc_name}'!{hist[-4]}{fr}:{hist[-1]}{fr}", f"'{fc_name}'!{hist[-8]}{fr}:{hist[-5]}{fr}"
                    g = f'=IFERROR(IF(AND(SUM({a})>0,SUM({b})>0),SUM({a})/SUM({b})-1,0),0)'
                else:
                    k = min(5, len(filled) - 1) if freq == 'A' else max(1, (min(8, len(filled)) - 1)) / 4
                    f0 = f"'{fc_name}'!{filled[-1 - int(k if freq == 'A' else min(8, len(filled)) - 1)]}{fr}"
                    g = f'=IFERROR(IF(AND({f0}>0,{lc}>0),({lc}/{f0})^(1/{k})-1,0),0)'
                da.cell(row=drow, column=4, value=g).number_format = PCT
                da.cell(row=drow, column=5, value=f'=MAX({floor},MIN({cap},D{drow}))+{adj}').number_format = PCT
            da.cell(row=drow, column=6, value=method)
            driver = f"'Driver Analysis'!$E${drow}"
            for t in range(1, horizon + 1):
                j = nh - 1 + t
                cl = get_column_letter(2 + j)
                if struct:
                    f = translate(last_val, last_src_col, row_map, cl)
                elif is_ratio:
                    avg = ','.join(f'{h}{fr}' for h in filled[-3:])
                    f = f'=AVERAGE({avg})' if t == 1 else f'={get_column_letter(1 + j)}{fr}'
                else:
                    step = t / 4 if freq == 'Q' else t
                    years = horizon / 4 if freq == 'Q' else horizon
                    g = f'({driver}+({lt}-{driver})*MIN(1,{step}/{years}))'
                    if freq == 'Q' and j - 4 >= 0:
                        f = f'={get_column_letter(2 + j - 4)}{fr}*(1+{g})'
                    else:
                        f = f'={get_column_letter(1 + j)}{fr}*(1+{g})' + ('^(1/4)' if freq == 'Q' else '')
                c = fs.cell(row=fr, column=2 + j, value=f)
                c.number_format = fmt
            if len(dash) < 8 and not is_ratio and not struct:
                dash.append((label.value if label else f'Line {fr}', fc_name, fr, nh, horizon))
            drow += 1
        sections.append((fc_name, f'Forecast of the company sheet "{src.title}" ({nh} {"quarters" if freq == "Q" else "years"} of history)'))
    if growth_n + struct_n < 5:
        return None, 'too few forecastable lines'

    db = Inputs(wb, 'Dashboard', 'Executive dashboard', index=0)
    db.section('Model')
    db.add('scen', 'Active scenario', f'={name_ref}', '@', formula=True)
    db.add('checks', 'Model integrity', '=IF(Checks!$B$3=0,"All checks pass","CHECK ERRORS")', '@', formula=True)
    db.add('lines', 'Line items forecast', f'=COUNTA(\'Driver Analysis\'!B4:B{drow - 1})', '0', formula=True)
    db.add('struct', 'Lines using the company\'s own formulas', f'=COUNTIF(\'Driver Analysis\'!F4:F{drow - 1},"Company formula*")', '0', formula=True)
    db.section('Key lines: last actual -> final forecast period')
    chart_rows = []
    for i, (lab, sheet, fr, nh, horizon) in enumerate(dash):
        last = f"'{sheet}'!{get_column_letter(1 + nh)}{fr}"
        fin = f"'{sheet}'!{get_column_letter(1 + nh + horizon)}{fr}"
        db.add(f'k{i}', str(lab)[:60] if not str(lab).startswith('=') else f'Line {i + 1}',
               f'=IFERROR({fin}/{last}-1,0)', PCT, 'Change from the last actual to the final forecast period', formula=True)
        chart_rows.append((sheet, fr, nh + horizon))
    if chart_rows:
        sheet, fr, n = chart_rows[0]
        lc = LineChart()
        lc.title, lc.height, lc.width = 'First key line: history and forecast', 7.5, 16
        lc.add_data(Reference(wb[sheet], min_col=1, max_col=1 + n, min_row=fr, max_row=fr), from_rows=True, titles_from_data=True)
        lc.set_categories(Reference(wb[sheet], min_col=2, max_col=1 + n, min_row=3, max_row=3))
        db.ws.add_chart(lc, 'E4')
    items = [('Scenario switch is 1, 2 or 3', f'IF(OR({sel_ref}=1,{sel_ref}=2,{sel_ref}=3),0,1)'),
             ('Growth drivers within the scenario limits',
              f"SUMPRODUCT(('Driver Analysis'!E4:E{drow - 1}>{cap}+{adj}+0.000001)*('Driver Analysis'!E4:E{drow - 1}<>\"\"))")]
    checks(wb, items)
    sec = [('Dashboard', 'Scenario, integrity and the key lines of the forecast')] + \
          [(o, 'Company sheet (historical figures - inputs)') for o in originals[:12]] + \
          [('Scenario Inputs', 'Growth limits, long-term rate and the Base / Upside / Downside scenario manager (inputs)'),
           ('Driver Analysis', 'Historical growth and forecast method for every line item')] + sections + [('Checks', 'Integrity checks')]
    cover(wb, f'Enterprise wide model - {LABEL}', category,
          f'Enterprise-wide operating model built on the company\'s own investor workbook ({title}). Every historical line '
          f'item is linked and forecast: {struct_n} lines keep the company\'s own formulas, {growth_n} grow at their own '
          f'historical rate within scenario limits, and {ratio_n} ratios hold their recent average. Base / Upside / '
          'Downside scenarios, a driver analysis, dashboard and integrity checks are included.', sec)
    wb.asof = str(max(p[0] for _, (hr, found, s_, f_) in blocks for _, p in found))
    return originals, None


def make(src, filename, workdir, anonymizer):
    """(path to the enhanced model, category, title, allowed input sheets) or (None, reason)."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if Path(src).stat().st_size > MAX_BYTES:
        return None, 'too large'
    fmt, macros = sniff(src)
    if not fmt:
        return None, 'not a readable workbook'
    path = Path(src)
    if fmt in ('xls', 'xlsb', 'template') or macros:
        conv = lo.convert([path], workdir / 'conv', 'xlsx', timeout=120).get(str(path))
        if not conv:
            return None, f'{fmt} conversion failed'
        path = Path(conv)
    try:
        pkg = Package(path)
    except Exception as err:  # noqa: BLE001
        return None, f'unreadable package ({type(err).__name__})'
    try:
        links.clean(pkg)
    except links.Reject as err:
        return None, f'external references: {err}'
    images.strip(pkg)
    sheets.drop_empty(pkg)
    texts = pkg.texts()
    if not FINANCIAL.search(' '.join(texts)[:20000]):
        return None, 'not financial'
    category, _ = classify.classify(Path(filename).stem, [n for n, _ in pkg.sheets], texts)
    infer.infer(pkg)
    anonymizer.package(pkg)
    for part in list(pkg.parts):
        if re.match(r'xl/(sharedStrings|comments\d*|persons/.*|threadedComments/.*)\.xml$|docProps/core\.xml$', part):
            t = pkg.text(part)
            t2 = t.replace('Redacted Name', enterprise.PERSON).replace('>Redacted<', f'>{enterprise.PERSON}<')
            if t2 != t:
                pkg.put(part, t2)
    if links.has_external(pkg) or pkg.broken_parts():
        return None, 'could not clean the package'
    clean = workdir / 'clean.xlsx'
    pkg.save(clean)
    try:
        wb = load_workbook(clean)
    except Exception as err:  # noqa: BLE001
        return None, f'does not open ({type(err).__name__})'
    scrub_sources(wb)
    title = nice_title(Path(filename).stem, anonymizer, category or 'Investor workbook')
    originals, why = enhance(wb, category or 'Operating model', title)
    if not originals:
        return None, why
    try:
        enterprise.finish(wb)
    except (enterprise.SourceMention, enterprise.BrokenReference) as err:
        return None, f'{type(err).__name__}: {err}'
    return (wb, category or 'Operating model', title, set(originals)), None
