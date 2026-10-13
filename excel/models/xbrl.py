"""Reads annual and quarterly figures out of an SEC XBRL company-facts document.

Values come back in USD millions (shares in millions), keyed by period end date.
Several us-gaap tags can carry the same concept; they are merged per period, the earlier
tag in each list taking priority, and the latest filing wins for restated periods.
"""
from datetime import date

FLOW_TAGS = {
    'revenue': ['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
                'RevenueFromContractWithCustomerIncludingAssessedTax', 'SalesRevenueNet',
                'SalesRevenueGoodsNet', 'SalesRevenueServicesNet', 'RevenuesNetOfInterestExpense'],
    'cogs': ['CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsSold', 'CostOfServices'],
    'ebit': ['OperatingIncomeLoss'],
    'interest': ['InterestExpense', 'InterestExpenseNonoperating', 'InterestExpenseDebt'],
    'pretax': ['IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
               'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments',
               'IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic'],
    'tax': ['IncomeTaxExpenseBenefit'],
    'net_income': ['NetIncomeLoss', 'ProfitLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic'],
    'da': ['DepreciationDepletionAndAmortization', 'DepreciationAndAmortization',
           'DepreciationAmortizationAndAccretionNet', 'Depreciation'],
    'sbc': ['ShareBasedCompensation', 'AllocatedShareBasedCompensationExpense'],
    'cfo': ['NetCashProvidedByUsedInOperatingActivities',
            'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations'],
    'cfi': ['NetCashProvidedByUsedInInvestingActivities',
            'NetCashProvidedByUsedInInvestingActivitiesContinuingOperations'],
    'cff': ['NetCashProvidedByUsedInFinancingActivities',
            'NetCashProvidedByUsedInFinancingActivitiesContinuingOperations'],
    'capex': ['PaymentsToAcquirePropertyPlantAndEquipment', 'PaymentsToAcquireProductiveAssets',
              'PaymentsForCapitalImprovements', 'PaymentsToDevelopRealEstateAssets', 'PaymentsToAcquireRealEstate'],
    'dividends': ['PaymentsOfDividends', 'PaymentsOfDividendsCommonStock'],
    'buybacks': ['PaymentsForRepurchaseOfCommonStock'],
    # Banks
    'int_income': ['InterestAndDividendIncomeOperating', 'InterestIncomeOperating', 'InterestAndFeeIncomeLoansAndLeases'],
    'int_expense_bank': ['InterestExpenseOperating', 'InterestExpense'],
    'provision': ['ProvisionForLoanLeaseAndOtherLosses', 'ProvisionForLoanAndLeaseLosses',
                  'ProvisionForCreditLossesNet', 'CreditLossExpenseReversal', 'ProvisionForLoanLossesExpensed'],
    'nonint_income': ['NoninterestIncome'],
    'nonint_expense': ['NoninterestExpense'],
    # REITs
    'gain_re': ['GainLossOnSaleOfRealEstateInvestmentProperty', 'GainsLossesOnSalesOfInvestmentRealEstate',
                'GainLossOnDispositionOfAssets1'],
    're_da': ['DepreciationAndAmortizationRealEstate', 'RealEstateDepreciationAndAmortization'],
}
INSTANT_TAGS = {
    'cash': ['CashAndCashEquivalentsAtCarryingValue',
             'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents', 'Cash'],
    'ar': ['AccountsReceivableNetCurrent', 'ReceivablesNetCurrent'],
    'inventory': ['InventoryNet'],
    'assets_current': ['AssetsCurrent'],
    'ppe': ['PropertyPlantAndEquipmentNet'],
    'assets': ['Assets'],
    'ap': ['AccountsPayableCurrent', 'AccountsPayableAndAccruedLiabilitiesCurrent'],
    'liabilities_current': ['LiabilitiesCurrent'],
    'debt': ['LongTermDebtNoncurrent', 'LongTermDebt', 'LongTermDebtAndCapitalLeaseObligations',
             'DebtInstrumentCarryingAmount', 'UnsecuredDebt', 'SeniorNotes', 'LongTermNotesPayable', 'NotesPayable'],
    'debt_current': ['LongTermDebtCurrent', 'DebtCurrent'],
    'liabilities': ['Liabilities'],
    'equity': ['StockholdersEquity'],
    'equity_total': ['StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'],
    'liab_and_equity': ['LiabilitiesAndStockholdersEquity'],
    # Banks
    'loans': ['LoansAndLeasesReceivableNetReportedAmount', 'FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss',
              'LoansAndLeasesReceivableNetOfDeferredIncome', 'NotesReceivableNet'],
    'deposits': ['Deposits'],
    'goodwill': ['Goodwill'],
    'intangibles': ['IntangibleAssetsNetExcludingGoodwill', 'FiniteLivedIntangibleAssetsNet'],
    # REITs
    're_net': ['RealEstateInvestmentPropertyNet'],
}
ANNUAL_REQUIRED = ['revenue', 'net_income', 'assets', 'equity', 'cash', 'cfo']


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _units(facts, tag, unit='USD', ns='us-gaap'):
    facts = facts.get('facts', facts)
    return ((facts.get(ns, {}).get(tag, {}) or {}).get('units', {}) or {}).get(unit, [])


def flows(facts, tags, lo, hi, forms=('10-K',)):
    """{(start, end): value} for duration facts between lo and hi days, latest filing wins."""
    out = {}
    for tag in reversed(tags):
        for f in sorted(_units(facts, tag), key=lambda f: f.get('filed', '')):
            if not f.get('start') or not str(f.get('form', '')).startswith(forms):
                continue
            if lo <= _days(f['start'], f['end']) <= hi:
                out[(f['start'], f['end'])] = f['val']
    return out


def instants(facts, tags, forms=('10-K',)):
    out = {}
    for tag in reversed(tags):
        for f in sorted(_units(facts, tag), key=lambda f: f.get('filed', '')):
            if not f.get('start') and str(f.get('form', '')).startswith(forms):
                out[f['end']] = f['val']
    return out


def _by_end(d):
    return {end: v for (start, end), v in d.items()}


def dei_latest(facts, tag, unit):
    vals = sorted(_units(facts, tag, unit, 'dei'), key=lambda f: (f.get('end', ''), f.get('filed', '')))
    return vals[-1]['val'] if vals else None


def annual(facts, min_years=3, max_years=6, required=ANNUAL_REQUIRED, anchor='revenue'):
    """(year end dates, {concept: [USD m per year or None]}) or None when filings are too thin."""
    series = {k: _by_end(flows(facts, t, 330, 400)) for k, t in FLOW_TAGS.items()}
    series.update({k: instants(facts, t) for k, t in INSTANT_TAGS.items()})
    ends = [e for e in sorted(series[anchor]) if all(e in series[k] for k in required)]
    run = []
    for e in reversed(ends):
        if run and not 330 <= _days(e, run[-1]) <= 400:
            break
        run.append(e)
    years = list(reversed(run))[-max_years:]
    if len(years) < min_years or date.fromisoformat(years[-1]).year < date.today().year - 2:
        return None
    data = {k: [None if series[k].get(e) is None else round(series[k][e] / 1e6, 3) for e in years] for k in series}
    return years, data


def quarterly(facts, min_years=3, max_years=4):
    """Fiscal-year blocks of quarterly data for the operating model.

    Returns (fiscal year end dates, {concept: {'q': [[q1,q2,q3] per year], 'fy': [per year]}}).
    Q4 is not stored: the model derives it as full year less the first three quarters."""
    out_keys = ['revenue', 'cogs', 'ebit', 'net_income']
    fy = {k: flows(facts, FLOW_TAGS[k], 330, 400) for k in out_keys}
    q = {k: flows(facts, FLOW_TAGS[k], 80, 100, forms=('10-Q', '10-K')) for k in out_keys}
    years = []
    for (start, end) in sorted(fy['revenue']):
        quarters = sorted((s, e) for (s, e) in q['revenue'] if start <= s and e <= end and _days(s, e) <= 100)
        # Three quarters starting at the fiscal year start, back to back.
        chain, cursor = [], start
        for s, e in quarters:
            if len(chain) < 3 and 0 <= _days(cursor, s) <= 7:
                chain.append((s, e))
                cursor = e
        if len(chain) == 3 and all(all(p in q[k] for p in chain) and (start, end) in fy[k] for k in ('revenue', 'net_income')):
            years.append(((start, end), chain))
    run = []
    for item in reversed(years):
        if run and not 330 <= _days(item[0][1], run[-1][0][1]) <= 400:
            break
        run.append(item)
    years = list(reversed(run))[-max_years:]
    if len(years) < min_years or date.fromisoformat(years[-1][0][1]).year < date.today().year - 2:
        return None
    data = {}
    for k in out_keys:
        data[k] = {
            'q': [[None if q[k].get(p) is None else round(q[k][p] / 1e6, 3) for p in chain] for _, chain in years],
            'fy': [None if fy[k].get(per) is None else round(fy[k][per] / 1e6, 3) for per, _ in years],
        }
    return [per[1] for per, _ in years], data
