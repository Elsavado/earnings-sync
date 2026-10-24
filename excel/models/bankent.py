"""Enterprise-wide bank models.

Core of every bank model: loans (gross, allowance, net), securities, cash and other assets, non-interest-bearing and
interest-bearing deposits, borrowings, equity and tangible book; net interest income on average earning assets and
opening funding; fee income; efficiency; provisions from an allowance roll-forward (charge-offs plus reserve build);
dividends, and share repurchases limited to capital above target; capital (RWA, CET1, leverage), liquidity and
funding; a Base / Upside / Downside scenario manager and an executive dashboard. Modules by type:
  bank_integrated  core only
  bank_capital     severe stress test of earnings and capital
  bank_alm         interest-rate risk: NII and EVE under parallel rate shocks
  bank_valuation   dividend discount, residual income and justified P/TBV with a sensitivity grid
  bank_strategic   ten-year horizon with every module
Interest expense and charge-offs run on opening balances, so there are no circular references.
"""
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

from . import enterprise, variants, xbrl
from .xl import (BOLD, INPUT, INPUT_FILL, MULT, NAVY, NOTE, NUM, PCT, PRICE, REDACTED, Inputs, Sheet, checks, col,
                 cover, data_sheet, new_workbook)

KINDS = {
    'bank_integrated': 'Integrated bank plan',
    'bank_capital': 'Bank capital planning & stress test',
    'bank_alm': 'Bank ALM & interest rate risk',
    'bank_valuation': 'Bank valuation',
    'bank_strategic': 'Strategic 10-year bank plan',
}
enterprise.BANK_KINDS.update(KINDS)
MODULES = {'bank_integrated': [], 'bank_capital': ['stress'], 'bank_alm': ['alm'], 'bank_valuation': ['valuation'],
           'bank_strategic': ['stress', 'alm', 'valuation']}
REQUIRED = ['int_income', 'int_expense_bank', 'nonint_expense', 'net_income', 'loans', 'deposits', 'assets', 'equity']
DATA_ROWS = [('int_income', 'Interest and dividend income'), ('int_expense_bank', 'Interest expense'),
             ('provision', 'Provision for credit losses'), ('nonint_income', 'Noninterest income'),
             ('nonint_expense', 'Noninterest expense'), ('pretax', 'Pre-tax income'), ('tax', 'Income tax expense'),
             ('net_income', 'Net income'), ('nco', 'Net charge-offs'), ('loans', 'Loans, net of allowance'),
             ('acl', 'Allowance for credit losses'), ('afs', 'Securities available for sale'),
             ('htm', 'Securities held to maturity'), ('assets', 'Total assets'), ('deposits', 'Total deposits'),
             ('nib_dep', 'Non-interest-bearing deposits'), ('equity', "Shareholders' equity"), ('goodwill', 'Goodwill'),
             ('intangibles', 'Other intangible assets'), ('dividends', 'Dividends paid'), ('buybacks', 'Share repurchases')]
SCEN = [('loan', 'Loan growth adjustment', 0.0, 0.02, -0.04, PCT),
        ('yield', 'Asset yield adjustment', 0.0, 0.0015, -0.0025, PCT),
        ('cost', 'Funding cost adjustment', 0.0, -0.001, 0.002, PCT),
        ('credit', 'Credit loss multiplier (charge-offs and reserves)', 1.0, 0.8, 1.75, '0.00"x"'),
        ('fee', 'Fee income growth adjustment', 0.0, 0.03, -0.08, PCT),
        ('eff', 'Efficiency ratio adjustment', 0.0, -0.01, 0.02, PCT)]


def prepare(facts, trim):
    got = xbrl.annual(facts, required=REQUIRED, anchor='net_income', max_years=40)  # every consecutive reported year
    if not got:
        return None
    ends, d = got
    if trim:
        if len(ends) - trim < 3:
            return None
        ends, d = ends[:-trim], {k: v[:-trim] for k, v in d.items()}
    nh = len(ends)
    if all(v is None for v in d['nco']):
        d['nco'] = list(d['provision'])  # long-run charge-offs approximated by provisions when not reported
    for i in range(nh):
        for k in ('provision', 'nonint_income', 'goodwill', 'intangibles', 'dividends', 'buybacks', 'tax', 'nco', 'acl',
                  'afs', 'htm', 'nib_dep'):
            if d[k][i] is None:
                d[k][i] = 0.0
        if d['pretax'][i] is None:
            d['pretax'][i] = round(d['net_income'][i] + d['tax'][i], 3)
        d['nco'][i] = abs(d['nco'][i])
    if d['assets'][-1] <= 0 or d['loans'][-1] <= 0 or d['int_income'][-1] <= 0 or d['deposits'][-1] <= 0:
        return None
    if any(d['afs'][i] + d['htm'][i] + d['loans'][i] > d['assets'][i] for i in range(nh)):
        for i in range(nh):
            d['afs'][i] = d['htm'][i] = 0.0
    if any(d['nib_dep'][i] > d['deposits'][i] for i in range(nh)):
        d['nib_dep'] = [0.0] * nh
    return ends, d


# Each bank model draws its own methods (variants.Variant, from the model key), so two models of one type differ in logic.
BANK = {
    'loan_growth': ['fade', 'decay', 'deposit_funded'],
    'deposit_pricing': ['flat', 'beta_to_rates', 'mix_shift'],
    'credit_cost': ['through_cycle', 'normalising', 'latest'],
    'capital_policy': ['historical_payout', 'cet1_target', 'fixed_payout'],
    'fees': ['ii_linked', 'asset_linked', 'fade_growth'],
    'stress_severity': ['adverse', 'severe', 'extreme'],
    'stress_shape': ['flat', 'front_loaded', 'u_shaped'],
    'stress_dividends': ['maintained', 'cut'],
    'curve_shock': ['parallel', 'steepener', 'flattener'],
    'deposit_beta': ['symmetric', 'asymmetric'],
    'valuation_weights': ['equal', 'rim_led', 'ddm_led', 'ptbv_led'],
    'ri_terminal': ['perpetuity', 'fading'],
    'cost_of_equity': ['capm', 'capm_premium'],
}
CORE_BLOCKS = ('loan_growth', 'deposit_pricing', 'credit_cost', 'capital_policy', 'fees')
MODULE_BLOCKS = {'stress': ('stress_severity', 'stress_shape', 'stress_dividends'), 'alm': ('curve_shock', 'deposit_beta'),
                 'valuation': ('valuation_weights', 'ri_terminal', 'cost_of_equity')}
BANK_MODULES = ['returns_tree', 'ppnr_bridge', 'deposit_franchise', 'capital_walk']
SEVERITY = {'adverse': (2.0, 0.08, 0.12), 'severe': (3.0, 0.12, 0.20), 'extreme': (4.0, 0.18, 0.30)}
CURVE = {'parallel': (1.0, 1.0), 'steepener': (0.5, 1.0), 'flattener': (1.0, 0.5)}
WEIGHTS = {'equal': (1 / 3, 1 / 3, 1 / 3), 'rim_led': (0.25, 0.5, 0.25), 'ddm_led': (0.5, 0.25, 0.25), 'ptbv_led': (0.25, 0.25, 0.5)}
BANK_WHY = {
    'fade': 'loan growth starts at its historical median and fades in a straight line to the long-term rate',
    'decay': 'excess loan growth decays geometrically, so the slowdown comes early',
    'deposit_funded': 'loans grow with deposits: balance-sheet growth is limited by the funding the bank can gather',
    'flat': 'asset yields and funding costs stay at their recent averages',
    'beta_to_rates': 'yields and deposit costs follow an expected rate path through their repricing betas',
    'mix_shift': 'non-interest-bearing deposits migrate towards interest-bearing accounts, raising the funding cost',
    'through_cycle': 'charge-offs and reserves at their average of recent years',
    'normalising': 'the charge-off rate moves from the latest year to its long-run average over the full history',
    'latest': 'charge-offs and reserve coverage held at the latest year, the best guide to the current book',
    'historical_payout': 'dividends and repurchases at their historical payout ratios, repurchases only from excess capital',
    'cet1_target': 'all capital above the CET1 target is returned through repurchases',
    'fixed_payout': 'a total payout target: dividends at the historical ratio, repurchases make up the rest when capital allows',
    'ii_linked': 'fee income grows with interest income',
    'asset_linked': 'fee income is a stable share of total assets',
    'fade_growth': 'fee income growth fades from its historical median to the long-term rate',
    'adverse': 'adverse stress: provisions x2, net interest income -8%, fees -12%',
    'severe': 'severe stress: provisions x3, net interest income -12%, fees -20%',
    'extreme': 'extreme stress: provisions x4, net interest income -18%, fees -30%',
    'front_loaded': 'the stress hits hardest in the first two years, then partly recovers',
    'u_shaped': 'the stress builds, peaks in years two and three and eases afterwards',
    'maintained': 'dividends are maintained while earnings are positive',
    'cut': 'dividends are suspended for the whole stress period',
    'parallel': 'rate shocks move short and long rates equally',
    'steepener': 'long rates move fully, short rates by half (a steepening curve)',
    'flattener': 'short rates move fully, long rates by half (a flattening curve)',
    'symmetric': 'deposit repricing is the same for rises and falls',
    'asymmetric': 'deposits reprice slower when rates rise than when they fall',
    'equal': 'equity value is the equal-weighted average of DDM, residual income and justified P/TBV',
    'rim_led': "residual income carries half the weight, as book value anchors a bank's value",
    'ddm_led': 'the dividend discount model carries half the weight: distributions are what shareholders receive',
    'ptbv_led': 'justified price to tangible book carries half the weight, as the market prices banks on P/TBV',
    'perpetuity': 'residual income continues to grow in perpetuity',
    'fading': 'residual income fades over time as competition erodes excess returns',
    'capm': 'cost of equity from CAPM',
    'capm_premium': 'CAPM plus a bank-specific risk premium',
}


BANK_HORIZONS = {'bank_integrated': [5, 6, 7], 'bank_capital': [5, 6], 'bank_alm': [5, 6], 'bank_valuation': [7, 8, 10],
                 'bank_strategic': [10, 12]}


def build(facts, sector, market, sic, kind, trim=0, profile=None, title=None):
    """title replaces 'Enterprise wide model - <kind>' (Excel Models bank models rebuilt on this engine keep their own name)."""
    got = prepare(facts, trim)
    if not got:
        return None
    ends, d = got
    mods = MODULES[kind]
    years = profile.pick(BANK_HORIZONS[kind]) if profile else (10 if kind == 'bank_strategic' else 5)
    bv = variants.Variant(f'{profile.key if profile else ends[-1] + sector}:bank', blocks=BANK, modules=BANK_MODULES)
    X = bv.methods
    nh, hi = len(ends), len(ends) - 1
    last = int(ends[-1][:4])
    periods = [f'FY{e[:4]}A' for e in ends] + [f'FY{last + k}E' for k in range(1, years + 1)]
    n, F0, FN = len(periods), nh, nh + years - 1
    wb = new_workbook()
    head = lambda t: f'{REDACTED} - {t}'  # noqa: E731
    ds = data_sheet(wb, head('Historical figures'), list(ends), DATA_ROWS, d, unit='USD millions')
    D = ds.ref

    shares = xbrl.dei_latest(facts, 'EntityCommonStockSharesOutstanding', 'shares')
    float_ = xbrl.dei_latest(facts, 'EntityPublicFloat', 'USD')
    bu, _, industry, _ = market.beta(sic)
    mi = Inputs(wb, 'Market Inputs', head('Market and valuation inputs'))
    mi.add('rf', 'Risk-free rate', market.rf, PCT, 'Current 10-year government bond yield')
    mi.add('erp', 'Equity risk premium', market.erp, PCT, 'Current implied equity risk premium')
    mi.add('beta', 'Equity beta', round(max(bu, 0.5) * 1.6, 3), '0.00', f'Industry beta ({industry}) relevered at bank leverage')
    mi.add('g', 'Long-term growth', 0.03, PCT, 'Growth of book value and distributions after the forecast')
    mi.add('mcap', 'Market value of equity (USD millions)', round(float_ / 1e6, 3) if float_ else 0, NUM)
    mi.add('shares', 'Shares outstanding (millions)', round(shares / 1e6, 3) if shares else 0, NUM)
    mi.add('k_step', 'Sensitivity step: cost of equity', 0.005, PCT)
    mi.add('g_step', 'Sensitivity step: growth', 0.005, PCT)
    if 'valuation' in mods:
        mi.section('Valuation method settings')
        for k_, lab, w in zip(('w_ddm', 'w_rim', 'w_ptbv'), ('Weight: dividend discount', 'Weight: residual income',
                                                             'Weight: justified P/TBV'), WEIGHTS[X['valuation_weights']]):
            mi.add(k_, lab, round(w, 6), PCT)
        if X['ri_terminal'] == 'fading':
            mi.add('omega', 'Persistence of residual income', round(bv.rng.uniform(0.6, 0.9), 2), '0.00',
                   'Share of residual income that survives each year after the forecast')
        if X['cost_of_equity'] == 'capm_premium':
            mi.add('prem', 'Bank-specific risk premium', round(bv.rng.choice([0.005, 0.01, 0.015]), 4), PCT)
    M = mi.ref

    bi = Inputs(wb, 'Bank Inputs', head('Capital, risk and stress inputs'))
    bi.section('Capital')
    bi.add('density', 'Risk-weighted assets % total assets', 0.72, PCT, 'Typical density for a commercial bank balance sheet')
    bi.add('target', 'Target CET1 ratio', 0.105, PCT, 'Management target including buffers')
    bi.add('min', 'Regulatory minimum CET1 ratio (incl. conservation buffer)', 0.07, PCT)
    bi.section('Growth guard-rails')
    bi.add('cap', 'Maximum starting loan growth', 0.15, PCT)
    bi.add('floor', 'Minimum starting loan growth', -0.05, PCT)
    bi.add('lt', 'Long-term loan growth', 0.03, PCT, 'Growth reached by the final forecast year')
    bi.section('Interest rate risk')
    bi.add('a_beta', 'Asset repricing beta (one year)', 0.45, PCT, 'Share of a rate move passed through to asset yields')
    bi.add('d_beta', 'Interest-bearing deposit beta (one year)', 0.35, PCT)
    bi.add('w_beta', 'Wholesale funding beta (one year)', 0.90, PCT)
    bi.add('a_dur', 'Asset duration (years)', 2.6, '0.0')
    bi.add('l_dur', 'Liability duration (years)', 1.4, '0.0')
    for k, bp in enumerate([-0.02, -0.01, 0.01, 0.02]):
        bi.add(f'shock{k}', f'Rate shock {k + 1}', bp, PCT)
    bi.section('Severe stress')
    sc_, sn_, sf_ = SEVERITY[X['stress_severity']]
    bi.add('s_credit', 'Provision multiplier', sc_, '0.00"x"')
    bi.add('s_nii', 'Net interest income decline', sn_, PCT)
    bi.add('s_fee', 'Fee income decline', sf_, PCT)
    bi.add('s_div', 'Dividends maintained during stress (1 = yes, 0 = cut)', 1 if X['stress_dividends'] == 'maintained' else 0, '0')
    bi.section('Method settings')
    if X['loan_growth'] == 'decay':
        bi.add('decay', 'Loan growth decay factor per year', round(bv.rng.uniform(0.55, 0.85), 2), '0.00')
    if X['deposit_pricing'] == 'beta_to_rates':
        bi.add('rate_chg', 'Expected change in policy rates per year', bv.rng.choice([-0.005, -0.0025, 0.0025, 0.005]), PCT)
    if X['deposit_pricing'] == 'mix_shift':
        nib_last = d['nib_dep'][hi] / d['deposits'][hi] if d['deposits'][hi] else 0.0
        bi.add('nib_tgt', 'Non-interest-bearing share of deposits by the final year', round(nib_last * bv.rng.uniform(0.75, 0.95), 4), PCT)
    if X['capital_policy'] == 'fixed_payout':
        bi.add('tp', 'Total payout target % net income', bv.rng.choice([0.6, 0.7, 0.8, 0.9]), PCT)
    short_w, long_w = CURVE[X['curve_shock']]
    bi.add('short_w', 'Short-rate share of each shock (repricing)', short_w, '0.00')
    bi.add('long_w', 'Long-rate share of each shock (economic value)', long_w, '0.00')
    up, down = (0.8, 1.2) if X['deposit_beta'] == 'asymmetric' else (1.0, 1.0)
    bi.add('d_up', 'Deposit beta multiplier when rates rise', up, '0.00')
    bi.add('d_down', 'Deposit beta multiplier when rates fall', down, '0.00')
    B_ = bi.ref

    si = Inputs(wb, 'Scenario Inputs', head('Scenario manager'))
    ws = si.ws
    r = si.next_row
    ws.cell(row=r, column=1, value='Active scenario (1 = Base, 2 = Upside, 3 = Downside)').font = BOLD
    sel = ws.cell(row=r, column=2, value=1)
    sel.font, sel.fill, sel.number_format = INPUT, INPUT_FILL, '0'
    dv = DataValidation(type='list', formula1='"1,2,3"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(sel.coordinate)
    sel_ref = f"'Scenario Inputs'!$B${r}"
    ws.cell(row=r + 1, column=1, value='Active scenario name')
    ws.cell(row=r + 1, column=2, value=f'=CHOOSE({sel_ref},"Base","Upside","Downside")').font = BOLD
    name_ref = f"'Scenario Inputs'!$B${r + 1}"
    r += 3
    for k, h in enumerate(['Driver adjustment', 'Base', 'Upside', 'Downside', 'Live (active case)']):
        ws.cell(row=r, column=1 + k, value=h).font = BOLD
    for letter in 'DE':
        ws.column_dimensions[letter].width = 16
    L = {}
    for key, label, base, up, down, fmt in SCEN:
        r += 1
        ws.cell(row=r, column=1, value=label)
        for k, v in enumerate((base, up, down)):
            cell = ws.cell(row=r, column=2 + k, value=v)
            cell.font, cell.fill, cell.number_format = INPUT, INPUT_FILL, fmt
        cell = ws.cell(row=r, column=5, value=f'=CHOOSE({sel_ref},B{r},C{r},D{r})')
        cell.number_format, cell.font = fmt, BOLD
        L[key] = f"'Scenario Inputs'!$E${r}"

    asm = Sheet(wb, 'Assumptions', head('Forecast drivers (from the historical years, with the live scenario)'), ['Driver'])
    is_ = Sheet(wb, 'Income Statement', head('Income statement'), periods, nh)
    bs = Sheet(wb, 'Balance Sheet', head('Balance sheet'), periods, nh)
    nb = Sheet(wb, 'NII Build', head('Net interest income build'), periods, nh)
    cq = Sheet(wb, 'Credit Quality', head('Loans, allowance roll-forward and credit costs'), periods, nh)
    cp = Sheet(wb, 'Capital', head('Regulatory capital and distributions (estimated)'), periods, nh)
    lq = Sheet(wb, 'Liquidity & Funding', head('Liquidity and funding structure'), periods, nh)
    rt = Sheet(wb, 'Returns & Efficiency', head('Profitability, returns and efficiency'), periods, nh)
    for key, label, bold, sec in [
        ('ii', 'Interest and dividend income', False, None), ('ie', 'Interest expense', False, None),
        ('nii', 'Net interest income', True, None), ('nonii', 'Noninterest (fee) income', False, None),
        ('rev', 'Total revenue', True, None), ('nonie', 'Noninterest expense', False, None),
        ('ppnr', 'Pre-provision net revenue', True, None), ('prov', 'Provision for credit losses', False, None),
        ('other', 'Securities gains, other items', False, None), ('pretax', 'Pre-tax income', True, None),
        ('tax', 'Income tax expense', False, None), ('ato', 'Discontinued operations & other', False, None),
        ('ni', 'Net income', True, None), ('div', 'Dividends', False, 'Distributions'), ('bb', 'Share repurchases', False, None),
        ('yr', 'Memo: forecast year', False, None)]:
        is_.row(key, label, bold, section=sec)
    for key, label, bold, sec in [
        ('gross', 'Gross loans', False, 'Assets'), ('acl', 'Less: allowance for credit losses', False, None),
        ('loans', 'Loans, net', True, None), ('sec', 'Investment securities', False, None),
        ('oa', 'Cash, other earning & other assets', False, None), ('assets', 'Total assets', True, None),
        ('nib', 'Non-interest-bearing deposits', False, 'Liabilities and equity'), ('ibd', 'Interest-bearing deposits', False, None),
        ('dep', 'Total deposits', True, None), ('ol', 'Borrowings & other liabilities', False, None),
        ('liab', 'Total liabilities', True, None), ('eq', "Shareholders' equity", True, None),
        ('tle', 'Total liabilities & equity', True, None), ('check', 'Balance check', False, None),
        ('gw', 'Memo: goodwill & intangibles', False, None), ('tbv', 'Memo: tangible book value', True, None)]:
        bs.row(key, label, bold, section=sec)
    I, B, N_, Q, K, LQ, R = is_.ref, bs.ref, nb.ref, cq.ref, cp.ref, lq.ref, rt.ref

    for key, label, bold, sec in [
        ('avg_assets', 'Average total assets', False, 'Earning side'), ('yield', 'Interest income yield on average assets', False, None),
        ('ii', 'Interest and dividend income', True, None),
        ('fund_open', 'Opening interest-bearing funding (deposits + borrowings)', False, 'Funding side'),
        ('cost', 'Cost of interest-bearing funding', False, None), ('ie', 'Interest expense', True, None),
        ('nii', 'Net interest income', True, 'Margin'), ('nim', 'Net interest margin (on average assets)', False, None),
        ('spread', 'Spread (yield less funding cost)', False, None), ('nib_benefit', 'Value of non-interest-bearing deposits', False, None)]:
        nb.row(key, label, bold, section=sec)
    for key, label, bold, sec in [
        ('gross_g', 'Gross loan growth', False, 'Loans'), ('acl_open', 'Opening allowance', False, 'Allowance roll-forward'),
        ('prov', 'Plus: provision', False, None), ('nco', 'Less: net charge-offs', False, None),
        ('acl_other', 'Other (acquisitions, adoption effects)', False, None), ('acl', 'Closing allowance', True, None),
        ('acl_chk', 'Check: roll-forward vs balance sheet', False, None),
        ('cov', 'Allowance % gross loans', False, 'Credit metrics'), ('nco_r', 'Net charge-off rate (on opening loans)', False, None),
        ('prov_r', 'Provision % opening loans', False, None), ('prov_nco', 'Provision / net charge-offs (x)', False, None),
        ('build', 'Reserve build / (release)', False, None)]:
        cq.row(key, label, bold, section=sec)
    for key, label, bold, sec in [
        ('rwa', 'Risk-weighted assets', False, 'Capital'), ('cet1', 'CET1 capital (tangible common equity)', True, None),
        ('cet1_r', 'CET1 ratio', True, None), ('lev', 'Leverage ratio (CET1 / tangible assets)', False, None),
        ('req', 'Capital required at target', False, None), ('excess', 'Excess / (shortfall) capital vs target', True, None),
        ('buffer', 'Buffer over regulatory minimum (pp)', False, None), ('test', 'Regulatory minimum test', False, None),
        ('gen', 'Capital generated (net income)', False, 'Distributions'), ('dist', 'Total distributions', False, None),
        ('payout', 'Total payout % net income', False, None)]:
        cp.row(key, label, bold, section=sec)
    for key, label in [('ldr', 'Loans / deposits'), ('dep_a', 'Deposits / assets'), ('nib_s', 'Non-interest-bearing % deposits'),
                       ('sec_a', 'Securities / assets'), ('liquid', '(Securities + cash & other) / assets'),
                       ('whole', 'Borrowings & other % total funding'), ('dep_g', 'Deposit growth')]:
        lq.row(key, label)
    for key, label in [('roa', 'Return on average assets'), ('roe', 'Return on average equity'),
                       ('rote', 'Return on average tangible equity'), ('eff', 'Efficiency ratio'),
                       ('fee_r', 'Fee income % revenue'), ('fee_ii', 'Fee income % interest income'),
                       ('fee_g', 'Fee income growth'), ('tax_r', 'Effective tax rate'), ('eq_a', 'Equity / assets')]:
        rt.row(key, label)
    if bv.has('returns_tree'):
        rt.row('tlev', 'Tangible leverage (average assets / average tangible equity)', section='Returns tree')
        rt.row('rote_d', 'ROTE = ROA x tangible leverage')
        rt.row('rote_chk', 'Check: tree vs ROTE')

    w0 = max(0, nh - 5)  # drivers from the latest five years; the full history stays on every sheet

    def span(sheet, key, a=0, b=hi):
        return sheet.span(key, max(a, w0), b)
    drivers = [
        ('loan_g', 'Starting gross loan growth (historical median, within limits) + scenario',
         f'MAX({B_("floor")},MIN({B_("cap")},IFERROR(MEDIAN({span(cq, "gross_g", 1)}),0)))+{L["loan"]}'),
        ('loan_a', 'Net loans % total assets', f'IFERROR(SUM({span(bs, "loans")})/SUM({span(bs, "assets")}),0)'),
        ('sec_a', 'Securities % total assets', f'IFERROR(SUM({span(bs, "sec")})/SUM({span(bs, "assets")}),0)'),
        ('dep_a', 'Deposits % total assets', f'IFERROR(SUM({span(bs, "dep")})/SUM({span(bs, "assets")}),0)'),
        ('nib_s', 'Non-interest-bearing % deposits', f'IFERROR(SUM({span(bs, "nib")})/SUM({span(bs, "dep")}),0)'),
        ('yield', 'Yield on average assets + scenario', f'IFERROR(AVERAGE({span(nb, "yield", 1)}),0)+{L["yield"]}'),
        ('cost', 'Cost of interest-bearing funding + scenario', f'MAX(0,IFERROR(AVERAGE({span(nb, "cost", 1)}),0)+{L["cost"]})'),
        ('fee', 'Fee income % interest income', f'IFERROR(SUM({span(is_, "nonii")})/SUM({span(is_, "ii")}),0)'),
        ('eff', 'Efficiency ratio + scenario', f'IFERROR(SUM({span(is_, "nonie")})/SUM({span(is_, "rev")}),0)+{L["eff"]}'),
        ('cov', 'Allowance % gross loans x credit multiplier', f'IFERROR(AVERAGE({span(cq, "cov")}),0)*{L["credit"]}'),
        ('nco', 'Net charge-off rate x credit multiplier', f'IFERROR(AVERAGE({span(cq, "nco_r", 1)}),0)*{L["credit"]}'),
        ('tax', 'Effective tax rate', f'MAX(0,MIN(1,IFERROR(SUM({span(is_, "tax")})/SUM({span(is_, "pretax")}),0)))'),
        ('div', 'Dividend payout % net income', f'MAX(0,MIN(1,IFERROR(-SUM({span(is_, "div")})/SUM({span(is_, "ni")}),0)))'),
        ('bb', 'Repurchases % net income (capital permitting)', f'MAX(0,MIN(1,IFERROR(-SUM({span(is_, "bb")})/SUM({span(is_, "ni")}),0)))')]
    if X['loan_growth'] == 'deposit_funded':
        drivers.append(('dep_g0', 'Starting deposit growth (historical median, within limits) + scenario',
                        f'MAX({B_("floor")},MIN({B_("cap")},IFERROR(MEDIAN({span(lq, "dep_g", 1)}),0)))+{L["loan"]}'))
    if X['credit_cost'] in ('normalising', 'latest'):
        drivers.append(('nco_last', 'Net charge-off rate, latest year x credit multiplier', f'{cq.ref("nco_r", hi)}*{L["credit"]}'))
    if X['credit_cost'] == 'normalising':
        drivers.append(('nco_lr', 'Net charge-off rate, full-history average x credit multiplier',
                        f'IFERROR(AVERAGE({cq.span("nco_r", 1, hi)}),0)*{L["credit"]}'))
    if X['credit_cost'] == 'latest':
        drivers.append(('cov_last', 'Allowance % gross loans, latest year x credit multiplier', f'{cq.ref("cov", hi)}*{L["credit"]}'))
    if X['fees'] == 'asset_linked':
        drivers.append(('fee_a', 'Fee income % total assets', f'IFERROR(SUM({span(is_, "nonii")})/SUM({span(bs, "assets")}),0)'))
    if X['fees'] == 'fade_growth':
        drivers.append(('fee_g0', 'Fee income growth (historical median, within -10% / +20%)',
                        f'MAX(-0.1,MIN(0.2,IFERROR(MEDIAN({span(rt, "fee_g", 1)}),0)))'))
    for key, label, f in drivers:
        asm.row(key, label)
        asm.set(key, 0, f'={f}', PCT)
    A = lambda k: asm.ref(k, 0, absolute=True)  # noqa: E731

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
            is_.set('ato', j, f'={D("net_income", j)}-({I("pretax", j)}-{I("tax", j)})')
            is_.set('div', j, f'=-{D("dividends", j)}')
            is_.set('bb', j, f'=-{D("buybacks", j)}')
            bs.set('acl', j, f'={D("acl", j)}')
            bs.set('loans', j, f'={D("loans", j)}', bold=True)
            bs.set('gross', j, f'={B("loans", j)}+{B("acl", j)}')
            bs.set('sec', j, f'={D("afs", j)}+{D("htm", j)}')
            bs.set('assets', j, f'={D("assets", j)}', bold=True)
            bs.set('nib', j, f'={D("nib_dep", j)}')
            bs.set('ibd', j, f'={D("deposits", j)}-{B("nib", j)}')
            bs.set('eq', j, f'={D("equity", j)}', bold=True)
            bs.set('gw', j, f'={D("goodwill", j)}+{D("intangibles", j)}')
            cq.set('nco', j, f'={D("nco", j)}')
        else:
            is_.set('yr', j, f'=N({I("yr", p)})+1', '0')
            is_.set('ii', j, f'={N_("ii", j)}')
            is_.set('ie', j, f'={N_("ie", j)}')
            t = f'{I("yr", j)}/{years}'  # share of the horizon elapsed
            fee_adj = f'*(1+{L["fee"]})' if j == F0 else ''
            if X['fees'] == 'asset_linked':
                is_.set('nonii', j, f'={B("assets", j)}*{A("fee_a")}{fee_adj}')
            elif X['fees'] == 'fade_growth':
                is_.set('nonii', j, f'={I("nonii", p)}*(1+{A("fee_g0")}+({B_("lt")}-{A("fee_g0")})*{t}){fee_adj}')
            else:
                is_.set('nonii', j, f'={I("nonii", p)}*(1+IFERROR({I("ii", j)}/{I("ii", p)}-1,0)+{L["fee"]})' if j == F0 else
                        f'={I("nonii", p)}*(1+IFERROR({I("ii", j)}/{I("ii", p)}-1,0))')
            is_.set('nonie', j, f'={I("rev", j)}*{A("eff")}')
            is_.set('prov', j, f'={Q("prov", j)}')
            is_.set('other', j, f'={I("yr", j)}-{I("yr", j)}')
            is_.set('tax', j, f'=MAX(0,{I("pretax", j)})*{A("tax")}')
            is_.set('ato', j, f'={I("yr", j)}-{I("yr", j)}')
            is_.set('div', j, f'=-MAX(0,{I("ni", j)})*{A("div")}')
            # Repurchases only from capital above the target CET1 ratio.
            excess = f'{B("eq", p)}+{I("ni", j)}+{I("div", j)}-{B("gw", j)}-{K("req", j)}'
            if X['capital_policy'] == 'cet1_target':
                is_.set('bb', j, f'=-MAX(0,{excess})')
            elif X['capital_policy'] == 'fixed_payout':
                is_.set('bb', j, f'=-MAX(0,MIN(MAX(0,{I("ni", j)})*MAX(0,{B_("tp")}-{A("div")}),{excess}))')
            else:
                is_.set('bb', j, f'=-MAX(0,MIN(MAX(0,{I("ni", j)})*{A("bb")},{excess}))')
            if X['loan_growth'] == 'decay':
                g = f'{B_("lt")}+({A("loan_g")}-{B_("lt")})*{B_("decay")}^{I("yr", j)}'
            elif X['loan_growth'] == 'deposit_funded':
                g = f'{A("dep_g0")}+({B_("lt")}-{A("dep_g0")})*{t}'
            else:
                g = f'{A("loan_g")}+({B_("lt")}-{A("loan_g")})*{t}'
            bs.set('gross', j, f'={B("gross", p)}*(1+{g})')
            bs.set('acl', j, f'={B("gross", j)}*{A("cov_last") if X["credit_cost"] == "latest" else A("cov")}')
            bs.set('loans', j, f'={B("gross", j)}-{B("acl", j)}', bold=True)
            bs.set('assets', j, f'=IFERROR({B("loans", j)}/{A("loan_a")},{B("assets", p)})', bold=True)
            bs.set('sec', j, f'={B("assets", j)}*{A("sec_a")}')
            bs.set('nib', j, f'={B("dep", j)}*({A("nib_s")}+({B_("nib_tgt")}-{A("nib_s")})*{t})' if X['deposit_pricing'] == 'mix_shift'
                   else f'={B("dep", j)}*{A("nib_s")}')
            bs.set('ibd', j, f'={B("dep", j)}-{B("nib", j)}')
            bs.set('eq', j, f'={B("eq", p)}+{I("ni", j)}+{I("div", j)}+{I("bb", j)}', bold=True)
            bs.set('gw', j, f'={B("gw", p)}')
            if X['credit_cost'] == 'latest':
                nco = A('nco_last')
            elif X['credit_cost'] == 'normalising':
                nco = f'({A("nco_last")}+({A("nco_lr")}-{A("nco_last")})*{t})'
            else:
                nco = A('nco')
            cq.set('nco', j, f'={B("gross", p)}*{nco}')
            cq.set('prov', j, f'={Q("nco", j)}+{B("acl", j)}-{Q("acl_open", j)}')
        is_.set('nii', j, f'={I("ii", j)}-{I("ie", j)}', bold=True)
        is_.set('rev', j, f'={I("nii", j)}+{I("nonii", j)}', bold=True)
        is_.set('ppnr', j, f'={I("rev", j)}-{I("nonie", j)}', bold=True)
        is_.set('pretax', j, f'={I("ppnr", j)}-{I("prov", j)}+{I("other", j)}', bold=True)
        is_.set('ni', j, f'={I("pretax", j)}-{I("tax", j)}+{I("ato", j)}', bold=True)
        bs.set('oa', j, f'={B("assets", j)}-{B("loans", j)}-{B("sec", j)}')
        if not h:
            bs.set('dep', j, f'={B("assets", j)}*{A("dep_a")}', bold=True)
        else:
            bs.set('dep', j, f'={B("nib", j)}+{B("ibd", j)}', bold=True)
        bs.set('ol', j, f'={B("assets", j)}-{B("dep", j)}-{B("eq", j)}')
        bs.set('liab', j, f'={B("dep", j)}+{B("ol", j)}', bold=True)
        bs.set('tle', j, f'={B("liab", j)}+{B("eq", j)}', bold=True)
        bs.set('check', j, f'=ROUND({B("loans", j)}+{B("sec", j)}+{B("oa", j)}-{B("tle", j)},3)')
        bs.set('tbv', j, f'={B("eq", j)}-{B("gw", j)}', bold=True)

        # NII build
        if j:
            nb.set('avg_assets', j, f'=AVERAGE({B("assets", p)},{B("assets", j)})')
            nb.set('fund_open', j, f'={B("ibd", p)}+{B("ol", p)}')
            if h:
                nb.set('ii', j, f'={I("ii", j)}', bold=True)
                nb.set('ie', j, f'={I("ie", j)}', bold=True)
                nb.set('yield', j, f'=IFERROR({N_("ii", j)}/{N_("avg_assets", j)},0)', PCT)
                nb.set('cost', j, f'=IFERROR({N_("ie", j)}/{N_("fund_open", j)},0)', PCT)
            else:
                if X['deposit_pricing'] == 'beta_to_rates':
                    nb.set('yield', j, f'={A("yield")}+{B_("a_beta")}*{B_("rate_chg")}*{I("yr", j)}', PCT)
                    nb.set('cost', j, f'=MAX(0,{A("cost")}+{B_("d_beta")}*{B_("rate_chg")}*{I("yr", j)})', PCT)
                else:
                    nb.set('yield', j, f'={A("yield")}', PCT)
                    nb.set('cost', j, f'={A("cost")}', PCT)
                nb.set('ii', j, f'={N_("avg_assets", j)}*{N_("yield", j)}', bold=True)
                nb.set('ie', j, f'={N_("fund_open", j)}*{N_("cost", j)}', bold=True)
            nb.set('nii', j, f'={N_("ii", j)}-{N_("ie", j)}', bold=True)
            nb.set('nim', j, f'=IFERROR({N_("nii", j)}/{N_("avg_assets", j)},0)', PCT)
            nb.set('spread', j, f'={N_("yield", j)}-{N_("cost", j)}', PCT)
            nb.set('nib_benefit', j, f'={B("nib", p)}*{N_("cost", j)}')
            # Credit quality
            cq.set('gross_g', j, f'=IFERROR({B("gross", j)}/{B("gross", p)}-1,0)', PCT)
            cq.set('acl_open', j, f'={B("acl", p)}')
            if h:
                cq.set('prov', j, f'={I("prov", j)}')
                cq.set('acl_other', j, f'={B("acl", j)}-({Q("acl_open", j)}+{Q("prov", j)}-{Q("nco", j)})')
            else:
                cq.set('acl_other', j, f'={Q("acl_open", j)}-{Q("acl_open", j)}')
            cq.set('acl', j, f'={Q("acl_open", j)}+{Q("prov", j)}-{Q("nco", j)}+{Q("acl_other", j)}', bold=True)
            cq.set('acl_chk', j, f'=ROUND({Q("acl", j)}-{B("acl", j)},3)')
            cq.set('nco_r', j, f'=IFERROR({Q("nco", j)}/{B("gross", p)},0)', PCT)
            cq.set('prov_r', j, f'=IFERROR({Q("prov", j)}/{B("gross", p)},0)', PCT)
            cq.set('prov_nco', j, f'=IFERROR({Q("prov", j)}/{Q("nco", j)},0)', MULT)
            cq.set('build', j, f'={Q("prov", j)}-{Q("nco", j)}')
            lq.set('dep_g', j, f'=IFERROR({B("dep", j)}/{B("dep", p)}-1,0)', PCT)
            rt.set('roa', j, f'=IFERROR({I("ni", j)}/AVERAGE({B("assets", p)},{B("assets", j)}),0)', PCT)
            rt.set('roe', j, f'=IFERROR({I("ni", j)}/AVERAGE({B("eq", p)},{B("eq", j)}),0)', PCT)
            rt.set('rote', j, f'=IFERROR({I("ni", j)}/AVERAGE({B("tbv", p)},{B("tbv", j)}),0)', PCT)
            rt.set('fee_g', j, f'=IFERROR({I("nonii", j)}/{I("nonii", p)}-1,0)', PCT)
            if bv.has('returns_tree'):
                rt.set('tlev', j, f'=IFERROR(AVERAGE({B("assets", p)},{B("assets", j)})/AVERAGE({B("tbv", p)},{B("tbv", j)}),0)', MULT)
                rt.set('rote_d', j, f'={R("roa", j)}*{R("tlev", j)}', PCT)
                rt.set('rote_chk', j, f'=ROUND(IF({R("tlev", j)}=0,0,{R("rote_d", j)}-{R("rote", j)}),6)')
        if h:
            cq.set('acl', j, f'={B("acl", j)}', bold=True) if not j else None
        cq.set('cov', j, f'=IFERROR({B("acl", j)}/{B("gross", j)},0)', PCT)
        # Capital
        cp.set('rwa', j, f'={B("assets", j)}*{B_("density")}')
        cp.set('cet1', j, f'={B("tbv", j)}', bold=True)
        cp.set('cet1_r', j, f'=IFERROR({K("cet1", j)}/{K("rwa", j)},0)', PCT, bold=True)
        cp.set('lev', j, f'=IFERROR({K("cet1", j)}/({B("assets", j)}-{B("gw", j)}),0)', PCT)
        cp.set('req', j, f'={K("rwa", j)}*{B_("target")}')
        cp.set('excess', j, f'={K("cet1", j)}-{K("req", j)}', bold=True)
        cp.set('buffer', j, f'=({K("cet1_r", j)}-{B_("min")})*100', '0.00')
        cp.set('test', j, f'=IF({K("cet1_r", j)}>={B_("min")},"Pass","Below minimum")', '@')
        cp.set('gen', j, f'={I("ni", j)}')
        cp.set('dist', j, f'=-({I("div", j)}+{I("bb", j)})')
        cp.set('payout', j, f'=IFERROR({K("dist", j)}/{I("ni", j)},0)', PCT)
        # Liquidity
        lq.set('ldr', j, f'=IFERROR({B("gross", j)}/{B("dep", j)},0)', PCT)
        lq.set('dep_a', j, f'=IFERROR({B("dep", j)}/{B("assets", j)},0)', PCT)
        lq.set('nib_s', j, f'=IFERROR({B("nib", j)}/{B("dep", j)},0)', PCT)
        lq.set('sec_a', j, f'=IFERROR({B("sec", j)}/{B("assets", j)},0)', PCT)
        lq.set('liquid', j, f'=IFERROR(({B("sec", j)}+{B("oa", j)})/{B("assets", j)},0)', PCT)
        lq.set('whole', j, f'=IFERROR({B("ol", j)}/({B("dep", j)}+{B("ol", j)}),0)', PCT)
        # Returns
        rt.set('eff', j, f'=IFERROR({I("nonie", j)}/{I("rev", j)},0)', PCT)
        rt.set('fee_r', j, f'=IFERROR({I("nonii", j)}/{I("rev", j)},0)', PCT)
        rt.set('fee_ii', j, f'=IFERROR({I("nonii", j)}/{I("ii", j)},0)', PCT)
        rt.set('tax_r', j, f'=IFERROR({I("tax", j)}/{I("pretax", j)},0)', PCT)
        rt.set('eq_a', j, f'=IFERROR({B("eq", j)}/{B("assets", j)},0)', PCT)
    asm.ws.cell(row=asm.next_row + 1, column=1, value='Goodwill and intangibles are held at the last historical level; '
                'borrowings and other liabilities balance the balance sheet; repurchases never take CET1 below target.').font = NOTE

    sections = [('Historical Data', 'Historical annual figures (USD millions) - hard-coded inputs'),
                ('Market Inputs', 'Rates, equity risk premium, beta, long-term growth and share data (inputs)'),
                ('Bank Inputs', 'Capital targets, growth guard-rails, rate-risk and stress parameters (inputs)'),
                ('Scenario Inputs', 'Base / Upside / Downside scenario manager (inputs)'),
                ('Assumptions', 'Forecast drivers from the historical years with the live scenario'),
                ('Income Statement', 'Net interest income to net income and distributions'),
                ('Balance Sheet', 'Loans, securities, deposits, funding, equity and tangible book'),
                ('NII Build', 'Average balances, yields, funding costs, margin and spread'),
                ('Credit Quality', 'Allowance roll-forward, charge-offs, provisions and coverage'),
                ('Capital', 'RWA, CET1 and leverage ratios, excess capital and distributions'),
                ('Liquidity & Funding', 'Loan-to-deposit, deposit mix, securities and wholesale funding'),
                ('Returns & Efficiency', 'ROA, ROE, ROTE, efficiency and fee income')]
    items = [(f'Balance sheet balances ({periods[j]})', B('check', j)) for j in range(n)]
    items += [(f'Allowance roll-forward ties ({periods[j]})', Q('acl_chk', j)) for j in range(F0, n)]
    items.append(('Scenario switch is 1, 2 or 3', f'IF(OR({sel_ref}=1,{sel_ref}=2,{sel_ref}=3),0,1)'))
    if bv.has('returns_tree'):
        items += [(f'Returns tree reconciles ({periods[j]})', R('rote_chk', j)) for j in range(F0, n)]
    if bv.has('deposit_franchise'):
        lq.row('nib_val', 'Funding benefit of non-interest-bearing deposits', section='Deposit franchise')
        lq.row('nib_nii', '  % net interest income')
        for j in range(1, n):
            lq.set('nib_val', j, f'={N_("nib_benefit", j)}', NUM)
            lq.set('nib_nii', j, f'=IFERROR({LQ("nib_val", j)}/{I("nii", j)},0)', PCT)
        sections[sections.index(('Liquidity & Funding', 'Loan-to-deposit, deposit mix, securities and wholesale funding'))] = (
            'Liquidity & Funding', 'Loan-to-deposit, deposit mix, securities, wholesale funding and the deposit franchise value')
    if bv.has('capital_walk'):
        cp.row('w_open', 'Opening CET1 capital', section='CET1 walk')
        cp.row('w_ni', 'Plus: net income')
        cp.row('w_dist', 'Less: distributions')
        cp.row('w_other', 'Goodwill, intangibles & other equity movements')
        cp.row('w_close', 'Closing CET1 capital', bold=True)
        cp.row('w_chk', 'Check: walk vs CET1')
        for j in range(1, n):
            p = j - 1
            cp.set('w_open', j, f'={K("cet1", p)}')
            cp.set('w_ni', j, f'={I("ni", j)}')
            cp.set('w_dist', j, f'={I("div", j)}+{I("bb", j)}')
            cp.set('w_other', j, f'={K("cet1", j)}-({K("w_open", j)}+{K("w_ni", j)}+{K("w_dist", j)})' if j < nh
                   else f'=-({B("gw", j)}-{B("gw", p)})')
            cp.set('w_close', j, f'={K("w_open", j)}+{K("w_ni", j)}+{K("w_dist", j)}+{K("w_other", j)}', bold=True)
            cp.set('w_chk', j, f'=ROUND({K("w_close", j)}-{K("cet1", j)},3)')
        items += [(f'CET1 walk reconciles ({periods[j]})', K('w_chk', j)) for j in range(F0, n)]
    if bv.has('ppnr_bridge'):
        pb = Sheet(wb, 'PPNR Bridge', head('Pre-provision net revenue bridge, year on year'), periods, nh)
        for key, label, bold in [('nii', 'Net interest income change', False), ('fee', 'Fee income change', False),
                                 ('exp', 'Noninterest expense change (increase = negative)', False), ('tot', 'Change in PPNR', True),
                                 ('chk', 'Bridge check (total - actual change)', False)]:
            pb.row(key, label, bold)
        for j in range(1, n):
            p = j - 1
            pb.set('nii', j, f'={I("nii", j)}-{I("nii", p)}')
            pb.set('fee', j, f'={I("nonii", j)}-{I("nonii", p)}')
            pb.set('exp', j, f'=-({I("nonie", j)}-{I("nonie", p)})')
            pb.set('tot', j, f'={pb.ref("nii", j)}+{pb.ref("fee", j)}+{pb.ref("exp", j)}', bold=True)
            pb.set('chk', j, f'=ROUND({pb.ref("tot", j)}-({I("ppnr", j)}-{I("ppnr", p)}),3)')
            items.append((f'PPNR bridge reconciles ({periods[j]})', pb.ref('chk', j)))
        sections.append(('PPNR Bridge', 'Net interest income, fee and expense effects on pre-provision net revenue'))
    extra = []
    c = dict(wb=wb, head=head, periods=periods, nh=nh, n=n, F0=F0, FN=FN, years=years, I=I, B=B, K=K, Q=Q, M=M, B_=B_,
             is_=is_, bs=bs, cp=cp, nb=nb, X=X)
    c.update(ends=ends, data=d, ds=ds, heading=head, profile=profile, base_last=d['assets'][hi])
    a, b = enterprise.company_lines(wb, c, facts, base=lambda j: B('assets', j), base_label='total assets')
    sections, items = sections + a, items + b
    if 'stress' in mods:
        a, b, e = stress(c)
        sections, items, extra = sections + a, items + b, extra + e
    if 'alm' in mods:
        a, b, e = alm(c)
        sections, items, extra = sections + a, items + b, extra + e
    if 'valuation' in mods:
        a, b, e = valuation(c)
        sections, items, extra = sections + a, items + b, extra + e
    shown = {b: X[b] for b in CORE_BLOCKS}
    for m in mods:
        shown.update({b: X[b] for b in MODULE_BLOCKS[m]})
    enterprise._methods_note(bi.ws, bi.next_row + 1, shown, BANK_WHY)
    sections = dashboard(c, name_ref, extra) + sections
    sections.append(('Checks', 'Integrity checks'))
    checks(wb, items)
    label = KINDS[kind]
    cover(wb, title or f'Enterprise wide model - {label}', f'{sector}',
          f'Enterprise-wide {label.lower()} built from the bank\'s historical financial statements with a {years}-year '
          'forecast: net interest income on average balances, fee income, efficiency, an allowance roll-forward that '
          'drives provisions, capital (RWA, CET1, leverage) with capital-constrained repurchases, liquidity and funding, '
          'and a Base / Upside / Downside scenario manager. This model\'s own methods: '
          + '; '.join(f'{b.replace("_", " ")}: {m.replace("_", " ")}' for b, m in shown.items())
          + '. All figures outside the input sheets are formulas.', sections)
    wb.properties.title = f'{REDACTED} - {label}'
    wb.asof = ends[-1][:4]
    wb.variant = bv
    return enterprise.finish(wb)


def stress(c):
    I, K, B_, periods, F0, FN, n = c['I'], c['K'], c['B_'], c['periods'], c['F0'], c['FN'], c['n']
    st = Sheet(c['wb'], 'Stress Test', c['head']('Severe stress test of earnings and capital'), periods, c['nh'])
    for key, label, bold, sec in [
        ('w', 'Stress intensity (1 = full severity)', False, 'Stress path'),
        ('nii', 'Net interest income (stressed)', False, 'Stressed earnings'), ('fee', 'Fee income (stressed)', False, None),
        ('exp', 'Noninterest expense', False, None), ('ppnr', 'Pre-provision net revenue', True, None),
        ('prov', 'Provision for credit losses (stressed)', False, None), ('pretax', 'Pre-tax income', True, None),
        ('tax', 'Income tax (no benefit on losses)', False, None), ('ni', 'Net income', True, None),
        ('div', 'Dividends', False, None),
        ('cet1', 'CET1 capital (stressed)', True, 'Stressed capital'), ('rwa', 'Risk-weighted assets', False, None),
        ('ratio', 'CET1 ratio (stressed)', True, None), ('vs_base', 'Change vs base CET1 ratio (pp)', False, None)]:
        st.row(key, label, bold, section=sec)
    S = st.ref
    hi = F0 - 1
    st.set('cet1', hi, f'={K("cet1", hi)}', bold=True)
    for j in range(F0, n):
        p = j - 1
        t = I('yr', j)
        shape = c['X']['stress_shape']
        st.set('w', j, {'flat': f'=1+{t}-{t}', 'front_loaded': f'=IF({t}<=2,1,0.4)',
                        'u_shaped': f'=IF({t}<=1,0.6,IF({t}<=3,1,0.5))'}[shape], '0.00')
        st.set('nii', j, f'={I("nii", j)}*(1-{B_("s_nii")}*{S("w", j)})')
        st.set('fee', j, f'={I("nonii", j)}*(1-{B_("s_fee")}*{S("w", j)})')
        st.set('exp', j, f'={I("nonie", j)}')
        st.set('ppnr', j, f'={S("nii", j)}+{S("fee", j)}-{S("exp", j)}', bold=True)
        st.set('prov', j, f'=MAX(0,{I("prov", j)})*(1+({B_("s_credit")}-1)*{S("w", j)})')
        st.set('pretax', j, f'={S("ppnr", j)}-{S("prov", j)}', bold=True)
        st.set('tax', j, f'=MAX(0,{S("pretax", j)})*IFERROR({I("tax", j)}/{I("pretax", j)},0)')
        st.set('ni', j, f'={S("pretax", j)}-{S("tax", j)}', bold=True)
        st.set('div', j, f'=IF({S("ni", j)}>0,{I("div", j)}*{B_("s_div")},0)')
        st.set('cet1', j, f'={S("cet1", p)}+{S("ni", j)}+{S("div", j)}', bold=True)
        st.set('rwa', j, f'={K("rwa", j)}')
        st.set('ratio', j, f'=IFERROR({S("cet1", j)}/{S("rwa", j)},0)', PCT, bold=True)
        st.set('vs_base', j, f'=({S("ratio", j)}-{K("cet1_r", j)})*100', '0.00')
    mn = f'MIN({st.span("ratio", F0, FN)})'
    r = st.next_row + 1
    st.ws.cell(row=r, column=1, value='Minimum stressed CET1 ratio').font = BOLD
    st.ws.cell(row=r, column=2, value=f'={mn}').number_format = PCT
    st.ws.cell(row=r + 1, column=1, value='Stress test result').font = BOLD
    st.ws.cell(row=r + 2, column=1, value='Cumulative stressed net income')
    st.ws.cell(row=r + 1, column=2, value=f'=IF({mn}>={B_("min")},"Pass","Fail")')
    st.ws.cell(row=r + 2, column=2, value=f'=SUM({st.span("ni", F0, FN)})').number_format = NUM
    extra = [('s_min', 'Minimum stressed CET1 ratio', f"='Stress Test'!$B${r}", PCT),
             ('s_res', 'Stress test result', f"='Stress Test'!$B${r + 1}", '@')]
    return [('Stress Test', 'Severe stress: lower NII and fees, multiplied credit losses, capital trough and pass / fail')], \
        [('Stressed capital rolls forward', f"{S('cet1', FN)}-({S('cet1', F0 - 1)}+SUM({st.span('ni', F0, FN)})+SUM({st.span('div', F0, FN)}))")], extra


def alm(c):
    I, B, B_, F0, nb = c['I'], c['B'], c['B_'], c['F0'], c['nb']
    hi = F0 - 1
    ws = c['wb'].create_sheet('Interest Rate Risk')
    ws.sheet_view.showGridLines = False
    ws['A1'] = c['head']('Interest rate risk: net interest income and economic value of equity')
    ws['A1'].font = Font(bold=True, size=13, color=NAVY)
    ws['A2'] = ('Instantaneous shocks applied to the first forecast year balance sheet; short-rate and long-rate shares of each '
                'shock and repricing betas on Bank Inputs.')
    ws['A2'].font = NOTE
    ws.column_dimensions['A'].width = 52
    shocks = [B_('shock0'), B_('shock1'), None, B_('shock2'), B_('shock3')]
    rows = ['Rate shock', 'Earning assets repricing', 'Interest-bearing deposits repricing', 'Wholesale funding repricing',
            'Change in interest income', 'Change in interest expense', 'Change in net interest income',
            'Net interest income after shock', 'Change % base net interest income', 'Change in economic value of equity',
            'EVE change % equity']
    for i, label in enumerate(rows):
        ws.cell(row=4 + i, column=1, value=label).font = BOLD if i in (0, 6, 9) else Font()
    assets, ibd, ol = B('assets', F0), B('ibd', F0), B('ol', F0)
    base_nii = I('nii', F0)
    for k, sh in enumerate(shocks):
        cl = col(k)
        ws.column_dimensions[cl].width = 14
        ws.cell(row=4, column=2 + k, value=f'={sh}' if sh else f'={B_("shock0")}-{B_("shock0")}').number_format = PCT
        x = f'{cl}$4'
        ws.cell(row=5, column=2 + k, value=f'={assets}*{B_("a_beta")}').number_format = NUM
        ws.cell(row=6, column=2 + k, value=f'={ibd}*{B_("d_beta")}*IF({x}>0,{B_("d_up")},{B_("d_down")})').number_format = NUM
        ws.cell(row=7, column=2 + k, value=f'={ol}*{B_("w_beta")}').number_format = NUM
        ws.cell(row=8, column=2 + k, value=f'={cl}5*{x}*{B_("short_w")}').number_format = NUM
        ws.cell(row=9, column=2 + k, value=f'=({cl}6+{cl}7)*{x}*{B_("short_w")}').number_format = NUM
        ws.cell(row=10, column=2 + k, value=f'={cl}8-{cl}9').number_format = NUM
        ws.cell(row=11, column=2 + k, value=f'={base_nii}+{cl}10').number_format = NUM
        ws.cell(row=12, column=2 + k, value=f'=IFERROR({cl}10/{base_nii},0)').number_format = PCT
        ws.cell(row=13, column=2 + k, value=f'=-({B("assets", hi)}*{B_("a_dur")}-({B("dep", hi)}+{B("ol", hi)})*{B_("l_dur")})*{x}*{B_("long_w")}').number_format = NUM
        ws.cell(row=14, column=2 + k, value=f'=IFERROR({cl}13/{B("eq", hi)},0)').number_format = PCT
    extra = [('a_up', 'NII change for +200 bp', "='Interest Rate Risk'!$F$12", PCT),
             ('a_eve', 'EVE change for +200 bp (% equity)', "='Interest Rate Risk'!$F$14", PCT)]
    return [('Interest Rate Risk', 'NII and EVE sensitivity to rate shocks along the chosen curve shape')], \
        [('Zero shock leaves NII unchanged', "'Interest Rate Risk'!$D$10")], extra


def valuation(c):
    I, B, M, K, periods, F0, FN, years = c['I'], c['B'], c['M'], c['K'], c['periods'], c['F0'], c['FN'], c['years']
    wb, head, cp = c['wb'], c['head'], c['cp']
    hi = F0 - 1
    vl = Sheet(wb, 'Valuation Model', head('Dividend discount and residual income'), periods, c['nh'])
    for key, label, bold, sec in [
        ('t', 'Discount year', False, 'Timing'), ('df', 'Discount factor at cost of equity', False, None),
        ('dist', 'Distributions (dividends + repurchases)', False, 'Dividend discount'), ('pv_dist', 'PV of distributions', True, None),
        ('bv_open', 'Opening book value', False, 'Residual income'), ('charge', 'Equity charge (cost of equity x opening book)', False, None),
        ('ri', 'Residual income', False, None), ('pv_ri', 'PV of residual income', True, None)]:
        vl.row(key, label, bold, section=sec)
    V = vl.ref
    vi = Inputs(wb, 'Valuation', head('Bank valuation summary'))
    vi.section('Cost of equity')
    X = c['X']
    if X['cost_of_equity'] == 'capm_premium':
        vi.add('ke', 'Cost of equity (CAPM + bank premium)', f'={M("rf")}+{M("beta")}*{M("erp")}+{M("prem")}', PCT, formula=True)
    else:
        vi.add('ke', 'Cost of equity (CAPM)', f'={M("rf")}+{M("beta")}*{M("erp")}', PCT, formula=True)
    ke, g = vi.ref('ke'), M('g')
    for j in range(F0, FN + 1):
        p = j - 1
        vl.set('t', j, f'={I("yr", j)}', '0')
        vl.set('df', j, f'=1/(1+{ke})^{V("t", j)}', '0.0000')
        vl.set('dist', j, f'={K("dist", j)}')
        vl.set('pv_dist', j, f'={V("dist", j)}*{V("df", j)}', bold=True)
        vl.set('bv_open', j, f'={B("eq", p)}')
        vl.set('charge', j, f'={V("bv_open", j)}*{ke}')
        vl.set('ri', j, f'={I("ni", j)}-{V("charge", j)}')
        vl.set('pv_ri', j, f'={V("ri", j)}*{V("df", j)}', bold=True)
    dist_n, ri_n, t_n = V('dist', FN), V('ri', FN), V('t', FN)
    vi.section('Dividend discount model')
    vi.add('ddm_pv', 'PV of forecast distributions', f'=SUM({vl.span("pv_dist", F0, FN)})', NUM, formula=True)
    vi.add('ddm_tv', 'PV of terminal value', f'={dist_n}*(1+{g})/({ke}-{g})/(1+{ke})^{t_n}', NUM, formula=True)
    vi.add('ddm', 'Equity value - DDM', f'={vi.ref("ddm_pv")}+{vi.ref("ddm_tv")}', NUM, formula=True)
    vi.section('Residual income model')
    vi.add('bv0', 'Current book value', f'={B("eq", hi)}', NUM, formula=True)
    vi.add('ri_pv', 'PV of forecast residual income', f'=SUM({vl.span("pv_ri", F0, FN)})', NUM, formula=True)
    if X['ri_terminal'] == 'fading':
        vi.add('ri_tv', 'PV of terminal residual income (fading at the persistence rate)',
               f'={ri_n}*{M("omega")}/(1+{ke}-{M("omega")})/(1+{ke})^{t_n}', NUM, formula=True)
    else:
        vi.add('ri_tv', 'PV of terminal residual income', f'={ri_n}*(1+{g})/({ke}-{g})/(1+{ke})^{t_n}', NUM, formula=True)
    vi.add('rim', 'Equity value - residual income', f'={vi.ref("bv0")}+{vi.ref("ri_pv")}+{vi.ref("ri_tv")}', NUM, formula=True)
    vi.section('Justified price to tangible book')
    vi.add('rote', 'Sustainable ROTE (forecast average)', f"=AVERAGE('Returns & Efficiency'!{col(F0)}{c['rote_row']}:{col(FN)}{c['rote_row']})"
           if 'rote_row' in c else f'=IFERROR(SUM({c["is_"].span("ni", F0, FN)})/SUM({c["bs"].span("tbv", F0 - 1, FN - 1)}),0)', PCT, formula=True)
    vi.add('ptbv', 'Justified P/TBV = (ROTE - g) / (Ke - g)', f'=IFERROR(MAX(0,({vi.ref("rote")}-{g})/({ke}-{g})),0)', MULT, formula=True)
    vi.add('ptbv_v', 'Equity value - justified P/TBV', f'={vi.ref("ptbv")}*{B("tbv", hi)}', NUM, formula=True)
    vi.section('Conclusion')
    vi.add('eq', 'Equity value - weighted average of the three methods',
           f'={M("w_ddm")}*{vi.ref("ddm")}+{M("w_rim")}*{vi.ref("rim")}+{M("w_ptbv")}*{vi.ref("ptbv_v")}', NUM, formula=True)
    vi.add('ps', 'Value per share (USD)', f'=IFERROR({vi.ref("eq")}/{M("shares")},0)', PRICE, formula=True)
    vi.add('p_tbv', 'Implied P/TBV', f'=IFERROR({vi.ref("eq")}/{B("tbv", hi)},0)', MULT, formula=True)
    vi.add('pe', 'Implied P/E (next year)', f'=IFERROR({vi.ref("eq")}/{I("ni", F0)},0)', MULT, formula=True)
    vi.add('vs', 'Value vs market value of equity', f'=IFERROR({vi.ref("eq")}/{M("mcap")}-1,0)', PCT, formula=True)
    se = wb.create_sheet('DDM Sensitivity')
    se.sheet_view.showGridLines = False
    se['A1'] = head('DDM equity value: cost of equity (rows) x long-term growth (columns)')
    se['A1'].font = Font(bold=True, size=13, color=NAVY)
    se.column_dimensions['A'].width = 16
    d_rng, t_rng = vl.span('dist', F0, FN), vl.span('t', F0, FN)
    for k, s in enumerate([-2, -1, 0, 1, 2]):
        se.cell(row=3, column=2 + k, value=f'={g}+({s})*{M("g_step")}').number_format = PCT
        se.cell(row=4 + k, column=1, value=f'={ke}+({s})*{M("k_step")}').number_format = PCT
        se.column_dimensions[col(k)].width = 14
    for r in range(5):
        for k in range(5):
            kk, gg = f'$A{4 + r}', f'{col(k)}$3'
            se.cell(row=4 + r, column=2 + k,
                    value=f'=IFERROR(SUMPRODUCT({d_rng}/(1+{kk})^{t_rng})+{dist_n}*(1+{gg})/({kk}-{gg})/(1+{kk})^{t_n},0)').number_format = NUM
    extra = [('v_ke', 'Cost of equity', f'={ke}', PCT), ('v_eq', 'Equity value (weighted methods)', f'={vi.ref("eq")}', NUM),
             ('v_ps', 'Value per share (USD)', f'={vi.ref("ps")}', PRICE)]
    return [('Valuation Model', 'Distributions and residual income by year, discounted at the cost of equity'),
            ('Valuation', 'DDM, residual income and justified P/TBV, per-share value and implied multiples'),
            ('DDM Sensitivity', 'DDM value across cost of equity and growth')], \
        [('Cost of equity exceeds growth (0 = yes)', f'IF({ke}>{g},0,1)'),
         ('Valuation weights sum to 100%', f'ROUND(({M("w_ddm")}+{M("w_rim")}+{M("w_ptbv")}-1)*100,6)'),
         ('DDM grid centre equals base DDM value', f"'DDM Sensitivity'!$D$6-{vi.ref('ddm')}")], extra


def dashboard(c, name_ref, extra):
    wb, I, K, nh, n, F0, FN = c['wb'], c['I'], c['K'], c['nh'], c['n'], c['F0'], c['FN']
    hi = nh - 1
    db = Inputs(wb, 'Dashboard', c['head']('Executive dashboard'), index=0)
    db.ws['A2'] = 'Key outputs of the live scenario. Every figure is a formula.'
    db.section('Scenario')
    db.add('scen', 'Active scenario', f'={name_ref}', '@', formula=True)
    db.add('checks', 'Model integrity', '=IF(Checks!$B$3=0,"All checks pass","CHECK ERRORS")', '@', formula=True)
    db.section('Earnings')
    nim = lambda j: f"'NII Build'!{col(j)}{c['nb'].rows['nim']}"  # noqa: E731
    db.add('nii_f', f'Net interest income {c["periods"][F0]}', f'={I("nii", F0)}', NUM, formula=True)
    db.add('nim_h', 'Net interest margin, last historical year', f'={nim(hi)}', PCT, formula=True)
    db.add('nim_f', 'Net interest margin, final forecast year', f'={nim(FN)}', PCT, formula=True)
    db.add('ni_f', 'Cumulative net income, forecast', f'=SUM({c["is_"].span("ni", F0, FN)})', NUM, formula=True)
    db.section('Capital')
    db.add('cet1_h', 'CET1 ratio, last historical year', f'={K("cet1_r", hi)}', PCT, formula=True)
    db.add('cet1_f', 'CET1 ratio, final forecast year', f'={K("cet1_r", FN)}', PCT, formula=True)
    db.add('dist_f', 'Cumulative distributions, forecast', f'=SUM({c["cp"].span("dist", F0, FN)})', NUM, formula=True)
    if extra:
        db.section('Module results')
        for key, label, f, fmt in extra:
            db.add(key, label, f, fmt, formula=True)
    is_, cp = c['is_'], c['cp']
    lc = LineChart()
    lc.title, lc.height, lc.width = 'Net interest income and PPNR (USD millions)', 7.5, 16
    for key in ('nii', 'ppnr'):
        r = is_.rows[key]
        lc.add_data(Reference(is_.ws, min_col=1, max_col=1 + n, min_row=r, max_row=r), from_rows=True, titles_from_data=True)
    lc.set_categories(Reference(is_.ws, min_col=2, max_col=1 + n, min_row=3, max_row=3))
    db.ws.add_chart(lc, 'E4')
    bc = BarChart()
    bc.title, bc.height, bc.width = 'CET1 ratio', 7.5, 16
    r = cp.rows['cet1_r']
    bc.add_data(Reference(cp.ws, min_col=1, max_col=1 + n, min_row=r, max_row=r), from_rows=True, titles_from_data=True)
    bc.set_categories(Reference(cp.ws, min_col=2, max_col=1 + n, min_row=3, max_row=3))
    db.ws.add_chart(bc, 'E20')
    return [('Dashboard', 'KPIs of the live scenario with NII, PPNR and CET1 charts')]
