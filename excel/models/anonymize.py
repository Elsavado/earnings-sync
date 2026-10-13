"""Anonymises a workbook package: company names become 'Redacted Company Name Inc'.

Covered: cell text (shared and inline strings), string literals in formulas, sheet names (with
every formula, defined name and chart reference updated), comments and their authors, drawing
and chart text, headers/footers, document properties, tickers, people's names in author-type
fields, e-mail addresses, web addresses and phone numbers.

Company names are matched against the SEC registrant list (multi-word names always; one-word
names when capitalised and either rare in English or a large registrant, minus ordinary words
such as 'Target' or 'Visa'), plus organisation names with a legal suffix found by spaCy.
"""
import re

from .xl import REDACTED
from .xlsxml import escape, unescape

LEGAL = {'inc', 'incorporated', 'corp', 'corporation', 'co', 'company', 'ltd', 'limited', 'plc', 'llc', 'lp', 'llp',
         'sa', 'ag', 'nv', 'se', 'gmbh', 'bv', 'spa', 'ab', 'asa', 'oyj', 'kk', 'com', 'the', 'de', 'cos'}
SUFFIX_RE = r'(?:,?\s+(?:Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Company|Ltd\.?|Limited|plc|PLC|LLC|L\.L\.C\.|LP|L\.P\.|S\.A\.|SA|AG|N\.V\.|NV|SE|GmbH|Holdings?|Group))'
GENERIC = set('''target visa gap shell block square snap match booking progressive general first energy american national
united global international capital financial group holdings value growth summit pioneer southern dominion apex
alliance premier eagle liberty patriot frontier heritage legacy pinnacle vista horizon crown keystone landmark
citizens peoples community republic federal union central western eastern northern mobile digital data cloud
target total ford? amazon? best regional prime select core quest insight agilent? ally? arch carrier lumen
nasdaq nyse cboe cme amex euronext moody moodys fitch bloomberg factset morningstar'''.replace('?', '').split())
GENERIC -= {'ford', 'amazon', 'agilent', 'ally'}
TICKER_RE = re.compile(r'\b(NYSE(?:\s*American|\s*Arca)?|NASDAQ|Nasdaq|AMEX|TSX|LSE|ASX|OTC|Ticker|Symbol|ticker|symbol)(\s*[:\-–]\s*|\s+)([A-Z][A-Z.]{0,5})\b')
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
URL_RE = re.compile(r'(?:https?://|www\.)[^\s"<>]+', re.I)
PHONE_RE = re.compile(r'(?<![\w.])(?:\+?\d{1,3}[\s.\-])?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}(?![\w.])')
AUTHOR_CONTEXT = re.compile(r'\b(prepared|created|modified|author|analyst|by|contact|model by|built by|reviewed)\b', re.I)
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9&'’\-]*\.?")


def _norm(tok):
    return tok.lower().strip(".,'’").replace('’', "'")


def core_tokens(name):
    toks = [_norm(t) for t in TOKEN_RE.findall(name.replace('/', ' '))]
    while toks and toks[-1] in LEGAL:
        toks.pop()
    while toks and toks[0] == 'the':
        toks.pop(0)
    return tuple(t for t in toks if t)


class Anonymizer:
    def __init__(self, names, top_names=(), nlp=None):
        """names: registrant names; top_names: the largest registrants (one-word names allowed)."""
        from wordfreq import zipf_frequency
        self.multi = set()
        self.single = set()
        top = {core_tokens(n) for n in top_names}
        for n in names:
            core = core_tokens(n)
            if not core:
                continue
            if len(core) > 1:
                self.multi.add(core)
            else:
                w = core[0]
                if len(w) >= 4 and w not in GENERIC and not w.isdigit() and (zipf_frequency(w, 'en') < 3.6 or core in top):
                    self.single.add(w)
        self.max_len = max((len(c) for c in self.multi), default=1)
        self.nlp = nlp
        self.count = 0

    # --- text -----------------------------------------------------------
    def text(self, s, people=False):
        if not s or not any(ch.isalpha() for ch in s):
            return s
        out = EMAIL_RE.sub('redacted@example.com', s)
        out = URL_RE.sub('[link removed]', out)
        out = PHONE_RE.sub('[phone removed]', out)
        out = TICKER_RE.sub(lambda m: f'{m.group(1)}{m.group(2)}REDACTED', out)
        out = self._names(out)
        if self.nlp and (people or AUTHOR_CONTEXT.search(out) or re.search(SUFFIX_RE + r'\b', out)):
            out = self._ner(out, people or bool(AUTHOR_CONTEXT.search(out)))
        if out != s:
            self.count += 1
        return out

    def _names(self, s):
        toks = [(m.start(), m.end(), m.group(0)) for m in TOKEN_RE.finditer(s)]
        spans, i = [], 0
        while i < len(toks):
            hit = 0
            for L in range(min(self.max_len, len(toks) - i), 0, -1):
                seg = toks[i:i + L]
                key = tuple(_norm(t[2]) for t in seg)
                if not seg[0][2][0].isupper():
                    break
                # Tokens must be contiguous words (only spaces, '&', ',' or '.' between them).
                if any(not re.fullmatch(r'[\s&,.]*', s[a[1]:b[0]]) for a, b in zip(seg, seg[1:])):
                    continue
                if (L > 1 and key in self.multi) or (L == 1 and key[0] in self.single):
                    hit = L
                    break
            if hit:
                start, end = toks[i][0], toks[i + hit - 1][1]
                m = re.match(SUFFIX_RE + r'+', s[end:])
                if m:
                    end += m.end()
                spans.append((start, end))
                i += hit
            else:
                i += 1
        for start, end in reversed(spans):
            s = s[:start] + REDACTED + s[end:]
        return s

    def _ner(self, s, people):
        try:
            doc = self.nlp(s[:20000])
        except Exception:  # noqa: BLE001
            return s
        for ent in reversed(doc.ents):
            if ent.label_ == 'ORG' and re.search(SUFFIX_RE + r'\.?$', ent.text) and REDACTED not in ent.text:
                s = s[:ent.start_char] + REDACTED + s[ent.end_char:]
            elif people and ent.label_ == 'PERSON' and len(ent.text.split()) >= 2:
                s = s[:ent.start_char] + 'Redacted Name' + s[ent.end_char:]
        return s

    # --- package --------------------------------------------------------
    def package(self, pkg):
        """Anonymises the package in place. Returns {old sheet name: new sheet name}."""
        def sub_t(part, people=False, tag='t'):
            if part not in pkg.parts:
                return
            text = pkg.text(part)
            pat = re.compile(rf'(<(?:\w+:)?{tag}(?:\s[^>]*)?>)(.*?)(</(?:\w+:)?{tag}>)', re.S)
            new = pat.sub(lambda m: m.group(1) + escape(self.text(unescape(m.group(2)), people)) + m.group(3), text)
            if new != text:
                pkg.put(part, new)

        sub_t('xl/sharedStrings.xml')
        for part in list(pkg.parts):
            if re.match(r'xl/(drawings|charts)/[^/]+\.xml$', part):
                sub_t(part)
            elif re.match(r'xl/comments\d*\.xml$', part):
                sub_t(part)
                sub_t(part, people=True, tag='author')
            elif re.match(r'xl/threadedComments/.*\.xml$', part):
                sub_t(part, tag='text')
            elif re.match(r'xl/persons/.*\.xml$', part):
                text = pkg.text(part)
                pkg.put(part, re.sub(r'displayName="[^"]*"', 'displayName="Redacted Name"', text)
                        .replace('userId="', 'userId="redacted').replace('providerId="', 'providerId="none'))
        # Document properties
        if 'docProps/core.xml' in pkg.parts:
            text = pkg.text('docProps/core.xml')
            for tag in ('dc:creator', 'cp:lastModifiedBy'):
                text = re.sub(rf'<{tag}>.*?</{tag}>', f'<{tag}>Redacted</{tag}>', text, flags=re.S)
            for tag in ('dc:title', 'dc:subject', 'dc:description', 'cp:keywords', 'cp:category'):
                text = re.sub(rf'(<{tag}>)(.*?)(</{tag}>)', lambda m: m.group(1) + escape(self.text(unescape(m.group(2)), True)) + m.group(3),
                              text, flags=re.S)
            pkg.put('docProps/core.xml', text)
        if 'docProps/app.xml' in pkg.parts:
            text = pkg.text('docProps/app.xml')
            for tag in ('Company', 'Manager'):
                text = re.sub(rf'<{tag}>.*?</{tag}>', f'<{tag}>Redacted</{tag}>', text, flags=re.S)
            text = re.sub(r'<HyperlinkBase>.*?</HyperlinkBase>', '<HyperlinkBase></HyperlinkBase>', text, flags=re.S)
            pkg.put('docProps/app.xml', text)
        for part in [p for p in pkg.parts if p.startswith('docProps/custom')]:
            pkg.drop(part)
        ct = pkg.text('[Content_Types].xml')
        ct2 = re.sub(r'<Override[^>]*PartName="/docProps/custom\.xml"[^>]*/>', '', ct)
        if ct2 != ct:
            pkg.put('[Content_Types].xml', ct2)
        rels = pkg.text('_rels/.rels') if '_rels/.rels' in pkg.parts else ''
        if 'custom.xml' in rels:
            pkg.put('_rels/.rels', re.sub(r'<Relationship[^>]*Target="docProps/custom\.xml"[^>]*/>', '', rels))

        # Sheet names, then inline strings, formula literals and headers/footers in every sheet.
        renames = {}
        used = {name for name, _ in pkg.sheets}
        for name, _ in pkg.sheets:
            new = self.text(name)
            if new != name:
                new = new.replace(REDACTED, 'Redacted Co')[:31].strip() or 'Sheet'
                base, k = new, 2
                while new in used and new != name:
                    new = f'{base[:28]} {k}'
                    k += 1
                used.add(new)
                renames[name] = new
        sheet_parts = [p for _, p in pkg.sheets]

        def fix_formula(f):
            f = unescape(f)
            for old, new in renames.items():
                q_new = "'" + new.replace("'", "''") + "'"
                f = f.replace("'" + old.replace("'", "''") + "'!", q_new + '!')
                if re.fullmatch(r'[A-Za-z_][\w.]*', old):
                    f = re.sub(rf'(?<![\w.\'])\b{re.escape(old)}!', q_new + '!', f)
            f = re.sub(r'"((?:[^"]|"")*)"', lambda m: '"' + self.text(m.group(1).replace('""', '"')).replace('"', '""') + '"', f)
            return escape(f)

        for part in sheet_parts:
            text = pkg.text(part)
            new = re.sub(r'(<f(?:\s[^>]*)?>)(.*?)(</f>)', lambda m: m.group(1) + fix_formula(m.group(2)) + m.group(3), text, flags=re.S)
            new = re.sub(r'(<is>.*?</is>)', lambda m: re.sub(r'(<t(?:\s[^>]*)?>)(.*?)(</t>)',
                                                             lambda n: n.group(1) + escape(self.text(unescape(n.group(2)))) + n.group(3),
                                                             m.group(1), flags=re.S), new, flags=re.S)
            for tag in ('oddHeader', 'oddFooter', 'evenHeader', 'evenFooter', 'firstHeader', 'firstFooter'):
                new = re.sub(rf'(<{tag}>)(.*?)(</{tag}>)', lambda m: m.group(1) + escape(self.text(unescape(m.group(2)), True)) + m.group(3),
                             new, flags=re.S)
            if new != text:
                pkg.put(part, new)
        for part in [p for p in pkg.parts if re.match(r'xl/charts/chart\d*\.xml$', p)]:
            text = pkg.text(part)
            new = re.sub(r'(<c:f>)(.*?)(</c:f>)', lambda m: m.group(1) + fix_formula(m.group(2)) + m.group(3), text, flags=re.S)
            if new != text:
                pkg.put(part, new)
        wb = pkg.text('xl/workbook.xml')
        for old, new in renames.items():
            wb = wb.replace(f'name="{escape(old).replace(chr(34), "&quot;")}"', f'name="{escape(new).replace(chr(34), "&quot;")}"')
        wb = re.sub(r'(<definedName\b[^>]*>)(.*?)(</definedName>)', lambda m: m.group(1) + fix_formula(m.group(2)) + m.group(3), wb, flags=re.S)
        pkg.put('xl/workbook.xml', wb)
        if 'docProps/app.xml' in pkg.parts and renames:
            text = pkg.text('docProps/app.xml')
            for old, new in renames.items():
                text = text.replace(f'<vt:lpstr>{escape(old)}</vt:lpstr>', f'<vt:lpstr>{escape(new)}</vt:lpstr>')
            pkg.put('docProps/app.xml', text)
        pkg.sheets = [(renames.get(n, n), p) for n, p in pkg.sheets]
        return renames
