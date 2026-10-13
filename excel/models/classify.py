"""Decides whether a workbook is a financial model and which kind.

Categories: LBO, DCF & valuation, industry-specific, three-statement, operating & FP&A.
Scored on the file name, sheet names and the workbook's text; a workbook with no
financial-model vocabulary is not a model and is rejected.
"""
import re

CATEGORIES = {
    'LBO model': [r'\blbo\b', r'leveraged buy-?out', r'sponsor equity', r'sources (and|&) uses', r'cash sweep',
                  r'\bmoic\b', r'exit multiple', r'term loan', r'senior (notes|debt)', r'mezzanine', r'paydown'],
    'DCF valuation model': [r'\bdcf\b', r'discounted cash flow', r'\bwacc\b', r'terminal value', r'enterprise value',
                            r'\bvaluation\b', r'comparable compan', r'\bcomps\b', r'precedent transaction', r'sum of the parts',
                            r'dividend discount', r'intrinsic value', r'implied share price', r'cost of equity', r'\bcapm\b',
                            r'free cash flow to (firm|equity)', r'\bfcff\b', r'\bfcfe\b', r'gordon growth', r'football field'],
    'Industry-specific model': [r'real estate', r'\bnoi\b', r'cap(italization)? rate', r'rent roll', r'\breit\b', r'\bffo\b',
                                r'hotel', r'\brevpar\b', r'occupancy', r'mining', r'ore reserve', r'oil (and|&) gas', r'\bbbl\b',
                                r'\bboe\b', r'production decline', r'project finance', r'\bppa\b', r'\bdscr\b', r'solar', r'wind farm',
                                r'power plant', r'\blcoe\b', r'hydrogen', r'\brnpv\b', r'clinical (trial|phase)', r'drug pipeline',
                                r'\bnim\b', r'net interest margin', r'loan book', r'insurance', r'combined ratio', r'premiums',
                                r'\bsaas\b', r'\barr\b', r'\bmrr\b', r'\bchurn\b', r'\bcac\b', r'\bltv\b', r'restaurant',
                                r'same[- ]store', r'retail', r'airline', r'\brask\b', r'shipping', r'data cent(er|re)',
                                r'telecom', r'\barpu\b', r'hospital', r'clinic', r'patient', r'infrastructure', r'toll road',
                                r'concession', r'construction', r'development', r'manufactur', r'agricultur', r'farm'],
    'Three-statement model': [r'three[- ]statement', r'3[- ]statement', r'integrated (financial )?model', r'balance sheet',
                              r'income statement', r'cash flow statement', r'statement of cash flows', r'\bp&l\b', r'profit (and|&) loss'],
    'Operating & FP&A model': [r'\bbudget', r'\bforecast', r'fp&a', r'operating model', r'variance', r'headcount',
                               r'rolling forecast', r'13[- ]week', r'cash flow forecast', r'revenue (model|build)',
                               r'business plan', r'start-?up', r'unit economics', r'\bkpi', r'break-?even', r'scenario',
                               r'sensitivity', r'driver', r'opex', r'capex', r'payroll', r'pricing model', r'cost model'],
}
FINANCE = [r'revenue', r'sales', r'ebitda', r'\bebit\b', r'net income', r'cash flow', r'\bnpv\b', r'\birr\b', r'capex',
           r'margin', r'interest', r'\btax', r'depreciation', r'equity', r'debt', r'dividend', r'expense', r'cost of',
           r'working capital', r'discount rate', r'profit']
_C = {k: [re.compile(p, re.I) for p in v] for k, v in CATEGORIES.items()}
_F = [re.compile(p, re.I) for p in FINANCE]
ORDER = ['LBO model', 'DCF valuation model', 'Industry-specific model', 'Three-statement model', 'Operating & FP&A model']


def classify(filename, sheet_names, texts):
    """Returns (category, scores) or (None, scores) when the workbook is not a financial model."""
    blob = ' '.join([filename.replace('_', ' ').replace('-', ' ')] + sheet_names + texts[:4000]).lower()
    head = ' '.join([filename.replace('_', ' ').replace('-', ' ')] + sheet_names).lower()
    fin = sum(1 for p in _F if p.search(blob))
    scores = {}
    for k, pats in _C.items():
        scores[k] = sum(1 for p in pats if p.search(blob)) + 2 * sum(1 for p in pats if p.search(head))
    if fin < 4:
        return None, scores
    statements = sum(1 for p in (r'income statement|profit (and|&) loss|\bp&l\b', r'balance sheet', r'cash flow')
                     if re.search(p, blob))
    if scores['LBO model'] >= 4:
        return 'LBO model', scores
    if scores['DCF valuation model'] >= 4:
        return 'DCF valuation model', scores
    if scores['Industry-specific model'] >= 4:
        return 'Industry-specific model', scores
    if statements == 3 or scores['Three-statement model'] >= 5:
        return 'Three-statement model', scores
    best = max(ORDER, key=lambda k: (scores[k], -ORDER.index(k)))
    if scores[best] >= 3:
        return best, scores
    return None, scores
