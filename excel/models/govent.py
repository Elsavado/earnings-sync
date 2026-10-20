"""Enterprise-wide government models, built from real statistics.

  gov_population  population projection by components of change (births, deaths, international and domestic
                  migration) for every US county and state and every country, with a public-service planning module
                  (housing, school places, hospital beds, water, waste, policing, teachers) and its capital needs
  gov_fiscal      fiscal accounts and debt sustainability for every country: debt dynamics, debt-stabilising primary
                  balance, gross financing needs and four stress tests
  gov_economy     macroeconomic framework for every country: GDP by expenditure, deflator, unemployment (Okun's law),
                  external balance and the savings-investment identity
  gov_project     appraisal of real public investment projects: disbursement, financing and loan service, economic
                  cost-benefit analysis (ENPV, EIRR, BCR) and switching values

As everywhere: real figures and assumptions sit on input sheets, everything else is a formula, and the workbook never
names where its figures come from.
"""
import csv
import io
import re
import time
from datetime import date

from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

from . import enterprise
from .xl import (BOLD, INPUT, INPUT_FILL, MULT, NAVY, NOTE, PCT, Inputs, Sheet, checks, col, cover, data_sheet,
                 new_workbook)

KINDS = {
    'gov_population': 'Population projection & service planning',
    'gov_fiscal': 'Fiscal & debt sustainability',
    'gov_economy': 'Macroeconomic framework',
    'gov_project': 'Public investment project appraisal',
}
enterprise.GOV_KINDS.update(KINDS)
PEOPLE = '#,##0'
BN = '#,##0.0_);(#,##0.0);"–"_)'
WB = 'https://api.worldbank.org/v2'
CENSUS = 'https://www2.census.gov/programs-surveys/popest/datasets/2020-{y}/counties/totals/co-est{y}-alldata.csv'
CENSUS_2010S = 'https://www2.census.gov/programs-surveys/popest/datasets/2010-2019/counties/totals/co-est2019-alldata.csv'
FIRST_YEAR = 1960  # history goes back as far as the statistics do


def _tail_run(years):
    """The latest run of consecutive years."""
    run = []
    for y in sorted(years, reverse=True):
        if run and run[-1] - y != 1:
            break
        run.append(y)
    return sorted(run)



# --- data -----------------------------------------------------------------------------------------------------------
def _wb_indicator(s, code, first, last):
    out, page = {}, 1
    while True:
        r = s.get(f'{WB}/country/all/indicator/{code}', params={'format': 'json', 'date': f'{first}:{last}', 'per_page': 20000,
                                                              'page': page}, timeout=120)
        r.raise_for_status()
        meta, rows = r.json()[0], (r.json()[1] or [])
        for x in rows:
            if x.get('value') is not None and x.get('countryiso3code'):
                out.setdefault(x['countryiso3code'], {})[int(x['date'])] = float(x['value'])
        if page >= int(meta.get('pages', 1)):
            return out
        page += 1


def _countries(s):
    r = s.get(f'{WB}/country', params={'format': 'json', 'per_page': 400}, timeout=60)
    r.raise_for_status()
    return {c['id']: c['name'] for c in r.json()[1] if c.get('region', {}).get('id') not in (None, 'NA', '')
            and c['region']['value'] != 'Aggregates'}


WB_POP = {'pop': 'SP.POP.TOTL', 'cbr': 'SP.DYN.CBRT.IN', 'cdr': 'SP.DYN.CDRT.IN', 'mig': 'SM.POP.NETM',
          'y014': 'SP.POP.0014.TO.ZS', 'y65': 'SP.POP.65UP.TO.ZS'}
WB_FISCAL = {'rev': 'GC.REV.XGRT.GD.ZS', 'tax': 'GC.TAX.TOTL.GD.ZS', 'exp': 'GC.XPN.TOTL.GD.ZS', 'int_rev': 'GC.XPN.INTP.RV.ZS',
             'debt': 'GC.DOD.TOTL.GD.ZS', 'gdp': 'NY.GDP.MKTP.CN', 'growth': 'NY.GDP.MKTP.KD.ZG', 'defl': 'NY.GDP.DEFL.KD.ZG'}
WB_ECON = {'gdp': 'NY.GDP.MKTP.CN', 'growth': 'NY.GDP.MKTP.KD.ZG', 'defl': 'NY.GDP.DEFL.KD.ZG', 'c': 'NE.CON.PRVT.ZS',
           'g': 'NE.CON.GOVT.ZS', 'i': 'NE.GDI.TOTL.ZS', 'x': 'NE.EXP.GNFS.ZS', 'm': 'NE.IMP.GNFS.ZS', 'ca': 'BN.CAB.XOKA.GD.ZS',
           'unemp': 'SL.UEM.TOTL.ZS', 'cpi': 'FP.CPI.TOTL.ZG', 'pop': 'SP.POP.TOTL', 'usd': 'NY.GDP.MKTP.CD'}


def load(kind, s, log):
    """[(entity id, entity)] for one model type."""
    last = date.today().year - 1
    if kind == 'gov_population':
        out = []
        older = {}
        r = s.get(CENSUS_2010S, timeout=180)
        if r.ok:
            for row in csv.DictReader(io.StringIO(r.content.decode('latin-1'))):
                older[row['STATE'] + row['COUNTY']] = row
        for y in (last, last - 1, last - 2):
            r = s.get(CENSUS.format(y=y), timeout=120)
            if r.ok:
                rows = list(csv.DictReader(io.StringIO(r.content.decode('latin-1'))))
                yrs = list(range(2020, y + 1))
                for row in rows:
                    state = row['SUMLEV'] == '040'
                    name = row['STNAME'] if state else f"{row['CTYNAME']}, {row['STNAME']}"
                    try:
                        series = {k: [float(row[f'{src}{t}']) for t in yrs] for k, src in
                                  (('pop', 'POPESTIMATE'), ('births', 'BIRTHS'), ('deaths', 'DEATHS'),
                                   ('intl', 'INTERNATIONALMIG'), ('dom', 'DOMESTICMIG'), ('resid', 'RESIDUAL'))}
                        series['base'] = float(row['ESTIMATESBASE2020'])
                        old = older.get(row['STATE'] + row['COUNTY'])
                        if old:  # the 2010s, when the place existed with the same code
                            early = {k: [float(old[f'{src}{t}']) for t in range(2010, 2020)] for k, src in
                                     (('pop', 'POPESTIMATE'), ('births', 'BIRTHS'), ('deaths', 'DEATHS'),
                                      ('intl', 'INTERNATIONALMIG'), ('dom', 'DOMESTICMIG'), ('resid', 'RESIDUAL'))}
                            series = {k: (early[k] + v if k in early else v) for k, v in series.items()}
                    except (KeyError, ValueError):
                        continue
                    if series['pop'][-1] < 1000:
                        continue
                    span_ = (list(range(2010, 2020)) if len(series['pop']) > len(yrs) else []) + yrs
                    out.append((f"us:{row['STATE']}{row['COUNTY']}", {'kind': 'us', 'name': name, 'years': span_, 'state': state, **series}))
                log(f'population: {len(out)} US states and counties')
                break
        names = _countries(s)
        data = {k: _wb_indicator(s, code, FIRST_YEAR, last) for k, code in WB_POP.items()}
        n0 = len(out)
        for iso, name in names.items():
            pop = data['pop'].get(iso, {})
            yrs = _tail_run([y for y in pop if all(y in data[k].get(iso, {}) for k in ('cbr', 'cdr'))])
            if len(yrs) < 6 or yrs[-1] < last - 2 or pop[yrs[-1]] < 50000:
                continue
            mig = data['mig'].get(iso, {})
            e = {'kind': 'country', 'name': name, 'years': yrs, 'pop': [pop[y] for y in yrs],
                 'births': [data['cbr'][iso][y] * pop[y] / 1000 for y in yrs],
                 'deaths': [data['cdr'][iso][y] * pop[y] / 1000 for y in yrs],
                 'intl': [mig.get(y, 0.0) for y in yrs], 'dom': [0.0] * len(yrs)}
            y014, y65 = data['y014'].get(iso, {}), data['y65'].get(iso, {})
            if all(y in y014 and y in y65 for y in yrs):
                e['y014'], e['y65'] = [y014[y] / 100 for y in yrs], [y65[y] / 100 for y in yrs]
            out.append((f'cty:{iso}', e))
        log(f'population: {len(out) - n0} countries')
        return out
    if kind in ('gov_fiscal', 'gov_economy'):
        names = _countries(s)
        spec = WB_FISCAL if kind == 'gov_fiscal' else WB_ECON
        data = {k: _wb_indicator(s, code, FIRST_YEAR, last) for k, code in spec.items()}
        need = ('rev', 'exp', 'gdp', 'growth', 'defl') if kind == 'gov_fiscal' else ('gdp', 'growth', 'defl', 'c', 'g', 'i', 'x', 'm')
        out = []
        for iso, name in names.items():
            yrs = _tail_run([y for y in range(FIRST_YEAR, last + 1) if all(y in data[k].get(iso, {}) for k in need)])
            if len(yrs) < 6 or yrs[-1] < last - 2:
                continue
            e = {'name': name, 'years': yrs}
            for k in spec:
                e[k] = [data[k].get(iso, {}).get(y) for y in yrs]
            if kind == 'gov_fiscal' and e['debt'][-1] is None:
                continue
            out.append((f'{kind}:{iso}', e))
        log(f'{kind}: {len(out)} countries with complete data')
        return out
    if kind == 'gov_project':
        out, start = [], 0
        fl = 'id,project_name,countryname,totalamt,lendprojectcost,boardapprovaldate,closingdate,sector1,status,mjsector1Name'
        while True:
            r = s.get('https://search.worldbank.org/api/v2/projects', params={'format': 'json', 'rows': 500, 'os': start, 'fl': fl},
                      timeout=120)
            if not r.ok:
                break
            js = r.json()
            projects = list((js.get('projects') or {}).values())
            if not projects:
                break
            for p in projects:
                try:
                    cost = float(str(p.get('lendprojectcost') or '0').replace(',', ''))
                    loan = float(str(p.get('totalamt') or '0').replace(',', ''))
                    a = date.fromisoformat(str(p.get('boardapprovaldate'))[:10])
                    c = p.get('closingdate') or ''
                    m = re.match(r'(\d+)/(\d+)/(\d{4})', c)
                    cl = date(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else date.fromisoformat(c[:10])
                except (ValueError, TypeError):
                    continue
                if cost < 5e6 or loan <= 0 or loan > cost * 1.0001 or cl <= a or a.year < 1995:
                    continue
                if re.search(r'development policy|\bDPF\b|\bDPO\b|\bDPL\b|budget support|policy (loan|credit|operation)|'
                             r'structural adjustment|emergency recovery loan|guarantee', p.get('project_name') or '', re.I):
                    continue  # budget support and guarantees are not investment projects
                sector = (p.get('sector1') or {}).get('Name') if isinstance(p.get('sector1'), dict) else None
                sector = sector or p.get('mjsector1Name') or 'Multisector'
                country = (p.get('countryname') or ['Multi-country'])
                country = country[0] if isinstance(country, list) else country
                out.append((f'prj:{p["id"]}', {'name': p.get('project_name') or 'Public investment project', 'country': country,
                                               'sector': sector, 'cost': cost / 1e6, 'loan': loan / 1e6,
                                               'approved': a.isoformat(), 'closing': cl.isoformat()}))
            start += 500
            if start >= int(js.get('total', 0)):
                break
            time.sleep(0.3)
        log(f'projects: {len(out)} with cost, financing and dates')
        return out
    raise ValueError(kind)


# --- shared pieces --------------------------------------------------------------------------------------------------
def _scenario(wb, si, rows, names=('Base', 'High', 'Low')):
    ws = si.ws
    r = si.next_row + 1
    ws.cell(row=r, column=1, value='Scenario manager').font = Font(bold=True, color=NAVY)
    r += 1
    ws.cell(row=r, column=1, value=f'Active scenario (1 = {names[0]}, 2 = {names[1]}, 3 = {names[2]})').font = BOLD
    sel = ws.cell(row=r, column=2, value=1)
    sel.font, sel.fill, sel.number_format = INPUT, INPUT_FILL, '0'
    dv = DataValidation(type='list', formula1='"1,2,3"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(sel.coordinate)
    sel_ref = f"'{si.title}'!$B${r}"
    ws.cell(row=r + 1, column=1, value='Active scenario name')
    ws.cell(row=r + 1, column=2, value=f'=CHOOSE({sel_ref},"{names[0]}","{names[1]}","{names[2]}")').font = BOLD
    name_ref = f"'{si.title}'!$B${r + 1}"
    r += 3
    for k, h in enumerate(['Driver', *names, 'Live (active case)']):
        ws.cell(row=r, column=1 + k, value=h).font = BOLD
    for letter in 'DE':
        ws.column_dimensions[letter].width = 16
    live = {}
    for key, label, vals, fmt in rows:
        r += 1
        ws.cell(row=r, column=1, value=label)
        for k, v in enumerate(vals):
            cell = ws.cell(row=r, column=2 + k, value=v)
            cell.font, cell.fill, cell.number_format = INPUT, INPUT_FILL, fmt
        cell = ws.cell(row=r, column=5, value=f'=CHOOSE({sel_ref},B{r},C{r},D{r})')
        cell.number_format, cell.font = fmt, BOLD
        live[key] = f"'{si.title}'!$E${r}"
    si.next_row = r + 2
    return live, name_ref, ('Scenario switch is 1, 2 or 3', f'IF(OR({sel_ref}=1,{sel_ref}=2,{sel_ref}=3),0,1)')


def _dashboard(wb, head, name_ref, items, chart=None):
    db = Inputs(wb, 'Dashboard', head('Executive dashboard'), index=0)
    db.ws['A2'] = 'Key outputs of the live scenario. Every figure is a formula.'
    db.section('Scenario')
    db.add('scen', 'Active scenario', f'={name_ref}', '@', formula=True)
    db.add('checks', 'Model integrity', '=IF(Checks!$B$3=0,"All checks pass","CHECK ERRORS")', '@', formula=True)
    db.section('Key results')
    for key, label, f, fmt in items:
        db.add(key, label, f, fmt, formula=True)
    if chart:
        sheet, keys, n, title = chart
        lc = LineChart()
        lc.title, lc.height, lc.width = title, 7.5, 16
        for key in keys:
            r = sheet.rows[key]
            lc.add_data(Reference(sheet.ws, min_col=1, max_col=1 + n, min_row=r, max_row=r), from_rows=True, titles_from_data=True)
        lc.set_categories(Reference(sheet.ws, min_col=2, max_col=1 + n, min_row=3, max_row=3))
        db.ws.add_chart(lc, 'E4')
    return [('Dashboard', 'Key results of the live scenario')]


def _finish(wb, title, place, desc, sections, items, asof):
    sections = sections + [('Checks', 'Integrity checks')]
    checks(wb, items)
    cover(wb, f'Enterprise wide model - {title}', place, desc, sections)
    ws = wb['Cover']
    ws['B2'] = place  # government models are about a named place or programme, not a redacted company
    wb.properties.title = f'{place} - {title}'
    wb.asof = asof
    return enterprise.finish(wb)


# --- population -----------------------------------------------------------------------------------------------------
def population(e):
    yrs, nh = e['years'], len(e['years'])
    horizon = 20
    periods = [str(y) for y in yrs] + [str(yrs[-1] + k) for k in range(1, horizon + 1)]
    n, hi, F0, FN = len(periods), nh - 1, nh, nh + horizon - 1
    wb = new_workbook()
    place = e['name']
    head = lambda t: f'{place} - {t}'  # noqa: E731
    rows = [('pop', 'Population (year end / mid-year estimate)'), ('births', 'Births'), ('deaths', 'Deaths'),
            ('intl', 'Net international migration'), ('dom', 'Net domestic migration')]
    vals = {k: [round(v) for v in e[k]] for k, _ in rows}
    if 'y014' in e:
        rows += [('y014', 'Population aged 0-14 (% of total)'), ('y65', 'Population aged 65+ (% of total)')]
        vals['y014'], vals['y65'] = [round(v, 4) for v in e['y014']], [round(v, 4) for v in e['y65']]
    ds = data_sheet(wb, head('Historical population and components of change'), periods[:nh], rows, vals, unit='Persons')
    for r in ds.rows.values():
        for j in range(nh):
            ds.ws.cell(row=r, column=2 + j).number_format = PEOPLE
    D = ds.ref
    si = Inputs(wb, 'Scenario Inputs', head('Projection settings and scenarios'))
    si.section('Trend settings')
    si.add('mort_drift', 'Annual change in the death rate (population ageing)', 0.006, PCT)
    si.add('fert_drift', 'Annual change in the birth rate', -0.004, PCT)
    si.add('mig_fade', 'Migration converges to this share of its recent average by the final year', 0.75, PCT)
    live, name_ref, sw = _scenario(wb, si, [('fert', 'Birth rate multiplier', (1.0, 1.08, 0.92), '0.00"x"'),
                                            ('mort', 'Death rate multiplier', (1.0, 0.96, 1.05), '0.00"x"'),
                                            ('mig', 'Migration multiplier', (1.0, 1.35, 0.55), '0.00"x"')])
    pi = Inputs(wb, 'Planning Inputs', head('Public-service planning standards and unit costs'))
    has_age = 'y014' in e
    pi.section('Age structure (used when the place has no age detail)')
    pi.add('sh014', 'Share of population aged 0-14', 0.18, PCT)
    pi.add('sh65', 'Share of population aged 65+', 0.18, PCT)
    pi.add('sh517', 'School-age share (5-17)', 0.165, PCT)
    pi.section('Service standards')
    std = [('hh', 'Average household size (persons)', 2.5, '0.00'), ('vac', 'Housing vacancy allowance', 0.07, PCT),
           ('beds', 'Hospital beds per 1,000 population', 2.8, '0.0'), ('ptr', 'Pupils per teacher', 16.0, '0.0'),
           ('police', 'Police officers per 1,000 population', 2.4, '0.0'), ('water', 'Water demand (litres per person per day)', 150.0, '0'),
           ('waste', 'Municipal waste (kg per person per day)', 2.2, '0.0'), ('enrol', 'School enrolment rate (school-age)', 0.95, PCT)]
    for key, label, v, fmt in std:
        pi.add(key, label, v, fmt)
    pi.section('Capital cost per unit (USD thousands)')
    for key, label, v in [('c_house', 'Housing unit', 320.0), ('c_bed', 'Hospital bed', 950.0), ('c_place', 'School place', 45.0),
                          ('c_water', 'Water capacity per 1,000 litres a day', 2.6)]:
        pi.add(key, label, v, '#,##0.0')
    P = pi.ref
    asm = Sheet(wb, 'Assumptions', head('Component rates (per 1,000 population, from the historical years)'), ['Rate'])
    pr = Sheet(wb, 'Projection', head('Population projection by components of change (live scenario)'), periods, nh, unit='Persons')
    for key, label, bold, sec in [
        ('open', 'Opening population', False, 'Components of change'), ('births', 'Plus: births', False, None),
        ('deaths', 'Less: deaths', False, None), ('natural', 'Natural increase', True, None),
        ('intl', 'Net international migration', False, None), ('dom', 'Net domestic migration', False, None),
        ('netmig', 'Net migration', True, None), ('resid', 'Statistical residual', False, None),
        ('close', 'Closing population', True, None), ('growth', 'Population growth', False, None),
        ('t', 'Projection year', False, 'Rates'), ('cbr', 'Crude birth rate (per 1,000)', False, None),
        ('cdr', 'Crude death rate (per 1,000)', False, None), ('nmr', 'Net migration rate (per 1,000)', False, None),
        ('y014', 'Aged 0-14', False, 'Age structure'), ('y1564', 'Aged 15-64', False, None), ('y65', 'Aged 65+', False, None),
        ('dep', 'Total dependency ratio', False, None), ('old', 'Old-age dependency ratio', False, None),
        ('chk', 'Check: closing = opening + components', False, 'Checks')]:
        pr.row(key, label, bold, section=sec)
    R = pr.ref
    w0 = max(1, nh - 5)  # rates from the latest five years; the full history stays on the sheets
    span = lambda key, a=w0, b=hi: pr.span(key, max(a, w0), b)  # noqa: E731
    a10 = max(0, nh - 10)
    for key, label, f in [
        ('cbr', 'Birth rate (average of recent years) x scenario', f'AVERAGE({span("cbr")})*{live["fert"]}'),
        ('cdr', 'Death rate (average of recent years) x scenario', f'AVERAGE({span("cdr")})*{live["mort"]}'),
        ('intl', 'Net international migration per year (recent average) x scenario', f'AVERAGE({span("intl")})*{live["mig"]}'),
        ('dom', 'Net domestic migration per year (recent average) x scenario', f'AVERAGE({span("dom")})*{live["mig"]}'),
        ('d014', 'Annual change in the 0-14 share', f'IFERROR(SLOPE({pr.span("y014", a10, hi)},{pr.span("t", a10, hi)}),0)' if has_age else f'{P("sh014")}-{P("sh014")}'),
        ('d65', 'Annual change in the 65+ share', f'IFERROR(SLOPE({pr.span("y65", a10, hi)},{pr.span("t", a10, hi)}),0)' if has_age else f'{P("sh65")}-{P("sh65")}')]:
        asm.row(key, label)
        asm.set(key, 0, f'={f}', '#,##0.000' if key in ('cbr', 'cdr', 'd014', 'd65') else PEOPLE)
    A = lambda k: asm.ref(k, 0, absolute=True)  # noqa: E731
    for j in range(n):
        p, h = j - 1, j < nh
        pr.set('t', j, f'={j}-{hi}' if False else (f'=N({R("t", p)})+1' if j else f'={D("pop", 0)}-{D("pop", 0)}'), '0')
        if h:
            pr.set('close', j, f'={D("pop", j)}', PEOPLE, bold=True)
            pr.set('births', j, f'={D("births", j)}', PEOPLE)
            pr.set('deaths', j, f'=-{D("deaths", j)}', PEOPLE)
            pr.set('intl', j, f'={D("intl", j)}', PEOPLE)
            pr.set('dom', j, f'={D("dom", j)}', PEOPLE)
            if has_age:
                pr.set('y014', j, f'={D("y014", j)}', PCT)
                pr.set('y65', j, f'={D("y65", j)}', PCT)
            else:
                pr.set('y014', j, f'={P("sh014")}', PCT)
                pr.set('y65', j, f'={P("sh65")}', PCT)
        else:
            k = f'{R("t", j)}-{R("t", hi)}'
            pr.set('births', j, f'={R("open", j)}/1000*{A("cbr")}*(1+{si.ref("fert_drift")})^({k})', PEOPLE)
            pr.set('deaths', j, f'=-{R("open", j)}/1000*{A("cdr")}*(1+{si.ref("mort_drift")})^({k})', PEOPLE)
            fade = f'(1-(1-{si.ref("mig_fade")})*({k})/{horizon})'
            pr.set('intl', j, f'={A("intl")}*{fade}', PEOPLE)
            pr.set('dom', j, f'={A("dom")}*{fade}', PEOPLE)
            pr.set('resid', j, f'={R("t", j)}-{R("t", j)}', PEOPLE)
            pr.set('close', j, f'={R("open", j)}+{R("natural", j)}+{R("netmig", j)}+{R("resid", j)}', PEOPLE, bold=True)
            pr.set('y014', j, f'=MAX(0.05,MIN(0.6,{R("y014", p)}+{A("d014")}))', PCT)
            pr.set('y65', j, f'=MAX(0.01,MIN(0.45,{R("y65", p)}+{A("d65")}))', PCT)
        pr.set('y1564', j, f'=1-{R("y014", j)}-{R("y65", j)}', PCT)
        pr.set('dep', j, f'=IFERROR(({R("y014", j)}+{R("y65", j)})/{R("y1564", j)},0)', PCT)
        pr.set('old', j, f'=IFERROR({R("y65", j)}/{R("y1564", j)},0)', PCT)
        if j:
            pr.set('open', j, f'={R("close", p)}', PEOPLE)
            pr.set('natural', j, f'={R("births", j)}+{R("deaths", j)}', PEOPLE, bold=True)
            pr.set('netmig', j, f'={R("intl", j)}+{R("dom", j)}', PEOPLE, bold=True)
            if h:
                pr.set('resid', j, f'={R("close", j)}-{R("open", j)}-{R("natural", j)}-{R("netmig", j)}', PEOPLE)
            pr.set('growth', j, f'=IFERROR({R("close", j)}/{R("open", j)}-1,0)', PCT)
            pr.set('cbr', j, f'=IFERROR({R("births", j)}/{R("open", j)}*1000,0)', '0.00')
            pr.set('cdr', j, f'=IFERROR(-{R("deaths", j)}/{R("open", j)}*1000,0)', '0.00')
            pr.set('nmr', j, f'=IFERROR({R("netmig", j)}/{R("open", j)}*1000,0)', '0.00')
            pr.set('chk', j, f'=ROUND({R("close", j)}-({R("open", j)}+{R("natural", j)}+{R("netmig", j)}+{R("resid", j)}),3)')

    sp = Sheet(wb, 'Service Planning', head('Public-service needs and capital investment (live scenario)'), periods[hi:], 1, unit='Units as stated')
    for key, label, bold, sec in [
        ('pop', 'Population', True, 'Demand'), ('hh', 'Households', False, None), ('homes', 'Housing units required', False, None),
        ('pupils', 'School pupils', False, None), ('teachers', 'Teachers required', False, None),
        ('beds', 'Hospital beds required', False, None), ('police', 'Police officers required', False, None),
        ('water', 'Water demand (million litres a day)', False, None), ('waste', 'Municipal waste (tonnes a year)', False, None),
        ('d_homes', 'Additional housing units', False, 'Additional capacity vs the base year'), ('d_places', 'Additional school places', False, None),
        ('d_beds', 'Additional hospital beds', False, None), ('d_water', 'Additional water capacity (million litres a day)', False, None),
        ('cap_house', 'Housing', False, 'Capital investment in the year (USD millions)'), ('cap_school', 'Schools', False, None),
        ('cap_health', 'Hospitals', False, None), ('cap_water', 'Water', False, None), ('cap', 'Total capital investment', True, None),
        ('cap_cum', 'Cumulative capital investment', True, None), ('cap_pc', 'Capital investment per resident (USD)', False, None)]:
        sp.row(key, label, bold, section=sec)
    S = sp.ref
    m = n - hi
    for jj in range(m):
        j, p = hi + jj, jj - 1
        school = f'IF({R("y014", j)}={P("sh014")},{P("sh517")},{R("y014", j)}*{P("sh517")}/{P("sh014")})'
        sp.set('pop', jj, f'={R("close", j)}', PEOPLE, bold=True)
        sp.set('hh', jj, f'={S("pop", jj)}/{P("hh")}', PEOPLE)
        sp.set('homes', jj, f'={S("hh", jj)}*(1+{P("vac")})', PEOPLE)
        sp.set('pupils', jj, f'={S("pop", jj)}*{school}*{P("enrol")}', PEOPLE)
        sp.set('teachers', jj, f'=IFERROR({S("pupils", jj)}/{P("ptr")},0)', PEOPLE)
        sp.set('beds', jj, f'={S("pop", jj)}/1000*{P("beds")}*(1+({R("y65", j)}-{R("y65", hi)}))', PEOPLE)
        sp.set('police', jj, f'={S("pop", jj)}/1000*{P("police")}', PEOPLE)
        sp.set('water', jj, f'={S("pop", jj)}*{P("water")}/1000000', '#,##0.00')
        sp.set('waste', jj, f'={S("pop", jj)}*{P("waste")}*365/1000', PEOPLE)
        sp.set('d_homes', jj, f'={S("homes", jj)}-{S("homes", 0)}', PEOPLE)
        sp.set('d_places', jj, f'={S("pupils", jj)}-{S("pupils", 0)}', PEOPLE)
        sp.set('d_beds', jj, f'={S("beds", jj)}-{S("beds", 0)}', PEOPLE)
        sp.set('d_water', jj, f'={S("water", jj)}-{S("water", 0)}', '#,##0.00')
        if jj:
            sp.set('cap_house', jj, f'=MAX(0,{S("d_homes", jj)}-MAX(0,{S("d_homes", p)}))*{P("c_house")}/1000', BN)
            sp.set('cap_school', jj, f'=MAX(0,{S("d_places", jj)}-MAX(0,{S("d_places", p)}))*{P("c_place")}/1000', BN)
            sp.set('cap_health', jj, f'=MAX(0,{S("d_beds", jj)}-MAX(0,{S("d_beds", p)}))*{P("c_bed")}/1000', BN)
            sp.set('cap_water', jj, f'=MAX(0,{S("d_water", jj)}-MAX(0,{S("d_water", p)}))*1000*{P("c_water")}/1000', BN)
            sp.set('cap', jj, f'=SUM({col(jj)}{sp.rows["cap_house"]}:{col(jj)}{sp.rows["cap_water"]})', BN, bold=True)
            sp.set('cap_cum', jj, f'=SUM({sp.span("cap", 1, jj)})', BN, bold=True)
            sp.set('cap_pc', jj, f'=IFERROR({S("cap", jj)}*1000000/{S("pop", jj)},0)', '#,##0.00')
    items = [_dash for _dash in [
        ('p0', f'Population {periods[hi]}', f'={R("close", hi)}', PEOPLE),
        ('p10', f'Population {periods[hi + 10]}', f'={R("close", hi + 10)}', PEOPLE),
        ('p20', f'Population {periods[FN]}', f'={R("close", FN)}', PEOPLE),
        ('cagr', 'Projected annual growth', f'=IFERROR(({R("close", FN)}/{R("close", hi)})^(1/{horizon})-1,0)', PCT),
        ('old', f'Old-age dependency ratio {periods[FN]}', f'={R("old", FN)}', PCT),
        ('homes', 'Additional housing units by the final year', f'={S("d_homes", m - 1)}', PEOPLE),
        ('capex', 'Cumulative public capital investment (USD millions)', f'={S("cap_cum", m - 1)}', BN)]]
    sections = _dashboard(wb, head, name_ref, items, (pr, ['close'], n, 'Population (persons)')) + [
        ('Historical Data', 'Historical population and components of change - hard-coded inputs'),
        ('Scenario Inputs', 'Trend settings and the Base / High / Low scenario manager (inputs)'),
        ('Planning Inputs', 'Service standards and capital unit costs (inputs)'),
        ('Assumptions', 'Component rates from the historical years with the live scenario'),
        ('Projection', f'{horizon}-year projection by components of change, with age structure and dependency ratios'),
        ('Service Planning', 'Housing, schools, hospitals, water, waste and policing needs with capital investment')]
    chk = [(f'Components add up ({periods[j]})', R('chk', j)) for j in range(1, n)] + [sw]
    kind = 'state' if e.get('state') else ('county' if e['kind'] == 'us' else 'country')
    desc = (f'Enterprise-wide population projection for {place} ({kind}): {horizon}-year projection by components of change '
            '(births, deaths, international and domestic migration) with fertility, mortality and migration scenarios, age '
            'structure and dependency ratios, and a public-service planning module that converts the projection into housing, '
            'school, hospital, water, waste and policing needs and the capital investment they require.')
    return _finish(wb, KINDS['gov_population'], place, desc, sections, chk, periods[hi])


# --- fiscal & debt sustainability ----------------------------------------------------------------------------------
def fiscal(e):
    yrs, nh = e['years'], len(e['years'])
    horizon = 10
    periods = [str(y) for y in yrs] + [f'{yrs[-1] + k}F' for k in range(1, horizon + 1)]
    n, hi, F0, FN = len(periods), nh - 1, nh, nh + horizon - 1
    wb = new_workbook()
    place = e['name']
    head = lambda t: f'{place} - {t}'  # noqa: E731
    fill = lambda v, d=0.0: [d if x is None else x for x in v]  # noqa: E731
    vals = {'gdp': [round(x / 1e9, 3) for x in e['gdp']], 'growth': [round(x / 100, 5) for x in e['growth']],
            'defl': [round(x / 100, 5) for x in e['defl']], 'rev': [round(x / 100, 5) for x in e['rev']],
            'tax': [round(x / 100, 5) for x in fill(e['tax'])], 'exp': [round(x / 100, 5) for x in e['exp']],
            'int_rev': [round(x / 100, 5) for x in fill(e['int_rev'])]}
    debt = e['debt']
    known = [x for x in debt if x is not None]
    vals['debt'] = [round((x if x is not None else known[0]) / 100, 5) for x in debt]
    rows = [('gdp', 'Nominal GDP (local currency, billions)'), ('growth', 'Real GDP growth'), ('defl', 'GDP deflator inflation'),
            ('rev', 'Revenue (% GDP)'), ('tax', 'Tax revenue (% GDP)'), ('exp', 'Expense (% GDP)'),
            ('int_rev', 'Interest payments (% revenue)'), ('debt', 'Central government debt (% GDP)')]
    ds = data_sheet(wb, head('Historical fiscal and macroeconomic data'), periods[:nh], rows, vals, unit='As stated')
    for key in ('growth', 'defl', 'rev', 'tax', 'exp', 'int_rev', 'debt'):
        for j in range(nh):
            ds.ws.cell(row=ds.rows[key], column=2 + j).number_format = PCT
    D = ds.ref
    si = Inputs(wb, 'Scenario Inputs', head('Fiscal path, financing terms and stress-test settings'))
    si.section('Medium-term anchors')
    si.add('lt_g', 'Long-run real growth', 0.03, PCT)
    si.add('lt_pi', 'Long-run inflation', 0.03, PCT)
    si.add('adj', 'Annual primary balance consolidation (% GDP, first five years)', 0.002, PCT)
    si.add('mat', 'Average maturity of debt (years)', 7.0, '0.0')
    si.add('new_spread', 'Spread of new borrowing over the effective rate', 0.005, PCT)
    si.add('anchor', 'Debt benchmark (% GDP)', 0.70, PCT, 'Prudential reference level')
    si.add('gfn_lim', 'Gross financing needs benchmark (% GDP)', 0.15, PCT)
    si.section('Stress tests')
    si.add('s_g', 'Growth shock (pp, two years)', -0.03, PCT)
    si.add('s_i', 'Interest rate shock', 0.02, PCT)
    si.add('s_pb', 'Primary balance shock (% GDP, two years)', -0.015, PCT)
    live, name_ref, sw = _scenario(wb, si, [('g', 'Real growth adjustment', (0.0, 0.0075, -0.01), PCT),
                                            ('rev', 'Revenue effort (% GDP)', (0.0, 0.005, -0.0075), PCT),
                                            ('i', 'Interest rate adjustment', (0.0, -0.005, 0.0125), PCT)],
                                   names=('Base', 'Optimistic', 'Adverse'))
    S_ = si.ref
    asm = Sheet(wb, 'Assumptions', head('Drivers from the historical years with the live scenario'), ['Driver'])
    fa = Sheet(wb, 'Fiscal Accounts', head('Fiscal accounts (local currency, billions; live scenario)'), periods, nh, unit='Local currency, billions')
    for key, label, bold, sec in [
        ('t', 'Forecast year', False, 'Macro'), ('g', 'Real GDP growth', False, None), ('pi', 'GDP deflator inflation', False, None),
        ('ng', 'Nominal GDP growth', False, None), ('gdp', 'Nominal GDP', True, None),
        ('rev', 'Total revenue', True, 'Revenue'), ('tax', 'Tax revenue', False, None), ('ntax', 'Non-tax revenue & grants', False, None),
        ('exp', 'Total expense', True, 'Expenditure'), ('int', 'Interest payments', False, None), ('pexp', 'Primary expense', False, None),
        ('pb', 'Primary balance', True, 'Balances'), ('ob', 'Overall balance', True, None),
        ('d_open', 'Opening debt', False, 'Debt'), ('borrow', 'Net borrowing (deficit)', False, None),
        ('sfa', 'Stock-flow adjustment', False, None), ('debt', 'Closing debt', True, None),
        ('rev_pct', 'Revenue % GDP', False, 'Ratios'), ('exp_pct', 'Expense % GDP', False, None),
        ('pb_pct', 'Primary balance % GDP', False, None), ('ob_pct', 'Overall balance % GDP', False, None),
        ('debt_pct', 'Debt % GDP', True, None), ('eff_i', 'Effective interest rate', False, None),
        ('int_rev', 'Interest % revenue', False, None)]:
        fa.row(key, label, bold, section=sec)
    R = fa.ref
    w0 = max(1, nh - 10)  # growth from the latest ten years; the full history stays on the sheets
    span = lambda key, a=w0, b=hi: fa.span(key, max(a, w0), b)  # noqa: E731
    for key, label, f in [
        ('g0', 'Starting real growth (historical median) + scenario', f'MEDIAN({span("g")})+{live["g"]}'),
        ('pi0', 'Starting inflation (median of last three years)', f'MEDIAN({fa.span("pi", hi - 2, hi)})'),
        ('rev', 'Revenue % GDP (last three years) + scenario', f'AVERAGE({fa.span("rev_pct", hi - 2, hi)})+{live["rev"]}'),
        ('tax_s', 'Tax share of revenue', f'IFERROR(SUM({fa.span("tax", 0, hi)})/SUM({fa.span("rev", 0, hi)}),0)'),
        ('pexp', 'Primary expense % GDP (last three years)', f'AVERAGE({fa.span("pexp", hi - 2, hi)})/AVERAGE({fa.span("gdp", hi - 2, hi)})'),
        ('i', 'Effective interest rate (recent) + scenario', f'MAX(0,IFERROR(AVERAGE({fa.span("eff_i", hi - 2, hi)}),0)+{live["i"]})')]:
        asm.row(key, label)
        asm.set(key, 0, f'={f}', PCT)
    A = lambda k: asm.ref(k, 0, absolute=True)  # noqa: E731
    for j in range(n):
        p, h = j - 1, j < nh
        if h:
            fa.set('g', j, f'={D("growth", j)}', PCT)
            fa.set('pi', j, f'={D("defl", j)}', PCT)
            fa.set('gdp', j, f'={D("gdp", j)}', BN, bold=True)
            fa.set('rev', j, f'={R("gdp", j)}*{D("rev", j)}', BN, bold=True)
            fa.set('tax', j, f'={R("gdp", j)}*{D("tax", j)}', BN)
            fa.set('exp', j, f'={R("gdp", j)}*{D("exp", j)}', BN, bold=True)
            fa.set('int', j, f'={R("rev", j)}*{D("int_rev", j)}', BN)
            fa.set('debt', j, f'={R("gdp", j)}*{D("debt", j)}', BN, bold=True)
        else:
            fa.set('t', j, f'=N({R("t", p)})+1', '0')
            fa.set('g', j, f'={A("g0")}+({S_("lt_g")}-{A("g0")})*MIN(1,{R("t", j)}/5)', PCT)
            fa.set('pi', j, f'={A("pi0")}+({S_("lt_pi")}-{A("pi0")})*MIN(1,{R("t", j)}/5)', PCT)
            fa.set('gdp', j, f'={R("gdp", p)}*(1+{R("ng", j)})', BN, bold=True)
            fa.set('rev', j, f'={R("gdp", j)}*{A("rev")}', BN, bold=True)
            fa.set('tax', j, f'={R("rev", j)}*{A("tax_s")}', BN)
            fa.set('int', j, f'={R("d_open", j)}*({A("i")}+{S_("new_spread")}*MIN(1,{R("t", j)}/{S_("mat")}))', BN)
            fa.set('pexp', j, f'={R("gdp", j)}*({A("pexp")}-{S_("adj")}*MIN(5,{R("t", j)}))', BN)
            fa.set('exp', j, f'={R("pexp", j)}+{R("int", j)}', BN, bold=True)
            fa.set('sfa', j, f'={R("t", j)}-{R("t", j)}', BN)
            fa.set('debt', j, f'={R("d_open", j)}+{R("borrow", j)}+{R("sfa", j)}', BN, bold=True)
        if h:
            fa.set('pexp', j, f'={R("exp", j)}-{R("int", j)}', BN)
        fa.set('ng', j, f'=(1+{R("g", j)})*(1+{R("pi", j)})-1', PCT)
        fa.set('ntax', j, f'={R("rev", j)}-{R("tax", j)}', BN)
        fa.set('pb', j, f'={R("rev", j)}-{R("pexp", j)}', BN, bold=True)
        fa.set('ob', j, f'={R("pb", j)}-{R("int", j)}', BN, bold=True)
        fa.set('rev_pct', j, f'=IFERROR({R("rev", j)}/{R("gdp", j)},0)', PCT)
        fa.set('exp_pct', j, f'=IFERROR({R("exp", j)}/{R("gdp", j)},0)', PCT)
        fa.set('pb_pct', j, f'=IFERROR({R("pb", j)}/{R("gdp", j)},0)', PCT)
        fa.set('ob_pct', j, f'=IFERROR({R("ob", j)}/{R("gdp", j)},0)', PCT)
        fa.set('debt_pct', j, f'=IFERROR({R("debt", j)}/{R("gdp", j)},0)', PCT, bold=True)
        fa.set('int_rev', j, f'=IFERROR({R("int", j)}/{R("rev", j)},0)', PCT)
        if j:
            fa.set('d_open', j, f'={R("debt", p)}', BN)
            fa.set('borrow', j, f'=-{R("ob", j)}', BN)
            if h:
                fa.set('sfa', j, f'={R("debt", j)}-{R("d_open", j)}-{R("borrow", j)}', BN)
            fa.set('eff_i', j, f'=IFERROR({R("int", j)}/{R("d_open", j)},0)', PCT)
    dsa = Sheet(wb, 'Debt Sustainability', head('Debt sustainability analysis (% GDP)'), periods[hi:], 1, unit='% of GDP')
    for key, label, bold, sec in [
        ('base', 'Debt - live scenario', True, 'Debt paths'), ('s_g', 'Debt - growth shock', False, None),
        ('s_i', 'Debt - interest rate shock', False, None), ('s_pb', 'Debt - primary balance shock', False, None),
        ('s_c', 'Debt - combined shock', False, None),
        ('ig', 'Interest-growth differential (r - g)', False, 'Dynamics'), ('stab', 'Debt-stabilising primary balance', False, None),
        ('gap', 'Primary balance gap (actual - stabilising)', False, None),
        ('gfn', 'Gross financing needs', True, 'Financing'), ('gfn_test', 'Financing needs test', False, None),
        ('debt_test', 'Debt benchmark test', False, None)]:
        dsa.row(key, label, bold, section=sec)
    Q = dsa.ref
    m = n - hi
    for jj in range(m):
        j, p = hi + jj, jj - 1
        if jj == 0:
            for key in ('base', 's_g', 's_i', 's_pb', 's_c'):
                dsa.set(key, 0, f'={R("debt_pct", hi)}', PCT, bold=key == 'base')
            continue
        shock2 = f'IF({jj}<=2,1,0)'
        r_, g_, pb = f'{R("eff_i", j)}', f'{R("ng", j)}', f'{R("pb_pct", j)}'
        dsa.set('base', jj, f'={R("debt_pct", j)}', PCT, bold=True)
        dsa.set('s_g', jj, f'={Q("s_g", p)}*(1+{r_})/(1+{g_}+{S_("s_g")}*{shock2})-({pb}+{S_("s_g")}*{shock2}*{R("rev_pct", j)})', PCT)
        dsa.set('s_i', jj, f'={Q("s_i", p)}*(1+{r_}+{S_("s_i")}*MIN(1,{jj}/{S_("mat")}))/(1+{g_})-{pb}', PCT)
        dsa.set('s_pb', jj, f'={Q("s_pb", p)}*(1+{r_})/(1+{g_})-({pb}+{S_("s_pb")}*{shock2})', PCT)
        dsa.set('s_c', jj, f'={Q("s_c", p)}*(1+{r_}+{S_("s_i")}*MIN(1,{jj}/{S_("mat")}))/(1+{g_}+{S_("s_g")}*{shock2})'
                f'-({pb}+({S_("s_pb")}+{S_("s_g")}*{R("rev_pct", j)})*{shock2})', PCT)
        dsa.set('ig', jj, f'=({r_}-{g_})/(1+{g_})', PCT)
        dsa.set('stab', jj, f'={Q("base", p)}*{Q("ig", jj)}', PCT)
        dsa.set('gap', jj, f'={pb}-{Q("stab", jj)}', PCT)
        dsa.set('gfn', jj, f'=-{R("ob_pct", j)}+{Q("base", p)}/{S_("mat")}', PCT, bold=True)
        dsa.set('gfn_test', jj, f'=IF({Q("gfn", jj)}<={S_("gfn_lim")},"Within benchmark","Above benchmark")', '@')
        dsa.set('debt_test', jj, f'=IF({Q("base", jj)}<={S_("anchor")},"Within benchmark","Above benchmark")', '@')
    items = [('d0', f'Debt % GDP {periods[hi]}', f'={R("debt_pct", hi)}', PCT),
             ('d1', f'Debt % GDP {periods[FN]} (live scenario)', f'={R("debt_pct", FN)}', PCT),
             ('dmax', 'Highest debt % GDP under the stress tests', f'=MAX({dsa.span("s_g", 1, m - 1)},{dsa.span("s_i", 1, m - 1)},'
              f'{dsa.span("s_pb", 1, m - 1)},{dsa.span("s_c", 1, m - 1)})', PCT),
             ('pb', 'Average primary balance % GDP, forecast', f'=AVERAGE({fa.span("pb_pct", F0, FN)})', PCT),
             ('stab', 'Debt-stabilising primary balance, first forecast year', f'={Q("stab", 1)}', PCT),
             ('gfn', 'Peak gross financing needs % GDP', f'=MAX({dsa.span("gfn", 1, m - 1)})', PCT)]
    sections = _dashboard(wb, head, name_ref, items, (fa, ['debt_pct', 'pb_pct'], n, 'Debt and primary balance (% GDP)')) + [
        ('Historical Data', 'Historical fiscal and macroeconomic data - hard-coded inputs'),
        ('Scenario Inputs', 'Anchors, financing terms, stress settings and the scenario manager (inputs)'),
        ('Assumptions', 'Drivers from the historical years with the live scenario'),
        ('Fiscal Accounts', 'Revenue, expenditure, balances, debt roll-forward and ratios'),
        ('Debt Sustainability', 'Debt paths under four stress tests, r - g, stabilising balance and financing needs')]
    chk = [(f'Debt rolls forward ({periods[j]})', f'ROUND({R("debt", j)}-({R("d_open", j)}+{R("borrow", j)}+{R("sfa", j)}),3)')
           for j in range(1, n)] + [sw]
    desc = (f'Enterprise-wide fiscal model and debt sustainability analysis for {place}: revenue, expenditure, primary and '
            f'overall balances and debt over a {horizon}-year horizon, with growth, revenue-effort and interest scenarios, '
            'interest-growth dynamics, the debt-stabilising primary balance, gross financing needs and growth, interest, '
            'primary-balance and combined stress tests against prudential benchmarks.')
    return _finish(wb, KINDS['gov_fiscal'], place, desc, sections, chk, periods[hi])


# --- macroeconomic framework ----------------------------------------------------------------------------------------
def economy(e):
    yrs, nh = e['years'], len(e['years'])
    horizon = 10
    periods = [str(y) for y in yrs] + [f'{yrs[-1] + k}F' for k in range(1, horizon + 1)]
    n, hi, F0, FN = len(periods), nh - 1, nh, nh + horizon - 1
    wb = new_workbook()
    place = e['name']
    head = lambda t: f'{place} - {t}'  # noqa: E731

    def series(k, scale=100, default=None):
        v = e.get(k) or [None] * nh
        known = [x for x in v if x is not None]
        d = default if default is not None else (known[-1] if known else 0.0)
        return [round((x if x is not None else d) / scale, 5) for x in v]
    vals = {'gdp': [round(x / 1e9, 3) for x in e['gdp']], 'growth': series('growth'), 'defl': series('defl'),
            'c': series('c'), 'g': series('g'), 'i': series('i'), 'x': series('x'), 'm': series('m'),
            'ca': series('ca', default=0.0), 'unemp': series('unemp'), 'cpi': series('cpi'), 'pop': series('pop', 1e6)}
    rows = [('gdp', 'Nominal GDP (local currency, billions)'), ('growth', 'Real GDP growth'), ('defl', 'GDP deflator inflation'),
            ('c', 'Household consumption (% GDP)'), ('g', 'Government consumption (% GDP)'), ('i', 'Gross capital formation (% GDP)'),
            ('x', 'Exports (% GDP)'), ('m', 'Imports (% GDP)'), ('ca', 'Current account balance (% GDP)'),
            ('unemp', 'Unemployment rate'), ('cpi', 'Consumer price inflation'), ('pop', 'Population (millions)')]
    ds = data_sheet(wb, head('Historical macroeconomic data'), periods[:nh], rows, vals, unit='As stated')
    for key in ('growth', 'defl', 'c', 'g', 'i', 'x', 'm', 'ca', 'unemp', 'cpi'):
        for j in range(nh):
            ds.ws.cell(row=ds.rows[key], column=2 + j).number_format = PCT
    D = ds.ref
    si = Inputs(wb, 'Scenario Inputs', head('Macro framework settings and scenarios'))
    si.section('Anchors')
    si.add('pot', 'Potential real growth', 0.03, PCT)
    si.add('lt_pi', 'Inflation target', 0.03, PCT)
    si.add('nairu', 'Natural rate of unemployment', 0.05, PCT)
    si.add('okun', "Okun's law coefficient", 0.4, '0.00')
    si.add('pop_g', 'Population growth', 0.01, PCT)
    si.add('conv', 'Years for growth and inflation to reach their anchors', 5.0, '0')
    live, name_ref, sw = _scenario(wb, si, [('g', 'Real growth adjustment', (0.0, 0.01, -0.015), PCT),
                                            ('pi', 'Inflation adjustment', (0.0, -0.005, 0.02), PCT),
                                            ('inv', 'Investment ratio adjustment (% GDP)', (0.0, 0.01, -0.015), PCT)],
                                   names=('Base', 'Optimistic', 'Adverse'))
    S_ = si.ref
    asm = Sheet(wb, 'Assumptions', head('Drivers from the historical years with the live scenario'), ['Driver'])
    mf = Sheet(wb, 'Macro Framework', head('Macroeconomic framework (local currency, billions; live scenario)'), periods, nh,
               unit='Local currency, billions')
    for key, label, bold, sec in [
        ('t', 'Forecast year', False, 'Output and prices'), ('g', 'Real GDP growth', False, None), ('pi', 'GDP deflator inflation', False, None),
        ('gdp', 'Nominal GDP', True, None), ('real', 'Real GDP index (last historical year = 100)', False, None),
        ('c', 'Household consumption', False, 'Expenditure'), ('gc', 'Government consumption', False, None),
        ('inv', 'Gross capital formation', False, None), ('x', 'Exports', False, None), ('m', 'Imports', False, None),
        ('disc', 'Statistical discrepancy', False, None), ('sum', 'GDP by expenditure', True, None),
        ('nx', 'Net exports', False, 'External and savings'), ('ca', 'Current account balance', False, None),
        ('sav', 'National saving (investment + current account)', False, None), ('sav_pct', 'Saving % GDP', False, None),
        ('u', 'Unemployment rate', False, 'Labour market'), ('gap', 'Growth gap vs potential', False, None),
        ('pop', 'Population (millions)', False, 'Living standards'), ('gdppc', 'GDP per person (local currency, thousands)', False, None),
        ('pc_g', 'Real GDP per person growth', False, None), ('chk', 'Check: expenditure = GDP', False, 'Checks')]:
        mf.row(key, label, bold, section=sec)
    R = mf.ref
    share = lambda k: f'AVERAGE({ds.span(k, hi - 2, hi)})'  # noqa: E731
    for key, label, f in [
        ('g0', 'Starting real growth (median of last five years) + scenario', f'MEDIAN({mf.span("g", max(1, hi - 4), hi)})+{live["g"]}'),
        ('pi0', 'Starting inflation (last year) + scenario', f'{D("defl", hi)}+{live["pi"]}'),
        ('c', 'Household consumption % GDP', share('c')), ('gc', 'Government consumption % GDP', share('g')),
        ('inv', 'Investment % GDP + scenario', f'{share("i")}+{live["inv"]}'), ('x', 'Exports % GDP', share('x')),
        ('m', 'Imports % GDP', share('m')), ('ca_nx', 'Current account less net exports % GDP (income, transfers)',
                                              f'{share("ca")}-({share("x")}-{share("m")})')]:
        asm.row(key, label)
        asm.set(key, 0, f'={f}', PCT)
    A = lambda k: asm.ref(k, 0, absolute=True)  # noqa: E731
    for j in range(n):
        p, h = j - 1, j < nh
        if h:
            mf.set('g', j, f'={D("growth", j)}', PCT)
            mf.set('pi', j, f'={D("defl", j)}', PCT)
            mf.set('gdp', j, f'={D("gdp", j)}', BN, bold=True)
            for key, src in (('c', 'c'), ('gc', 'g'), ('inv', 'i'), ('x', 'x'), ('m', 'm'), ('ca', 'ca')):
                mf.set(key, j, f'={R("gdp", j)}*{D(src, j)}', BN)
            mf.set('disc', j, f'={R("gdp", j)}-({R("c", j)}+{R("gc", j)}+{R("inv", j)}+{R("x", j)}-{R("m", j)})', BN)
            mf.set('u', j, f'={D("unemp", j)}', PCT)
            mf.set('pop', j, f'={D("pop", j)}', '#,##0.00')
        else:
            mf.set('t', j, f'=N({R("t", p)})+1', '0')
            fade = f'MIN(1,{R("t", j)}/{S_("conv")})'
            mf.set('g', j, f'={A("g0")}+({S_("pot")}-{A("g0")})*{fade}', PCT)
            mf.set('pi', j, f'={A("pi0")}+({S_("lt_pi")}-{A("pi0")})*{fade}', PCT)
            mf.set('gdp', j, f'={R("gdp", p)}*(1+{R("g", j)})*(1+{R("pi", j)})', BN, bold=True)
            mf.set('inv', j, f'={R("gdp", j)}*{A("inv")}', BN)
            mf.set('x', j, f'={R("gdp", j)}*{A("x")}', BN)
            mf.set('m', j, f'={R("gdp", j)}*{A("m")}', BN)
            mf.set('gc', j, f'={R("gdp", j)}*{A("gc")}', BN)
            mf.set('disc', j, f'={R("t", j)}-{R("t", j)}', BN)
            # Household consumption closes the identity in the forecast.
            mf.set('c', j, f'={R("gdp", j)}-({R("gc", j)}+{R("inv", j)}+{R("x", j)}-{R("m", j)})-{R("disc", j)}', BN)
            mf.set('ca', j, f'={R("nx", j)}+{R("gdp", j)}*{A("ca_nx")}', BN)
            mf.set('u', j, f'=MAX(0,{R("u", p)}-{S_("okun")}*({R("g", j)}-{S_("pot")})+({S_("nairu")}-{R("u", p)})*0.2)', PCT)
            mf.set('pop', j, f'={R("pop", p)}*(1+{S_("pop_g")})', '#,##0.00')
        mf.set('real', j, f'=100*{R("gdp", j)}/{R("gdp", hi)}' if j == hi else
               (f'={R("real", j + 1)}/(1+{R("g", j + 1)})' if j < hi else f'={R("real", p)}*(1+{R("g", j)})'), '0.0')
        mf.set('sum', j, f'={R("c", j)}+{R("gc", j)}+{R("inv", j)}+{R("x", j)}-{R("m", j)}+{R("disc", j)}', BN, bold=True)
        mf.set('nx', j, f'={R("x", j)}-{R("m", j)}', BN)
        mf.set('sav', j, f'={R("inv", j)}+{R("ca", j)}', BN)
        mf.set('sav_pct', j, f'=IFERROR({R("sav", j)}/{R("gdp", j)},0)', PCT)
        mf.set('gap', j, f'={R("g", j)}-{S_("pot")}', PCT)
        mf.set('gdppc', j, f'=IFERROR({R("gdp", j)}/{R("pop", j)},0)', '#,##0.00')
        if j:
            mf.set('pc_g', j, f'=IFERROR(({R("real", j)}/{R("pop", j)})/({R("real", p)}/{R("pop", p)})-1,0)', PCT)
        mf.set('chk', j, f'=ROUND({R("sum", j)}-{R("gdp", j)},3)')
    items = [('g', 'Average real growth, forecast', f'=AVERAGE({mf.span("g", F0, FN)})', PCT),
             ('pi', 'Average inflation, forecast', f'=AVERAGE({mf.span("pi", F0, FN)})', PCT),
             ('gdp', f'Nominal GDP {periods[FN]} (billions)', f'={R("gdp", FN)}', BN),
             ('u', f'Unemployment {periods[FN]}', f'={R("u", FN)}', PCT),
             ('ca', 'Average current account % GDP, forecast', f'=SUM({mf.span("ca", F0, FN)})/SUM({mf.span("gdp", F0, FN)})', PCT),
             ('pc', 'Cumulative real income per person growth',
              f'=IFERROR(({R("real", FN)}/{R("pop", FN)})/({R("real", hi)}/{R("pop", hi)})-1,0)', PCT)]
    sections = _dashboard(wb, head, name_ref, items, (mf, ['gdp', 'sum'], n, 'Nominal GDP (billions)')) + [
        ('Historical Data', 'Historical macroeconomic data - hard-coded inputs'),
        ('Scenario Inputs', 'Potential growth, inflation target, labour-market settings and scenarios (inputs)'),
        ('Assumptions', 'Expenditure shares and starting points from history with the live scenario'),
        ('Macro Framework', 'Output, prices, expenditure, external balance, saving, unemployment and living standards')]
    chk = [(f'Expenditure adds up to GDP ({periods[j]})', R('chk', j)) for j in range(n)] + [sw]
    desc = (f'Enterprise-wide macroeconomic framework for {place}: {horizon}-year projection of real growth, prices and '
            'nominal GDP, GDP by expenditure (consumption, government, investment, exports and imports), the current '
            "account and national saving, unemployment through Okun's law, and income per person, with Base / "
            'Optimistic / Adverse scenarios.')
    return _finish(wb, KINDS['gov_economy'], place, desc, sections, chk, periods[hi])


# --- public investment project appraisal ----------------------------------------------------------------------------
BENEFIT = [(r'transport|road|rail|port|airport', 0.15), (r'energy|power|electric|renewable', 0.14),
           (r'water|sanitation|irrigation|flood', 0.12), (r'agricultur|fisher|forest|rural', 0.13),
           (r'health|nutrition|education|social|protection', 0.11), (r'urban|municipal|housing|digital|ict', 0.13)]


def project(e, market):
    a, cl = date.fromisoformat(e['approved']), date.fromisoformat(e['closing'])
    build_years = max(2, min(10, round((cl - a).days / 365.25)))
    life = 25
    horizon = build_years + life
    first = a.year
    periods = [str(first + k) for k in range(horizon + 1)]
    n = len(periods)
    rate = next((v for rx, v in BENEFIT if re.search(rx, e['sector'], re.I)), 0.125)
    wb = new_workbook()
    place = e['country']
    title = re.sub(r'\s+', ' ', e['name']).strip()
    head = lambda t: f'{title} - {t}'  # noqa: E731
    pi = Inputs(wb, 'Historical Data', head('Project facts'))
    pi.section('Project')
    pi.add('cost', 'Total project cost (USD millions)', round(e['cost'], 3), '#,##0.00')
    pi.add('loan', 'External loan financing (USD millions)', round(e['loan'], 3), '#,##0.00')
    pi.add('year0', 'Approval year', first, '0')
    pi.add('build', 'Implementation period (years)', build_years, '0')
    pi.ws.cell(row=pi.next_row + 1, column=1, value=f'Country: {place}').font = NOTE
    pi.ws.cell(row=pi.next_row + 2, column=1, value=f'Sector: {e["sector"]}').font = NOTE
    H = pi.ref
    ai = Inputs(wb, 'Project Inputs', head('Appraisal assumptions'))
    ai.section('Economic analysis')
    ai.add('sdr', 'Social discount rate', 0.06, PCT)
    ai.add('ben', 'Annual economic benefits at full capacity (% of capital cost)', rate, PCT, f'Typical for {e["sector"]} investments')
    ai.add('ramp', 'Years to reach full benefits after completion', 3.0, '0')
    ai.add('om', 'Operation and maintenance (% of capital cost per year)', 0.025, PCT)
    ai.add('scf', 'Standard conversion factor (shadow pricing of costs)', 0.9, '0.00')
    ai.add('life', 'Economic life after completion (years)', life, '0')
    ai.add('resid', 'Residual value at the end of the horizon (% of capital cost)', 0.10, PCT)
    ai.section('Disbursement profile')
    ai.add('peak', 'Disbursement curve shape (higher = more back-loaded)', 1.6, '0.00')
    ai.section('Loan terms')
    ai.add('ref', 'Reference rate', round(market.sofr, 4), PCT, 'Current secured overnight financing rate')
    ai.add('spread', 'Lending spread', 0.0085, PCT)
    ai.add('grace', 'Grace period (years from approval)', 5.0, '0')
    ai.add('mat', 'Final maturity (years from approval)', 20.0, '0')
    ai.add('fee', 'Commitment fee on undisbursed balance', 0.0025, PCT)
    ai.section('Sensitivity')
    ai.add('s_cost', 'Cost overrun test', 0.20, PCT)
    ai.add('s_ben', 'Benefit shortfall test', 0.20, PCT)
    ai.add('s_delay', 'Benefit delay test (years)', 2.0, '0')
    live, name_ref, sw = _scenario(wb, ai, [('cost', 'Capital cost multiplier', (1.0, 0.95, 1.25), '0.00"x"'),
                                            ('ben', 'Benefit multiplier', (1.0, 1.10, 0.80), '0.00"x"')],
                                   names=('Base', 'Favourable', 'Adverse'))
    P = ai.ref
    cf = Sheet(wb, 'Project Cash Flows', head('Disbursement, financing and economic flows (USD millions; live scenario)'),
               periods, None, unit='USD millions')
    for key, label, bold, sec in [
        ('t', 'Year from approval', False, 'Timing'), ('bld', 'Implementation year (1 = yes)', False, None),
        ('op', 'Operating year number', False, None),
        ('w', 'Disbursement weight', False, 'Capital cost'), ('capex', 'Capital expenditure', True, None),
        ('cum', 'Cumulative capital expenditure', False, None), ('pct', 'Physical progress', False, None),
        ('loan_d', 'Loan disbursement', False, 'Financing'), ('gov', 'Government counterpart funding', False, None),
        ('l_open', 'Loan - opening balance', False, 'Loan service'), ('l_rep', 'Loan - principal repayment', False, None),
        ('l_close', 'Loan - closing balance', True, None), ('l_int', 'Loan - interest', False, None),
        ('l_fee', 'Loan - commitment fee', False, None), ('l_serv', 'Total debt service', True, None),
        ('e_cost', 'Economic capital cost (shadow priced)', False, 'Economic analysis'), ('e_om', 'Operation & maintenance', False, None),
        ('e_ben', 'Economic benefits', False, None), ('e_res', 'Residual value', False, None),
        ('e_net', 'Net economic flow', True, None), ('df', 'Discount factor', False, None), ('pv', 'Present value', True, None),
        ('pv_ben', 'PV of benefits', False, None), ('pv_cost', 'PV of costs', False, None),
        ('s_cost', 'Net flow - cost overrun test', False, 'Sensitivity flows'), ('s_ben', 'Net flow - benefit shortfall test', False, None),
        ('s_delay', 'Net flow - benefit delay test', False, None)]:
        cf.row(key, label, bold, section=sec)
    C = cf.ref
    cost = f'{H("cost")}*{live["cost"]}'
    wsum = f'SUM({cf.span("w", 0, n - 1)})'
    for j in range(n):
        p = j - 1
        cf.set('t', j, f'={H("year0")}-{H("year0")}' if j == 0 else f'={C("t", p)}+1', '0')
        cf.set('bld', j, f'=IF({C("t", j)}<{H("build")},1,0)', '0')
        cf.set('op', j, f'=MAX(0,{C("t", j)}-{H("build")}+1)', '0')
        cf.set('w', j, f'={C("bld", j)}*(({C("t", j)}+1)^{P("peak")}-{C("t", j)}^{P("peak")})', '0.000')
        cf.set('capex', j, f'=IFERROR({cost}*{C("w", j)}/{wsum},0)', bold=True)
        cf.set('cum', j, f'=SUM({cf.span("capex", 0, j)})')
        cf.set('pct', j, f'=IFERROR({C("cum", j)}/({cost}),0)', PCT)
        cf.set('loan_d', j, f'={C("capex", j)}*{H("loan")}/{H("cost")}')
        cf.set('gov', j, f'={C("capex", j)}-{C("loan_d", j)}')
        cf.set('l_open', j, f'={C("l_close", p)}' if j else f'={C("t", j)}')
        cf.set('l_rep', j, f'=IF({C("t", j)}>={P("grace")},MIN({C("l_open", j)},{C("l_open", j)}/MAX(1,{P("mat")}-{C("t", j)})),0)')
        cf.set('l_close', j, f'={C("l_open", j)}+{C("loan_d", j)}-{C("l_rep", j)}', bold=True)
        cf.set('l_int', j, f'=({C("l_open", j)}+{C("loan_d", j)}/2)*({P("ref")}+{P("spread")})')
        cf.set('l_fee', j, f'=MAX(0,{H("loan")}*{live["cost"]}-SUM({cf.span("loan_d", 0, j)}))*{P("fee")}')
        cf.set('l_serv', j, f'={C("l_rep", j)}+{C("l_int", j)}+{C("l_fee", j)}', bold=True)
        ramp = f'MIN(1,{C("op", j)}/{P("ramp")})'
        cf.set('e_cost', j, f'=-{C("capex", j)}*{P("scf")}')
        cf.set('e_om', j, f'=-IF({C("op", j)}>0,{H("cost")}*{P("om")}*{P("scf")},0)')
        cf.set('e_ben', j, f'=IF({C("op", j)}>0,{H("cost")}*{P("ben")}*{live["ben"]}*{ramp},0)')
        cf.set('e_res', j, f'=IF({j}={n - 1},{H("cost")}*{P("resid")},0)' if j == n - 1 else f'={C("t", j)}-{C("t", j)}')
        cf.set('e_net', j, f'={C("e_cost", j)}+{C("e_om", j)}+{C("e_ben", j)}+{C("e_res", j)}', bold=True)
        cf.set('df', j, f'=1/(1+{P("sdr")})^{C("t", j)}', '0.0000')
        cf.set('pv', j, f'={C("e_net", j)}*{C("df", j)}', bold=True)
        cf.set('pv_ben', j, f'=({C("e_ben", j)}+{C("e_res", j)})*{C("df", j)}')
        cf.set('pv_cost', j, f'=-({C("e_cost", j)}+{C("e_om", j)})*{C("df", j)}')
        cf.set('s_cost', j, f'={C("e_net", j)}+{C("e_cost", j)}*{P("s_cost")}')
        cf.set('s_ben', j, f'={C("e_net", j)}-{C("e_ben", j)}*{P("s_ben")}')
        delayed = (f'IF({C("op", j)}>{P("s_delay")},{H("cost")}*{P("ben")}*{live["ben"]}*MIN(1,({C("op", j)}-{P("s_delay")})/{P("ramp")}),0)')
        cf.set('s_delay', j, f'={C("e_net", j)}-{C("e_ben", j)}+{delayed}')
    ea = Inputs(wb, 'Economic Analysis', head('Economic appraisal results'))
    rng = lambda k: cf.span(k, 0, n - 1)  # noqa: E731
    ea.section('Results (live scenario)')
    ea.add('enpv', 'Economic net present value (USD millions)', f'=SUM({rng("pv")})', '#,##0.00', formula=True)
    ea.add('eirr', 'Economic internal rate of return', f'=IFERROR(IRR({rng("e_net")}),0)', PCT, formula=True)
    ea.add('bcr', 'Benefit-cost ratio', f'=IFERROR(SUM({rng("pv_ben")})/SUM({rng("pv_cost")}),0)', '0.00', formula=True)
    ea.add('verdict', 'Decision rule (ENPV > 0 and EIRR > discount rate)',
           f'=IF(AND({ea.ref("enpv")}>0,{ea.ref("eirr")}>{P("sdr")}),"Economically viable","Not viable")', '@', formula=True)
    ea.section('Sensitivity')
    ea.add('npv_c', 'ENPV with cost overrun', f'=NPV({P("sdr")},{cf.span("s_cost", 1, n - 1)})+{C("s_cost", 0)}', '#,##0.00', formula=True)
    ea.add('npv_b', 'ENPV with benefit shortfall', f'=NPV({P("sdr")},{cf.span("s_ben", 1, n - 1)})+{C("s_ben", 0)}', '#,##0.00', formula=True)
    ea.add('npv_d', 'ENPV with benefit delay', f'=NPV({P("sdr")},{cf.span("s_delay", 1, n - 1)})+{C("s_delay", 0)}', '#,##0.00', formula=True)
    ea.add('sv_cost', 'Switching value: capital cost increase that sets ENPV to zero',
           f'=IFERROR({ea.ref("enpv")}/-SUMPRODUCT({rng("e_cost")},{rng("df")}),0)', PCT, formula=True)
    ea.add('sv_ben', 'Switching value: benefit decrease that sets ENPV to zero',
           f'=IFERROR({ea.ref("enpv")}/SUMPRODUCT({rng("e_ben")},{rng("df")}),0)', PCT, formula=True)
    ea.section('Financing')
    ea.add('loan_share', 'Loan share of project cost', f'=IFERROR({H("loan")}/{H("cost")},0)', PCT, formula=True)
    ea.add('int_total', 'Total interest and fees (USD millions)', f'=SUM({rng("l_int")})+SUM({rng("l_fee")})', '#,##0.00', formula=True)
    ea.add('peak_serv', 'Peak annual debt service (USD millions)', f'=MAX({rng("l_serv")})', '#,##0.00', formula=True)
    items = [('enpv', 'ENPV (USD millions)', f'={ea.ref("enpv")}', '#,##0.00'), ('eirr', 'EIRR', f'={ea.ref("eirr")}', PCT),
             ('bcr', 'Benefit-cost ratio', f'={ea.ref("bcr")}', '0.00'), ('verdict', 'Decision', f'={ea.ref("verdict")}', '@'),
             ('sv', 'Cost switching value', f'={ea.ref("sv_cost")}', PCT),
             ('serv', 'Peak debt service (USD millions)', f'={ea.ref("peak_serv")}', '#,##0.00')]
    sections = _dashboard(wb, head, name_ref, items, (cf, ['e_net'], n, 'Net economic flow (USD millions)')) + [
        ('Historical Data', 'Project cost, financing, approval year and implementation period - hard-coded inputs'),
        ('Project Inputs', 'Discount rate, benefits, O&M, shadow prices, disbursement shape, loan terms and scenarios (inputs)'),
        ('Project Cash Flows', 'Disbursement, financing, loan service and economic flows by year'),
        ('Economic Analysis', 'ENPV, EIRR, benefit-cost ratio, sensitivity tests and switching values')]
    chk = [('Disbursements equal project cost', f'SUM({rng("capex")})-{cost}'),
           ('Financing equals disbursements', f'SUM({rng("loan_d")})+SUM({rng("gov")})-SUM({rng("capex")})'),
           ('Loan fully repaid by the end of the horizon', f'{C("l_close", n - 1)}'),
           ('Disbursement weights are positive during implementation', f'IF(MIN({rng("w")})<0,1,0)'), sw]
    desc = (f'Enterprise-wide appraisal of the public investment project "{title}" in {place} ({e["sector"]}): disbursement '
            f'over a {build_years}-year implementation period, loan and counterpart financing with full loan service, '
            f'and an economic cost-benefit analysis over a {life}-year life (ENPV, EIRR, benefit-cost ratio) with cost, benefit '
            'and delay tests and switching values.')
    wbk = _finish(wb, KINDS['gov_project'], place, desc, sections, chk, periods[0])
    return wbk


def build(kind, entity, market):
    if kind == 'gov_population':
        return population(entity)
    if kind == 'gov_fiscal':
        return fiscal(entity)
    if kind == 'gov_economy':
        return economy(entity)
    return project(entity, market)


def file_label(kind, entity, wb):
    if kind == 'gov_project':
        sector = re.sub(r'[^A-Za-z&,\- ]', '', entity['sector'])[:40].strip()
        return f'Enterprise wide model - {KINDS[kind]} - {entity["country"]} - {sector} - {wb.asof}'
    return f'Enterprise wide model - {KINDS[kind]} - {entity["name"]} - {wb.asof}'
