"""Linked three-statement model (income statement, balance sheet, cash flow) with a
five-year forecast, revolver and minimum-cash logic, ratios, checks, and an FFO/AFFO
schedule for REITs.

Reported figures sit only on 'Historical Data'. Historical statement lines read that sheet
(with reconciling lines computed so every subtotal ties to the reported totals); every
forecast line runs off 'Assumptions', whose drivers are formulas over the historical years.
"""
from . import xbrl
from .xl import (BOLD, NOTE, NUM, PCT, REDACTED, Sheet, checks, col, cover, data_sheet, new_workbook, scenario_inputs)

FORECAST_YEARS = 5

DATA_ROWS = [
    ('revenue', 'Revenue'), ('cogs', 'Cost of revenue'), ('ebit', 'Operating income'),
    ('interest', 'Interest expense'), ('pretax', 'Pre-tax income'), ('tax', 'Income tax expense'),
    ('net_income', 'Net income'), ('cash', 'Cash and equivalents'), ('ar', 'Accounts receivable'),
    ('inventory', 'Inventory'), ('assets_current', 'Total current assets'), ('ppe', 'PP&E and real estate, net'),
    ('assets', 'Total assets'), ('ap', 'Accounts payable'), ('liabilities_current', 'Total current liabilities'),
    ('debt', 'Long-term debt'), ('liabilities', 'Total liabilities'), ('equity', "Shareholders' equity"),
    ('da', 'Depreciation & amortisation'), ('cfo', 'Cash from operations'), ('cfi', 'Cash from investing'),
    ('cff', 'Cash from financing'), ('capex', 'Capital expenditure'), ('dividends', 'Dividends paid'),
    ('buybacks', 'Share repurchases'), ('st_debt', 'Short-term borrowings'),
]
REIT_ROWS = [('re_da', 'Real estate depreciation & amortisation'), ('gain_re', 'Gains on sale of real estate')]


def prepare(facts, max_years=6):
    """Annual data with derivable gaps filled, or None when the filings are too thin."""
    got = xbrl.annual(facts, max_years=max_years)
    if not got:
        return None
    ends, d = got
    n = len(ends)
    for i in range(n):
        for k in ('cogs', 'interest', 'ar', 'inventory', 'ppe', 'ap', 'debt', 'da', 'capex', 'dividends', 'tax',
                  'buybacks', 'cfi', 'cff', 're_da', 'gain_re', 'st_debt'):
            if d[k][i] is None:
                d[k][i] = 0.0
        if d['pretax'][i] is None:
            d['pretax'][i] = round(d['net_income'][i] + d['tax'][i], 3)
        if d['ebit'][i] is None:
            d['ebit'][i] = round(d['pretax'][i] + d['interest'][i], 3)
        if d['assets_current'][i] is None:
            d['assets_current'][i] = round(d['cash'][i] + d['ar'][i] + d['inventory'][i], 3)
        if d['liabilities_current'][i] is None:
            d['liabilities_current'][i] = d['ap'][i]
        if d['liabilities'][i] is None:
            te = d['equity_total'][i]
            d['liabilities'][i] = round(d['assets'][i] - (te if te is not None else d['equity'][i]), 3)
        if d['re_net'][i]:
            d['ppe'][i] = round(d['ppe'][i] + d['re_net'][i], 3)
    if any(v is None or v <= 0 for v in d['revenue']) or d['assets'][-1] <= 0:
        return None
    return ends, d


def build(facts, sector, is_reit=False, years=FORECAST_YEARS, trim=0, extend=None, title=None, description=None, deep=False):
    """years: forecast length; trim: drop the latest reported years (an earlier as-of date);
    extend(wb, ctx) -> (sections, check items) adds modules that build on the three statements.
    deep: keep every consecutive reported year (drivers still use the latest five)."""
    got = prepare(facts, 40 if deep else 6)
    if not got:
        return None
    ends, data = got
    if trim:
        if len(ends) - trim < 3:
            return None
        ends, data = ends[:-trim], {k: v[:-trim] for k, v in data.items()}
        if any(v is None or v <= 0 for v in data['revenue']) or data['assets'][-1] <= 0:
            return None
    FORECAST_YEARS = years  # noqa: N806
    nh = len(ends)
    last = int(ends[-1][:4])
    # Bases for two drivers, chosen here so the workbook needs no threshold constants: when the
    # tagged debt is too small to explain the interest bill (or PP&E too small for the D&A),
    # the ratio would be meaningless, so a broader base is used instead.
    sum_ = lambda k, a=0, b=None: sum(data[k][a:b])  # noqa: E731
    debt_wide = sum_('debt') <= 0 or sum_('interest') / max(sum_('debt'), 1e-9) > 0.2
    da_on_rev = sum_('ppe', 0, -1) <= 0 or sum_('da', 1) / max(sum_('ppe', 0, -1), 1e-9) > 0.5
    periods = [f'FY{e[:4]}A' for e in ends] + [f'FY{last + k}E' for k in range(1, FORECAST_YEARS + 1)]
    n = len(periods)
    H, F = range(nh), range(nh, n)
    wb = new_workbook()
    heading = lambda t: f'{REDACTED} - {t}'  # noqa: E731

    rows = DATA_ROWS + (REIT_ROWS if is_reit else [])
    ds = data_sheet(wb, heading('Reported figures (Form 10-K)'), [e for e in ends], rows, data)
    D = lambda k, j: ds.ref(k, j)  # noqa: E731

    si = scenario_inputs(wb, heading('Scenario inputs'))
    asm = Sheet(wb, 'Assumptions', heading('Forecast drivers (derived from the historical years)'), ['Driver'])
    is_ = Sheet(wb, 'Income Statement', heading('Income Statement'), periods, nh)
    bs = Sheet(wb, 'Balance Sheet', heading('Balance Sheet'), periods, nh)
    cf = Sheet(wb, 'Cash Flow', heading('Cash Flow Statement'), periods, nh)
    rt = Sheet(wb, 'Ratios', heading('Key ratios'), periods, nh)

    for key, label, bold in [('revenue', 'Revenue', True), ('growth', '  growth %', False), ('cogs', 'Cost of revenue', False),
                             ('gross', 'Gross profit', True), ('opex', 'Operating expenses', False),
                             ('ebit', 'Operating income (EBIT)', True), ('interest', 'Interest expense', False),
                             ('other', 'Other income (expense)', False), ('pretax', 'Pre-tax income', True),
                             ('tax', 'Income tax expense', False), ('ato', 'Discontinued ops, minority interest & other', False),
                             ('net_income', 'Net income', True)]:
        is_.row(key, label, bold)
    is_.row('yr', 'Memo: forecast year', gap_before=True)
    is_.row('da', 'Memo: depreciation & amortisation')
    is_.row('ebitda', 'Memo: EBITDA', bold=True)

    for key, label, bold, sec in [('cash', 'Cash and equivalents', False, 'Assets'), ('ar', 'Accounts receivable', False, None),
                                  ('inventory', 'Inventory', False, None), ('oca', 'Other current assets', False, None),
                                  ('tca', 'Total current assets', True, None), ('ppe', 'PP&E, net', False, None),
                                  ('onca', 'Other non-current assets', False, None), ('ta', 'Total assets', True, None),
                                  ('ap', 'Accounts payable', False, 'Liabilities & equity'),
                                  ('ocl', 'Other current liabilities', False, None), ('tcl', 'Total current liabilities', True, None),
                                  ('revolver', 'Revolver / short-term borrowings', False, None), ('debt', 'Long-term debt', False, None),
                                  ('oncl', 'Other non-current liabilities', False, None), ('tl', 'Total liabilities', True, None),
                                  ('equity', "Shareholders' equity", False, None),
                                  ('nci', 'Non-controlling interest & other equity', False, None),
                                  ('te', 'Total equity', True, None), ('tle', 'Total liabilities & equity', True, None)]:
        bs.row(key, label, bold, section=sec)
    bs.row('check', 'Balance check (assets - liabilities & equity)', gap_before=True)

    for key, label, bold, sec in [('ni', 'Net income', False, 'Operating activities'), ('da', 'Depreciation & amortisation', False, None),
                                  ('wc', 'Working capital & other operating items', False, None),
                                  ('cfo', 'Cash from operations', True, None),
                                  ('capex', 'Capital expenditure', False, 'Investing activities'),
                                  ('oinv', 'Other investing', False, None), ('cfi', 'Cash from investing', True, None),
                                  ('div', 'Dividends paid', False, 'Financing activities'),
                                  ('ofin', 'Debt & other financing', False, None),
                                  ('avail', 'Memo: cash available before repurchases', False, None),
                                  ('buyback', 'Share repurchases (from surplus cash only)', False, None),
                                  ('pre', 'Memo: cash before revolver', False, None),
                                  ('draw', 'Revolver draw / (repayment)', False, None), ('cff', 'Cash from financing', True, None),
                                  ('net', 'Net change in cash', True, 'Cash reconciliation'),
                                  ('fx', 'FX, restricted cash & other reconciling items', False, None),
                                  ('end', 'Closing cash', True, None),
                                  ('check', 'Cash check (closing cash - balance sheet)', False, None)]:
        cf.row(key, label, bold, section=sec)

    for key, label in [('gm', 'Gross margin'), ('em', 'EBITDA margin'), ('om', 'EBIT margin'), ('nm', 'Net margin'),
                       ('roe', 'Return on average equity'), ('roa', 'Return on average assets'),
                       ('cr', 'Current ratio (x)'), ('lev', 'Total debt / EBITDA (x)'), ('cov', 'EBITDA / interest (x)'),
                       ('cash_pct', 'Cash % revenue'), ('fcf', 'Free cash flow (CFO - capex)'), ('fcf_m', 'FCF margin')]:
        rt.row(key, label)

    I = lambda k, j: is_.ref(k, j)  # noqa: E731,E741
    B = lambda k, j: bs.ref(k, j)  # noqa: E731
    C = lambda k, j: cf.ref(k, j)  # noqa: E731
    R = lambda k, j: rt.ref(k, j)  # noqa: E731
    hi = nh - 1
    w0 = max(0, nh - 5)  # drivers come from the latest five reported years; older years are shown for context
    w1 = max(1, w0)
    Ih = lambda k, j0=w0: is_.span(k, j0, hi)  # noqa: E731
    Bh = lambda k, j0=w0: bs.span(k, j0, hi)  # noqa: E731
    Ch = lambda k, j0=w0: cf.span(k, j0, hi)  # noqa: E731

    drivers = [
        ('growth', 'Starting revenue growth (historical median, within the scenario limits)',
         f'MAX({si.ref("floor")},MIN({si.ref("cap")},IFERROR(MEDIAN({Ih("growth", w1)}),0)))'),
        ('cogs_pct', 'Cost of revenue % revenue', f'IFERROR(SUM({Ih("cogs")})/SUM({Ih("revenue")}),0)'),
        ('opex_pct', 'Operating expenses % revenue', f'IFERROR(SUM({Ih("opex")})/SUM({Ih("revenue")}),0)'),
        ('other_pct', 'Other income % revenue', f'IFERROR(SUM({Ih("other")})/SUM({Ih("revenue")}),0)'),
        ('int_rate', 'Interest rate on debt and other non-current liabilities' if debt_wide else 'Interest rate on debt',
         f'IFERROR(SUM({Ih("interest")})/(SUM({Bh("debt")})+SUM({Bh("oncl")})),0)' if debt_wide
         else f'IFERROR(SUM({Ih("interest")})/SUM({Bh("debt")}),0)'),
        ('tax_rate', 'Effective tax rate', f'MAX(0,MIN(1,IFERROR(SUM({Ih("tax")})/SUM({Ih("pretax")}),0)))'),
        ('ar_pct', 'Receivables % revenue', f'IFERROR(SUM({Bh("ar")})/SUM({Ih("revenue")}),0)'),
        ('inv_pct', 'Inventory % cost of revenue', f'IFERROR(SUM({Bh("inventory")})/SUM({Ih("cogs")}),0)'),
        ('oca_pct', 'Other current assets % revenue', f'IFERROR(SUM({Bh("oca")})/SUM({Ih("revenue")}),0)'),
        ('ap_pct', 'Payables % cost of revenue', f'IFERROR(SUM({Bh("ap")})/SUM({Ih("cogs")}),0)'),
        ('ocl_pct', 'Other current liabilities % revenue', f'IFERROR(SUM({Bh("ocl")})/SUM({Ih("revenue")}),0)'),
        ('capex_pct', 'Capital expenditure % revenue', f'IFERROR(-SUM({Ch("capex")})/SUM({Ih("revenue")}),0)'),
        ('dep_rate', 'D&A % revenue', f'IFERROR(SUM({Ch("da")})/SUM({Ih("revenue")}),0)') if da_on_rev else
        ('dep_rate', 'D&A % opening PP&E', f"IFERROR(SUM({Ch('da', w1)})/SUM({bs.span('ppe', w1 - 1, hi - 1)}),0)"),
        ('payout', 'Dividend payout % net income', f'MAX(0,MIN(1,IFERROR(-SUM({Ch("div")})/SUM({Ih("net_income")}),0)))'),
        ('buyback', 'Share repurchases % net income', f'MAX(0,MIN(1,IFERROR(-SUM({Ch("buyback")})/SUM({Ih("net_income")}),0)))'),
        ('min_cash', 'Minimum cash % revenue (lowest historical level)', f'MAX(0,MIN({rt.span("cash_pct", 0, hi)}))'),
    ]
    for key, label, f in drivers:
        asm.row(key, label)
        asm.set(key, 0, f'={f}', PCT)
    asm.ws.cell(row=asm.next_row + 1, column=1,
                value='Long-term debt, other non-current items and non-controlling interest are held at the last reported level; '
                      'share repurchases follow the historical ratio but only out of cash above the minimum; '
                      'the revolver funds any shortfall below minimum cash and is repaid from surplus cash.').font = NOTE
    A = lambda k: asm.ref(k, 0, absolute=True)  # noqa: E731

    for j in range(n):
        p, h = j - 1, j < nh
        # Income statement
        if not h:
            is_.set('yr', j, f'=N({I("yr", p)})+1', '0')
        is_.set('revenue', j, f'={D("revenue", j)}' if h else f'={I("revenue", p)}*(1+{I("growth", j)})', bold=True)
        if j:
            is_.set('growth', j, f'=IFERROR({I("revenue", j)}/{I("revenue", p)}-1,0)' if h else
                    f'={A("growth")}+({si.ref("lt")}-{A("growth")})*{I("yr", j)}/{FORECAST_YEARS}', PCT)
        is_.set('cogs', j, f'={D("cogs", j)}' if h else f'={I("revenue", j)}*{A("cogs_pct")}')
        is_.set('gross', j, f'={I("revenue", j)}-{I("cogs", j)}', bold=True)
        is_.set('opex', j, f'={I("gross", j)}-{D("ebit", j)}' if h else f'={I("revenue", j)}*{A("opex_pct")}')
        is_.set('ebit', j, f'={I("gross", j)}-{I("opex", j)}', bold=True)
        is_.set('interest', j, f'={D("interest", j)}' if h else (f'=({B("debt", p)}+{B("oncl", p)}+{B("revolver", p)})*{A("int_rate")}' if debt_wide
                                                                     else f'=({B("debt", p)}+{B("revolver", p)})*{A("int_rate")}'))
        is_.set('other', j, f'={D("pretax", j)}-({I("ebit", j)}-{I("interest", j)})' if h else f'={I("revenue", j)}*{A("other_pct")}')
        is_.set('pretax', j, f'={I("ebit", j)}-{I("interest", j)}+{I("other", j)}', bold=True)
        is_.set('tax', j, f'={D("tax", j)}' if h else f'=MAX(0,{I("pretax", j)})*{A("tax_rate")}')
        if h:
            is_.set('ato', j, f'={D("net_income", j)}-({I("pretax", j)}-{I("tax", j)})')
            is_.set('net_income', j, f'={I("pretax", j)}-{I("tax", j)}+{I("ato", j)}', bold=True)
        else:
            is_.set('net_income', j, f'={I("pretax", j)}-{I("tax", j)}', bold=True)
        is_.set('da', j, f'={C("da", j)}')
        is_.set('ebitda', j, f'={I("ebit", j)}+{I("da", j)}', bold=True)

        # Balance sheet
        if h:
            bs.set('cash', j, f'={D("cash", j)}')
            bs.set('ar', j, f'={D("ar", j)}')
            bs.set('inventory', j, f'={D("inventory", j)}')
            bs.set('oca', j, f'={D("assets_current", j)}-{B("cash", j)}-{B("ar", j)}-{B("inventory", j)}')
            bs.set('ppe', j, f'={D("ppe", j)}')
            bs.set('onca', j, f'={D("assets", j)}-{B("tca", j)}-{B("ppe", j)}')
            bs.set('ap', j, f'={D("ap", j)}')
            bs.set('ocl', j, f'={D("liabilities_current", j)}-{B("ap", j)}-{B("revolver", j)}')
            bs.set('revolver', j, f'={D("st_debt", j)}')
            bs.set('debt', j, f'={D("debt", j)}')
            bs.set('oncl', j, f'={D("liabilities", j)}-{B("tcl", j)}-{B("debt", j)}-{B("revolver", j)}')
            bs.set('equity', j, f'={D("equity", j)}')
            bs.set('nci', j, f'={B("ta", j)}-{B("tl", j)}-{B("equity", j)}')
        else:
            bs.set('cash', j, f'={B("cash", p)}+{C("net", j)}')
            bs.set('ar', j, f'={I("revenue", j)}*{A("ar_pct")}')
            bs.set('inventory', j, f'={I("cogs", j)}*{A("inv_pct")}')
            bs.set('oca', j, f'={I("revenue", j)}*{A("oca_pct")}')
            bs.set('ppe', j, f'={B("ppe", p)}-{C("capex", j)}-{C("da", j)}')
            bs.set('onca', j, f'={B("onca", p)}')
            bs.set('ap', j, f'={I("cogs", j)}*{A("ap_pct")}')
            bs.set('ocl', j, f'={I("revenue", j)}*{A("ocl_pct")}')
            bs.set('revolver', j, f'={B("revolver", p)}+{C("draw", j)}')
            bs.set('debt', j, f'={B("debt", p)}')
            bs.set('oncl', j, f'={B("oncl", p)}')
            bs.set('equity', j, f'={B("equity", p)}+{I("net_income", j)}+{C("div", j)}+{C("buyback", j)}')
            bs.set('nci', j, f'={B("nci", p)}')
        bs.set('tca', j, f'=SUM({col(j)}{bs.rows["cash"]}:{col(j)}{bs.rows["oca"]})', bold=True)
        bs.set('ta', j, f'={B("tca", j)}+{B("ppe", j)}+{B("onca", j)}', bold=True)
        bs.set('tcl', j, f'={B("ap", j)}+{B("ocl", j)}', bold=True)  # revolver shown separately below
        bs.set('tl', j, f'={B("tcl", j)}+{B("revolver", j)}+{B("debt", j)}+{B("oncl", j)}', bold=True)
        bs.set('te', j, f'={B("equity", j)}+{B("nci", j)}', bold=True)
        bs.set('tle', j, f'={B("tl", j)}+{B("te", j)}', bold=True)
        bs.set('check', j, f'=ROUND({B("ta", j)}-{B("tle", j)},3)')

        # Cash flow
        cf.set('ni', j, f'={I("net_income", j)}')
        if h:
            cf.set('da', j, f'={D("da", j)}')
            cf.set('wc', j, f'={D("cfo", j)}-{C("ni", j)}-{C("da", j)}')
            cf.set('capex', j, f'=-{D("capex", j)}')
            cf.set('oinv', j, f'={D("cfi", j)}-{C("capex", j)}')
            cf.set('div', j, f'=-{D("dividends", j)}')
            cf.set('buyback', j, f'=-{D("buybacks", j)}')
            if j:
                cf.set('draw', j, f'={B("revolver", j)}-{B("revolver", p)}')
                cf.set('avail', j, f'={B("cash", p)}+{C("cfo", j)}+{C("cfi", j)}+{C("div", j)}+{C("ofin", j)}')
                cf.set('pre', j, f'={C("avail", j)}+{C("buyback", j)}')
                cf.set('ofin', j, f'={D("cff", j)}-{C("div", j)}-{C("buyback", j)}-{C("draw", j)}')
            else:
                cf.set('ofin', j, f'={D("cff", j)}-{C("div", j)}-{C("buyback", j)}')
        else:
            cf.set('da', j, f'={I("revenue", j)}*{A("dep_rate")}' if da_on_rev else f'={B("ppe", p)}*{A("dep_rate")}')
            cf.set('wc', j, f'=-({B("ar", j)}-{B("ar", p)})-({B("inventory", j)}-{B("inventory", p)})-({B("oca", j)}-{B("oca", p)})'
                              f'+({B("ap", j)}-{B("ap", p)})+({B("ocl", j)}-{B("ocl", p)})')
            cf.set('capex', j, f'=-{I("revenue", j)}*{A("capex_pct")}')
            cf.set('oinv', j, f'=-({B("onca", j)}-{B("onca", p)})')
            cf.set('div', j, f'=-MAX(0,{I("net_income", j)})*{A("payout")}')
            cf.set('ofin', j, f'=({B("debt", j)}-{B("debt", p)})+({B("oncl", j)}-{B("oncl", p)})+({B("nci", j)}-{B("nci", p)})')
            cf.set('avail', j, f'={B("cash", p)}+{C("cfo", j)}+{C("cfi", j)}+{C("div", j)}+{C("ofin", j)}')
            cf.set('buyback', j, f'=-MAX(0,MIN(MAX(0,{I("net_income", j)})*{A("buyback")},{C("avail", j)}-{I("revenue", j)}*{A("min_cash")}))')
            cf.set('pre', j, f'={C("avail", j)}+{C("buyback", j)}')
            cf.set('draw', j, f'=MAX(-{B("revolver", p)},{I("revenue", j)}*{A("min_cash")}-{C("pre", j)})')
        cf.set('cfo', j, f'={C("ni", j)}+{C("da", j)}+{C("wc", j)}', bold=True)
        cf.set('cfi', j, f'={C("capex", j)}+{C("oinv", j)}', bold=True)
        cf.set('cff', j, f'={C("div", j)}+{C("buyback", j)}+{C("ofin", j)}+{C("draw", j)}', bold=True)
        cf.set('net', j, f'={C("cfo", j)}+{C("cfi", j)}+{C("cff", j)}', bold=True)
        if j:
            cf.set('fx', j, f'={B("cash", j)}-{B("cash", p)}-{C("net", j)}')
            cf.set('end', j, f'={B("cash", p)}+{C("net", j)}+{C("fx", j)}', bold=True)
            cf.set('check', j, f'=ROUND({C("end", j)}-{B("cash", j)},3)')

        # Ratios
        rt.set('gm', j, f'=IFERROR({I("gross", j)}/{I("revenue", j)},0)', PCT)
        rt.set('em', j, f'=IFERROR({I("ebitda", j)}/{I("revenue", j)},0)', PCT)
        rt.set('om', j, f'=IFERROR({I("ebit", j)}/{I("revenue", j)},0)', PCT)
        rt.set('nm', j, f'=IFERROR({I("net_income", j)}/{I("revenue", j)},0)', PCT)
        if j:
            rt.set('roe', j, f'=IFERROR({I("net_income", j)}/AVERAGE({B("equity", p)},{B("equity", j)}),0)', PCT)
            rt.set('roa', j, f'=IFERROR({I("net_income", j)}/AVERAGE({B("ta", p)},{B("ta", j)}),0)', PCT)
        rt.set('cr', j, f'=IFERROR({B("tca", j)}/{B("tcl", j)},0)', '0.00"x"')
        rt.set('lev', j, f'=IFERROR(({B("debt", j)}+{B("revolver", j)})/{I("ebitda", j)},0)', '0.0"x"')
        rt.set('cov', j, f'=IFERROR({I("ebitda", j)}/{I("interest", j)},0)', '0.0"x"')
        rt.set('cash_pct', j, f'=IFERROR({B("cash", j)}/{I("revenue", j)},0)', PCT)
        rt.set('fcf', j, f'={C("cfo", j)}+{C("capex", j)}', NUM)
        rt.set('fcf_m', j, f'=IFERROR({R("fcf", j)}/{I("revenue", j)},0)', PCT)

    sections = [('Historical Data', 'Reported annual figures from Form 10-K XBRL (USD millions) - hard-coded source data'),
                ('Scenario Inputs', 'Long-term growth and limits on starting growth (inputs)'),
                ('Assumptions', 'Forecast drivers, each calculated from the historical years'),
                ('Income Statement', 'Historical and forecast income statement'),
                ('Balance Sheet', 'Historical and forecast balance sheet with revolver'),
                ('Cash Flow', 'Indirect cash flow statement with minimum-cash revolver logic'),
                ('Ratios', 'Profitability, returns, liquidity, leverage and cash conversion')]
    check_items = [(f'Balance sheet balances ({periods[j]})', B('check', j)) for j in range(n)]
    check_items += [(f'Cash flow ties to balance sheet cash ({periods[j]})', C('check', j)) for j in range(1, n)]

    if is_reit:
        ff = Sheet(wb, 'FFO & AFFO', heading('Funds from operations (NAREIT definition)'), periods, nh)
        for key, label, bold in [('ni', 'Net income', False), ('reda', 'Real estate depreciation & amortisation', False),
                                 ('gain', 'Less: gains on sale of real estate', False), ('ffo', 'Funds from operations (FFO)', True),
                                 ('capex', 'Less: recurring capital expenditure', False), ('affo', 'Adjusted FFO (AFFO)', True),
                                 ('payout', 'Dividends % AFFO', False)]:
            ff.row(key, label, bold)
        for j in range(n):
            h = j < nh
            ff.set('ni', j, f'={I("net_income", j)}')
            ff.set('reda', j, f'=IF({D("re_da", j)}<>0,{D("re_da", j)},{C("da", j)})' if h else f'={C("da", j)}')
            if h:
                ff.set('gain', j, f'=-{D("gain_re", j)}')
            ff.set('ffo', j, f'={ff.ref("ni", j)}+{ff.ref("reda", j)}+{ff.ref("gain", j)}', bold=True)
            ff.set('capex', j, f'={C("capex", j)}')
            ff.set('affo', j, f'={ff.ref("ffo", j)}+{ff.ref("capex", j)}', bold=True)
            ff.set('payout', j, f'=IFERROR(-{C("div", j)}/{ff.ref("affo", j)},0)', PCT)
        sections.append(('FFO & AFFO', 'REIT funds from operations and adjusted FFO, with dividend cover'))

    if extend:
        more_sections, more_checks = extend(wb, dict(
            ds=ds, si=si, asm=asm, is_=is_, bs=bs, cf=cf, rt=rt, periods=periods, ends=ends, data=data, nh=nh, n=n,
            years=FORECAST_YEARS, heading=heading, A=A, D=D, debt_wide=debt_wide, da_on_rev=da_on_rev, is_reit=is_reit))
        sections += more_sections
        check_items += more_checks
    sections.append(('Checks', 'Balance and cash checks for every year'))
    checks(wb, check_items)
    kind = title or ('REIT three-statement model with FFO/AFFO' if is_reit else 'Three-statement financial model')
    cover(wb, kind, sector, description or
          'Integrated income statement, balance sheet and cash flow built from the company\'s reported 10-K figures, '
          f'with a {FORECAST_YEARS}-year forecast driven by historical ratios. The balance sheet balances in every year, '
          'the revolver keeps cash at its historical minimum, and all checks are summarised on the Checks sheet.',
          sections + [])
    wb.properties.title = f'{REDACTED} - {kind}'
    wb.properties.creator = REDACTED
    return wb
