"""Topic, language and licence filters (user rule: finance, accounting, hedge fund and financial analysis only;
English only)."""
import re

FIN = re.compile(
    r'\b(?:financ\w*|budget\w*|accounting|accountan\w*|audit\w*|invest\w*|pension\w*|retirement (?:board|system|fund)|'
    r'treasur\w*|fiscal|revenue\w*|appropriation\w*|taxation|tax (?:policy|reform|levy|rate)|municipal bonds?|bonds?|'
    r'debt|capital markets?|monetary|FOMC|federal reserve|securities|SEC|FASB|GASB|IASB|IFRS|ISSB|PCAOB|AICPA|GAAP|'
    r'hedge funds?|asset management|portfolio|economic outlook|earnings|banking|banks?|insurance|actuar\w*|valuation|'
    r'financial statements?|CFO|controller|comptroller|private equity|venture capital|credit|lending|mortgage|'
    r'stock market|equity research|wealth management|fintech|payments|interest rates?|inflation)\b', re.I)
MEET = re.compile(
    r'\b(?:meetings?|webinars?|webcasts?|board|committee|hearings?|session|conference|roundtable|forum|town ?hall|'
    r'press conference|briefing|panel|symposium|council|investor day|capital markets day|analyst day|'
    r'advisory group|commission)\b', re.I)
NOT_EN = re.compile(r'[Ѐ-ӿ؀-ۿऀ-ॿ぀-ヿ一-鿿가-힯]')
FOREIGN_WORDS = re.compile(r'\b(?:reunión|sesión|presupuesto|réunion|séance|sitzung|haushalt|riunione|bilancio|'
                           r'reunião|orçamento|vergadering|financiën|conseil municipal)\b', re.I)


def finance(*texts):
    return any(FIN.search(t or '') for t in texts)


def meeting(*texts):
    return any(MEET.search(t or '') for t in texts)


def english(title, lang=None):
    if lang and not str(lang).lower().startswith(('en', 'eng')):
        return False
    t = title or ''
    if NOT_EN.search(t) or FOREIGN_WORDS.search(t):
        return False
    letters = [c for c in t if c.isalpha()]
    return not letters or sum(c.isascii() for c in letters) / len(letters) > 0.9


LICENCES = [
    (r'publicdomain/zero', 'CC0 1.0 (public domain dedication)'),
    (r'publicdomain/mark|licenses/publicdomain', 'Public domain'),
    (r'by-nc-nd/', 'CC BY-NC-ND'), (r'by-nc-sa/', 'CC BY-NC-SA'), (r'by-nc/', 'CC BY-NC'),
    (r'by-nd/', 'CC BY-ND'), (r'by-sa/', 'CC BY-SA'), (r'licenses/by/', 'CC BY'),
]


def licence_name(url):
    """Creative Commons licence address -> short name with version (e.g. 'CC BY-SA 4.0')."""
    u = (url or '').lower()
    for pat, name in LICENCES:
        if re.search(pat, u):
            m = re.search(r'/(\d\.\d)', u)
            return f'{name} {m.group(1)}' if m and name.startswith('CC ') and 'CC0' not in name else name
    return None
