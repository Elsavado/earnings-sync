"""Bank model (industry-specific): net interest income build, provisions, efficiency,
balance sheet growth, capital and returns, and a justified price-to-tangible-book valuation.

Forecast interest and provisions run on opening balances, so the model has no circular
references; other liabilities and borrowings balance the balance sheet.
"""
from . import xbrl
from .xl import (MULT, NOTE, NUM, PCT, REDACTED, Inputs, Sheet, checks, cover, data_sheet, new_workbook)

YEARS = 5
REQUIRED = ['int_income', 'int_expense_bank', 'nonint_expense', 'net_income', 'loans', 'deposits', 'assets', 'equity']
DATA_ROWS = [('int_income', 'Interest and dividend income'), ('int_expense_bank', 'Interest expense'),
             ('provision', 'Provision for credit losses'), ('nonint_income', 'Noninterest income'),
             ('nonint_expense', 'Noninterest expense'), ('pretax', 'Pre-tax income'), ('tax', 'Income tax expense'),
             ('net_income', 'Net income'), ('loans', 'Loans, net'), ('assets', 'Total assets'), ('deposits', 'Deposits'),
             ('equity', "Shareholders' equity"), ('goodwill', 'Goodwill'), ('intangibles', 'Other intangible assets'),
             ('dividends', 'Dividends paid'), ('buybacks', 'Share repurchases')]


def build(facts, sector, market, sic=None):
    got = xbrl.annual(facts, required=REQUIRED, anchor='net_income')
    if not got:
        return None
    ends, d = got
    nh = len(ends)
    for i in range(nh):
        for k in ('provision', 'nonint_income', 'goodwill', 'intangibles', 'dividends', 'buybacks', 'tax'):
            if d[k][i] is None:
                d[k][i] = 0.0
        if d['pretax'][i] is None:
            d['pretax'][i] = round(d['net_income'][i] + d['tax'][i], 3)
    if d['assets'][-1] <= 0 or d['loans'][-1] <= 0 or d['int_income'][-1] <= 0:
        return None
    float_ = xbrl.dei_latest(facts, 'EntityPublicFloat', 'USD')

    hi = nh - 1
    last = int(ends[-1][:4])
    periods = [f'FY{e[:4]}A' for e in ends] + [f'FY{last + k}E' for k in range(1, YEARS + 1)]
    n = len(periods)
    wb = new_workbook()
    head = lambda t: f'{REDACTED} - {t}'  # noqa: E731
    ds = data_sheet(wb, head('Reported figures (Form 10-K)'), list(ends), DATA_ROWS, d)
    D = ds.ref

    bu, _, industry, beta_note = market.beta(sic)
    mi = Inputs(wb, 'Market Inputs', head('Market and valuation inputs'))
    mi.add('rf', 'Risk-free rate', market.rf, PCT, market.notes['rf'])
    mi.add('erp', 'Equity risk premium', market.erp, PCT, market.notes['erp'])
    mi.add('beta', 'Equity beta (industry)', round(max(bu, 0.5) * 1.6, 3), '0.00',
           f'{beta_note}; relevered at a typical bank equity/assets of about 10%')
    mi.add('g', 'Long-term growth of tangible book value', 0.03, PCT)
    mi.add('mcap', 'Market value of equity (USD millions)', round(float_ / 1e6, 3) if float_ else 0, NUM,
           'Public float from the 10-K cover page (excludes insider holdings)')
    M = mi.ref

    asm = Sheet(wb, 'Assumptions', head('Forecast drivers (derived from the historical years)'), ['Driver'])
    is_ = Sheet(wb, 'Income Statement', head('Income statement'), periods, nh)
    bs = Sheet(wb, 'Balance Sheet', head('Balance sheet'), periods, nh)
    cr = Sheet(wb, 'Capital & Returns', head('Capital, profitability and efficiency'), periods, nh)
    for key, label, bold in [('ii', 'Interest and dividend income', False), ('ie', 'Interest expense', False),
                             ('nii', 'Net interest income', True), ('nonii', 'Noninterest income', False),
                             ('rev', 'Total revenue', True), ('nonie', 'Noninterest expense', False),
                             ('ppnr', 'Pre-provision net revenue', True), ('prov', 'Provision for credit losses', False),
                             ('other', 'Other items', False), ('pretax', 'Pre-tax income', True), ('tax', 'Income tax expense', False),
                             ('ni', 'Net income', True), ('div', 'Dividends', False), ('bb', 'Share repurchases', False)]:
        is_.row(key, label, bold)
    for key, label, bold in [('loans', 'Loans, net', False), ('oa', 'Cash, securities & other assets', False),
                             ('assets', 'Total assets', True), ('dep', 'Deposits', False),
                             ('ol', 'Borrowings & other liabilities', False), ('liab', 'Total liabilities', True),
                             ('eq', "Shareholders' equity", True), ('tle', 'Total liabilities & equity', True),
                             ('check', 'Balance check', False), ('gw', 'Memo: goodwill & intangibles', False),
                             ('tbv', 'Memo: tangible book value', True)]:
        bs.row(key, label, bold, gap_before=key in ('dep', 'check'))
    for key, label in [('nim', 'Net interest income % opening assets'), ('yield', 'Interest income % opening assets'),
                       ('cost', 'Interest expense % opening deposits & borrowings'), ('eff', 'Efficiency ratio'),
                       ('nonii_r', 'Noninterest income % interest income'), ('prov_r', 'Provision % opening loans'),
                       ('roa', 'Return on average assets'), ('roe', 'Return on average equity'),
                       ('rote', 'Return on average tangible equity'), ('eq_a', 'Equity / assets'),
                       ('tce', 'Tangible equity / tangible assets'), ('ltd', 'Loans / deposits'), ('loan_g', 'Loan growth'),
                       ('payout', 'Total payout % net income')]:
        cr.row(key, label)
    I = is_.ref  # noqa: E741
    B = bs.ref
    C = cr.ref

    drivers = [
        ('loan_g', 'Loan growth (median of historical years)', f'IFERROR(MEDIAN({cr.span("loan_g", 1, hi)}),0)'),
        ('loan_a', 'Loans % total assets', f'IFERROR(SUM({bs.span("loans", 0, hi)})/SUM({bs.span("assets", 0, hi)}),0)'),
        ('dep_a', 'Deposits % total assets', f'IFERROR(SUM({bs.span("dep", 0, hi)})/SUM({bs.span("assets", 0, hi)}),0)'),
        ('yield', 'Interest income % opening assets', f'IFERROR(AVERAGE({cr.span("yield", 1, hi)}),0)'),
        ('cost', 'Interest expense % opening deposits & borrowings', f'IFERROR(AVERAGE({cr.span("cost", 1, hi)}),0)'),
        ('nonii', 'Noninterest income % interest income', f'IFERROR(SUM({is_.span("nonii", 0, hi)})/SUM({is_.span("ii", 0, hi)}),0)'),
        ('eff', 'Efficiency ratio (noninterest expense % revenue)', f'IFERROR(SUM({is_.span("nonie", 0, hi)})/SUM({is_.span("rev", 0, hi)}),0)'),
        ('prov', 'Provision % opening loans', f'IFERROR(AVERAGE({cr.span("prov_r", 1, hi)}),0)'),
        ('tax', 'Effective tax rate', f'MAX(0,MIN(1,IFERROR(SUM({is_.span("tax", 0, hi)})/SUM({is_.span("pretax", 0, hi)}),0)))'),
        ('div', 'Dividend payout % net income', f'MAX(0,MIN(1,IFERROR(-SUM({is_.span("div", 0, hi)})/SUM({is_.span("ni", 0, hi)}),0)))'),
        ('bb', 'Repurchases % net income', f'MAX(0,MIN(1,IFERROR(-SUM({is_.span("bb", 0, hi)})/SUM({is_.span("ni", 0, hi)}),0)))'),
    ]
    for key, label, f in drivers:
        asm.row(key, label)
        asm.set(key, 0, f'={f}', PCT)
    A = lambda k: asm.ref(k, 0, absolute=True)  # noqa: E731
    asm.ws.cell(row=asm.next_row + 1, column=1, value='Goodwill and intangibles are held at the last reported level; '
                'combined payout is capped so equity never falls below its opening level net of losses.').font = NOTE

    for j in range(n):
        p, h = j - 1, j < nh
        if h:
            is_.set('ii', j, f'={D("int_income", j)}')
            is_.set('ie', j, f'={D("int_expense_bank", j)}')
            is_.set('nonii', j, f'={D("nonint_income", j)}')
            is_.set('nonie', j, f'={D("nonint_expense", j)}')
            is_.set('prov', j, f'={D("provision", j)}')
            is_.set('other', j, f'={D("pretax", j)}-({I("ppnr", j)}-{I("prov", j)})')
            is_.set('tax', j, f'={D("tax", j)}')
            is_.set('ni', j, f'={D("net_income", j)}', bold=True)
            is_.set('div', j, f'=-{D("dividends", j)}')
            is_.set('bb', j, f'=-{D("buybacks", j)}')
            bs.set('loans', j, f'={D("loans", j)}')
            bs.set('assets', j, f'={D("assets", j)}', bold=True)
            bs.set('dep', j, f'={D("deposits", j)}')
            bs.set('eq', j, f'={D("equity", j)}', bold=True)
            bs.set('gw', j, f'={D("goodwill", j)}+{D("intangibles", j)}')
        else:
            is_.set('ii', j, f'={B("assets", p)}*{A("yield")}')
            is_.set('ie', j, f'=({B("dep", p)}+{B("ol", p)})*{A("cost")}')
            is_.set('nonii', j, f'={I("ii", j)}*{A("nonii")}')
            is_.set('nonie', j, f'={I("rev", j)}*{A("eff")}')
            is_.set('prov', j, f'={B("loans", p)}*{A("prov")}')
            is_.set('tax', j, f'=MAX(0,{I("pretax", j)})*{A("tax")}')
            is_.set('ni', j, f'={I("pretax", j)}-{I("tax", j)}', bold=True)
            is_.set('div', j, f'=-MAX(0,{I("ni", j)})*{A("div")}')
            is_.set('bb', j, f'=-MAX(0,{I("ni", j)})*{A("bb")}')
            bs.set('loans', j, f'={B("loans", p)}*(1+{A("loan_g")})')
            bs.set('assets', j, f'=IFERROR({B("loans", j)}/{A("loan_a")},{B("assets", p)})', bold=True)
            bs.set('dep', j, f'={B("assets", j)}*{A("dep_a")}')
            bs.set('eq', j, f'={B("eq", p)}+{I("ni", j)}+{I("div", j)}+{I("bb", j)}', bold=True)
            bs.set('gw', j, f'={B("gw", p)}')
        is_.set('nii', j, f'={I("ii", j)}-{I("ie", j)}', bold=True)
        is_.set('rev', j, f'={I("nii", j)}+{I("nonii", j)}', bold=True)
        is_.set('ppnr', j, f'={I("rev", j)}-{I("nonie", j)}', bold=True)
        is_.set('pretax', j, f'={I("ppnr", j)}-{I("prov", j)}+{I("other", j)}', bold=True)
        bs.set('oa', j, f'={B("assets", j)}-{B("loans", j)}')
        bs.set('ol', j, f'={B("assets", j)}-{B("dep", j)}-{B("eq", j)}')
        bs.set('liab', j, f'={B("dep", j)}+{B("ol", j)}', bold=True)
        bs.set('tle', j, f'={B("liab", j)}+{B("eq", j)}', bold=True)
        bs.set('check', j, f'=ROUND({B("loans", j)}+{B("oa", j)}-{B("tle", j)},3)')
        bs.set('tbv', j, f'={B("eq", j)}-{B("gw", j)}', bold=True)
        if j:
            cr.set('nim', j, f'=IFERROR({I("nii", j)}/{B("assets", p)},0)', PCT)
            cr.set('yield', j, f'=IFERROR({I("ii", j)}/{B("assets", p)},0)', PCT)
            cr.set('cost', j, f'=IFERROR({I("ie", j)}/({B("dep", p)}+{B("ol", p)}),0)', PCT)
            cr.set('prov_r', j, f'=IFERROR({I("prov", j)}/{B("loans", p)},0)', PCT)
            cr.set('roa', j, f'=IFERROR({I("ni", j)}/AVERAGE({B("assets", p)},{B("assets", j)}),0)', PCT)
            cr.set('roe', j, f'=IFERROR({I("ni", j)}/AVERAGE({B("eq", p)},{B("eq", j)}),0)', PCT)
            cr.set('rote', j, f'=IFERROR({I("ni", j)}/AVERAGE({B("tbv", p)},{B("tbv", j)}),0)', PCT)
            cr.set('loan_g', j, f'=IFERROR({B("loans", j)}/{B("loans", p)}-1,0)', PCT)
        cr.set('eff', j, f'=IFERROR({I("nonie", j)}/{I("rev", j)},0)', PCT)
        cr.set('nonii_r', j, f'=IFERROR({I("nonii", j)}/{I("ii", j)},0)', PCT)
        cr.set('eq_a', j, f'=IFERROR({B("eq", j)}/{B("assets", j)},0)', PCT)
        cr.set('tce', j, f'=IFERROR({B("tbv", j)}/({B("assets", j)}-{B("gw", j)}),0)', PCT)
        cr.set('ltd', j, f'=IFERROR({B("loans", j)}/{B("dep", j)},0)', PCT)
        cr.set('payout', j, f'=IFERROR(-({I("div", j)}+{I("bb", j)})/{I("ni", j)},0)', PCT)

    va = Inputs(wb, 'Valuation', head('Justified price to tangible book value'))
    va.add('ke', 'Cost of equity (CAPM)', f'={M("rf")}+{M("beta")}*{M("erp")}', PCT, formula=True)
    va.add('rote', 'Sustainable ROTE (forecast average)', f'=AVERAGE({cr.span("rote", nh, n - 1)})', PCT, formula=True)
    va.add('ptbv', 'Justified P/TBV = (ROTE - g) / (Ke - g)', f'=IFERROR(MAX(0,({va.ref("rote")}-{M("g")})/({va.ref("ke")}-{M("g")})),0)', MULT, formula=True)
    va.add('tbv', 'Tangible book value (latest year)', f'={B("tbv", hi)}', NUM, formula=True)
    va.add('eqv', 'Implied equity value', f'={va.ref("tbv")}*{va.ref("ptbv")}', NUM, formula=True)
    va.add('pe', 'Implied P/E on next-year earnings', f'=IFERROR({va.ref("eqv")}/{I("ni", nh)},0)', MULT, formula=True)
    va.add('vs', 'Implied value vs market value of equity', f'=IFERROR({va.ref("eqv")}/{M("mcap")}-1,0)', PCT,
           'Float excludes insider holdings', formula=True)

    checks(wb, [(f'Balance sheet balances ({periods[j]})', B('check', j)) for j in range(n)] +
           [('Cost of equity exceeds growth (0 = yes)', f'IF({va.ref("ke")}>{M("g")},0,1)')])
    cover(wb, 'Bank model (net interest income, credit, capital and valuation)', f'{sector} (peer group: {industry})',
          'Industry-specific bank model built from the company\'s reported 10-K figures: interest income and expense on '
          'opening balances, provisions on opening loans, efficiency-ratio cost base, balance sheet growth led by loans, '
          'capital and return ratios, and a justified price-to-tangible-book valuation.',
          [('Historical Data', 'Reported annual figures (USD millions) - hard-coded source data'),
           ('Market Inputs', 'Risk-free rate, ERP, beta, growth and market value (inputs)'),
           ('Assumptions', 'Forecast drivers calculated from history'),
           ('Income Statement', 'Net interest income to net income'),
           ('Balance Sheet', 'Loans, deposits, equity and tangible book value'),
           ('Capital & Returns', 'NIM, efficiency, credit cost, ROA/ROE/ROTE, capital ratios'),
           ('Valuation', 'Justified P/TBV and implied equity value'),
           ('Checks', 'Integrity checks')])
    wb.properties.title = f'{REDACTED} - Bank model'
    wb.properties.creator = REDACTED
    return wb
