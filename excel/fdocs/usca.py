"""English, US and Canada only (user, 2026-10-24: "I only want US and Canada content in English").

Rules shared by the office collector and its cleanup: a record must be written in English (its metadata language
when given, its title, and later its text) and come from the United States or Canada (the creators' affiliations,
or a US / Canadian government publisher). Titles are compared in a normalised form so that one record's many
files, or re-uploads of the same work, are collected once. No dependencies, so a cleanup script can import it alone.
"""
import re
import unicodedata

STATES = ('Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut', 'Delaware', 'Florida',
          'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland',
          'Massachusetts', 'Michigan', 'Minnesota', 'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada',
          'New Hampshire', 'New Jersey', 'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma',
          'Oregon', 'Pennsylvania', 'Rhode Island', 'South Carolina', 'South Dakota', 'Tennessee', 'Texas', 'Utah',
          'Vermont', 'Virginia', 'Washington', 'West Virginia', 'Wisconsin', 'Wyoming', 'District of Columbia')
PROVINCES = ('Ontario', 'Quebec', 'Québec', 'British Columbia', 'Alberta', 'Manitoba', 'Saskatchewan', 'Nova Scotia',
             'New Brunswick', 'Newfoundland', 'Prince Edward Island', 'Yukon', 'Nunavut', 'Northwest Territories')
# Georgia is left out of STATES (also a country); its institutions are named here instead.
INSTITUTIONS = ('Georgia Tech', 'Georgia Institute of Technology', 'University of Georgia', 'Georgia State', 'Emory',
                'Harvard', 'Stanford', 'Yale', 'Princeton', 'Columbia University', 'Cornell', 'Duke University',
                'Johns Hopkins', 'Caltech', 'California Institute of Technology', 'Massachusetts Institute of Technology',
                r'\bMIT\b', 'UC Berkeley', 'UCLA', 'UCSF', 'UC Davis', 'UC San Diego', 'Carnegie Mellon',
                'Northwestern University', 'University of Chicago', 'Vanderbilt', 'Rice University', 'Brown University',
                'Dartmouth', 'Purdue', 'Rutgers', 'Tufts', 'Georgetown', 'Mayo Clinic', 'Smithsonian', r'\bNIH\b',
                r'\bNASA\b', r'\bNOAA\b', r'\bUSGS\b', r'\bUSDA\b', r'\bCDC\b', r'\bNIST\b', r'\bNREL\b', r'\bNSF\b',
                'National Laboratory', 'Federal Reserve', 'McGill', 'University of Toronto', 'McMaster', 'Waterloo',
                r'\bUBC\b', 'Dalhousie', 'Simon Fraser', 'Carleton', "Queen's University", 'Concordia University',
                'York University', 'Université de Montréal', 'University of Ottawa', 'Western University',
                'Statistics Canada', 'Health Canada', 'Government of Canada')
USCA = re.compile(r'\bU\.?S\.?A\b|\bUnited States\b|\bU\.S\.|\bCanada\b|\bCanadian\b|' +
                  '|'.join(r'\b' + re.escape(p) + r'\b' for p in STATES + PROVINCES) + '|' + '|'.join(INSTITUTIONS))
# Common words of other languages that never appear in an English title (accent-free, lower case).
FOREIGN = set('de del della di la le les des du et und der die das von zur zum fur uber mit para por los las una el '
              'em na no dos das com sobre nas nos och av pa en het van een voor naar ze w na dla oraz il per con nel '
              'sul tra kai tou tis ston'.split())
AMBIGUOUS = set('de la le du van von en na no w pa em av'.split())
LANG_OK = {'eng', 'en', 'english'}
ENGLISH_STOP = set('the of and to in a is that for on with as by are be this from at or an it which will not have has '
                   'was were'.split())


def english_title(title):
    """No letters outside the Latin alphabet (Cyrillic, Greek...), almost no accents and no foreign function words."""
    letters = [ch for ch in title if ch.isalpha()]
    if not letters:
        return False
    if any(unicodedata.name(ch, '').split(' ')[0] not in ('LATIN',) for ch in letters):
        return False
    if sum(not ch.isascii() for ch in letters) > max(1, len(letters) // 40):
        return False
    plain = re.sub(r'\bet\.?\s+al\b', ' ', title.lower())  # 'et al.' is English usage
    words = re.findall(r'[a-z]+', unicodedata.normalize('NFKD', plain).encode('ascii', 'ignore').decode())
    # Names such as 'De Soto' or 'Van Buren' allow one ambiguous word in a long title; never a clearly foreign one.
    if any(w in FOREIGN - AMBIGUOUS for w in words):
        return False
    return sum(w in FOREIGN for w in words) <= (1 if len(words) >= 8 else 0)


def english_text(text, min_tokens=50):
    """Prose check, as kinds.english: enough common English words among the first 30,000 characters."""
    toks = re.findall(r'[a-z]+', text[:30000].lower())
    if len(toks) < min_tokens:
        letters = [ch for ch in text[:30000] if ch.isalpha()]
        return bool(letters) and sum(ch.isascii() for ch in letters) / len(letters) > 0.97
    return sum(t in ENGLISH_STOP for t in toks) / len(toks) > 0.12


def zenodo_language(md):
    lang = (md.get('language') or '').strip().lower()
    return not lang or lang in LANG_OK


def zenodo_usca(md):
    """The first creator with an affiliation must be in the US or Canada (or, with no affiliations, a US/CA location)."""
    people = [p for p in (md.get('creators') or []) + (md.get('contributors') or []) if isinstance(p, dict)]
    affs = [str(p.get('affiliation') or '') for p in people if p.get('affiliation')]
    if affs:
        return bool(USCA.search(affs[0]))
    places = ' '.join(str((loc or {}).get('place') or '') for loc in (md.get('locations') or []))
    return bool(places and USCA.search(places))


def norm_title(title):
    """Title key for near-duplicates: lower case, accents/punctuation/numbers/versions dropped, first 12 words."""
    t = unicodedata.normalize('NFKD', title.lower()).encode('ascii', 'ignore').decode()
    t = re.sub(r'\b(?:v(?:ersion)?\s*\d+(?:\.\d+)*|part\s+\d+|\d+(?:st|nd|rd|th)?)\b', ' ', t)
    # Monthly and quarterly editions of one series read as one title (2026-10-29).
    t = re.sub(r'\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|'
               r'oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|q[1-4]|fy|cy)\b', ' ', t)
    words = re.findall(r'[a-z]+', t)
    return ' '.join(words[:12])
