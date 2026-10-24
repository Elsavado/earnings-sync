"""Practitioner layer for the enhanced models (user, 2026-10-23: "real human-like work if a practitioner
was to look at it").

What an experienced modeller adds around the mechanics: the reasoning behind each assumption, written
next to it and updated live from the numbers; an outputs page with commentary that reads the model's
own results; sanity flags that point at results worth a second look; a note on the methods chosen and
why; and the conventions used. Every sentence is a formula over the model, so it stays true when an
input changes. Nothing here invents authorship or history.
"""
from openpyxl.styles import Alignment, Font

from .xl import BOLD, NAVY, NOTE, NUM, PCT

WHY = {
    'fade': 'growth starts at the historical median and fades in a straight line to the long-term rate - a neutral convergence view',
    'decay': 'excess growth decays geometrically, front-loading the slowdown, as competitive advantage periods usually erode fastest early',
    'stepdown': 'near-term growth is held at the recent run-rate (visibility from backlog / contracts), then steps down to the long-term rate',
    'cagr': 'the starting point is the 3-year CAGR rather than the median, so one unusual year does not set the trajectory',
    'price_volume': 'revenue is split into price (inflation) and volume, so pricing power and unit growth can be challenged separately',
    'scenario_weighted': 'the forecast is the probability-weighted outcome of base, upside and downside growth paths',
    'pct': 'costs scale with revenue at their historical ratio - appropriate where the cost base is largely variable',
    'fixed_variable': 'operating costs are split into fixed and variable parts by regression on the history, capturing operating leverage',
    'margin_target': 'gross margin migrates from the latest year back to its through-cycle average, i.e. mean reversion of pricing and mix',
    'opex_leverage': 'operating costs grow at a fraction of revenue growth, reflecting scale economies in overheads',
    'pct_avg': 'working capital ratios use the multi-year average, smoothing year-end timing noise',
    'days_converge': 'receivable, inventory and payable days move from the latest year to their historical average',
    'last_ratio': 'working capital is held at the latest year\'s ratios, the best indicator of current terms with customers and suppliers',
    'maintenance_growth': 'capex is built as maintenance (a multiple of D&A) plus growth capex tied to the revenue increase and capital intensity',
    'useful_life': 'D&A is depreciation of the opening asset base over its implied useful life plus a half-year on new spend',
    'intensity_fade': 'capex intensity converges to D&A, i.e. the asset base stabilises by the end of the forecast',
    'effective': 'tax at the historical effective rate on positive pre-tax income',
    'nol': 'accumulated tax losses shelter future profits before tax becomes payable',
    'statutory_blend': 'the effective tax rate moves to the statutory rate as one-off credits roll off',
    'hold': 'term debt is held flat, with the revolver absorbing cash shortfalls and surpluses',
    'amortise': 'term debt amortises each year, refinanced only through the revolver if cash runs short',
    'target_leverage': 'debt is sized to the company\'s historical leverage multiple of EBITDA, as a capital-structure policy',
    'payout': 'dividends follow the historical payout ratio',
    'dps_growth': 'the dividend per share grows at a steady rate, the usual board policy for progressive payers',
    'payout_target': 'the payout ratio moves to a target level over the forecast',
    'historical': 'interest at the historical effective cost of debt on opening balances (no circularity)',
    'rate_curve': 'the cost of debt reprices towards risk-free plus a credit spread as existing debt is refinanced',
}
WRAP = Alignment(wrap_text=True, vertical='top')


def _note(ws, r, text):
    c = ws.cell(row=r, column=3, value=text)
    c.font = NOTE
    c.alignment = WRAP


def annotate(wb, v, c):
    is_, bs, cf, rt, asm, si = c['is_'], c['bs'], c['cf'], c['rt'], c['asm'], c['si']
    nh, n, N, periods = c['nh'], c['n'], c['years'], c['periods']
    hi, f0, fN = nh - 1, nh, n - 1
    A = c['A']

    # 1. Rationale next to each driver (column C of the assumptions sheet), live from the numbers.
    ws = asm.ws
    ws.column_dimensions['C'].width = 90
    say = {
        'growth': lambda r: f'="Starting growth of "&TEXT(B{r},"0.0%")&", converging to the long-term "&TEXT({si.ref("lt")},"0.0%")&" by {periods[fN]}; '
                            f'capped at "&TEXT({si.ref("cap")},"0%")&" and floored at "&TEXT({si.ref("floor")},"0%")&"."',
        'cogs_pct': lambda r: f'="Cost of revenue has averaged "&TEXT(B{r},"0.0%")&" of revenue, i.e. a gross margin of "&TEXT(1-B{r},"0.0%")&"."',
        'opex_pct': lambda r: f'="Operating costs at "&TEXT(B{r},"0.0%")&" of revenue on average"&IF(B{r}>0.5," - a cost-heavy model; margins are sensitive to this line","")&"."',
        'tax_rate': lambda r: f'="Effective tax rate of "&TEXT(B{r},"0.0%")&IF(B{r}<0.15," - well below statutory, likely credits or loss relief; treat with care","")&"."',
        'int_rate': lambda r: f'="Implied cost of debt "&TEXT(B{r},"0.0%")&IF(B{r}>0.12," - high, the interest line probably includes non-debt items",'
                              f'IF(B{r}<0.02," - low, debt may be largely non-interest-bearing",""))&"."',
        'min_cash': lambda r: f'="Operating cash floor of "&TEXT(B{r},"0.0%")&" of revenue - the lowest the company has held, so the revolver funds anything below it."',
        'capex_pct': lambda r: f'="Capex has run at "&TEXT(B{r},"0.0%")&" of revenue against D&A of "&TEXT({A("dep_rate")},"0.0%")&IF({A("dep_rate")}>B{r}," - under-investing relative to depreciation","")&"."',
        'payout': lambda r: f'="Historical payout of "&TEXT(B{r},"0%")&" of net income"&IF(B{r}=0," - no dividend history","")&"."',
        'buyback': lambda r: f'="Buybacks have absorbed "&TEXT(B{r},"0%")&" of net income; in the forecast they come only from cash above the floor."',
    }
    for k, fn in say.items():
        if k in asm.rows:
            ws.cell(row=asm.rows[k], column=3, value=fn(asm.rows[k])).font = NOTE
    r0 = asm.next_row + 3
    ws.cell(row=r0, column=1, value='Why these methods').font = Font(bold=True, color=NAVY)
    for i, (block, m) in enumerate(v.methods.items(), 1):
        ws.cell(row=r0 + i, column=1, value=block.replace('_', ' ').capitalize())
        _note(ws, r0 + i, f'{m.replace("_", " ").capitalize()}: {WHY.get(m, "")}.')

    # 2. Outputs page with commentary and sanity flags.
    d = wb.create_sheet('Dashboard', 1)
    d.sheet_view.showGridLines = False
    d.column_dimensions['A'].width = 34
    for col_ in 'BCD':
        d.column_dimensions[col_].width = 14
    d.column_dimensions['E'].width = 80
    d['A1'] = 'Key outputs and commentary'
    d['A1'].font = Font(bold=True, size=13, color=NAVY)
    d['A2'] = 'All figures USD millions unless stated; every sentence below recalculates with the model.'
    d['A2'].font = NOTE
    d['A4'], d['B4'], d['C4'], d['D4'] = 'Metric', periods[hi], periods[f0], periods[fN]
    for c_ in ('A4', 'B4', 'C4', 'D4'):
        d[c_].font = BOLD
    I, B, C, R = is_.ref, bs.ref, cf.ref, rt.ref
    metrics = [('Revenue', lambda j: I('revenue', j), NUM), ('EBITDA', lambda j: I('ebitda', j), NUM),
               ('EBITDA margin', lambda j: R('em', j), PCT), ('Net income', lambda j: I('net_income', j), NUM),
               ('Free cash flow', lambda j: R('fcf', j), NUM), ('Total debt / EBITDA', lambda j: R('lev', j), '0.0"x"'),
               ('Return on equity', lambda j: R('roe', j), PCT), ('Closing cash', lambda j: B('cash', j), NUM)]
    for i, (lab, ref, fmt) in enumerate(metrics, 5):
        d.cell(row=i, column=1, value=lab)
        for k, j in enumerate((hi, f0, fN)):
            cell = d.cell(row=i, column=2 + k, value=f'={ref(j)}')
            cell.number_format = fmt
    r = 5 + len(metrics) + 1
    d.cell(row=r, column=1, value='Commentary').font = Font(bold=True, color=NAVY)
    rev0, revN = I('revenue', hi), I('revenue', fN)
    em0, emN = R('em', hi), R('em', fN)
    fc = lambda key, sheet=cf: sheet.span(key, f0, fN)  # noqa: E731
    lines = [
        f'="Revenue compounds at "&TEXT(IFERROR(({revN}/{rev0})^(1/{N})-1,0),"0.0%")&" a year, from "&TEXT({rev0},"#,##0")&" to "&TEXT({revN},"#,##0")&"."',
        f'="EBITDA margin "&IF({emN}>={em0},"expands","contracts")&" by "&TEXT(ABS({emN}-{em0})*10000,"0")&" bp to "&TEXT({emN},"0.0%")&" by {periods[fN]}."',
        f'="Cumulative free cash flow over the forecast: "&TEXT(SUM({rt.span("fcf", f0, fN)}),"#,##0")&", of which "&TEXT(-SUM({fc("div")}),"#,##0")&" is paid out as dividends."',
        f'="Leverage goes from "&TEXT({R("lev", hi)},"0.0")&"x to "&TEXT({R("lev", fN)},"0.0")&"x EBITDA"&IF({R("lev", fN)}<{R("lev", hi)}," as the business de-levers."," - watch refinancing capacity.")',
        f'="Return on equity in the final year: "&TEXT({R("roe", fN)},"0.0%")&IF({R("roe", fN)}>{R("roe", hi)},", above",", below")&" the latest reported "&TEXT({R("roe", hi)},"0.0%")&"."',
    ]
    for t in lines:
        r += 1
        cell = d.cell(row=r, column=1, value=t)
        cell.alignment = Alignment(wrap_text=False)
    r += 2
    d.cell(row=r, column=1, value='Sanity flags').font = Font(bold=True, color=NAVY)
    flags = [
        ('Forecast growth vs history', f'=IF(MAX({is_.span("growth", f0, fN)})>MAX({is_.span("growth", 1, hi)})+0.05,'
                                       f'"Review: forecast growth exceeds anything in the reported history","OK - within the historical range")'),
        ('Equity', f'=IF(MIN({bs.span("te", f0, fN)})<0,"Review: total equity turns negative in the forecast","OK - equity stays positive")'),
        ('Leverage', f'=IF(MAX({rt.span("lev", f0, fN)})>4,"Review: debt above 4x EBITDA in at least one year","OK - leverage below 4x")'),
        ('Liquidity', f'=IF(MAX({cf.span("draw", f0, fN)})>0,"Note: the revolver is drawn to hold minimum cash","OK - funded from internal cash flow")'),
        ('Margins', f'=IF(MIN({rt.span("om", f0, fN)})<0,"Review: operating losses in the forecast","OK - operating margin positive")'),
    ]
    for lab, f in flags:
        r += 1
        d.cell(row=r, column=1, value=lab)
        d.cell(row=r, column=2, value=f)
    r += 2
    d.cell(row=r, column=1, value='Conventions').font = Font(bold=True, color=NAVY)
    for t in ['Blue cells are inputs, black cells are formulas, green cells link to another sheet.',
              'Cash outflows are negative on the cash flow statement; costs are shown as positive amounts on the income statement.',
              'Interest is charged on opening balances, so the model has no circular references.',
              f'Fiscal years; "A" = reported, "E" = forecast. Forecast horizon: {N} years.']:
        r += 1
        d.cell(row=r, column=1, value=t).font = NOTE
    return [('Dashboard', 'Key outputs, live commentary, sanity flags and conventions')]
