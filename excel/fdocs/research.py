"""Workspace kinds: research notebooks ('scinotebooks'), Figma designs together with the HTML/CSS built from them
('figma') and style guides ('styleguides').

Finance only (user, 2026-10-27; topic.py): notebooks on quantitative finance, trading, portfolios, hedge funds,
accounting, risk and financial analysis (finance libraries or several finance terms in their text), and designs and
guidelines for finance products or teams. The STEM notebooks collected before stay on Drive; none are added.

Sources are openly licensed only:
- scinotebooks: GitHub repositories in the Jupyter language whose README points to a paper, a thesis or an
  arXiv/DOI record, and Zenodo research records (their .ipynb files and the GitHub repository they archive).
  Course work (homework, assignments, labs) is rejected; a notebook must be scientific (a science library or
  several domain terms), explained (markdown cells) and substantial (code cells).
- figma: GitHub repositories that commit a real Figma file (.fig, not a Git LFS pointer) next to an HTML/CSS
  implementation. The package is one zip: figma/design-N.fig plus web/<the HTML, CSS and their assets>.

Anonymisation follows the other types, except that people's names become 'John Doe' (user, 2026-10-19); e-mails and personal links are
removed, the repository owner's login and home-directory user names are replaced. The science, the code, the
charts it draws and the designs themselves are kept.
"""
import hashlib
import io
import json
import re
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

import requests

from models.xl import REDACTED

from . import anon as _anon
from . import sources
from .topic import finance as is_finance, terms as finance_terms
from .sources import _add, _gh, late

KINDS = ('scinotebooks', 'figma', 'styleguides')
OPEN = {'mit', 'apache-2.0', 'bsd-3-clause', 'bsd-2-clause', 'gpl-3.0', 'gpl-2.0', 'lgpl-3.0', 'agpl-3.0', 'cc0-1.0',
        'unlicense', 'cc-by-4.0', 'cc-by-sa-4.0', 'mpl-2.0', 'isc', 'bsl-1.0', 'zlib', 'epl-2.0', 'wtfpl', 'ofl-1.1'}
ZIP_DATE = (2026, 1, 1, 0, 0, 0)  # fixed dates: the same content always gives the same zip (duplicate check)

# --- research notebooks -------------------------------------------------------------------------
# Finance, accounting, hedge-fund and financial-analysis notebooks only (user, 2026-10-27; topic.py).
TOPICS = ['quantitative finance', 'algorithmic trading', 'portfolio optimization', 'hedge fund', 'backtesting',
          'financial analysis', 'financial statements', 'accounting', 'asset pricing', 'factor investing',
          'risk management', 'value at risk', 'credit risk', 'credit scoring', 'option pricing', 'derivatives pricing',
          'fixed income', 'yield curve', 'stock market', 'stock prediction', 'volatility forecasting',
          'financial econometrics', 'financial time series', 'market microstructure', 'corporate finance', 'valuation',
          'fraud detection', 'banking', 'insurance', 'actuarial', 'fintech', 'cryptocurrency trading', 'forex',
          'earnings', 'financial forecasting', 'public finance', 'monetary policy', 'macroeconomics finance']
MARKERS = ['arxiv', 'doi', 'thesis', 'paper', 'dissertation', 'publication', 'analysis', 'strategy']
FINANCE_LIBS = re.compile(
    r'^\s*(?:import|from)\s+(yfinance|pandas_datareader|QuantLib|zipline|backtrader|pyfolio|empyrical|quantstats|ta|talib|'
    r'arch|riskfolio|pypfopt|ffn|bt|vectorbt|alpha_vantage|quandl|nasdaqdatalink|ccxt|fredapi|wrds|edgar|'
    r'sec_edgar_downloader|finta|mplfinance|qlib|finrl|alpaca_trade_api|ib_insync|openbb)\b', re.M)
DOMAIN = re.compile(
    r'hamiltonian|eigen(?:value|state|vector)|wave ?function|schr[oö]dinger|quantum|lattice|spin|boson|fermion|'
    r'galax|redshift|stellar|exoplanet|telescope|spectr|photometr|cosmolog|dark matter|molecul|reaction|catalys|'
    r'orbital|density functional|\bdft\b|crystal|alloy|band ?gap|protein|enzyme|genom|transcript|gene expression|'
    r'sequenc|\brna\b|\bdna\b|single.cell|neuron|spike|\beeg\b|fmri|cortex|species|population dynamics|'
    r'epidemi|infection|climate|precipitation|ocean|atmospher|seismic|earthquake|geophys|aquifer|hydrolog|'
    r'navier|turbulen|reynolds|fluid|plasma|thermodynam|entropy|differential equation|\bpde\b|\bode\b|'
    r'finite element|monte carlo|markov chain|bayesian|posterior|likelihood|simulation|experiment|measurement|'
    r'hypothesis|wavelength|frequency|magnetic|electric field|laser|optic|diffusion|kinetic|equilibrium|'
    r'stress|strain|signal|sensor|robot|trajectory', re.I)
COURSEWORK = re.compile(r'\b(?:homework|assignments?|problem set|exercises?(?: \d)?|lab \d|quiz|midterm|final exam|'
                        r'coursera|udemy|bootcamp|kaggle competition|tutorial \d)\b', re.I)
FIELDS = [
    ('Algorithmic trading', r'backtest|zipline|backtrader|vectorbt|trading strateg|algorithmic trading|alpaca|ib_insync'),
    ('Portfolio management', r'portfolio|pypfopt|riskfolio|efficient frontier|markowitz|sharpe ratio|asset allocation'),
    ('Hedge funds and factor investing', r'hedge fund|factor (?:model|investing)|fama|long.short'),
    ('Derivatives and option pricing', r'option pricing|black.scholes|QuantLib|implied volatility|greeks|binomial tree'),
    ('Fixed income', r'fixed income|yield curve|bond (?:pricing|yield)|term structure'),
    ('Risk management', r'value at risk|expected shortfall|credit risk|risk management|stress test|default probab'),
    ('Credit and banking', r'credit scor|loan|banking|lending|fraud'),
    ('Accounting and financial statements', r'accounting|financial statement|balance sheet|income statement|cash flow|edgar|10-k'),
    ('Valuation and corporate finance', r'valuation|discounted cash|\bdcf\b|wacc|corporate finance|capital structure'),
    ('Volatility and financial econometrics', r'volatility|garch|\barch\b|econometric|cointegration'),
    ('Cryptocurrency markets', r'crypto|bitcoin|ethereum|ccxt|blockchain'),
    ('Insurance and actuarial', r'insurance|actuar'),
    ('Macroeconomics and public finance', r'monetary|inflation|interest rate|fiscal|public finance|fredapi'),
    ('Stock market analysis', r'stock|equit|yfinance|share price|market data'),
]
# Scientific eponyms are not people to redact ('Navier-Stokes', 'Runge-Kutta', 'Hartree-Fock', 'Bessel').
EPONYMS = set('''abel airy ampere arrhenius avogadro bayes bernoulli bessel biot black blackman bloch bohr boltzmann born
bose bragg broyden brown butterworth carlo cauchy chandrasekhar chebyshev cholesky clausius compton coulomb courant
cox crank debye delaunay dijkstra dirac dirichlet doppler einstein euler faraday fermi feynman fick fisher fletcher
fock fokker fourier fresnel friedmann friedrichs frenk galerkin gauss gaussian gibbs goldfarb golay gram green hamilton
hamming hann hartree hastings heaviside heisenberg helmholtz hermite higgs hilbert hodgkin hooke hopf hubble huxley
ising jacobi jones kalman kaplan kepler kirchhoff kohn kolmogorov kruskal kutta lagrange laguerre lanczos langevin
laplace legendre lemaitre lennard levenberg lewy lomb lorentz lorenz lotka lyapunov mandelbrot markov marquardt
maxwell mead meier menten metropolis michaelis monte morse navarro navier nelder nernst newton nicolson nyquist ohm
oppenheimer pauli pearson planck poisson rabi raman raphson rayleigh riemann robertson runge rutherford savitzky
scargle schmidt schrodinger schrödinger schwarzschild shannon sham shanno slater snell spearman stark stokes student
taylor tukey turing verlet volterra voronoi walker wallis weibull weinberg welch whitney wiener wilcoxon yukawa zeeman
collaboration consortium team survey mission telescope observatory gaia tess euclid webb chandra spitzer herschel galex
wise sloan rubin vera ligo virgo kagra swift juno cassini rosetta hipparcos lamost desi roman grace atlas alice lhcb cms
icecube planck magellan keck subaru alma lofar meerkat ska apollo artemis voyager galileo copernicus sentinel landsat
modis aqua terra aura argo jason ensemble pandas jupyter python julia'''.split())


def _license_ok(repo):
    return ((repo.get('license') or {}).get('key') or '').lower() in OPEN


def _notebook_files(s, full, branch, limit=12):
    return sources._repo_files(s, full, branch, lambda p: p.endswith('.ipynb') and '.ipynb_checkpoints' not in p
                               and not re.search(r'(?:^|/)(?:test|tests|docs?/_build|site-packages)/', p),
                               8 * 2**20, limit)


def _queue_repo_notebooks(state, kind, s, full, branch, source, extra=None):
    added = 0
    if f'ghrepo:{kind}:{full}' in state['seen']:
        return 0
    state['seen'][f'ghrepo:{kind}:{full}'] = 1
    for f in _notebook_files(s, full, branch):
        url = f'https://raw.githubusercontent.com/{full}/{quote(branch)}/{quote(f["path"])}'
        cand = {'key': f'gh:{full}:{f["path"]}'[:300], 'url': url, 'ext': 'ipynb', 'orgs': [], 'source': source,
                'owner': full.split('/')[0]}
        cand.update(extra or {})
        added += _add(state, kind, cand)
    return added


def sci_github(state, kind, s, log, pages=2):
    """Jupyter repositories whose README cites a paper, thesis, arXiv or DOI record, one topic at a time."""
    added = 0
    for topic in TOPICS:
        for marker in MARKERS:
            cur = state['cursors'].setdefault(f'sci:gh:{topic}:{marker}', {'page': 1})
            if cur.get('done'):
                continue
            for _ in range(pages):
                if late():
                    return added
                try:
                    r = s.get('https://api.github.com/search/repositories', headers=_gh(s), timeout=60,
                              params={'q': f'{topic} {marker} in:readme language:"Jupyter Notebook" fork:false',
                                      'per_page': 50, 'page': cur['page'], 'sort': 'stars'})
                    if r.status_code == 403:
                        time.sleep(30)
                        break
                    items = r.json().get('items', []) if r.ok else None
                except (requests.RequestException, ValueError):
                    items = None
                if items is None:
                    break
                time.sleep(2)  # search API: 30 requests a minute
                for repo in items:
                    if late():
                        return added
                    if _license_ok(repo) and repo.get('size', 0) < 2_000_000:
                        added += _queue_repo_notebooks(state, kind, s, repo['full_name'], repo.get('default_branch') or 'main',
                                                       'github', {'topic': topic})
                cur['page'] += 1
                if len(items) < 50 or cur['page'] > 20:
                    cur['done'] = True
                    break
    return added


ZENODO_LIC = re.compile(r'^(?:cc-by|cc0|mit|apache|bsd|gpl|lgpl|agpl|mpl|isc|unlicense|cc-zero)', re.I)
GH_REPO = re.compile(r'github\.com/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+?)(?:\.git)?(?:/tree/([^/?#]+))?(?:[/?#]|$)')


def sci_zenodo(state, kind, s, log, pages=2):
    """Zenodo research records: their own .ipynb files and the GitHub repository they archive."""
    added = 0
    for topic in TOPICS:
        cur = state['cursors'].setdefault(f'sci:zenodo:{topic}', {'page': 1})
        if cur.get('done'):
            continue
        for _ in range(pages):
            if late():
                return added
            try:
                r = s.get('https://zenodo.org/api/records', timeout=60,
                          params={'q': f'(jupyter OR ipynb OR notebook) AND "{topic}"', 'size': 25, 'page': cur['page']})
                if r.status_code == 429:  # 30 requests a minute
                    time.sleep(60)
                    return added
                hits = r.json()['hits']['hits'] if r.ok else None
            except (requests.RequestException, ValueError, KeyError):
                hits = None
            if hits is None:
                break
            time.sleep(2.5)
            for h in hits:
                if late():
                    return added
                md = h.get('metadata') or {}
                if not ZENODO_LIC.match((md.get('license') or {}).get('id', '') or ''):
                    continue
                for f in h.get('files', [])[:40]:
                    key = f.get('key', '')
                    url = (f.get('links') or {}).get('self')
                    if key.lower().endswith('.ipynb') and url and 0 < f.get('size', 0) <= 8 * 2**20:
                        added += _add(state, kind, {'key': f'zenodo:{h["id"]}:{key}'[:300], 'url': url, 'ext': 'ipynb',
                                                    'orgs': [], 'source': 'zenodo', 'topic': topic})
                for rel in md.get('related_identifiers') or []:
                    m = GH_REPO.search(rel.get('identifier') or '')
                    if m:
                        added += _queue_repo_notebooks(state, kind, s, f'{m[1]}/{m[2]}', m[3] or 'HEAD', 'zenodo',
                                                       {'topic': topic})
                        break
            cur['page'] += 1
            if len(hits) < 25 or cur['page'] > 40:
                cur['done'] = True
                break
    return added


# Start of a word in JSON text: no letter or digit before it, except the 'n'/'t'/'r' of an escaped
# line break or tab ('\nStefania').
START = r'(?:(?<![A-Za-z0-9])|(?<=\\[ntr]))'


def _owner_scrub(text, owner):
    """The repository owner's login and home-directory user names ('/home/jsmith/', 'C:\\Users\\jsmith')."""
    text = re.sub(r'((?:/home/|/Users/|[A-Za-z]:\\\\Users\\\\|[A-Za-z]:\\Users\\)(?!user\b))[^/\\\s"\']+', r'\1user', text)
    if owner and len(owner) >= 4:
        text = re.sub(rf'{START}{re.escape(owner)}(?![A-Za-z0-9])', 'redacted', text, flags=re.I)
    return text


OBF_EMAIL = re.compile(r'[\w.+\-]+\s?(?:@|\[at\]|\(at\)|\{at\})\s?[\w\-]+(?:(?:\.|\s?\[dot\]\s?|\s?\(dot\)\s?)[\w\-]+)+', re.I)
AFFILIATION = re.compile(r'universi|institu|istituto|faculty|facult[ée]|department|\bdept\b|laborator|\blab\b|college|'
                         r'school of|centre|center for|academy|hospital|observator|osservatorio|observatoire|\bcnrs\b|'
                         r'\binaf\b|\binfn\b|\bcsic\b|\binria\b|\binserm\b|\bmax planck\b|\bnasa\b|\bcern\b|\besa\b|\beso\b',
                         re.I)
NAME_TOKEN = r"(?:[A-Z][a-zà-ÿ'’\-]+|[A-Z]\.(?:\s?[A-Z]\.)?)"
NAME_LINE = re.compile(rf'{NAME_TOKEN}(?:\s+{NAME_TOKEN}){{1,3}}')
AUTHOR_LABEL = re.compile(r'^\s*[#>*\-\s]*(?:@?authors?|written by|created by|prepared by|contact|maintainer|by)\s*[:\-]?\s*(.+)$',
                          re.I | re.M)


def _namelike(p):
    """'Thomas Boch', 'Katharina A. Lutz': no eponym ('Monte Carlo') and no everyday word ('Data Presentation')."""
    from wordfreq import zipf_frequency
    words = [w.strip('.') for w in p.split() if len(w.strip('.')) > 1]
    first = words[0].lower() if words else ''
    return bool(words) and not any(w.lower() in EPONYMS for w in words) and \
        (first in _anon.first_names() or all(zipf_frequency(w.lower(), 'en') < 4.3 for w in words))


def _author_block(nb):
    """The title block research notebooks open with: author lines, e-mails, affiliations and addresses.
    Rewrites them in the first markdown cells and returns the people's names found (to replace everywhere)."""
    names = set()
    cells = [c for c in nb.get('cells', []) if c.get('cell_type') == 'markdown'][:3]
    for c in cells:
        lines = _anon._src(c).split('\n')
        flag = [bool(OBF_EMAIL.search(ln) or AFFILIATION.search(ln) or re.search(r'orcid|\bphd\b|doctoral|supervisor', ln, re.I))
                for ln in lines]
        for i, ln in enumerate(lines):
            body = re.sub(r'^[\s#>*\-]+|[\s*_]+$', '', ln)
            m = AUTHOR_LABEL.match(ln)
            near = any(flag[max(0, i - 3):i + 4])
            if m:
                for part in re.split(r',|;|\band\b|&', m.group(1)):
                    part = re.sub(r'[*_`\[\]()]|\d', '', part).strip()
                    if NAME_LINE.fullmatch(part):
                        names.add(part)
            elif body and len(body) <= 400:
                # Affiliation markers ('Amodeo¹,', 'Matsumoto (1) Kohji', 'Lutz^2', '†') separate names too.
                flat = re.sub(r'\(\s*\d+(?:\s*,\s*\d+)*\s*\)|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|\^\{?[\d,]+\}?|<sup>.*?</sup>|[*†‡§]|\$\^\{?[\w,]+\}?\$|\d+',
                              ',', body)
                flat = re.sub(r'\b([A-Z]\.)(?=[A-Z][a-z])', r'\1 ', re.sub(r'[_`]', '', flat))  # 'G.Sorce'
                parts = [p.strip(' .:') for p in re.split(r',|;|\band\b|&', flat) if p.strip(' .:')]
                listed = len(parts) >= 2 and sum(len(p.split()) >= 2 for p in parts) >= 2
                if parts and (near or listed) and all(NAME_LINE.fullmatch(p) and _namelike(p) for p in parts) \
                        and not DOMAIN.search(body):
                    names |= set(parts)
            if OBF_EMAIL.search(ln):
                lines[i] = OBF_EMAIL.sub('redacted@example.com', ln)
            elif AFFILIATION.search(body) and len(body) <= 160:
                lines[i] = re.sub(re.escape(body), 'Redacted Institution', ln) if body else ln
            elif near and re.search(r'\d', body) and body.count(',') >= 2:  # a postal address
                lines[i] = ''
        c['source'] = '\n'.join(lines)
    return {n for n in names if len(n) >= 5 and 'Redacted' not in n and _anon.PERSON not in n}


def _names_scrub(text, names):
    """Replaces the author names (full, and a rare surname alone) in the notebook's JSON text."""
    from wordfreq import zipf_frequency
    pats = set()
    for n in names:
        pats.add(r'\s+'.join(re.escape(w) for w in n.split()))
        last = n.split()[-1].strip('.')
        if len(last) >= 4 and zipf_frequency(last.lower(), 'en') < 3.0:
            pats.add(re.escape(last))
    for p in sorted(pats, key=len, reverse=True):
        text = re.sub(rf'{START}{p}(?![A-Za-z])', _anon.PERSON, text)
    # The general pass may already have replaced a surname: 'Yosuke John Doe' → 'John Doe'.
    for first in {n.split()[0] for n in names if len(n.split()[0]) > 2}:
        text = re.sub(rf'{START}{re.escape(first)}\s+(?:[A-Z]\.\s*)*{_anon.PERSON}', _anon.PERSON, text)
    # A first name that is also a company's name ('Massimo') was replaced as a company before the person was known.
    return re.sub(rf'{re.escape(REDACTED)}\s+{_anon.PERSON}', _anon.PERSON, text)


def notebook(cand, raw, work, out, A):
    try:
        nb = json.loads(raw.read_bytes().decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return {'ok': False, 'reason': 'not JSON'}
    cells = nb.get('cells', []) if isinstance(nb, dict) else []
    code = [c for c in cells if c.get('cell_type') == 'code']
    md = [c for c in cells if c.get('cell_type') == 'markdown']
    code_src = '\n'.join(_anon._src(c) for c in code)
    md_src = '\n'.join(_anon._src(c) for c in md)
    if len(code) < 6:
        return {'ok': False, 'reason': f'only {len(code)} code cells'}
    if len(md) < 2 or len(md_src.split()) < 60:
        return {'ok': False, 'reason': 'no explanation (markdown)'}
    if COURSEWORK.search(md_src[:20000]) or COURSEWORK.search(cand['url']):
        return {'ok': False, 'reason': 'course work'}
    libs = {m.group(1) for m in FINANCE_LIBS.finditer(code_src)}
    terms = finance_terms(md_src[:50000])
    if not (libs and len(terms) >= 2) and len(terms) < 4:  # finance only (user, 2026-10-27)
        return {'ok': False, 'reason': 'not a finance notebook'}
    letters = [ch for ch in md_src if ch.isalpha()]
    if letters and sum(ch.isascii() for ch in letters) / len(letters) < 0.9:
        return {'ok': False, 'reason': 'not English'}
    authors = _author_block(nb)
    src = work / 'nb.ipynb'
    src.write_text(json.dumps(nb, ensure_ascii=False), encoding='utf-8')
    dst = out / 'nb.ipynb'
    _anon.NOT_NAMES |= EPONYMS  # this worker only handles research notebooks
    _anon.STRICT_PERSON = True
    why = A.ipynb(src, dst, keep_plots=True)
    if why:
        return {'ok': False, 'reason': why}
    text = _names_scrub(_owner_scrub(dst.read_text(encoding='utf-8'), cand.get('owner')), authors)
    text = OBF_EMAIL.sub('redacted@example.com', text) if '[at]' in text or '(at)' in text else text
    try:
        json.loads(text)
    except ValueError:
        return {'ok': False, 'reason': 'notebook broken by anonymising'}
    dst.write_text(text, encoding='utf-8')
    hay = '\n'.join(libs) + '\n' + md_src[:30000] + '\n' + cand.get('topic', '')
    field = next((name for name, pat in FIELDS if re.search(pat, hay, re.I)), 'Financial analysis')
    return {'ok': True, 'path': str(dst), 'ext': 'ipynb', 'label': f'Research notebook - {field}'}


# --- Figma designs with HTML/CSS ----------------------------------------------------------------
FIG_CODE_QUERIES = ['figma ".fig" extension:md', '"design.fig"', 'figma ".fig file"', 'figma "fig file" extension:md',
                    '".fig" figma html css extension:md', 'figma design file ".fig" extension:md']
FIG_REPO_QUERIES = ['figma in:readme language:HTML', 'figma in:readme language:CSS', 'figma in:readme language:SCSS',
                    'figma design html css', 'figma to html', 'figma landing page', 'figma ui kit', 'figma template html',
                    'figma mockup html', 'figma prototype html', 'figma website', 'figma portfolio', 'figma frontend',
                    'figma responsive', 'figma design system css', 'figma fintech', 'figma banking app',
                    'figma finance dashboard', 'figma crypto wallet', 'figma trading app', 'figma budget app',
                    'figma invoice', 'figma payment app', 'figma investment app', 'figma accounting dashboard']
FIXTURE = re.compile(r'(?:^|/)(?:tests?|__tests__|fixtures?|spec|testdata|samples?)/', re.I)
WEB = re.compile(r'\.(?:html?|css|scss|sass|less|svg|png|jpe?g|gif|webp|avif|ico|woff2?|ttf|otf|eot)$', re.I)
SKIP_DIR = re.compile(r'(?:^|/)(?:node_modules|vendor|bower_components|\.git|\.github|\.vscode|\.idea|__MACOSX)/', re.I)
CATEGORY = [('Landing page', r'landing'), ('Portfolio', r'portfolio|resume|\bcv\b'),
            ('E-commerce', r'e-?commerce|\bshop|store\b|\bcart\b|product'), ('Dashboard', r'dashboard|admin panel|analytics'),
            ('Mobile app', r'mobile app|\bios\b|android'), ('Blog', r'\bblog'), ('Restaurant and food', r'restaurant|food|recipe|cafe'),
            ('Travel', r'travel|hotel|booking|tour'), ('Education', r'education|course|school|learning'),
            ('Finance', r'bank|finance|crypto|wallet|payment'), ('Health', r'health|medical|fitness|clinic'),
            ('Real estate', r'real estate|property|apartment'), ('Agency', r'agency|startup|saas|business')]



FIN_DESIGN = re.compile(r'\bbank|crypto|wallet|money|fintech|invest|trading|stock|portfolio|accounting|invoice|budget|'
                        r'expense|payment|financ|loan|insurance|\btax\b|payroll|ledger|hedge', re.I)


def _finance_repo(repo):
    """Designs and guidelines for finance products or teams only (user, 2026-10-27): name, description or topics."""
    text = ' '.join([repo['full_name'].replace('-', ' ').replace('_', ' '), repo.get('description') or '',
                     ' '.join(repo.get('topics') or [])])
    return is_finance(text) or bool(FIN_DESIGN.search(text))

def _fig_ok(data):
    """A real Figma file: 'fig-kiwi' binary, or the newer zip holding canvas.fig (never a Git LFS pointer)."""
    if len(data) < 2048:
        return False
    if data[:8] == b'fig-kiwi':
        return True
    if data[:2] == b'PK':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                return any(n.endswith('canvas.fig') for n in z.namelist())
        except zipfile.BadZipFile:
            return False
    return False


def _figma_repo(state, kind, s, repo):
    """Queues a repository when it holds a Figma file and an HTML/CSS implementation."""
    full = repo['full_name']
    if f'ghrepo:{kind}:{full}' in state['seen']:
        return 0
    state['seen'][f'ghrepo:{kind}:{full}'] = 1
    if not _license_ok(repo) or repo.get('size', 0) > 400_000 or repo.get('fork') or not _finance_repo(repo):
        return 0
    if COURSEWORK.search(full.replace('-', ' ').replace('_', ' ')) or COURSEWORK.search(repo.get('description') or ''):
        return 0
    branch = repo.get('default_branch') or 'main'
    try:
        r = s.get(f'https://api.github.com/repos/{full}/git/trees/{quote(branch)}?recursive=1', headers=_gh(s), timeout=60)
        tree = r.json().get('tree', []) if r.ok else []
    except (requests.RequestException, ValueError):
        return 0
    blobs = [t for t in tree if t.get('type') == 'blob' and not SKIP_DIR.search(t['path'])]
    # Test fixtures of Figma-parsing libraries are not designs.
    figs = [t['path'] for t in blobs if t['path'].lower().endswith('.fig') and 2048 <= t.get('size', 0) <= 150 * 2**20
            and not FIXTURE.search(t['path'])][:5]
    web = [t for t in blobs if WEB.search(t['path']) and t.get('size', 0) <= 5 * 2**20]
    if not figs or not any(re.search(r'\.html?$', t['path'], re.I) for t in web) \
            or not any(re.search(r'\.(?:css|scss|sass|less)$', t['path'], re.I) for t in web):
        return 0
    web.sort(key=lambda t: (not re.search(r'\.(?:html?|css|scss|sass|less)$', t['path'], re.I), t['path']))
    readme = next((t['path'] for t in blobs if re.fullmatch(r'readme(?:\.md|\.txt)?', t['path'], re.I)), None)
    base = f'https://raw.githubusercontent.com/{full}/{quote(branch)}/'
    return int(_add(state, kind, {'key': f'figma:{full}', 'url': base + quote(figs[0]), 'ext': 'fig', 'orgs': [],
                                  'source': 'github', 'owner': full.split('/')[0], 'base': base, 'figs': figs,
                                  'web': [t['path'] for t in web[:300]], 'readme': readme,
                                  'about': (repo.get('description') or '')[:300]}))


def figma_github(state, kind, s, log, pages=2):
    added = 0
    for q in FIG_CODE_QUERIES:  # READMEs that mention a .fig file: the likeliest repositories
        cur = state['cursors'].setdefault(f'figma:code:{q}', {'page': 1})
        if cur.get('done'):
            continue
        for _ in range(pages):
            if late():
                return added
            try:
                r = s.get('https://api.github.com/search/code', headers=_gh(s), timeout=60,
                          params={'q': q, 'per_page': 100, 'page': cur['page']})
                if r.status_code == 403:
                    time.sleep(60)
                    break
                items = r.json().get('items', []) if r.ok else None
            except (requests.RequestException, ValueError):
                items = None
            if items is None:
                break
            time.sleep(7)  # code search: 10 requests a minute
            for full in dict.fromkeys(i['repository']['full_name'] for i in items):
                if late():
                    return added
                if f'ghrepo:{kind}:{full}' in state['seen']:
                    continue
                try:
                    rr = s.get(f'https://api.github.com/repos/{full}', headers=_gh(s), timeout=30)
                    repo = rr.json() if rr.ok else None
                except (requests.RequestException, ValueError):
                    repo = None
                if repo:
                    added += _figma_repo(state, kind, s, repo)
            cur['page'] += 1
            if len(items) < 100 or cur['page'] > 10:
                cur['done'] = True
                break
    for q in FIG_REPO_QUERIES:
        cur = state['cursors'].setdefault(f'figma:repo:{q}', {'page': 1})
        if cur.get('done'):
            continue
        for _ in range(pages):
            if late():
                return added
            try:
                r = s.get('https://api.github.com/search/repositories', headers=_gh(s), timeout=60,
                          params={'q': f'{q} fork:false', 'per_page': 50, 'page': cur['page']})
                if r.status_code == 403:
                    time.sleep(30)
                    break
                items = r.json().get('items', []) if r.ok else None
            except (requests.RequestException, ValueError):
                items = None
            if items is None:
                break
            time.sleep(2)
            for repo in items:
                if late():
                    return added
                added += _figma_repo(state, kind, s, repo)
            cur['page'] += 1
            if len(items) < 50 or cur['page'] > 20:
                cur['done'] = True
                break
    return added


SOCIAL = re.compile(r'(?:mailto:|tel:|https?://(?:www\.)?(?:linkedin\.com|twitter\.com|x\.com|facebook\.com|instagram\.com|'
                    r't\.me|wa\.me|github\.com|dribbble\.com|behance\.net))[^"\'\s>]*', re.I)


def _scrub_html(A, html, owner):
    def text(m):
        return '>' + A.scrub(m.group(1)) + '<'

    parts = re.split(r'(<(?:script|style)\b.*?</(?:script|style)\s*>)', html, flags=re.S | re.I)
    for i in range(0, len(parts), 2):  # outside <script>/<style>: visible text, comments and labelling attributes
        p = parts[i]
        p = re.sub(r'<meta\s+[^>]*name=["\']?(?:author|creator|publisher)["\']?[^>]*>', '', p, flags=re.I)
        p = re.sub(r'<!--(.*?)-->', lambda m: '<!--' + A.scrub(m.group(1)) + '-->', p, flags=re.S)
        p = re.sub(r'>([^<]+)<', text, p)
        p = re.sub(r'\b(alt|title|placeholder|aria-label|content)=(["\'])(.*?)\2',
                   lambda m: f'{m.group(1)}={m.group(2)}{A.scrub(m.group(3))}{m.group(2)}', p, flags=re.S | re.I)
        parts[i] = SOCIAL.sub('#', p)
    for i in range(1, len(parts), 2):  # inline styles: only their comments
        parts[i] = re.sub(r'/\*(.*?)\*/', lambda m: '/*' + A.scrub(m.group(1)) + '*/', parts[i], flags=re.S)
    return _owner_scrub(''.join(parts), owner)


def _scrub_css(A, css, owner):
    css = re.sub(r'/\*(.*?)\*/', lambda m: '/*' + A.scrub(m.group(1)) + '*/', css, flags=re.S)  # comments only: url() stays
    return _owner_scrub(css, owner)


def _scrub_fig(A, data):
    """Newer .fig files are zips with meta.json (file name, client data): scrub its strings. The design canvas
    itself (canvas.fig, a compressed binary) is kept as drawn."""
    if data[:2] != b'PK':
        return data
    src = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            raw = src.read(info)
            if info.filename == 'meta.json':
                try:
                    meta = json.loads(raw)

                    def walk(o):
                        if isinstance(o, dict):
                            return {k: walk(v) for k, v in o.items()}
                        if isinstance(o, list):
                            return [walk(v) for v in o]
                        return A.scrub(o) if isinstance(o, str) else o
                    raw = json.dumps(walk(meta)).encode()
                except ValueError:
                    pass
            dst.writestr(zipfile.ZipInfo(info.filename, ZIP_DATE), raw,
                         zipfile.ZIP_STORED if info.filename.endswith(('.png', '.jpg')) else zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def figma(cand, raw, work, out, A, budget=100 * 2**20):
    s = sources.session()
    first = raw.read_bytes()
    if not _fig_ok(first):
        return {'ok': False, 'reason': 'not a Figma file (or a Git LFS pointer)'}
    figs, total = [first], len(first)
    for p in cand['figs'][1:]:
        try:
            r = s.get(cand['base'] + quote(p), timeout=120)
        except requests.RequestException:
            continue
        if r.ok and _fig_ok(r.content) and total + len(r.content) < budget:
            figs.append(r.content)
            total += len(r.content)
    web, failed = {}, 0
    for p in cand['web']:
        if total > budget or failed > 20:
            break
        try:
            r = s.get(cand['base'] + quote(p), timeout=60)
        except requests.RequestException:
            failed += 1
            continue
        if not r.ok:
            failed += 1
            continue
        web[p] = r.content
        total += len(r.content)
    pages = [p for p in web if re.search(r'\.html?$', p, re.I)]
    styles = [p for p in web if re.search(r'\.(?:css|scss|sass|less)$', p, re.I)]
    if not pages or not styles:
        return {'ok': False, 'reason': 'HTML/CSS could not be downloaded'}
    readme = ''
    if cand.get('readme'):
        try:
            r = s.get(cand['base'] + quote(cand['readme']), timeout=60)
            readme = r.text if r.ok else ''
        except requests.RequestException:
            pass
    visible = '\n'.join(re.sub(r'<[^>]+>', ' ', re.sub(r'<(script|style)\b.*?</\1\s*>', ' ', web[p].decode('utf-8', 'replace'),
                                                                  flags=re.S | re.I)) for p in pages)
    if COURSEWORK.search(readme[:5000]):
        return {'ok': False, 'reason': 'course work'}
    A.learn(readme[:200000] + '\n' + visible[:600000])
    owner = cand.get('owner')
    dst = out / 'pack.zip'
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as z:
        for i, data in enumerate(figs, 1):
            z.writestr(zipfile.ZipInfo(f'figma/design-{i}.fig', ZIP_DATE), _scrub_fig(A, data), zipfile.ZIP_STORED)
        for p, data in sorted(web.items()):
            name = 'web/' + _owner_scrub(p, owner)
            if re.search(r'\.html?$', p, re.I):
                data = _scrub_html(A, data.decode('utf-8', 'replace'), owner).encode('utf-8')
            elif re.search(r'\.(?:css|scss|sass|less)$', p, re.I):
                data = _scrub_css(A, data.decode('utf-8', 'replace'), owner).encode('utf-8')
            elif p.lower().endswith('.svg'):
                svg = data.decode('utf-8', 'replace')
                svg = re.sub(r'<metadata\b.*?</metadata>', '', svg, flags=re.S | re.I)
                data = _owner_scrub(svg, owner).encode('utf-8')
            z.writestr(zipfile.ZipInfo(name, ZIP_DATE), data)
    hay = ' '.join([cand.get('about', ''), readme[:5000], visible[:20000]])
    cat = next((name for name, pat in CATEGORY if re.search(pat, hay, re.I)), 'Website')
    raw = hashlib.sha256(b''.join(hashlib.sha256(f).digest() for f in sorted(figs))).hexdigest()  # same designs = duplicate
    return {'ok': True, 'path': str(dst), 'ext': 'zip', 'label': f'Figma design and HTML-CSS - {cat}', 'raw': raw}


# --- style guides and guidelines ------------------------------------------------------------------------------------
STYLE_REPO_QUERIES = ['topic:style-guide', 'topic:styleguide', 'topic:design-system', 'topic:brand-guidelines',
                      'topic:coding-standards', 'topic:coding-style', 'topic:writing-style-guide', 'topic:content-design',
                      'topic:design-guidelines', 'topic:accessibility-guidelines', 'topic:api-guidelines', 'topic:design-tokens',
                      '"style guide" in:name,description', '"brand guidelines" in:name,description',
                      '"design guidelines" in:name,description', '"coding standards" in:name,description',
                      '"API guidelines" in:name,description', '"content style guide" in:name,description',
                      '"design system" in:name,description', 'topic:fintech design-system', 'topic:banking design-system',
                      '"financial writing" style guide', 'accounting guidelines in:name,description',
                      'finance "style guide" in:name,description', 'investment guidelines in:name,description']
STYLE_DOC = re.compile(r'\.(?:md|mdx|markdown|rst|txt|adoc|pdf)$', re.I)
STYLE_PATH = re.compile(r'(?:^|/)(?:docs?|guide|guides|guidelines?|style[-_ ]?guide|handbook|standards?|principles|'
                        r'foundations|components|patterns|content|writing|brand|tokens|accessibility|rules)(?:/|$)|'
                        r'(?:^|/)[^/]*(?:style|guide|guideline|standard|convention|principle|readme)[^/]*$', re.I)
STYLE_SKIP = re.compile(r'(?:^|/)(?:changelog|history|license|licence|code_of_conduct|security|funding|authors|'
                        r'contributors|codeowners|node_modules|vendor|test|tests|__tests__|fixtures?|examples?/.+/node_modules)',
                        re.I)
STYLE_CATEGORY = [('Brand guidelines', r'\bbrand|logo usage|visual identity'),
                  ('Accessibility guidelines', r'accessib|\bwcag\b|\ba11y\b'),
                  ('API design guidelines', r'\bapi\b.*(?:guideline|design|standard)|rest(?:ful)? api'),
                  ('Writing and content style guide', r'writing|content style|tone of voice|voice and tone|editorial'),
                  ('Design system', r'design system|design tokens|component library|ui kit'),
                  ('Coding style guide', r'coding|code style|lint|naming convention|javascript|python|java\b|css|sql|go\b|rust'),
                  ('Project guidelines', r'.')]


def _style_repo(state, kind, s, repo):
    """Queues a repository whose documents form a real style guide or set of guidelines."""
    full = repo['full_name']
    if f'ghrepo:{kind}:{full}' in state['seen']:
        return 0
    state['seen'][f'ghrepo:{kind}:{full}'] = 1
    name = full.replace('-', ' ').replace('_', ' ')
    if not _license_ok(repo) or repo.get('fork') or repo.get('archived') and repo.get('stargazers_count', 0) < 20 \
            or repo.get('stargazers_count', 0) < 3 or re.search(r'\bawesome\b', name, re.I) \
            or COURSEWORK.search(name) or COURSEWORK.search(repo.get('description') or '') or not _finance_repo(repo):
        return 0
    branch = repo.get('default_branch') or 'main'
    docs = sources._repo_files(s, full, branch, lambda p: bool(STYLE_DOC.search(p) and STYLE_PATH.search(p)
                                                                and not STYLE_SKIP.search(p) and not SKIP_DIR.search(p)),
                               15 * 2**20, 400)
    docs = sorted(docs, key=lambda t: (t['path'].count('/'), t['path']))[:150]
    if len(docs) < 3 or sum(t.get('size', 0) for t in docs) < 12_000:
        return 0
    base = f'https://raw.githubusercontent.com/{full}/{quote(branch)}/'
    return int(_add(state, kind, {'key': f'style:{full}', 'url': base + quote(docs[0]['path']), 'ext': 'zip', 'orgs': [],
                                  'source': 'github', 'owner': full.split('/')[0], 'base': base,
                                  'docs': [t['path'] for t in docs], 'about': (repo.get('description') or '')[:300],
                                  'topics': ' '.join(repo.get('topics') or [])[:300]}))


def style_github(state, kind, s, log, pages=2):
    added = 0
    for q in STYLE_REPO_QUERIES:
        cur = state['cursors'].setdefault(f'style:repo:{q}', {'page': 1})
        if cur.get('done'):
            continue
        for _ in range(pages):
            if late():
                return added
            try:
                r = s.get('https://api.github.com/search/repositories', headers=_gh(s), timeout=60,
                          params={'q': f'{q} fork:false', 'sort': 'stars', 'per_page': 50, 'page': cur['page']})
                if r.status_code == 403:
                    time.sleep(30)
                    break
                items = r.json().get('items', []) if r.ok else None
            except (requests.RequestException, ValueError):
                items = None
            if items is None:
                break
            time.sleep(2)
            for repo in items:
                if late():
                    return added
                added += _style_repo(state, kind, s, repo)
            cur['page'] += 1
            if len(items) < 50 or cur['page'] > 20:
                cur['done'] = True
                break
    return added


CODE = re.compile(r'(```.*?```|~~~.*?~~~|`[^`\n]+`|<pre\b.*?</pre>|<code\b.*?</code>)', re.S | re.I)
HANDLE = re.compile(r'(?<![\w.@/])@([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))\b(?![.\w-]*\.[a-z]{2,})')
EN_WORDS = set('the and of to a in is for that it on with as are be this you use should not or by an if when your can '
               'do from at we have will more than'.split())


def _prose(text):
    return CODE.sub(' ', text)


def _english(text):
    words = re.findall(r"[A-Za-z']+|[^\x00-\x7f\s]+", text.lower())
    return len(words) < 40 or sum(w in EN_WORDS for w in words) / len(words) >= 0.15


NAMEISH = r"[A-Z][\w'.-]+(?: [A-Z][\w'.-]+){1,3}"
PROFILE = re.compile(r"\[(?:" + NAMEISH + r"|@?[\w-]{2,39})\]\((https?://(?:www\.)?(?:github\.com|gitlab\.com|twitter\.com|x\.com|linkedin\.com/in)/[\w.-]+/?)\)")
CREDIT_LINE = re.compile(r'(?i)\b(?:courtesy of|thanks to|translated by|translation by|maintained by|created by|written by|authored by|contributed by)\b')
CREDIT_LINK = re.compile(r'\[' + NAMEISH + r'\]\(')
CONTRIB_ANCHOR = re.compile(r'(href="#[A-Za-z0-9]+-)[^"]+"')


def _credits(p):
    """Credit lists before the general scrub: profile links, 'Courtesy of [A] [B]' lines and all-contributors anchors."""
    p = PROFILE.sub(lambda m: f'[{_anon.PERSON}]({m.group(1)})', p)
    p = '\n'.join(CREDIT_LINK.sub(f'[{_anon.PERSON}](', ln) if CREDIT_LINE.search(ln) else ln for ln in p.split('\n'))
    return CONTRIB_ANCHOR.sub(r'\1salvador-sekwa"', p)


def _scrub_guide(A, text):
    """Names, e-mails and @handles in the prose; code blocks and inline code are left exactly as written."""
    parts = CODE.split(text)
    for i in range(0, len(parts), 2):
        p = _credits(parts[i])
        p = A.scrub(p)
        p = HANDLE.sub('@salvador-sekwa', p)
        firsts = _anon.first_names()

        def collapse(m):  # "Nicholas C. Salvador Sekwa" / "Salvador Salvador Sekwa" -> "Salvador Sekwa"
            toks = m.group(1).split()
            if all(len(t.rstrip('.')) == 1 or t.rstrip('.').lower() in firsts or t == 'Salvador' for t in toks):
                return _anon.PERSON
            return m.group(0)
        from wordfreq import zipf_frequency

        def first_last(m):  # "John Resig": a known first name and an uncommon capitalised word
            first, last = m.group(1), m.group(2)
            if first.lower() in firsts and first != 'Salvador' and zipf_frequency(last.lower(), 'en') < 3.2:
                return _anon.PERSON
            return m.group(0)
        p = re.sub(r"\b([A-Z][a-z]+)\s+(?:[A-Z]\.\s+)?([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b", first_last, p)
        p = re.sub(rf"\b((?:[A-Z][a-z]*\.?\s+){{1,3}}){re.escape(_anon.PERSON)}", collapse, p)
        parts[i] = p
    return ''.join(parts)


def _md_title(path, text):
    m = re.search(r'^\s*#\s+(.+)$', text, re.M)
    return (m.group(1).strip() if m else Path(path).stem.replace('-', ' ').replace('_', ' ').strip().capitalize())[:120]


def styleguide(cand, raw, work, out, A, budget=60 * 2**20):
    """A zip of the guide's documents (anonymised) plus one combined STYLE-GUIDE.md in reading order."""
    s = sources.session()
    files, total, failed = {}, 0, 0
    for p in cand['docs']:
        if total > budget or failed > 15:
            break
        try:
            r = s.get(cand['base'] + quote(p), timeout=60)
        except requests.RequestException:
            failed += 1
            continue
        if not r.ok:
            failed += 1
            continue
        files[p] = r.content
        total += len(r.content)
    texts = {p: d.decode('utf-8', 'replace') for p, d in files.items() if not p.lower().endswith('.pdf')}
    # English documents only (translations of a guide are left out); the PDFs stay as they are.
    texts = {p: t for p, t in texts.items() if _english(_prose(t))}
    files = {p: d for p, d in files.items() if p in texts or p.lower().endswith('.pdf')}
    words = sum(len(t.split()) for t in texts.values())
    if len(files) < 3 or words < 1500:
        return {'ok': False, 'reason': f'too little guidance ({words} words)'}
    if COURSEWORK.search(' '.join(list(texts.values())[:3])[:5000]):
        return {'ok': False, 'reason': 'course work'}
    A.learn('\n'.join(texts.values())[:800000])
    owner = cand.get('owner')
    dst = out / 'guide.zip'
    combined = []
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as z:
        for p, data in sorted(files.items(), key=lambda kv: (kv[0].count('/'), kv[0])):
            name = 'guide/' + _owner_scrub(p, owner)
            if p in texts:
                body = SOCIAL.sub('#', _owner_scrub(_scrub_guide(A, texts[p]), owner))
                z.writestr(zipfile.ZipInfo(name, ZIP_DATE), body.encode('utf-8'))
                combined.append(f'\n\n---\n\n<!-- {name} -->\n\n# {_md_title(p, body)}\n\n' +
                                re.sub(r'^\s*#\s+.+$', '', body, count=1, flags=re.M).strip())
            else:
                z.writestr(zipfile.ZipInfo(name, ZIP_DATE), data)
        hay = ' '.join([cand.get('about', ''), cand.get('topics', ''), ' '.join(list(texts.values())[:2])[:4000]])
        cat = next(n for n, pat in STYLE_CATEGORY if re.search(pat, hay, re.I))
        head = f'# {cat}\n\nCombined edition of {len(texts)} guidance documents in reading order.\n'
        z.writestr(zipfile.ZipInfo('STYLE-GUIDE.md', ZIP_DATE), (head + ''.join(combined)).encode('utf-8'))
    raw_hash = hashlib.sha256(b''.join(hashlib.sha256(files[p]).digest() for p in sorted(files))).hexdigest()
    return {'ok': True, 'path': str(dst), 'ext': 'zip', 'label': f'Style guide - {cat}', 'raw': raw_hash}


def process(cand, kind, raw, work, A):
    # Placeholders for people: John Doe for notebooks and Figma (user, 2026-10-19), Salvador Sekwa for style guides
    # (user, 2026-10-20). This collector's workers run nothing else.
    _anon.PERSON = 'Salvador Sekwa' if kind == 'styleguides' else 'John Doe'
    if kind == 'styleguides':
        _anon.STRICT_PERSON = True  # technical terms ('Webpack') are rare words, not names
    out = Path(work) / 'out'
    out.mkdir(exist_ok=True)
    if kind == 'styleguides':
        return styleguide(cand, raw, Path(work), out, A)
    return notebook(cand, raw, Path(work), out, A) if kind == 'scinotebooks' else figma(cand, raw, Path(work), out, A)


def sci_sources(state, kind, s, log):
    """Zenodo and GitHub take turns going first, so neither fills the queue alone."""
    turn = state['cursors'].setdefault('sci:turn', {'n': 0})
    turn['n'] += 1
    added = 0
    for fn in ((sci_zenodo, sci_github) if turn['n'] % 2 else (sci_github, sci_zenodo)):
        if not late():
            added += fn(state, kind, s, log, pages=1)
    return added


def prune(state, kind, log):
    """At the start of a run: drops candidates queued before the finance-only rule (user, 2026-10-27)."""
    q = state['queue'].get(kind, [])
    if kind == 'scinotebooks':
        keep = [c for c in q if c.get('topic') in TOPICS]
    else:
        keep = [c for c in q if _finance_repo({'full_name': c['key'].split(':', 1)[-1], 'description': c.get('about'),
                                               'topics': (c.get('topics') or '').split()})]
    for c in q:
        if c not in keep:
            state['queued'].pop(c['key'], None)
    state['queue'][kind] = keep
    if len(q) > len(keep):
        log(f'  {kind}: {len(q) - len(keep)} queued candidate(s) not about finance dropped')


DISCOVER = {'scinotebooks': [sci_sources], 'figma': [figma_github], 'styleguides': [style_github]}
