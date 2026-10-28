"""Made-up company names (user, 2026-10-28): every real company gets one invented name, the same everywhere —
headers, e-mail and web domains (dynegy.com → <invented>.com), subjects, bodies, attachments, file and folder
names. Generic words, regulators and government agencies, universities and non-profits stay.

A company is keyed by its core name ('pacific gas and electric', 'dynegy'): the legal suffix ('Inc', 'Corp') and
words after the core ('Enron North America Corp' → '<Invented> North America Corp') are kept. Where companies come
from: the SEC registrant list (models.anonymize.Anonymizer rules: multi-word names always, one-word names only when
rare in English), a seed list of the energy-trading era's companies and partnerships, names written with a legal
suffix, and the labels of commercial domains (.com/.net/.biz/country .co.*) in addresses and links.
Invented names are pronounceable made-up words, never an English word, a first name or a registrant, and never
sharing three letters at the start with the real name. Tickers in context ('NYSE: XYZ', '(XYZ)') get made-up
tickers.
"""
import hashlib
import hmac
import re

from fdocs.anon import NOT_NAMES
from models.anonymize import GENERIC, SUFFIX_RE, TOKEN_RE, core_tokens, _norm

# Companies and partnerships of the energy-trading corpus that are no longer SEC registrants (or are written
# differently there). Lower-case core names.
SEED = '''enron; enron online; enronxgate; azurix; wessex water; dabhol power; elektro; portland general; transwestern;
northern natural gas; northern border; eott; houston natural gas; internorth; zond; mariner energy; lj m; ljm; ljm2;
chewco; jedi; raptor; whitewing; marlin water; osprey trust; atlantic water trust; new power company; newpower;
dynegy; mirant; reliant; calpine; aquila; utilicorp; el paso; pg e; pacific gas and electric; southern california
edison; socal edison; sempra; san diego gas and electric; sdg e; williams energy; williams companies; duke energy;
dominion resources; entergy; txu; cms energy; constellation energy; nrg energy; cinergy; allegheny energy; aes;
avista; puget sound energy; sierra pacific; nevada power; coral energy; koch industries; kinder morgan; exxonmobil;
exxon; mobil; texaco; chevron; conoco; phillips petroleum; arthur andersen; andersen consulting; vinson elkins;
merrill lynch; cibc; citigroup; citibank; salomon smith barney; credit suisse first boston; csfb; jp morgan;
j p morgan; chase manhattan; morgan stanley; goldman sachs; bank of america; barclays; deutsche bank; nymex;
intercontinental exchange; platts; blockbuster; compaq; accenture; kpmg; pricewaterhousecoopers; deloitte touche;
ernst young; mckinsey; bracewell patterson; akin gump; skadden arps; sullivan cromwell; weil gotshal; dow jones;
bloomberg; reuters; natural gas intelligence; mcgraw hill; standard poor; moody; fitch; bp amoco; royal dutch shell;
tenaska; cargill; aep; american electric power; pseg; public service enterprise; firstenergy; edison mission;
pinnacle west; idacorp; tractebel; powerex; bc hydro; transcanada; westcoast energy; nicor; peoples energy;
questar; kn energy; tenneco; columbia gas; coastal corporation; panhandle eastern; texas eastern; tejas gas;
valero; ultramar; sun company; ameren; xcel energy; northern states power; detroit edison; consumers energy;
pepco; conectiv; bge; baltimore gas and electric; exelon; peco; commonwealth edison; comed; illinova;
dynegy marketing; el paso merchant; mirant americas; reliant energy services; microsoft; google; alphabet; facebook;
netflix; yahoo; ebay; paypal; walmart; wal mart; boeing; amazon; intel; cisco; oracle corporation; ibm; adobe;
nvidia; tesla motors; starbucks; mcdonalds; coca cola; pepsico; procter gamble; johnson johnson; general electric;
general motors; exxon mobil; aol; time warner; worldcom; tyco; qwest; global crossing; adelphia; halliburton'''
SEED = [tuple(w.split()) for w in (x.strip() for x in SEED.replace('\n', ' ').split(';')) if w]
# Labels of domains that are not companies.
NOT_COMPANY_DOMAINS = {'example', 'localhost', 'www', 'mail', 'email', 'smtp'}
KEEP_TLDS = ('.gov', '.edu', '.mil', '.org', '.int', '.us')
DOMAIN = re.compile(r'(?<![\w.\-@])((?:[a-z0-9\-]+\.)*)([a-z0-9][a-z0-9\-]{1,62})((?:\.co|\.com)?\.(?:com|net|biz|info|'
                    r'co|uk|ca|au|de|fr|jp|ch|nl|no|se|be|es|it|in|br|mx|ar|cn|hk|sg)\b)(?![.\-]?[A-Za-z0-9])', re.I)
HOST_AT = re.compile(r'@([A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,})')
SUFFIXED = re.compile(r"\b((?:(?:[A-Z]\.|[A-Z][\w&'’\-]*)[ \t]+){0,3}[A-Z][\w&'’\-]*)" + SUFFIX_RE + r"(?![\w])")
TICKER_CTX = re.compile(r'\b(NYSE(?:\s*American|\s*Arca)?|NASDAQ|Nasdaq|AMEX|TSX|OTC|OTCBB|Ticker|Symbol|ticker|symbol)'
                        r'(\s*[:\-–]\s*|\s+)([A-Z][A-Z.]{0,5})\b')
TICKER_PAREN = re.compile(r'\((?:(NYSE|NASDAQ|Nasdaq|AMEX|TSX|OTC)\s*[:\-]?\s*)?([A-Z]{1,5})\)')
ON = 'bcdfghjklmnprstvz'
NU = 'aeiou'
CODA = ['', '', 'n', 'r', 'l', 's', 'x', 'nt', 'rd', 'lt', 'm']


def _style(src, word):
    """'ENRON' → 'TALVERO', 'enron' → 'talvero', 'Enron' → 'Talvero'."""
    if src.isupper() and len(src) > 1:
        return word.upper()
    if src.islower():
        return word.lower()
    return word[0].upper() + word[1:]


class Companies:
    def __init__(self, maps, own, key, registrants=(), top=(), tickers=(), tick_maps=(), tick_own=None):
        """maps: {core: invented} of every source; own: this source's map (updated); registrants/top: SEC names (as
        for models.anonymize.Anonymizer); tickers: SEC tickers."""
        from wordfreq import zipf_frequency
        from fdocs.anon import first_names
        self.zipf = zipf_frequency
        self.own, self.key = own, key
        self.map = {}
        for m in maps:
            for k, v in m.items():
                self.map.setdefault(k, v)
        self.map.update(own)
        self.taken = {v.lower() for v in self.map.values()}
        self.taken_flat = {v.replace(' ', '') for v in self.taken} | {w for v in self.taken for w in v.split()}
        self.firsts = first_names()
        self.multi, self.single = set(), set()
        self.common_single = set()  # one-word names that are everyday words ('apple', 'target'): only where a document names them as a company
        self.seed = set(SEED)
        top = {core_tokens(n) for n in top}
        for n in registrants:
            self._add(core_tokens(n), core_tokens(n) in top)
        for c in SEED:
            self._add(c, True)
        for k in self.map:
            if not k.startswith('dom:'):
                self._add(tuple(k.split()), True)
        # Replaced inside longer words too ('EnronOnline'): only names that are not part of English words.
        self.compound = ({c[0] for c in SEED if len(c) == 1 and len(c[0]) >= 5 and self.zipf(c[0], 'en') < 3.0}
                         | {k for k in self.map if ' ' not in k and not k.startswith('dom:') and self.zipf(k, 'en') < 2.0})
        # tickers: {ticker: SEC title} (a list is accepted too)
        self.ticker_title = {k.upper(): v for k, v in tickers.items()} if isinstance(tickers, dict) else {}
        self.tickers = {t.upper() for t in tickers}
        self.tick_own = {} if tick_own is None else tick_own
        self.ticker_map = {}
        for m in tick_maps:
            self.ticker_map.update(m)
        self.ticker_map.update(self.tick_own)
        self.tick_taken = set(self.ticker_map.values())
        self.start()

    def start(self):
        """A new document."""
        self.seen = set()  # cores replaced in this document (for the leak check)
        self.active = set()  # everyday-word company names this document uses as a company
        self.doc_tickers = set()

    def _add(self, core, big=False):
        if not core:
            return False
        if len(core) > 1:
            if all(w in GENERIC or self.zipf(w, 'en') >= 4.5 for w in core) and core not in {c for c in SEED}:
                return False
            self.multi.add(core)
        else:
            w = core[0]
            if len(w) < 3 or w.isdigit():
                return False
            if core not in self.seed and (w in GENERIC or self.zipf(w, 'en') >= 3.6):
                self.common_single.add(w)
                return False
            self.single.add(w)
        self.max_len = max([len(c) for c in self.multi] + [1])
        return True

    # --- the map ---------------------------------------------------------------------------
    def _word(self, d, i):
        n = 2 + d[i] % 2
        w = ''
        for j in range(n):
            b = d[i + 1 + j * 3: i + 4 + j * 3]
            w += ON[b[0] % len(ON)] + NU[b[1] % len(NU)] + (CODA[b[2] % len(CODA)] if j == n - 1 else '')
        return w.capitalize()

    def pseudo(self, core):
        """Invented name for a core (tuple or 'space joined')."""
        k = ' '.join(core) if isinstance(core, tuple) else core
        if k in self.map:
            return self.map[k]
        salt = 0
        while True:
            d = hmac.new(self.key, f'co:{k}#{salt}'.encode(), hashlib.sha256).digest()
            name = self._word(d, 0) if len(k.split()) == 1 else f'{self._word(d, 0)} {self._word(d, 12)}'
            lw = name.lower()
            ok = (lw not in self.taken and all(self.zipf(w, 'en') < 1.5 and w not in self.firsts for w in lw.split())
                  and not any(w[:3] == r[:3] for w in lw.split() for r in k.removeprefix('dom:').split())
                  and tuple(lw.split()) not in
                  self.multi and lw not in self.single)
            if ok:
                break
            salt += 1
        self.map[k] = self.own[k] = name
        self.taken.add(name.lower())
        self.taken_flat |= {name.lower().replace(' ', '')} | set(name.lower().split())
        if not k.startswith('dom:'):
            self._add(tuple(k.split()), True)
        return name

    def ticker(self, t):
        """Made-up ticker: same length (at least 3 letters), never a real ticker, never given twice."""
        if t not in self.ticker_map:
            salt = 0
            while True:
                d = hmac.new(self.key, f'tk:{t}#{salt}'.encode(), hashlib.sha256).digest()
                s = ''.join(chr(65 + b % 26) for b in d[:max(3, len(t.replace('.', '')))])
                if s not in self.tick_taken and s not in self.tickers and s != t:
                    break
                salt += 1
            self.ticker_map[t] = self.tick_own[t] = s
            self.tick_taken.add(s)
        return self.ticker_map[t]

    # --- learning ----------------------------------------------------------------------------
    def learn_domain(self, label):
        """A commercial domain's label names a company: 'dynegy' (from dynegy.com)."""
        label = label.lower()
        if label in NOT_COMPANY_DOMAINS or len(label) < 2 or label in self.taken_flat:
            return None
        k = label.replace('-', ' ') if '-' in label else label
        known = k in self.map or k in self.single or tuple(k.split()) in self.multi
        if not known and any(self.zipf(w, 'en') >= 2.0 for w in k.split()):
            k = 'dom:' + k  # 'wellhead.com': an ordinary word, replaced only where it is a domain
        if k not in self.map:
            self.pseudo(k)
        if ' ' not in k and not k.startswith('dom:') and self.zipf(k, 'en') < 2.0:
            self.compound.add(k)
        return k

    def learn(self, text):
        """Names written with a legal suffix ('Tejas Gas Corp', 'Dynegy Inc.') become companies."""
        for m in SUFFIXED.finditer(text or ''):
            core = core_tokens(m.group(1))
            while core and core[0] in ('the', 'and', 'of', 'by', 'with', 'from', 'to', 'for', 'at', 'in', 'on', 'our',
                                       'its', 'their', 'between', 'among'):
                core = core[1:]
            while core and core[0] in NOT_NAMES:
                core = core[1:]
            if not core or len(core) > 4 or all(w in GENERIC or self.zipf(w, 'en') >= 4.3 for w in core):
                continue
            if any(w in self.taken_flat for w in core):  # a made-up name of ours
                continue
            if len(core) == 1 and (self.zipf(core[0], 'en') >= 3.5 or core[0] in GENERIC):
                if core[0] in self.common_single:  # 'Apple Inc.': this document names the company
                    self.active.add(core[0])
                    self.pseudo(core)
                continue
            # 'Enron North America Corp': the known company inside is enough (its words after it are kept).
            if any(core[:i] in self.multi or (i == 1 and core[0] in self.single) for i in range(1, len(core) + 1)):
                continue
            if any(w in ('university', 'college', 'commission', 'department', 'agency', 'board', 'committee',
                         'government', 'state', 'city', 'county', 'federal', 'school', 'institute', 'foundation')
                   for w in core):
                continue
            if self._add(core, True):
                self.pseudo(core)

    # --- text --------------------------------------------------------------------------------------
    def domain(self, host):
        """'mail.dynegy.com' → 'mail.<invented>.com' (government, school and non-profit domains stay)."""
        lead = re.match(r"^[\s'\"<(]*", host).group(0)
        tail = re.search(r"[\s'\">),;.]*$", host).group(0)
        core = host[len(lead):len(host) - len(tail)]
        if core and '.' not in core and re.fullmatch(r'[A-Za-z][A-Za-z0-9\-]{1,62}', core):
            k = self.learn_domain(core)  # Lotus Notes and Exchange: 'person@ENRON'
            if not k:
                return host
            self.seen.add(k)
            new = self.map[k].replace(' ', '')
            return lead + (new.upper() if core.isupper() else new.lower()) + tail
        m = DOMAIN.fullmatch(core.lower())
        if not m or core.lower().endswith(KEEP_TLDS):
            return host
        host = core
        k = self.learn_domain(m.group(2))
        if not k:
            return host
        self.seen.add(k)
        subs = []
        for lab in m.group(1).split('.')[:-1]:
            sk = lab if lab in self.map else ('dom:' + lab if 'dom:' + lab in self.map else None)
            if sk:
                self.seen.add(sk)
            subs.append(self.map[sk].replace(' ', '').lower() if sk else lab)
        prefix = ''.join(x + '.' for x in subs)
        return f'{lead}{prefix}{self.map[k].replace(" ", "").lower()}{m.group(3)}{tail}'

    def sub(self, text, learn=True):
        if not text:
            return text
        if learn:
            self.learn_all(text)
        text = DOMAIN.sub(lambda m: self.domain(m.group(0)) if not m.group(0).lower().endswith(KEEP_TLDS) else m.group(0),
                          text)
        text = self._names(text)
        text = TICKER_CTX.sub(lambda m: m.group(1) + m.group(2) + self.ticker(m.group(3)), text)
        text = TICKER_PAREN.sub(lambda m: m.group(0) if m.group(1) or m.group(2) not in self.doc_tickers
                                else '(' + self.ticker(m.group(2)) + ')', text)
        return text

    def learn_all(self, text):
        """Learns the companies a text names (legal suffixes, tickers in context, domains). Called on a whole
        message or document first, so a name met late is replaced from the start."""
        if not text:
            return
        self.learn(text)
        for h in HOST_AT.findall(text) + [m.group(0) for m in DOMAIN.finditer(text)]:
            m = DOMAIN.fullmatch(h.lower().strip('.'))
            if m and not h.lower().endswith(KEEP_TLDS):
                self.learn_domain(m.group(2))
                for lab in m.group(1).split('.')[:-1]:  # 'shockwave.<company>.net': a product or company label
                    if lab in self.map or 'dom:' + lab in self.map:
                        continue
                    if len(lab) >= 4 and not re.fullmatch(r'(?:www\d*|mail\d*|smtp|mx\d*|ns\d*|web|ftp|pop\d*|imap|'
                                                          r'mailman|lists?|email|news|home|members?|users?|secure|'
                                                          r'[a-z]?\d+|[a-z]{1,3}\d*)', lab):
                        self.learn_domain(lab)
        if True:
            # A ticker named in context: its SEC registrant is a company of this document.
            for m in list(TICKER_CTX.finditer(text)) + list(TICKER_PAREN.finditer(text)):
                ctx = m.re is TICKER_CTX or m.group(1)
                t = m.group(3) if m.re is TICKER_CTX else m.group(2)
                title = self.ticker_title.get(t)
                core = core_tokens(title) if title else ()
                if not core:
                    continue
                # '(BESS)' after 'battery energy storage system' is not a ticker: the company's name must be near.
                if not ctx and core[0] not in text[max(0, m.start() - 100):m.start()].lower():
                    continue
                self.doc_tickers.add(t)
                if len(core) == 1 and not self._add(core, True):
                    self.active.add(core[0])
                else:
                    self._add(core, True)
                self.pseudo(core)

    def _names(self, s):
        toks = [(m.start(), m.end(), m.group(0)) for m in TOKEN_RE.finditer(s)]
        spans, i = [], 0
        while i < len(toks):
            hit = 0
            for L in range(min(self.max_len, len(toks) - i), 0, -1):
                seg = toks[i:i + L]
                key = tuple(_norm(t[2]) for t in seg)
                if not seg[0][2][0].isalpha():
                    break
                if any(not re.fullmatch(r'[\s&,.\-]*', s[a[1]:b[0]]) for a, b in zip(seg, seg[1:])):
                    continue
                # Capitalised in running text; an all-lower one-word name only when it is rare (a domain label).
                if not (seg[0][2][0].isupper() or (L == 1 and self.zipf(key[0], 'en') < 2.0 and key[0] in self.single)):
                    continue
                if L == 1 and seg[0][2][0].isupper() and key[0] not in self.single and key[0] not in self.active:
                    stem = re.sub(r'(?:ing|ed|es|s)$', '', key[0])
                    if len(stem) >= 4 and (stem in self.single or stem in self.active):
                        key = (stem,)
                if (L > 1 and key in self.multi) or (L == 1 and (key[0] in self.single or
                                                              (key[0] in self.active and seg[0][2][0].isupper()))):
                    hit = L
                    break
            if hit:
                start, end = toks[i][0], toks[i + hit - 1][1]
                last = toks[i + hit - 1][2].rstrip('.')
                if last.lower().endswith(("'s", "’s")):
                    end = toks[i + hit - 1][0] + len(last) - 2
                elif toks[i + hit - 1][2].endswith('.'):
                    end -= 1
                core = tuple(_norm(t[2]) for t in toks[i:i + hit])
                spans.append((start, end, core))
                i += hit
            else:
                i += 1
        for start, end, core in reversed(spans):
            k = ' '.join(core)
            self.seen.add(k)
            s = s[:start] + _style(s[start:end].replace(' ', ''), self.pseudo(k)) + s[end:]
        # Distinctive names inside longer words and compounds ('EnronOnline', 'enronxgate', 'ENRON_NA').
        low = s.lower()
        for w in sorted((w for w in self.compound if len(w) >= 5 and w in low and self.zipf(w, 'en') < 3.8),
                        key=len, reverse=True):
            if w in s.lower():
                s = re.sub(re.escape(w), lambda m: _style(m.group(0), self.pseudo(w).replace(' ', '')), s, flags=re.I)
                self.seen.add(w)
        return s

    def is_company(self, first, last):
        return (_norm(first), _norm(last)) in self.multi

    def words(self):
        """Every word of a known company name (made-up people's names never use them)."""
        return {w for c in self.multi for w in c} | self.single

    def leaks(self, text):
        """Real company names replaced in this document that are still in text."""
        low = (text or '').lower()
        out = []
        for k in self.seen:
            if k.startswith('dom:'):
                if re.search(r'[@.]' + re.escape(k[4:].replace(' ', '-')) + r'\.', low):
                    out.append(k[4:])
                continue
            words = k.split()
            if k in self.compound and len(k) >= 5:  # replaced inside any word, so it must be gone in any case
                if k in low:
                    out.append(k)
                continue
            if len(words) == 1 and self.zipf(k, 'en') >= 2.0:
                if re.search(r'\b' + re.escape(k.capitalize()) + r'\b', text or '') or (
                        len(k) >= 5 and re.search('(?i:' + re.escape(k) + ')(?=[A-Z@/])', text or '')):
                    out.append(k)
                continue
            if len(k) >= 4 and re.search(r'\b' + r'[\s&,.\-]*'.join(map(re.escape, words)) + r'\b', low):
                if not (len(words) == 1 and self.zipf(k, 'en') >= 3.0):
                    out.append(k)
        for w in self.active:  # everyday words: only their capitalised use is the company
            if re.search(r'' + re.escape(w.capitalize()) + r'', text or ''):
                out.append(w)
        return out
