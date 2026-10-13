"""Quarterly operating and FP&A model.

Quarterly actuals (Q1-Q3 from 10-Q filings, Q4 derived as full year less nine months), LTM
and year-over-year analysis, seasonality profile, an eight-quarter rolling forecast, a
budget-versus-actual variance analysis for the latest fiscal year, and a KPI summary.
"""
from . import xbrl
from .xl import (NUM, PCT, REDACTED, Inputs, Sheet, checks, col, cover, data_sheet, new_workbook)

CONCEPTS = [('revenue', 'Revenue'), ('cogs', 'Cost of revenue'), ('ebit', 'Operating income'), ('net_income', 'Net income')]


def build(facts, sector, **_):
    got = xbrl.quarterly(facts)
    if not got:
        return None
    ends, q = got
    ny = len(ends)
    for k in ('cogs', 'ebit'):
        if any(v is None for v in q[k]['fy']) or any(v is None for yr in q[k]['q'] for v in yr):
            if k == 'ebit':
                return None
            q[k] = {'q': [[0.0] * 3 for _ in range(ny)], 'fy': [0.0] * ny}
    if any(v is None or v <= 0 for v in q['revenue']['fy']):
        return None

    fy_labels = [f'FY{e[:4]}' for e in ends]
    rows, values = [], {}
    for key, label in CONCEPTS:
        for i, part in enumerate(['Q1', 'Q2', 'Q3']):
            rows.append((f'{key}_q{i + 1}', f'{label} - {part} (10-Q)'))
            values[f'{key}_q{i + 1}'] = [q[key]['q'][y][i] for y in range(ny)]
        rows.append((f'{key}_fy', f'{label} - full year (10-K)'))
        values[f'{key}_fy'] = q[key]['fy']
    wb = new_workbook()
    head = lambda t: f'{REDACTED} - {t}'  # noqa: E731
    ds = data_sheet(wb, head('Reported quarterly and annual figures'), [f'FY ended {e}' for e in ends], rows, values)
    D = ds.ref

    quarters = [f'Q{k + 1} {fy}' for fy in fy_labels for k in range(4)]
    nq = len(quarters)
    qa = Sheet(wb, 'Quarterly Actuals', head('Quarterly actuals (Q4 = full year less Q1-Q3)'), quarters)
    for key, label, bold, sec in [('revenue', 'Revenue', True, 'Income statement'), ('cogs', 'Cost of revenue', False, None),
                                  ('gross', 'Gross profit', True, None), ('opex', 'Operating expenses', False, None),
                                  ('ebit', 'Operating income', True, None), ('below', 'Interest, tax & other', False, None),
                                  ('ni', 'Net income', True, None),
                                  ('gm', 'Gross margin', False, 'Margins and growth'), ('opex_r', 'Opex % revenue', False, None),
                                  ('om', 'Operating margin', False, None), ('yoy', 'Revenue growth vs same quarter last year', False, None),
                                  ('ltm_rev', 'LTM revenue', True, 'Last twelve months'), ('ltm_ebit', 'LTM operating income', False, None),
                                  ('ltm_om', 'LTM operating margin', False, None)]:
        qa.row(key, label, bold, section=sec)
    Q = qa.ref
    src = {'revenue': 'revenue', 'cogs': 'cogs', 'ebit': 'ebit', 'ni': 'net_income'}
    for j in range(nq):
        y, k = divmod(j, 4)
        for key, concept in src.items():
            if k < 3:
                f = f'={D(f"{concept}_q{k + 1}", y)}'
            else:
                f = f'={D(f"{concept}_fy", y)}-{D(f"{concept}_q1", y)}-{D(f"{concept}_q2", y)}-{D(f"{concept}_q3", y)}'
            qa.set(key, j, f, bold=key in ('revenue', 'ebit', 'ni'))
        qa.set('gross', j, f'={Q("revenue", j)}-{Q("cogs", j)}', bold=True)
        qa.set('opex', j, f'={Q("gross", j)}-{Q("ebit", j)}')
        qa.set('below', j, f'={Q("ni", j)}-{Q("ebit", j)}')
        qa.set('gm', j, f'=IFERROR({Q("gross", j)}/{Q("revenue", j)},0)', PCT)
        qa.set('opex_r', j, f'=IFERROR({Q("opex", j)}/{Q("revenue", j)},0)', PCT)
        qa.set('om', j, f'=IFERROR({Q("ebit", j)}/{Q("revenue", j)},0)', PCT)
        if j >= 4:
            qa.set('yoy', j, f'=IFERROR({Q("revenue", j)}/{Q("revenue", j - 4)}-1,0)', PCT)
        if j >= 3:
            qa.set('ltm_rev', j, f'=SUM({qa.span("revenue", j - 3, j)})', bold=True)
            qa.set('ltm_ebit', j, f'=SUM({qa.span("ebit", j - 3, j)})')
            qa.set('ltm_om', j, f'=IFERROR({Q("ltm_ebit", j)}/{Q("ltm_rev", j)},0)', PCT)

    # Seasonality: each quarter's share of the year, per year and on average.
    se = Sheet(wb, 'Seasonality', head('Seasonality profile'), fy_labels + ['Average'], unit='Share of full-year figure / ratio')
    for k in range(4):
        se.row(f'share{k}', f'Q{k + 1} share of annual revenue', section='Revenue seasonality' if k == 0 else None)
    se.row('share_sum', 'Total', bold=True)
    for k in range(4):
        se.row(f'gm{k}', f'Q{k + 1} gross margin', section='Gross margin by quarter' if k == 0 else None)
    for k in range(4):
        se.row(f'opex{k}', f'Q{k + 1} opex % revenue', section='Operating expense ratio by quarter' if k == 0 else None)
    se.row('conv', 'Net income % operating income (full year)', section='Below the operating line')
    se.row('growth', 'Annual revenue growth')
    S = se.ref
    for y in range(ny):
        fy_rev = f'SUM({qa.span("revenue", 4 * y, 4 * y + 3)})'
        for k in range(4):
            j = 4 * y + k
            se.set(f'share{k}', y, f'=IFERROR({Q("revenue", j)}/{fy_rev},0)', PCT)
            se.set(f'gm{k}', y, f'={Q("gm", j)}', PCT)
            se.set(f'opex{k}', y, f'={Q("opex_r", j)}', PCT)
        se.set('share_sum', y, f'=SUM({se.span("share0", y, y).split("!")[1].split(":")[0]}:{col(y)}{se.rows["share3"]})', PCT, bold=True)
        se.set('conv', y, f'=IFERROR(SUM({qa.span("ni", 4 * y, 4 * y + 3)})/SUM({qa.span("ebit", 4 * y, 4 * y + 3)}),0)', PCT)
        if y:
            se.set('growth', y, f'=IFERROR(SUM({qa.span("revenue", 4 * y, 4 * y + 3)})/SUM({qa.span("revenue", 4 * y - 4, 4 * y - 1)})-1,0)', PCT)
    av = ny
    for key in [f'{p}{k}' for p in ('share', 'gm', 'opex') for k in range(4)] + ['conv']:
        se.set(key, av, f'=AVERAGE({se.span(key, 0, ny - 1)})', PCT, bold=True)
    se.set('share_sum', av, f'=SUM({col(av)}{se.rows["share0"]}:{col(av)}{se.rows["share3"]})', PCT, bold=True)
    se.set('growth', av, f'=IFERROR(MEDIAN({se.span("growth", 1, ny - 1)}),0)', PCT, bold=True)

    # Rolling forecast: next two fiscal years by quarter.
    last = int(ends[-1][:4])
    fc_years = [f'FY{last + 1}E', f'FY{last + 2}E']
    fq = [f'Q{k + 1} {fy}' for fy in fc_years for k in range(4)]
    rf = Sheet(wb, 'Rolling Forecast', head('Eight-quarter rolling forecast'), fq, 0)
    for key, label, bold in [('fy_rev', 'Full-year revenue target', False), ('revenue', 'Revenue', True), ('cogs', 'Cost of revenue', False),
                             ('gross', 'Gross profit', True), ('opex', 'Operating expenses', False), ('ebit', 'Operating income', True),
                             ('ni', 'Net income', True), ('om', 'Operating margin', False), ('yoy', 'Revenue growth vs same quarter last year', False)]:
        rf.row(key, label, bold)
    R = rf.ref
    G = S('growth', av)
    last_fy_rev = f'SUM({qa.span("revenue", nq - 4, nq - 1)})'
    for j in range(8):
        y, k = divmod(j, 4)
        rf.set('fy_rev', j, f'={last_fy_rev}*(1+{G})' if y == 0 else f'={last_fy_rev}*(1+{G})^2')
        rf.set('revenue', j, f'={R("fy_rev", j)}*{se.ref(f"share{k}", av, absolute=True)}', bold=True)
        rf.set('cogs', j, f'={R("revenue", j)}*(1-{se.ref(f"gm{k}", av, absolute=True)})')
        rf.set('gross', j, f'={R("revenue", j)}-{R("cogs", j)}', bold=True)
        rf.set('opex', j, f'={R("revenue", j)}*{se.ref(f"opex{k}", av, absolute=True)}')
        rf.set('ebit', j, f'={R("gross", j)}-{R("opex", j)}', bold=True)
        rf.set('ni', j, f'={R("ebit", j)}*{se.ref("conv", av, absolute=True)}', bold=True)
        rf.set('om', j, f'=IFERROR({R("ebit", j)}/{R("revenue", j)},0)', PCT)
        prior = Q('revenue', nq - 4 + j) if j < 4 else R('revenue', j - 4)
        rf.set('yoy', j, f'=IFERROR({R("revenue", j)}/{prior}-1,0)', PCT)

    # Budget vs actual for the latest fiscal year: budget = same quarter of the prior year
    # grown at the prior year's annual growth rate.
    va = Sheet(wb, 'Variance Analysis', head(f'Budget vs actual, {fy_labels[-1]}'), [f'Q{k + 1}' for k in range(4)] + ['Full year'])
    lines = [('revenue', 'Revenue', 1), ('gross', 'Gross profit', 1), ('opex', 'Operating expenses', -1), ('ebit', 'Operating income', 1)]
    for key, label, _ in lines:
        va.row(f'{key}_a', f'{label} - actual', bold=True, section=label)
        va.row(f'{key}_b', f'{label} - budget')
        va.row(f'{key}_v', 'Variance')
        va.row(f'{key}_p', 'Variance %')
        va.row(f'{key}_f', 'Favourable / unfavourable')
    V = va.ref
    budget_growth = S('growth', ny - 2) if ny >= 3 else G
    for key, label, sign in lines:
        for k in range(5):
            if k < 4:
                j = nq - 4 + k
                va.set(f'{key}_a', k, f'={Q(key, j)}', bold=True)
                if key == 'revenue':
                    va.set(f'{key}_b', k, f'={Q("revenue", j - 4)}*(1+{budget_growth})')
                else:
                    ratio = f'IFERROR({Q(key, j - 4)}/{Q("revenue", j - 4)},0)'
                    va.set(f'{key}_b', k, f'={V("revenue_b", k)}*{ratio}')
            else:
                va.set(f'{key}_a', k, f'=SUM({va.span(f"{key}_a", 0, 3)})', bold=True)
                va.set(f'{key}_b', k, f'=SUM({va.span(f"{key}_b", 0, 3)})')
            va.set(f'{key}_v', k, f'={V(f"{key}_a", k)}-{V(f"{key}_b", k)}')
            va.set(f'{key}_p', k, f'=IFERROR({V(f"{key}_v", k)}/ABS({V(f"{key}_b", k)}),0)', PCT)
            cond = f'{V(f"{key}_v", k)}>=0' if sign > 0 else f'{V(f"{key}_v", k)}<=0'
            va.set(f'{key}_f', k, f'=IF({cond},"Favourable","Unfavourable")', 'General')

    # KPI summary
    kp = Inputs(wb, 'KPI Summary', head('Key performance indicators'))
    lq = nq - 1
    kp.section(f'Latest twelve months (to Q4 {fy_labels[-1]})')
    kp.add('ltm_rev', 'LTM revenue', f'={Q("ltm_rev", lq)}', NUM, formula=True)
    kp.add('ltm_growth', 'LTM revenue growth', f'=IFERROR({Q("ltm_rev", lq)}/{Q("ltm_rev", lq - 4)}-1,0)' if lq - 4 >= 3 else f'={G}', PCT, formula=True)
    kp.add('ltm_gm', 'LTM gross margin', f'=IFERROR(SUM({qa.span("gross", lq - 3, lq)})/{Q("ltm_rev", lq)},0)', PCT, formula=True)
    kp.add('ltm_om', 'LTM operating margin', f'={Q("ltm_om", lq)}', PCT, formula=True)
    kp.section('Forecast')
    for i, fy in enumerate(fc_years):
        kp.add(f'fc_rev{i}', f'{fy} revenue', f'=SUM({rf.span("revenue", 4 * i, 4 * i + 3)})', NUM, formula=True)
        kp.add(f'fc_ebit{i}', f'{fy} operating income', f'=SUM({rf.span("ebit", 4 * i, 4 * i + 3)})', NUM, formula=True)
    kp.section('Latest fiscal year vs budget')
    kp.add('var_rev', 'Revenue variance %', f'={V("revenue_p", 4)}', PCT, formula=True)
    kp.add('var_ebit', 'Operating income variance %', f'={V("ebit_p", 4)}', PCT, formula=True)

    items = [(f'Quarters add up to reported full year revenue ({fy_labels[y]})',
              f'SUM({qa.span("revenue", 4 * y, 4 * y + 3)})-{D("revenue_fy", y)}') for y in range(ny)]
    items += [('Seasonality shares sum to 100%', f'({S("share_sum", av)}-1)*100'),
              ('Forecast quarters add up to annual target (year 1)', f'SUM({rf.span("revenue", 0, 3)})-{R("fy_rev", 0)}'),
              ('Forecast quarters add up to annual target (year 2)', f'SUM({rf.span("revenue", 4, 7)})-{R("fy_rev", 4)}')]
    checks(wb, items)
    cover(wb, 'Quarterly operating & FP&A model', sector,
          'Operating model on quarterly data from 10-Q and 10-K filings: quarterly P&L with Q4 derived from the annual '
          'figures, LTM and year-over-year trends, a seasonality profile, an eight-quarter rolling forecast, a budget-versus-'
          'actual variance analysis for the latest fiscal year and a KPI summary.',
          [('Historical Data', 'Reported quarterly (10-Q) and annual (10-K) figures - hard-coded source data'),
           ('Quarterly Actuals', 'Quarterly P&L, margins, growth and LTM'),
           ('Seasonality', 'Quarterly revenue shares, margins and cost ratios'),
           ('Rolling Forecast', 'Next eight quarters'),
           ('Variance Analysis', 'Budget vs actual by quarter for the latest fiscal year'),
           ('KPI Summary', 'Headline metrics'),
           ('Checks', 'Integrity checks')])
    wb.properties.title = f'{REDACTED} - Quarterly operating & FP&A model'
    wb.properties.creator = REDACTED
    return wb
