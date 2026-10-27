"""Subject rule for the Workspace collectors (user, 2026-10-27): "anything the collector collects, should be
finance/accounting/hedgefund/ finance analysis/ games data only" -- for every document and data type. The games
collector (excel/gaming) keeps games data; every other collector keeps only finance, accounting, hedge-fund and
financial-analysis content.

finance(text) counts the distinct finance terms in a title, description, keyword list or file text. Terms that are
also everyday, scientific or code words ('account', 'loss', 'derivative', 'bank', 'fund', 'risk', 'forecast',
'bonds', 'stocks', 'inflation', 'volatility', 'var') only count in their finance phrases, so a physics talk or a
research acknowledgement ('funded by') does not pass.
"""
import re

FINANCE = re.compile(
    r'financ\w*|accounting|accountan\w*|bookkeep\w*|ledger|budget\w*|fiscal|treasury|audit\w*|'
    r'balance sheet|income statement|profit and loss|\bp&l\b|cash ?flow|statement of (?:financial position|operations)|'
    r'chart of accounts|trial balance|journal entr\w+|accounts? (?:payable|receivable)|general ledger|'
    r'revenue\w*|expenditure\w*|expenses?|payroll|invoice\w*|vendor payments?|disbursements?|reconciliation|'
    r'cost accounting|management accounting|costing|cost (?:analysis|estimate|centre|center)|'
    r'\btax(?:es|ation)?\b|\bvat\b|\bgaap\b|\bifrs\b|\bcpa\b|\bcfa\b|'
    r'invest\w*|portfolio\w*|hedge funds?|mutual funds?|pension funds?|investment funds?|fund (?:balance|accounting)|'
    r'asset (?:management|allocation|pricing)|wealth management|private equity|venture capital|'
    r'equit(?:y|ies) research|stock (?:market|price|returns?|exchange|portfolio)s?|share prices?|securities|'
    r'(?:government|corporate|municipal|treasury) bonds?|bond (?:yield|market|pricing|portfolio)s?|fixed income|yield curve|'
    r'capital (?:markets?|budgeting|structure|expenditure)|valuation\w*|dividend\w*|earnings|\beps\b|\bebitda\b|'
    r'\bnpv\b|\birr\b|\bdcf\b|\broi\b|\bwacc\b|discounted cash|net present value|'
    r'credit (?:risk|rating|scor\w+|card|union)|market risk|financial risk|risk management|value at risk|'
    r'loans?\b|lending|mortgage\w*|debt\b|interest rates?|banking|central bank|commercial bank|'
    r'bank (?:statement|reconciliation|account|loan|balance)|monetary policy|inflation rate|consumer price|'
    r'insurance|actuar\w+|annuit\w+|'
    r'trading|trader|algorithmic trading|backtest\w*|quantitative finance|option pricing|black.scholes|'
    r'financial derivatives?|futures contracts?|implied volatility|(?:price|market|stock) volatility|forex|exchange rates?|'
    r'annual report|10-k|quarterly report|earnings call|financial (?:model\w*|analysis|plan\w*|forecast\w*|reporting|'
    r'statements?|ratios?|performance|literacy)|economic (?:analysis|indicators?)|public finance|procurement spend\w*|'
    r'fintech|payments?\b|cryptocurrenc\w+|bitcoin',
    re.I)


def terms(text):
    """The distinct finance terms in text (lower-case)."""
    return {m.group(0).lower() for m in FINANCE.finditer(text or '')}


def finance(text, need=1):
    """True when text is about finance, accounting, investing or financial analysis (at least need distinct terms)."""
    return len(terms(text)) >= need
