"""Made-up names for real people (user, 2026-10-28: "use unique made up names"): the same person gets the same
made-up name everywhere — headers, display names, e-mail addresses, bodies, signatures, attachments, file and
folder names — and no two people share one. Company names are kept.

A person is keyed by 'first last' (lower case, middle initials dropped). The made-up name is drawn from
fdocs/first_names.txt and howco/surnames.txt (US Census 2010) with an HMAC of the key, so a person met by two
sources gets the same name; the map is saved per source in the private folder and every source loads all maps,
so a name in use is never handed to someone else. A drawn name that is itself a real person's name is skipped.
"""
import hashlib
import hmac
import os
import re
from pathlib import Path

from fdocs.anon import NOT_NAMES, NOT_PERSON_PHRASES, WORDLIKE, first_names

_HERE = Path(__file__).parent
ROLE = re.compile(r'announce|news|info|admin|help|mailer|daemon|noreply|no-reply|list|team|desk|support|office|'
                  r'sales|trading|group|all\b|everyone|hr\b|payroll|benefits|security|it\.|postmaster|webmaster|'
                  r'feedback|contact|service|confirm|operations|accounting|clickathome|enron\.', re.I)
NICK = {'ken': 'kenneth', 'jeff': 'jeffrey', 'mike': 'michael', 'bill': 'william', 'will': 'william', 'bob': 'robert',
        'rob': 'robert', 'jim': 'james', 'jimmy': 'james', 'tom': 'thomas', 'steve': 'steven', 'dave': 'david',
        'dan': 'daniel', 'chris': 'christopher', 'rick': 'richard', 'rich': 'richard', 'dick': 'richard',
        'phil': 'phillip', 'greg': 'gregory', 'joe': 'joseph', 'tim': 'timothy', 'sam': 'samuel', 'kate': 'katherine',
        'kathy': 'kathleen', 'liz': 'elizabeth', 'beth': 'elizabeth', 'sue': 'susan', 'jen': 'jennifer',
        'jenny': 'jennifer', 'andy': 'andrew', 'drew': 'andrew', 'matt': 'matthew', 'pat': 'patrick', 'ed': 'edward',
        'ted': 'edward', 'ron': 'ronald', 'don': 'donald', 'larry': 'lawrence', 'jerry': 'gerald', 'tony': 'anthony',
        'vince': 'vincent', 'nick': 'nicholas', 'stan': 'stanley', 'ben': 'benjamin', 'fred': 'frederick',
        'al': 'albert', 'alex': 'alexander', 'charlie': 'charles', 'chuck': 'charles', 'doug': 'douglas',
        'jack': 'john', 'johnny': 'john', 'jon': 'jonathan', 'les': 'leslie', 'lou': 'louis',
        'meg': 'margaret', 'peggy': 'margaret', 'pete': 'peter', 'ray': 'raymond', 'sally': 'sarah',
        'terry': 'terrence', 'tommy': 'thomas', 'wes': 'wesley', 'zach': 'zachary', 'jeffery': 'jeffrey'}
# Firms and places that read like 'Firstname Surname'.
NOT_PEOPLE = {'morgan stanley', 'arthur andersen', 'merrill lynch', 'dean witter', 'charles schwab', 'smith barney',
              'paine webber', 'raymond james', 'edward jones', 'william blair', 'thomas weisel', 'kidder peabody',
              'wells fargo', 'lehman brothers', 'bear stearns', 'price waterhouse', 'deloitte touche', 'coopers lybrand',
              'donaldson lufkin', 'goldman sachs', 'salomon smith', 'jefferies group', 'duke energy', 'pacific gas',
              'ernst young', 'grant thornton', 'johnson controls', 'johnson matthey', 'dow jones', 'marsh mclennan',
              'lazard freres', 'john deere', 'jack henry', 'robert half', 'thomson reuters', 'thomson financial',
              'franklin templeton', 'harley davidson', 'george washington', 'abraham lincoln', 'martin luther',
              'corpus christi', 'baton rouge', 'palo alto', 'virginia beach', 'georgia power', 'florida power',
              'carolina power', 'alberta energy', 'william morris', 'morgan keegan', 'piper jaffray', 'houlihan lokey',
              'evercore partners', 'duff phelps', 'kroll associates', 'standard poor', 'moody investors',
              'fitch ratings', 'henry hub', 'wall street', 'main street', 'charles river', 'morgan guaranty',
              'warren buffett', 'mary kay', 'ralph lauren', 'calvin klein', 'tommy hilfiger', 'ruth chris'}
# Words that end company and place names, never surnames.
NOT_LAST = set('''corp corporation inc incorporated co company companies ltd limited llc lp llp plc group holdings
holding partners partnership energy gas power electric oil petroleum resources services systems international bank
banc bancorp trust capital financial securities investments management marketing trading pipeline utilities
industries enterprises associates consulting solutions technologies networks communications america americas
canada europe asia texas university college school fund funds exchange markets online services north south east
west street avenue road boulevard county city state center centre hall building tower plaza'''.split())
PLACE_FIRST = {'san', 'santa', 'los', 'las', 'fort', 'port', 'saint', 'st', 'lake', 'mount', 'mt', 'new', 'el', 'la',
               'le', 'de', 'del', 'van', 'von', 'north', 'south', 'east', 'west', 'upper', 'lower'}
WORD = r"[A-Z][a-z][A-Za-z'’\-]*"
CAP = re.compile(rf"\b({WORD})(\s+(?:[A-Z]\.?\s+)?)({WORD})\b")
CAP_UP = re.compile(r"\b([A-Z]{2,})(\s+(?:[A-Z]\.?\s+)?)([A-Z]{2,})\b")
LAST_FIRST = re.compile(rf"\b({WORD}|[A-Z]{{2,}}),\s*({WORD}|[A-Z]{{2,}})(\s+[A-Z]\.?)?\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+'\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
X500 = re.compile(r"/O=[A-Z0-9 ]+/OU=[^\s<>\"',;]*?/CN=RECIPIENTS/CN=([A-Za-z0-9._\-]+)", re.I)


def _zipf(w):
    from wordfreq import zipf_frequency
    return zipf_frequency(w.lower(), 'en')


def _norm(w):
    return re.sub(r"['’]s$", '', w).strip(".,'’").lower()


class People:
    def __init__(self, maps, own, key, avoid=(), domain=None, is_company=None):
        """maps: {source: {person key: 'First Last'}} loaded from Drive; own: this source's map (updated)."""
        self.own, self.key = own, key.encode() if isinstance(key, str) else key
        avoid = {w.lower() for w in avoid}
        self.domain = domain or (lambda d: d)
        self.is_company = is_company or (lambda f, l: False)
        self.map = {}
        for m in maps:
            for k, v in m.items():
                self.map.setdefault(k, v)
        self.map.update(own)
        self.taken = set(self.map.values())
        firsts = sorted(first_names())
        self.firsts = [f.title() for f in firsts if f.isalpha() and 3 <= len(f) <= 9 and f not in WORDLIKE
                       and f not in NOT_NAMES and f not in avoid]
        self.lasts = [s.strip() for s in (_HERE / 'surnames.txt').read_text(encoding='utf-8').splitlines()
                      if s.strip() and not s.startswith('#') and s.strip().lower() not in WORDLIKE
                      and s.strip().lower() not in avoid]
        self.first_set = set(first_names())
        self.surname_set = {s.lower() for s in self.lasts}
        self.by_last = {}
        self.by_first = {}
        for k in self.map:
            self._index(k)
        self._common = {}

    def _index(self, k):
        f, _, l = k.partition(' ')
        self.by_last.setdefault(l, set()).add(k)
        self.by_first.setdefault(f, set()).add(k)

    def common(self, w):
        w = w.lower()
        if w not in self._common:
            self._common[w] = _zipf(w)
        return self._common[w]

    # --- the map -----------------------------------------------------------------------
    def resolve(self, first, last):
        """Key of a known person: exact, or the same surname with a nickname / short form of the first name."""
        f, l = _norm(first), _norm(last)
        k = f'{f} {l}'
        if k in self.map:
            return k
        cands = self.by_last.get(l) or ()
        if not cands or len(f) < 2:
            return None
        full = NICK.get(f, f)
        hits = [c for c in cands if c.split(' ', 1)[0] in (full, f) or NICK.get(c.split(' ', 1)[0]) == f
                or (len(f) >= 3 and c.split(' ', 1)[0].startswith(f))]
        return hits[0] if len(hits) == 1 else None

    def fake(self, first, last):
        """True for a made-up name we wrote ourselves."""
        return f'{first.title()} {_norm(last).title()}' in self.taken

    def pseudo(self, first, last):
        """'First Last' made up for this real person (created on first use)."""
        k = self.resolve(first, last) or f'{_norm(first)} {_norm(last)}'
        if k in self.map:
            return self.map[k]
        salt = 0
        while True:
            d = hmac.new(self.key, f'{k}#{salt}'.encode(), hashlib.sha256).digest()
            name = f'{self.firsts[int.from_bytes(d[:4], "big") % len(self.firsts)]} ' \
                   f'{self.lasts[int.from_bytes(d[4:8], "big") % len(self.lasts)]}'
            if name not in self.taken and name.lower() not in self.map and name.split()[0].lower() != _norm(first):
                break
            salt += 1
        self.map[k] = self.own[k] = name
        self.taken.add(name)
        self._index(k)
        return name

    def known(self, first, last):
        return self.resolve(first, last) is not None

    def is_first(self, w):
        w = _norm(w)
        return w in self.first_set and w not in WORDLIKE and w not in NOT_NAMES

    def person_like(self, first, last):
        """An unknown 'Firstname Surname' that reads as a person (learned as a new one)."""
        pair = f'{_norm(first)} {_norm(last)}'
        f = _norm(first)
        wordlike_ok = f in WORDLIKE and f in self.first_set and _norm(last) in self.surname_set
        return ((self.is_first(first) or wordlike_ok) and self.plausible_last(last) and pair not in NOT_PEOPLE
                and not self.is_company(first, last)
                and pair not in NOT_PERSON_PHRASES and _norm(first) not in PLACE_FIRST and not self.fake(first, last))

    def plausible_last(self, w):
        w = _norm(w)
        return (len(w) >= 2 and w not in NOT_NAMES and w not in WORDLIKE and w not in NOT_LAST
                and self.common(w) < (5.0 if w in self.surname_set else 4.3)
                and not (w.endswith(('ing', 'tion', 'ment', 'ness')) and self.common(w) >= 2.5))

    # --- people in addresses and display names ---------------------------------------------
    def from_display(self, display):
        """('first', 'last') from 'Allen, Phillip K.', 'Phillip K Allen', 'Phillip.Allen' or None."""
        d = re.sub(r'\s*\(.*?\)|["\']', '', display or '').strip()
        d = re.sub(r'@.*$', '', d)
        if not d or len(d) > 60:
            return None
        if ',' in d:
            last, _, rest = d.partition(',')
            parts = rest.split()
            first = parts[0] if parts else ''
            last = last.split()[-1] if last.split() else ''
        else:
            parts = [p for p in re.split(r'[\s._]+', d) if p]
            parts = [p for p in parts if len(p.strip('.')) > 1] or parts
            if len(parts) < 2:
                return None
            first, last = parts[0], parts[-1]
            # 'Hargrove  Mac D': surname first without a comma (two spaces in many address books).
            if not self.is_first(first) and len(parts) >= 2 and self.is_first(parts[1]) and not self.known(first, last):
                first, last = parts[1], parts[0]
        first, last = first.strip('.'), last.strip('.')
        if not (first.isalpha() and last.replace('-', '').replace("'", '').isalpha()) or len(first) < 2 or len(last) < 2:
            return None
        if _norm(first) in NOT_NAMES or _norm(last) in NOT_NAMES:
            return None
        if not (self.is_first(first) or self.known(first, last)):
            return None
        return first, last

    def address(self, addr, display=''):
        """Made-up address for a real one: first.last@ the same domain. Role and system addresses keep their local
        part when it names no person."""
        local, _, domain = addr.partition('@')
        domain = self.domain(domain)
        who = self.from_display(display) or self.from_display(local)
        if who:
            f, l = self.pseudo(*who).lower().split()
            return f'{f}.{l}@{domain}'
        if ROLE.search(local) and not re.search(r'[a-z]{2,}\.[a-z]{2,}', local.lower()) or local.lower() in (
                'enron.announcements', 'announcements.enron', 'enron.messaging.administration'):
            return f'{local}@{domain}'
        d = hmac.new(self.key, local.lower().encode(), hashlib.sha256).hexdigest()[:6]
        return f'person.{d}@{domain}'

    # --- text --------------------------------------------------------------------------------
    def sub(self, text, participants=(), learn=True):
        """Replaces people's names in text. participants: [(first, last)] of the message (their first and last names
        alone are replaced too). learn: unknown 'Firstname Surname' pairs become new people."""
        if not text:
            return text
        text = EMAIL.sub(lambda m: self.address(m.group(0)), text)
        text = X500.sub(lambda m: '/O=ORG/OU=NA/CN=RECIPIENTS/CN=' + self._x500(m.group(1)), text)

        def lastfirst(m):
            last, first = m.group(1), m.group(2)
            if self.fake(first, last) or f'{_norm(first)} {_norm(last)}' in NOT_PEOPLE:
                return m.group(0)
            if self.known(first, last) or (learn and self.person_like(first, last) and m.group(1) != m.group(1).upper()):
                p = self.pseudo(first, last).split()
                out = f'{p[1]}, {p[0]}'
                return out.upper() if last.isupper() and len(last) > 1 else out
            return m.group(0)
        text = LAST_FIRST.sub(lastfirst, text)

        def full(m):
            first, gap, last = m.group(1), m.group(2), m.group(3)
            pair = f'{_norm(first)} {_norm(last)}'
            if pair in NOT_PERSON_PHRASES or pair in NOT_PEOPLE or self.fake(first, last) or self.is_company(first, last):
                return m.group(0)
            if self.known(first, last) or (learn and self.person_like(first, last)):
                p = self.pseudo(first, last).split()
                poss = "'s" if re.search(r"['’]s$", last) else ''
                out = f'{p[0]} {p[1]}{poss}'
                return out.upper() if first.isupper() else out
            return m.group(0)
        text = CAP.sub(full, text)
        text = CAP_UP.sub(lambda m: full(m) if self.known(m.group(1), m.group(3)) else m.group(0), text)
        def initial(m):
            hits = [k for k in self.by_last.get(m.group(2).lower(), ()) if k[0] == m.group(1).lower()]
            if len(hits) != 1:
                return m.group(0)
            p = self.map[hits[0]].split()
            return p[0][0] + p[1]
        text = re.sub(r'\b([A-Z])([A-Z][a-z]{2,})\b', initial, text)
        for first, last in participants:
            p = self.pseudo(first, last).split()
            f = _norm(first)
            forms = {f} | {n for n, full in NICK.items() if full == f}
            for form in sorted(forms, key=len, reverse=True):
                if len(form) < 2:
                    continue
                if len(form) >= 3 and form not in WORDLIKE and self.common(form) < 5.0:
                    text = re.sub(rf"\b{re.escape(form)}\b", p[0], text, flags=re.I)
                else:  # 'Mark', 'Bill', 'Ed': only as a greeting or a sign-off on its own line
                    text = re.sub(rf"(?im)^([ \t>]*(?:(?:hi|hello|hey|dear|thanks|thank you|regards|cheers|best)[ ,!]*)?)"
                                  rf"{re.escape(form)}\b(?=[ \t]*(?:[,:!.\-]|$))", lambda m: m.group(1) + p[0], text)
            if self.plausible_last(last) and len(last) >= 3:
                text = re.sub(rf"\b{re.escape(last)}\b", p[1], text, flags=re.I)
        return text

    def _x500(self, cn):
        """Exchange recipient ids ('PALLEN'): a made-up id of the same shape."""
        return 'U' + hmac.new(self.key, cn.lower().encode(), hashlib.sha256).hexdigest()[:7].upper()

    def leaks(self, text, participants):
        """Real names of the message's people still in text (for the checks)."""
        out = []
        for first, last in participants:
            if self.plausible_last(last) and len(last) >= 4 and re.search(rf'\b{re.escape(last)}\b', text, re.I):
                out.append(last)
        return out


def key_material():
    """HMAC key: a stable secret of the workflow (never written anywhere)."""
    k = os.environ.get('HOWCO_KEY') or os.environ.get('GOOGLE_CLIENT_SECRET') or 'local-test-key'
    return hashlib.sha256(('howco:' + k).encode()).digest()
