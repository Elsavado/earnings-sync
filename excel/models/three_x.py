"""Enhanced three-statement model: the linked statements of three.py with model-specific logic.

Each model draws its own methods from variants.THREE (revenue, costs, working capital, capital
spending, tax, financing, payouts, interest) and its own analysis modules, so two models of this
type forecast differently, not only look different. The balance sheet still balances in every year,
closing cash still ties to the cash flow, and every figure outside the input sheets is a formula.
"""
from . import variants
from .three import DATA_ROWS, REIT_ROWS, prepare
from .xl import (BOLD, NOTE, NUM, PCT, REDACTED, Sheet, checks, col, cover, data_sheet, new_workbook, scenario_inputs)

MULT = '0.00"x"'
DAYS = '0.0'


def _allowed(data):
    """Methods the company's history can support."""
    has_inv = sum(data['inventory']) > 0 and sum(data['cogs']) > 0
    has_ppe = sum(data['ppe'][:-1]) > 0 and sum(data['da'][1:]) > 0
    has_debt = data['debt'][-1] > 0
    has_div = sum(data['dividends']) > 0
    losses = sum(1 for v in data['pretax'] if v < 0)
    n = len(data['revenue'])

    def ok(block, m):
        if m == 'days_converge' and not has_inv:
            return False
        if m in ('useful_life', 'maintenance_growth') and not has_ppe:
            return False
        if m in ('amortise', 'target_leverage') and not has_debt:
            return False
        if m == 'dps_growth' and not has_div:
            return False
        if m == 'nol' and not losses:
            return False
        if m in ('cagr', 'fixed_variable') and n < 3:
            return False
        return True
    return ok


def build(facts, sector, key, is_reit=False, years=None, trim=0, extend=None, title=None, description=None, deep=False):
    """The same hooks as three.build: years overrides the variant's horizon; trim drops the latest reported years;
    extend(wb, ctx) -> (sections, check items) adds modules (the Enterprise models bring their own scenario manager,
    so this model's scenario_manager module is left out when extend is given); deep keeps every reported year."""
    got = prepare(facts, 40 if deep else 6)
    if not got:
        return None
    ends, data = got
    if trim:
        if len(ends) - trim < 3:
            return None
        ends, data = ends[:-trim], {k: v_[:-trim] for k, v_ in data.items()}
        if any(x is None or x <= 0 for x in data['revenue']) or data['assets'][-1] <= 0:
            return None
    v = variants.Variant(key, allowed=_allowed(data))
    if years:
        v.years = years
    if extend:
        v.modules.discard('scenario_manager')
    N = v.years
    P = v.params
    nh = len(ends)
    last = int(ends[-1][:4])
    sum_ = lambda k, a=0, b=None: sum(data[k][a:b])  # noqa: E731
    debt_wide = sum_('debt') <= 0 or sum_('interest') / max(sum_('debt'), 1e-9) > 0.2
    da_on_rev = sum_('ppe', 0, -1) <= 0 or sum_('da', 1) / max(sum_('ppe', 0, -1), 1e-9) > 0.5
    if da_on_rev and v.method('capex') == 'useful_life':
        v.methods['capex'] = 'pct'
    periods = [f'FY{e[:4]}A' for e in ends] + [f'FY{last + k}E' for k in range(1, N + 1)]
    n = len(periods)
    wb = new_workbook()
    heading = lambda t: f'{REDACTED} - {t}'  # noqa: E731

    rows = DATA_ROWS + (REIT_ROWS if is_reit else [])
    ds = data_sheet(wb, heading('Reported figures (Form 10-K)'), list(ends), rows, data)
    D = lambda k, j: ds.ref(k, j)  # noqa: E731

    si = scenario_inputs(wb, heading('Scenario inputs'))
    M = v.methods
    # Inputs used by this model's methods only.
    si.section('Model-specific settings')
    if M['revenue'] == 'decay':
        si.add('decay', 'Growth decay factor per year', P['decay'], '0.00', 'Excess growth over the long-term rate shrinks by this factor each year')
    if M['revenue'] == 'stepdown':
        si.add('step', 'Years held at starting growth', min(P['step_years'], N - 1), '0', 'Then a straight line to the long-term rate')
    if M['revenue'] == 'price_volume' or M['costs'] == 'fixed_variable':
        si.add('infl', 'Price / cost inflation', P['inflation'], PCT)
    if M['revenue'] == 'scenario_weighted':
        pb, pu, pd = P['scenario_p']
        si.add('p_up', 'Probability of upside case', pu, PCT)
        si.add('p_down', 'Probability of downside case', pd, PCT)
        si.add('spread', 'Upside / downside growth spread', P['scenario_spread'], PCT)
    if M['costs'] == 'opex_leverage':
        si.add('elast', 'Opex growth as a share of revenue growth', P['elasticity'], '0.00', 'Below 1 = operating leverage')
    if M['capex'] == 'maintenance_growth':
        si.add('maint', 'Maintenance capex as a multiple of D&A', P['maint_factor'], MULT)
    if M['financing'] == 'amortise':
        si.add('amort', 'Long-term debt repaid each year (% of last reported)', P['amort'], PCT)
    if M['tax'] == 'statutory_blend':
        si.add('stat', 'Statutory tax rate', P['statutory'], PCT, 'The effective rate moves to this rate by the final year')
    if M['payout'] == 'dps_growth':
        si.add('dps_g', 'Annual dividend growth', P['dps_growth'], PCT)
    if M['payout'] == 'payout_target':
        si.add('pay_t', 'Target dividend payout ratio', P['payout_target'], PCT)
    if M['interest'] == 'rate_curve':
        si.add('rf', 'Risk-free rate', P['rf'], PCT)
        si.add('cr_spread', 'Credit spread', P['spread'], PCT, 'Debt reprices to risk-free + spread by the final year')
    if v.has('scenario_manager'):
        si.add('case', 'Active case (1 = base, 2 = upside, 3 = downside)', 1, '0')
        si.add('case_g', 'Case growth adjustment', 0.02, PCT)
        si.add('case_m', 'Case cost-ratio adjustment', 0.01, PCT)
    S = si.ref

    asm = Sheet(wb, 'Assumptions', heading('Forecast drivers (derived from the historical years)'), ['Driver'])
    is_ = Sheet(wb, 'Income Statement', heading('Income Statement'), periods, nh)
    bs = Sheet(wb, 'Balance Sheet', heading('Balance Sheet'), periods, nh)
    cf = Sheet(wb, 'Cash Flow', heading('Cash Flow Statement'), periods, nh)
    rt = Sheet(wb, 'Ratios', heading('Key ratios'), periods, nh)

    is_rows = [('revenue', 'Revenue', True), ('growth', '  growth %', False)]
    if M['revenue'] == 'price_volume':
        is_rows += [('price', '  of which price', False), ('volume', '  of which volume', False)]
    if M['revenue'] == 'scenario_weighted':
        is_rows += [('g_up', '  upside-case growth', False), ('g_down', '  downside-case growth', False)]
    is_rows += [('cogs', 'Cost of revenue', False), ('gross', 'Gross profit', True), ('opex', 'Operating expenses', False),
                ('ebit', 'Operating income (EBIT)', True), ('interest', 'Interest expense', False),
                ('other', 'Other income (expense)', False), ('pretax', 'Pre-tax income', True),
                ('tax', 'Income tax expense', False), ('ato', 'Discontinued ops, minority interest & other', False),
                ('net_income', 'Net income', True)]
    for k_, label, bold in is_rows:
        is_.row(k_, label, bold)
    is_.row('yr', 'Memo: forecast year', gap_before=True)
    is_.row('da', 'Memo: depreciation & amortisation')
    is_.row('ebitda', 'Memo: EBITDA', bold=True)
    if M['tax'] == 'nol':
        is_.row('nol_open', 'Memo: tax losses brought forward')
        is_.row('nol_close', 'Memo: tax losses carried forward')
    if M['tax'] == 'statutory_blend':
        is_.row('tax_rate', 'Memo: tax rate applied')
    if M['interest'] == 'rate_curve':
        is_.row('int_rate', 'Memo: interest rate applied')
    if M['payout'] == 'payout_target':
        is_.row('payout', 'Memo: dividend payout ratio')

    for k_, label, bold, sec in [('cash', 'Cash and equivalents', False, 'Assets'), ('ar', 'Accounts receivable', False, None),
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
        bs.row(k_, label, bold, section=sec)
    bs.row('check', 'Balance check (assets - liabilities & equity)', gap_before=True)

    for k_, label, bold, sec in [('ni', 'Net income', False, 'Operating activities'), ('da', 'Depreciation & amortisation', False, None),
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
        cf.row(k_, label, bold, section=sec)

    ratio_rows = [('gm', 'Gross margin'), ('em', 'EBITDA margin'), ('om', 'EBIT margin'), ('nm', 'Net margin'),
                  ('roe', 'Return on average equity'), ('roa', 'Return on average assets'),
                  ('cr', 'Current ratio (x)'), ('lev', 'Total debt / EBITDA (x)'), ('cov', 'EBITDA / interest (x)'),
                  ('cash_pct', 'Cash % revenue'), ('fcf', 'Free cash flow (CFO - capex)'), ('fcf_m', 'FCF margin')]
    if M['working_capital'] == 'days_converge' or v.has('cash_conversion'):
        ratio_rows += [('dso', 'Days sales outstanding'), ('dio', 'Days inventory outstanding'),
                       ('dpo', 'Days payables outstanding'), ('ccc', 'Cash conversion cycle (days)')]
    if v.has('dupont'):
        ratio_rows += [('at', 'Asset turnover (x)'), ('em_x', 'Equity multiplier (x)'), ('roe_d', 'ROE - DuPont (margin x turnover x leverage)')]
    if v.has('roic_tree'):
        ratio_rows += [('nopat', 'NOPAT'), ('ic', 'Invested capital (equity + debt - cash)'), ('roic', 'Return on average invested capital'),
                       ('ic_turn', 'Capital turnover (x)'), ('nopat_m', 'NOPAT margin')]
    if v.has('breakeven'):
        ratio_rows += [('tc', 'Memo: total operating costs'), ('be_rev', 'Break-even revenue'), ('mos', 'Margin of safety')]
    for k_, label in ratio_rows:
        rt.row(k_, label)

    I = lambda k, j: is_.ref(k, j)  # noqa: E731,E741
    B = lambda k, j: bs.ref(k, j)  # noqa: E731
    C = lambda k, j: cf.ref(k, j)  # noqa: E731
    R = lambda k, j: rt.ref(k, j)  # noqa: E731
    hi = nh - 1
    w0 = max(0, nh - 5)
    w1 = max(1, w0)
    Ih = lambda k, j0=w0: is_.span(k, j0, hi)  # noqa: E731
    Bh = lambda k, j0=w0: bs.span(k, j0, hi)  # noqa: E731
    Ch = lambda k, j0=w0: cf.span(k, j0, hi)  # noqa: E731
    Rh = lambda k, j0=w0: rt.span(k, j0, hi)  # noqa: E731

    g_lim = lambda x: f'MAX({S("floor")},MIN({S("cap")},{x}))'  # noqa: E731
    drivers = [
        ('growth', 'Starting revenue growth (3-year CAGR, within the scenario limits)' if M['revenue'] == 'cagr'
         else 'Starting revenue growth (historical median, within the scenario limits)',
         g_lim(f'IFERROR(({I("revenue", hi)}/{I("revenue", max(0, hi - 3))})^(1/{min(3, hi)})-1,0)') if M['revenue'] == 'cagr'
         else g_lim(f'IFERROR(MEDIAN({Ih("growth", w1)}),0)')),
        ('cogs_pct', 'Cost of revenue % revenue', f'IFERROR(SUM({Ih("cogs")})/SUM({Ih("revenue")}),0)'),
        ('opex_pct', 'Operating expenses % revenue', f'IFERROR(SUM({Ih("opex")})/SUM({Ih("revenue")}),0)'),
        ('other_pct', 'Other income % revenue', f'IFERROR(SUM({Ih("other")})/SUM({Ih("revenue")}),0)'),
        ('int_rate', 'Interest rate on debt and other non-current liabilities' if debt_wide else 'Interest rate on debt',
         f'IFERROR(SUM({Ih("interest")})/(SUM({Bh("debt")})+SUM({Bh("oncl")})),0)' if debt_wide
         else f'IFERROR(SUM({Ih("interest")})/SUM({Bh("debt")}),0)'),
        ('tax_rate', 'Effective tax rate', f'MAX(0,MIN(1,IFERROR(SUM({Ih("tax")})/SUM({Ih("pretax")}),0)))'),
        ('oca_pct', 'Other current assets % revenue', f'IFERROR(SUM({Bh("oca")})/SUM({Ih("revenue")}),0)'),
        ('ocl_pct', 'Other current liabilities % revenue', f'IFERROR(SUM({Bh("ocl")})/SUM({Ih("revenue")}),0)'),
        ('payout', 'Dividend payout % net income', f'MAX(0,MIN(1,IFERROR(-SUM({Ch("div")})/SUM({Ih("net_income")}),0)))'),
        ('buyback', 'Share repurchases % net income', f'MAX(0,MIN(1,IFERROR(-SUM({Ch("buyback")})/SUM({Ih("net_income")}),0)))'),
        ('min_cash', 'Minimum cash % revenue (lowest historical level)', f'MAX(0,MIN({rt.span("cash_pct", 0, hi)}))'),
    ]
    wcm = M['working_capital']
    if wcm == 'last_ratio':
        drivers += [('ar_pct', 'Receivables % revenue (latest year)', f'IFERROR({B("ar", hi)}/{I("revenue", hi)},0)'),
                    ('inv_pct', 'Inventory % cost of revenue (latest year)', f'IFERROR({B("inventory", hi)}/{I("cogs", hi)},0)'),
                    ('ap_pct', 'Payables % cost of revenue (latest year)', f'IFERROR({B("ap", hi)}/{I("cogs", hi)},0)')]
    elif wcm == 'days_converge':
        for d_, lab in (('dso', 'Receivable'), ('dio', 'Inventory'), ('dpo', 'Payable')):
            drivers += [(f'{d_}_last', f'{lab} days, latest year', f'{R(d_, hi)}'),
                        (f'{d_}_avg', f'{lab} days, historical average', f'IFERROR(AVERAGE({Rh(d_)}),0)')]
    else:
        drivers += [('ar_pct', 'Receivables % revenue', f'IFERROR(SUM({Bh("ar")})/SUM({Ih("revenue")}),0)'),
                    ('inv_pct', 'Inventory % cost of revenue', f'IFERROR(SUM({Bh("inventory")})/SUM({Ih("cogs")}),0)'),
                    ('ap_pct', 'Payables % cost of revenue', f'IFERROR(SUM({Bh("ap")})/SUM({Ih("cogs")}),0)')]
    capm = M['capex']
    drivers += [('capex_pct', 'Capital expenditure % revenue', f'IFERROR(-SUM({Ch("capex")})/SUM({Ih("revenue")}),0)'),
                ('dep_rate', 'D&A % revenue', f'IFERROR(SUM({Ch("da")})/SUM({Ih("revenue")}),0)') if da_on_rev else
                ('dep_rate', 'D&A % opening PP&E', f"IFERROR(SUM({Ch('da', w1)})/SUM({bs.span('ppe', w1 - 1, hi - 1)}),0)")]
    if capm == 'maintenance_growth':
        drivers += [('ppe_rev', 'PP&E per unit of revenue (capital intensity)', f'IFERROR(SUM({Bh("ppe")})/SUM({Ih("revenue")}),0)')]
    if capm == 'useful_life':
        drivers += [('life', 'Average useful life of PP&E (years)',
                     f"MAX(3,MIN(40,IFERROR(SUM({bs.span('ppe', w1 - 1, hi - 1)})/SUM({Ch('da', w1)}),10)))")]
    if capm == 'intensity_fade':
        drivers += [('capex_last', 'Capital expenditure % revenue (latest year)', f'IFERROR(-{C("capex", hi)}/{I("revenue", hi)},0)'),
                    ('da_rev', 'D&A % revenue (steady-state capex)', f'IFERROR(SUM({Ch("da")})/SUM({Ih("revenue")}),0)')]
    cm = M['costs']
    if cm == 'fixed_variable':
        drivers += [('var', 'Variable opex per unit of revenue (regression)', f'IFERROR(SLOPE({Ih("opex")},{Ih("revenue")}),0)'),
                    ('fixed', 'Fixed opex (regression intercept)', f'IFERROR(INTERCEPT({Ih("opex")},{Ih("revenue")}),0)')]
    if cm == 'margin_target':
        drivers += [('gm_last', 'Gross margin, latest year', f'IFERROR({I("gross", hi)}/{I("revenue", hi)},0)'),
                    ('gm_tgt', 'Gross margin, historical average (target)', f'IFERROR(SUM({Ih("gross")})/SUM({Ih("revenue")}),0)')]
    if M['financing'] == 'target_leverage':
        drivers += [('lev_tgt', 'Target long-term debt / EBITDA (historical median)',
                     f'MAX(0,IFERROR(MEDIAN({Rh("lev")}),0))')]
    if M['tax'] == 'nol':
        drivers += [('nol0', 'Tax losses available at the forecast start', f'MAX(0,-SUM({is_.span("pretax", 0, hi)}))')]
    if v.has('breakeven'):
        drivers += [('be_var', 'Variable cost ratio (regression of total costs on revenue)',
                     f'MAX(0,MIN(0.99,IFERROR(SLOPE({rt.span("tc", 0, hi)},{is_.span("revenue", 0, hi)}),0)))'),
                    ('be_fix', 'Fixed costs (regression intercept)',
                     f'MAX(0,IFERROR(INTERCEPT({rt.span("tc", 0, hi)},{is_.span("revenue", 0, hi)}),0))')]
    for k_, label, f in drivers:
        asm.row(k_, label)
        asm.set(k_, 0, f'={f}', DAYS if k_.endswith(('_last', '_avg')) and wcm == 'days_converge' and k_[:3] in ('dso', 'dio', 'dpo')
                else ('0.0' if k_ in ('life',) else (NUM if k_ in ('fixed', 'nol0', 'be_fix') else PCT)))
    method_note = 'Methods in this model - ' + '; '.join(v.describe())
    asm.ws.cell(row=asm.next_row + 1, column=1, value=method_note).font = NOTE
    A = lambda k: asm.ref(k, 0, absolute=True)  # noqa: E731
    t = lambda j: f'{I("yr", j)}/{N}'  # noqa: E731  share of the horizon elapsed
    case_g = f'CHOOSE({S("case")},0,{S("case_g")},-{S("case_g")})' if v.has('scenario_manager') else None
    case_m = f'CHOOSE({S("case")},0,-{S("case_m")},{S("case_m")})' if v.has('scenario_manager') else None

    for j in range(n):
        p, h = j - 1, j < nh
        if not h:
            is_.set('yr', j, f'=N({I("yr", p)})+1', '0')
        # ---- revenue
        rm = M['revenue']
        if h:
            is_.set('revenue', j, f'={D("revenue", j)}', bold=True)
            if j:
                is_.set('growth', j, f'=IFERROR({I("revenue", j)}/{I("revenue", p)}-1,0)', PCT)
        else:
            g0, lt = A('growth'), S('lt')
            if rm == 'decay':
                g = f'{lt}+({g0}-{lt})*{S("decay")}^{I("yr", j)}'
            elif rm == 'stepdown':
                g = f'IF({I("yr", j)}<={S("step")},{g0},{g0}+({lt}-{g0})*({I("yr", j)}-{S("step")})/({N}-{S("step")}))'
            else:
                g = f'{g0}+({lt}-{g0})*{t(j)}'
            if case_g:
                g = f'({g})+{case_g}'
            if rm == 'price_volume':
                is_.set('price', j, f'={S("infl")}', PCT)
                is_.set('volume', j, f'=(1+{g})/(1+{S("infl")})-1', PCT)
                is_.set('revenue', j, f'={I("revenue", p)}*(1+{I("price", j)})*(1+{I("volume", j)})', bold=True)
                is_.set('growth', j, f'=IFERROR({I("revenue", j)}/{I("revenue", p)}-1,0)', PCT)
            elif rm == 'scenario_weighted':
                is_.set('g_up', j, f'={g}+{S("spread")}', PCT)
                is_.set('g_down', j, f'={g}-{S("spread")}', PCT)
                is_.set('growth', j, f'=(1-{S("p_up")}-{S("p_down")})*({g})+{S("p_up")}*{I("g_up", j)}+{S("p_down")}*{I("g_down", j)}', PCT)
                is_.set('revenue', j, f'={I("revenue", p)}*(1+{I("growth", j)})', bold=True)
            else:
                is_.set('growth', j, f'={g}', PCT)
                is_.set('revenue', j, f'={I("revenue", p)}*(1+{I("growth", j)})', bold=True)
        # ---- costs
        if h:
            is_.set('cogs', j, f'={D("cogs", j)}')
            is_.set('opex', j, f'={I("gross", j)}-{D("ebit", j)}')
        else:
            adj = f'*(1+{case_m})' if case_m else ''
            if cm == 'margin_target':
                is_.set('cogs', j, f'={I("revenue", j)}*(1-({A("gm_last")}+({A("gm_tgt")}-{A("gm_last")})*{t(j)})){adj}')
            else:
                is_.set('cogs', j, f'={I("revenue", j)}*{A("cogs_pct")}{adj}')
            if cm == 'fixed_variable':
                is_.set('opex', j, f'=IF(AND({A("var")}>=0,{A("var")}<1,{A("fixed")}>=0),'
                                   f'{A("fixed")}*(1+{S("infl")})^{I("yr", j)}+{A("var")}*{I("revenue", j)},{I("revenue", j)}*{A("opex_pct")})')
            elif cm == 'opex_leverage':
                is_.set('opex', j, f'={I("opex", p)}*(1+{I("growth", j)}*{S("elast")})')
            else:
                is_.set('opex', j, f'={I("revenue", j)}*{A("opex_pct")}')
        is_.set('gross', j, f'={I("revenue", j)}-{I("cogs", j)}', bold=True)
        is_.set('ebit', j, f'={I("gross", j)}-{I("opex", j)}', bold=True)
        # ---- interest, tax
        base_debt = (f'({B("debt", p)}+{B("oncl", p)}+{B("revolver", p)})' if debt_wide else f'({B("debt", p)}+{B("revolver", p)})')
        if h:
            is_.set('interest', j, f'={D("interest", j)}')
        elif M['interest'] == 'rate_curve':
            is_.set('int_rate', j, f'={A("int_rate")}+({S("rf")}+{S("cr_spread")}-{A("int_rate")})*{t(j)}', PCT)
            is_.set('interest', j, f'={base_debt}*{I("int_rate", j)}')
        else:
            is_.set('interest', j, f'={base_debt}*{A("int_rate")}')
        is_.set('other', j, f'={D("pretax", j)}-({I("ebit", j)}-{I("interest", j)})' if h else f'={I("revenue", j)}*{A("other_pct")}')
        is_.set('pretax', j, f'={I("ebit", j)}-{I("interest", j)}+{I("other", j)}', bold=True)
        if h:
            is_.set('tax', j, f'={D("tax", j)}')
        elif M['tax'] == 'nol':
            is_.set('nol_open', j, f'={A("nol0")}' if j == nh else f'={I("nol_close", p)}')
            is_.set('nol_close', j, f'=MAX(0,{I("nol_open", j)}-MAX(0,{I("pretax", j)}))+MAX(0,-{I("pretax", j)})')
            is_.set('tax', j, f'=MAX(0,{I("pretax", j)}-{I("nol_open", j)})*{A("tax_rate")}')
        elif M['tax'] == 'statutory_blend':
            is_.set('tax_rate', j, f'={A("tax_rate")}+({S("stat")}-{A("tax_rate")})*{t(j)}', PCT)
            is_.set('tax', j, f'=MAX(0,{I("pretax", j)})*{I("tax_rate", j)}')
        else:
            is_.set('tax', j, f'=MAX(0,{I("pretax", j)})*{A("tax_rate")}')
        if h:
            is_.set('ato', j, f'={D("net_income", j)}-({I("pretax", j)}-{I("tax", j)})')
            is_.set('net_income', j, f'={I("pretax", j)}-{I("tax", j)}+{I("ato", j)}', bold=True)
        else:
            is_.set('net_income', j, f'={I("pretax", j)}-{I("tax", j)}', bold=True)
        is_.set('da', j, f'={C("da", j)}')
        is_.set('ebitda', j, f'={I("ebit", j)}+{I("da", j)}', bold=True)

        # ---- balance sheet
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
            if wcm == 'days_converge':
                for d_ in ('dso', 'dio', 'dpo'):
                    rt.set(d_, j, f'={A(d_ + "_last")}+({A(d_ + "_avg")}-{A(d_ + "_last")})*{t(j)}', DAYS)
                bs.set('ar', j, f'={I("revenue", j)}*{R("dso", j)}/365')
                bs.set('inventory', j, f'={I("cogs", j)}*{R("dio", j)}/365')
                bs.set('ap', j, f'={I("cogs", j)}*{R("dpo", j)}/365')
            else:
                bs.set('ar', j, f'={I("revenue", j)}*{A("ar_pct")}')
                bs.set('inventory', j, f'={I("cogs", j)}*{A("inv_pct")}')
                bs.set('ap', j, f'={I("cogs", j)}*{A("ap_pct")}')
            bs.set('oca', j, f'={I("revenue", j)}*{A("oca_pct")}')
            bs.set('ppe', j, f'={B("ppe", p)}-{C("capex", j)}-{C("da", j)}')
            bs.set('onca', j, f'={B("onca", p)}')
            bs.set('ocl', j, f'={I("revenue", j)}*{A("ocl_pct")}')
            bs.set('revolver', j, f'={B("revolver", p)}+{C("draw", j)}')
            if M['financing'] == 'amortise':
                bs.set('debt', j, f'=MAX(0,{B("debt", p)}-{B("debt", hi)}*{S("amort")})')
            elif M['financing'] == 'target_leverage':
                bs.set('debt', j, f'=MAX(0,{I("ebitda", j)})*{A("lev_tgt")}')
            else:
                bs.set('debt', j, f'={B("debt", p)}')
            bs.set('oncl', j, f'={B("oncl", p)}')
            bs.set('equity', j, f'={B("equity", p)}+{I("net_income", j)}+{C("div", j)}+{C("buyback", j)}')
            bs.set('nci', j, f'={B("nci", p)}')
        bs.set('tca', j, f'=SUM({col(j)}{bs.rows["cash"]}:{col(j)}{bs.rows["oca"]})', bold=True)
        bs.set('ta', j, f'={B("tca", j)}+{B("ppe", j)}+{B("onca", j)}', bold=True)
        bs.set('tcl', j, f'={B("ap", j)}+{B("ocl", j)}', bold=True)
        bs.set('tl', j, f'={B("tcl", j)}+{B("revolver", j)}+{B("debt", j)}+{B("oncl", j)}', bold=True)
        bs.set('te', j, f'={B("equity", j)}+{B("nci", j)}', bold=True)
        bs.set('tle', j, f'={B("tl", j)}+{B("te", j)}', bold=True)
        bs.set('check', j, f'=ROUND({B("ta", j)}-{B("tle", j)},3)')

        # ---- cash flow
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
            life_da = None
            if capm == 'useful_life':
                life_da = f'={B("ppe", p)}/{A("life")}-{C("capex", j)}/(2*{A("life")})'
            cf.set('da', j, life_da or (f'={I("revenue", j)}*{A("dep_rate")}' if da_on_rev else f'={B("ppe", p)}*{A("dep_rate")}'))
            cf.set('wc', j, f'=-({B("ar", j)}-{B("ar", p)})-({B("inventory", j)}-{B("inventory", p)})-({B("oca", j)}-{B("oca", p)})'
                             f'+({B("ap", j)}-{B("ap", p)})+({B("ocl", j)}-{B("ocl", p)})')
            if capm == 'maintenance_growth':
                cf.set('capex', j, f'=-({S("maint")}*{C("da", j)}+MAX(0,{I("revenue", j)}-{I("revenue", p)})*{A("ppe_rev")})')
            elif capm == 'intensity_fade':
                cf.set('capex', j, f'=-{I("revenue", j)}*({A("capex_last")}+({A("da_rev")}-{A("capex_last")})*{t(j)})')
            else:
                cf.set('capex', j, f'=-{I("revenue", j)}*{A("capex_pct")}')
            cf.set('oinv', j, f'=-({B("onca", j)}-{B("onca", p)})')
            pm = M['payout']
            if pm == 'dps_growth':
                cf.set('div', j, f'={C("div", p)}*(1+{S("dps_g")})')
            elif pm == 'payout_target':
                is_.set('payout', j, f'={A("payout")}+({S("pay_t")}-{A("payout")})*{t(j)}', PCT)
                cf.set('div', j, f'=-MAX(0,{I("net_income", j)})*{I("payout", j)}')
            else:
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

        # ---- ratios and analysis modules
        rt.set('gm', j, f'=IFERROR({I("gross", j)}/{I("revenue", j)},0)', PCT)
        rt.set('em', j, f'=IFERROR({I("ebitda", j)}/{I("revenue", j)},0)', PCT)
        rt.set('om', j, f'=IFERROR({I("ebit", j)}/{I("revenue", j)},0)', PCT)
        rt.set('nm', j, f'=IFERROR({I("net_income", j)}/{I("revenue", j)},0)', PCT)
        if j:
            rt.set('roe', j, f'=IFERROR({I("net_income", j)}/AVERAGE({B("equity", p)},{B("equity", j)}),0)', PCT)
            rt.set('roa', j, f'=IFERROR({I("net_income", j)}/AVERAGE({B("ta", p)},{B("ta", j)}),0)', PCT)
        rt.set('cr', j, f'=IFERROR({B("tca", j)}/{B("tcl", j)},0)', MULT)
        rt.set('lev', j, f'=IFERROR(({B("debt", j)}+{B("revolver", j)})/{I("ebitda", j)},0)', '0.0"x"')
        rt.set('cov', j, f'=IFERROR({I("ebitda", j)}/{I("interest", j)},0)', '0.0"x"')
        rt.set('cash_pct', j, f'=IFERROR({B("cash", j)}/{I("revenue", j)},0)', PCT)
        rt.set('fcf', j, f'={C("cfo", j)}+{C("capex", j)}', NUM)
        rt.set('fcf_m', j, f'=IFERROR({R("fcf", j)}/{I("revenue", j)},0)', PCT)
        if 'dso' in rt.rows and (h or wcm != 'days_converge'):
            rt.set('dso', j, f'=IFERROR({B("ar", j)}/{I("revenue", j)}*365,0)', DAYS)
            rt.set('dio', j, f'=IFERROR({B("inventory", j)}/{I("cogs", j)}*365,0)', DAYS)
            rt.set('dpo', j, f'=IFERROR({B("ap", j)}/{I("cogs", j)}*365,0)', DAYS)
        if 'dso' in rt.rows:
            rt.set('ccc', j, f'={R("dso", j)}+{R("dio", j)}-{R("dpo", j)}', DAYS)
        if v.has('dupont') and j:
            rt.set('at', j, f'=IFERROR({I("revenue", j)}/AVERAGE({B("ta", p)},{B("ta", j)}),0)', MULT)
            rt.set('em_x', j, f'=IFERROR(AVERAGE({B("ta", p)},{B("ta", j)})/AVERAGE({B("equity", p)},{B("equity", j)}),0)', MULT)
            rt.set('roe_d', j, f'={R("nm", j)}*{R("at", j)}*{R("em_x", j)}', PCT)
        if v.has('roic_tree'):
            rt.set('nopat', j, f'={I("ebit", j)}*(1-{A("tax_rate")})', NUM)
            rt.set('ic', j, f'={B("te", j)}+{B("debt", j)}+{B("revolver", j)}-{B("cash", j)}', NUM)
            rt.set('nopat_m', j, f'=IFERROR({R("nopat", j)}/{I("revenue", j)},0)', PCT)
            if j:
                rt.set('ic_turn', j, f'=IFERROR({I("revenue", j)}/AVERAGE({R("ic", p)},{R("ic", j)}),0)', MULT)
                rt.set('roic', j, f'={R("nopat_m", j)}*{R("ic_turn", j)}', PCT)
        if v.has('breakeven'):
            rt.set('tc', j, f'={I("cogs", j)}+{I("opex", j)}', NUM)
            rt.set('be_rev', j, f'=IFERROR({A("be_fix")}/(1-{A("be_var")}),0)', NUM)
            rt.set('mos', j, f'=IFERROR(({I("revenue", j)}-{R("be_rev", j)})/{I("revenue", j)},0)', PCT)

    sections = [('Historical Data', 'Reported annual figures from Form 10-K XBRL (USD millions) - hard-coded source data'),
                ('Scenario Inputs', 'Growth limits and the settings used by this model\'s methods (inputs)'),
                ('Assumptions', 'Forecast drivers, each calculated from the historical years, and the methods used'),
                ('Income Statement', 'Historical and forecast income statement'),
                ('Balance Sheet', 'Historical and forecast balance sheet with revolver'),
                ('Cash Flow', 'Indirect cash flow statement with minimum-cash revolver logic'),
                ('Ratios', 'Profitability, returns, liquidity, leverage, cash conversion and analysis modules')]
    check_items = [(f'Balance sheet balances ({periods[j]})', B('check', j)) for j in range(n)]
    check_items += [(f'Cash flow ties to balance sheet cash ({periods[j]})', C('check', j)) for j in range(1, n)]

    if v.has('piotroski') and n >= 3:
        q = Sheet(wb, 'Quality Score', heading('Financial strength score (Piotroski-style, 8 signals)'), periods, nh)
        sig = [('s_roa', 'Return on assets positive'), ('s_cfo', 'Cash from operations positive'),
               ('s_droa', 'Return on assets improving'), ('s_accr', 'Cash from operations above net income'),
               ('s_lev', 'Leverage (debt / assets) falling'), ('s_cr', 'Current ratio improving'),
               ('s_gm', 'Gross margin improving'), ('s_at', 'Asset turnover improving')]
        for k_, label in sig:
            q.row(k_, label)
        q.row('score', 'Score (0-8)', bold=True, gap_before=True)
        Q = q.ref
        lev_ = lambda j: f'IFERROR(({B("debt", j)}+{B("revolver", j)})/{B("ta", j)},0)'  # noqa: E731
        turn = lambda j: f'IFERROR({I("revenue", j)}/{B("ta", j)},0)'  # noqa: E731
        for j in range(2, n):
            p = j - 1
            q.set('s_roa', j, f'=IF({R("roa", j)}>0,1,0)', '0')
            q.set('s_cfo', j, f'=IF({C("cfo", j)}>0,1,0)', '0')
            q.set('s_droa', j, f'=IF({R("roa", j)}>{R("roa", p)},1,0)', '0')
            q.set('s_accr', j, f'=IF({C("cfo", j)}>{I("net_income", j)},1,0)', '0')
            q.set('s_lev', j, f'=IF({lev_(j)}<{lev_(p)},1,0)', '0')
            q.set('s_cr', j, f'=IF({R("cr", j)}>{R("cr", p)},1,0)', '0')
            q.set('s_gm', j, f'=IF({R("gm", j)}>{R("gm", p)},1,0)', '0')
            q.set('s_at', j, f'=IF({turn(j)}>{turn(p)},1,0)', '0')
            q.set('score', j, f'=SUM({col(j)}{q.rows["s_roa"]}:{col(j)}{q.rows["s_at"]})', '0', bold=True)
        sections.append(('Quality Score', 'Eight-signal financial strength score for each year'))

    if v.has('growth_bridge'):
        gb = Sheet(wb, 'EBIT Bridge', heading('Operating income bridge, year on year'), periods, nh)
        for k_, label, bold in [('vol', 'Revenue change at prior-year gross margin', False), ('mix', 'Gross margin change', False),
                                ('opx', 'Operating expense change', False), ('tot', 'Change in operating income', True),
                                ('chk', 'Bridge check (total - actual change)', False)]:
            gb.row(k_, label, bold)
        G = gb.ref
        for j in range(1, n):
            p = j - 1
            gb.set('vol', j, f'=({I("revenue", j)}-{I("revenue", p)})*{R("gm", p)}')
            gb.set('mix', j, f'={I("revenue", j)}*({R("gm", j)}-{R("gm", p)})')
            gb.set('opx', j, f'=-({I("opex", j)}-{I("opex", p)})')
            gb.set('tot', j, f'={G("vol", j)}+{G("mix", j)}+{G("opx", j)}', bold=True)
            gb.set('chk', j, f'=ROUND({G("tot", j)}-({I("ebit", j)}-{I("ebit", p)}),3)')
            check_items.append((f'EBIT bridge reconciles ({periods[j]})', G('chk', j)))
        sections.append(('EBIT Bridge', 'Volume, margin and cost effects on operating income'))

    if is_reit:
        ff = Sheet(wb, 'FFO & AFFO', heading('Funds from operations (NAREIT definition)'), periods, nh)
        for k_, label, bold in [('ni', 'Net income', False), ('reda', 'Real estate depreciation & amortisation', False),
                                ('gain', 'Less: gains on sale of real estate', False), ('ffo', 'Funds from operations (FFO)', True),
                                ('capex', 'Less: recurring capital expenditure', False), ('affo', 'Adjusted FFO (AFFO)', True),
                                ('payout', 'Dividends % AFFO', False)]:
            ff.row(k_, label, bold)
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
            years=N, heading=heading, A=A, D=D, debt_wide=debt_wide, da_on_rev=da_on_rev, is_reit=is_reit, variant=v))
        sections += more_sections
        check_items += more_checks
    else:
        from . import enterprise as E
        from .unique import Profile
        ctx = dict(ds=ds, si=si, asm=asm, is_=is_, bs=bs, cf=cf, rt=rt, periods=periods, ends=ends, data=data, nh=nh, n=n,
                   years=N, heading=heading, A=A, D=D, profile=Profile(key))
        for fn in (lambda: E.company_lines(wb, ctx, facts), lambda: E.rnd(wb, ctx, facts), lambda: E.sbc(wb, ctx)):
            try:
                more, _ = fn()
                sections += more
            except Exception:  # noqa: BLE001  (an optional module never stops the model)
                pass
    from .practice import annotate
    sections += annotate(wb, v, dict(is_=is_, bs=bs, cf=cf, rt=rt, asm=asm, si=si, periods=periods, nh=nh, n=n, years=N, A=A, S=S))

    sections.append(('Checks', 'Balance, cash and bridge checks for every year'))
    checks(wb, check_items)
    kind = title or ('REIT three-statement model (enhanced)' if is_reit else 'Three-statement financial model (enhanced)')
    methods = ('This model uses its own forecasting methods: ' + '; '.join(v.describe()).lower() + '. Analysis modules: ' +
               (', '.join(sorted(m.replace('_', ' ') for m in v.modules)) or 'none') + '.')
    cover(wb, kind, sector,
          (description + ' ' + methods) if description else
          'Integrated income statement, balance sheet and cash flow built from the company\'s reported 10-K figures, '
          f'with a {N}-year forecast. ' + methods +
          ' The balance sheet balances in every year and all checks are summarised on the Checks sheet.',
          sections)
    wb.properties.title = f'{REDACTED} - {kind}'
    wb.properties.creator = REDACTED
    wb.variant = v
    return wb
