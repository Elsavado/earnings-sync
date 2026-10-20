"""Document types: Drive folder, file label, and the keyword gate a document must pass.

Each gate is (phrases, head): at least one phrase must appear (case-insensitive) in the first
`head` characters of the document text. min_words keeps out cover letters and one-page stubs.
"""
import re

KINDS = {
    'cim': {
        'folder': 'CIMs, QoE & Diligence Reports',
        'phrases': ['discussion materials', 'presentation to the special committee', 'presentation to the board',
                    'confidential information memorandum', 'quality of earnings', 'due diligence', 'agreed-upon procedures',
                    'fairness opinion', 'valuation analysis', 'project '],
        'head': 6000, 'min_words': 400,
    },
    'research': {
        'folder': 'Industry & Market Research',
        'phrases': ['industry', 'market', 'sector', 'value chain', 'competitive'],
        'head': 8000, 'min_words': 1500,
    },
    'equity': {
        'folder': 'Equity Research & Investment Thesis',
        'phrases': ['equity research', 'equity valuation', 'target price', 'price target', 'investment thesis',
                    'recommendation', 'discounted cash flow', 'valuation'],
        'head': 15000, 'min_words': 2000,
    },
    'letters': {
        'folder': 'LP Updates & Investor Letters',
        'phrases': ['dear limited partners', 'dear partners', 'dear fellow', 'dear shareholders', 'dear stockholders',
                    'dear unitholders', 'dear investors', 'to our shareholders', 'letter to shareholders'],
        'head': 4000, 'min_words': 300,
    },
    'memos': {
        'folder': 'Investment & IC Memos',
        'phrases': ['investment committee', 'investment memorandum', 'project appraisal', 'investment recommendation',
                    'board of investment', 'recommendation', 'proposed investment'],
        'head': 10000, 'min_words': 800,
    },
    'deals': {
        'folder': 'Term Sheets, LOIs & NDAs',
        'phrases': ['letter of intent', 'term sheet', 'summary of terms', 'non-disclosure agreement', 'nondisclosure agreement',
                    'confidentiality agreement', 'mutual confidentiality', 'indicative proposal', 'non-binding proposal'],
        'head': 2500, 'min_words': 250,
    },
    'transcripts': {
        'folder': 'Earnings Call Transcripts',
        'phrases': ['operator'],
        'also': ['earnings', 'quarter', 'results'],
        'head': 6000, 'min_words': 1500,
    },
    'notebooks': {
        'folder': 'Jupyter Notebooks',
        'phrases': [],
        'head': 0, 'min_words': 0,
    },
    'contracts': {
        'folder': 'Contracts',
        'phrases': ['agreement', 'contract'],
        'head': 3000, 'min_words': 800,
    },
    # Workspace kinds (research.py): research notebooks from STEM papers and theses; Figma designs with the
    # HTML/CSS built from them. Gated by research.py, not on text.
    'scinotebooks': {'folder': 'Jupyter Notebooks (STEM)', 'phrases': [], 'head': 0, 'min_words': 0, 'workspace': True},
    'figma': {'folder': 'Figma Designs', 'phrases': [], 'head': 0, 'min_words': 0, 'workspace': True},
    'styleguides': {'folder': 'Style Guides & Guidelines', 'phrases': [], 'head': 0, 'min_words': 0, 'workspace': True},
    # Tabular kinds: gated on column headers by tab.py, not on text.
    'transactions': {'folder': 'Financial Transactions', 'phrases': [], 'head': 0, 'min_words': 0},
    'payroll': {'folder': 'Employee Payroll & Payments', 'phrases': [], 'head': 0, 'min_words': 0},
}
TABULAR = {'transactions', 'payroll'}

LABEL = {
    'cim': 'Diligence report', 'research': 'Industry research', 'equity': 'Equity research', 'letters': 'Investor letter',
    'memos': 'Investment memo', 'deals': 'Deal document', 'transcripts': 'Earnings call transcript', 'notebooks': 'Notebook',
    'contracts': 'Contract', 'transactions': 'Transactions', 'payroll': 'Payroll',
    'scinotebooks': 'Research notebook', 'figma': 'Figma design and HTML-CSS', 'styleguides': 'Style guide',
}
FIN_KINDS = [k for k, v in KINDS.items() if not v.get('workspace')]  # the Financial documents workflow's types

# Finer labels from the document's own heading (never its title, which may name the company).
SUBLABEL = [
    ('cim', r'due diligence narrative|narrative report', 'Due diligence narrative report'),
    ('cim', r'executive summary.{0,400}due diligence|due diligence.{0,400}executive summary', 'Due diligence executive summary'),
    ('cim', r'quality of earnings', 'Quality of earnings report'),
    ('cim', r'confidential information memorandum', 'Confidential information memorandum'),
    ('cim', r'fairness opinion|fairness analysis', 'Fairness opinion presentation'),
    ('cim', r'preliminary (?:discussion materials|valuation)', 'Preliminary valuation discussion materials'),
    ('cim', r'special committee', 'Special committee presentation'),
    ('cim', r'board of directors|presentation to the board', 'Board presentation'),
    ('cim', r'valuation analys[ie]s', 'Valuation analysis'),
    ('cim', r'discussion materials', 'Banker discussion materials'),
    ('cim', r'agreed-upon procedures|due diligence', 'Due diligence report'),
    ('deals', r'letter of intent', 'Letter of intent'),
    ('deals', r'term sheet|summary of terms', 'Term sheet'),
    ('deals', r'non-?disclosure|confidentiality agreement', 'NDA'),
    ('deals', r'indicative proposal|non-binding proposal', 'Indicative proposal'),
    ('letters', r'limited partners|dear partners', 'LP letter'),
    ('letters', r'shareholders|stockholders|unitholders', 'Shareholder letter'),
    ('memos', r'project appraisal', 'Project appraisal memo'),
    ('memos', r'investment committee', 'IC memo'),
    ('equity', r'equity research|target price|price target', 'Equity research report'),
    ('equity', r'investment thesis', 'Investment thesis'),
    ('contracts', r'employment agreement', 'Employment agreement'),
    ('contracts', r'credit agreement|loan agreement', 'Credit agreement'),
    ('contracts', r'supply agreement', 'Supply agreement'),
    ('contracts', r'licen[cs]e agreement', 'License agreement'),
    ('contracts', r'consulting agreement|services agreement', 'Services agreement'),
    ('contracts', r'(?:stock|asset|share|unit) purchase agreement', 'Purchase agreement'),
    ('contracts', r'lease agreement|lease\b', 'Lease agreement'),
]


def gate(kind, text):
    """Returns None when the text belongs to the type, otherwise the reason it does not."""
    k = KINDS[kind]
    words = len(text.split())
    if words < k['min_words']:
        return f'too short ({words} words)'
    head = text[:k['head']].lower()
    if k['phrases'] and not any(p in head for p in k['phrases']):
        return 'not this document type'
    if k.get('also') and not any(p in head for p in k['also']):
        return 'not this document type'
    if not english(text):
        return 'not English'
    return None


def label(kind, text):
    head = text[:KINDS[kind]['head'] or 3000].lower()
    for k, pat, name in SUBLABEL:
        if k == kind and re.search(pat, head, re.S):
            return name
    return LABEL[kind]


STOP = set('the of and to in a is that for on with as by are be this from at or an it which will not have has was were'.split())


def english(text):
    toks = re.findall(r'[a-z]+', text[:30000].lower())
    return len(toks) > 50 and sum(t in STOP for t in toks) / len(toks) > 0.12
