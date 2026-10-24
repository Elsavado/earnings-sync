"""Numbered pseudonyms for the people in the game-development material (user, 2026-10-24, personal use).

Within one repository or dataset, each person becomes "Contributor 001", "Contributor 002", ... in order of first
appearance (4 digits when a repository has more than 999 contributors); e-mail addresses become
contributor001@users.invalid. Licence files (LICENSE, COPYING, NOTICE ...) are never changed, so licence texts and
their copyright lines stay intact; each manifest keeps the source URL and licence, so every item stays traceable.

  rewrite_repo(dir)          rewrites a bare/mirror clone's full history: author, committer and tagger names and
                             e-mails, names and e-mails in commit and tag messages, and known contributor names in
                             every non-licence text file (README, AUTHORS, CONTRIBUTORS, CREDITS, source headers)
  Names / text()             the numbering and free-text replacement used for documents and manifests
  document(path, ext, names) design documents: md/txt/csv text, DOCX (text and properties), PDF (redacted in place)
"""
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

LICENCE_FILE = re.compile(r'(?i)(?:^|/)(?:licen[cs]e|copying|copyright|notice|unlicense|patents?)(?:[._-][^/]*)?$')
BOT = re.compile(r'(?i)\[bot\]|^(?:github|gitlab|bitbucket|web-flow|dependabot|renovate|github-actions|weblate|transifex|travis|'
                 r'semantic-release|greenkeeper|snyk|codecov|crowdin|allcontributors|pre-commit-ci)\b|noreply@github\.com$')
CUE = re.compile(r"(?i)\b(?:author(?:s|ed by)?|written by|created by|made by|designed by|by|designer|lead designer|producer|"
                 r"programmer|artist|contact|prepared by|maintainer)[ \t]*[:\-–]?[ \t]+"
                 r"([A-Z][a-zA-Z'’.-]+(?:[ \t]+(?:[A-Z]\.|[A-Z][a-zA-Z'’-]+)){1,3})")
PAIR = re.compile(r"\b([A-Z][a-z]+)[ \t]+(?:[A-Z]\.[ \t]+)?([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b")
# capitalised words after a first name that are not surnames in these documents
NOT_SURNAME = set('''game games design document documents engine studio studios edition mode level levels island kingdom city world
quest story stories system systems unity unreal godot version update map maps menu team project player players character
characters boss enemy enemies weapon weapons item items power powers point points day days night year years act chapter
part section page table figure screen scene scenes room rooms house forest castle tower dungeon mountain river lake sea
park street road station school university college company inc ltd llc corp foundation institute press media entertainment
interactive software games'''.split())
EMAIL = re.compile(r'\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b')
_FIRSTS = None


def firsts():
    global _FIRSTS
    if _FIRSTS is None:
        try:
            p = Path(__file__).resolve().parent.parent / 'fdocs' / 'first_names.txt'
            _FIRSTS = {ln.strip().lower() for ln in p.read_text(encoding='utf-8').splitlines() if ln and not ln.startswith('#')}
        except OSError:
            _FIRSTS = set()
    return _FIRSTS


def common(word, threshold=3.2):
    try:
        from wordfreq import zipf_frequency
        return zipf_frequency(word.lower(), 'en') >= threshold
    except Exception:  # noqa: BLE001
        return False


class Names:
    """Per-repository / per-dataset numbering. key -> label; emails follow their person's number."""

    def __init__(self, width=3):
        self.width, self.label, self.order = width, {}, []

    def get(self, key, alias=()):
        k = key.strip().lower()
        if not k:
            return key
        if k not in self.label:
            for a in alias:
                if a.strip().lower() in self.label:
                    self.label[k] = self.label[a.strip().lower()]
                    break
            else:
                self.order.append(k)
                self.label[k] = f'Contributor {len(self.order):0{self.width}d}'
        for a in alias:
            if a.strip():
                self.label.setdefault(a.strip().lower(), self.label[k])
        return self.label[k]

    def email(self, label):
        return f'{label.lower().replace(" ", "")}@users.invalid'

    def known(self):
        """Names worth replacing in free text: two or more words, or a single distinctive handle."""
        return {k: v for k, v in self.label.items() if '@' not in k and len(k) >= 4 and (' ' in k or not common(k))}


def text(s, names, find_people=True, handles=False):
    """Replaces known names, e-mails and (optionally) detected person names in s."""
    if not s:
        return s
    known = names.known()
    for k in sorted(known, key=len, reverse=True):
        if ' ' in k or handles:
            s = re.sub(r'(?i)(?<![\w@])' + re.escape(k) + r'(?![\w])', known[k], s)

    def mail(m):
        e = m.group(0)
        if e.lower().endswith('@users.invalid'):
            return e
        lab = names.label.get(e.lower()) or names.get(e)
        return names.email(lab)
    if find_people:
        def cue(m):
            who = m.group(1)
            if who.startswith('Contributor ') or common(who.split()[0]) and not who.split()[0].lower() in firsts():
                return m.group(0)
            return m.group(0).replace(who, names.get(who))
        s = CUE.sub(cue, s)

        def pair(m):
            first, last = m.group(1), m.group(2)
            if (first.lower() in firsts() and first != 'Contributor' and last.lower() not in NOT_SURNAME
                    and not common(last, 4.6)):
                return names.get(m.group(0))
            return m.group(0)
        s = PAIR.sub(pair, s)
    return EMAIL.sub(mail, s)  # after the names, so people are numbered before stand-alone addresses


# ---------------------------------------------------------------- git history
def identities(repo):
    """(name, email) pairs of authors, committers and taggers in order of first appearance."""
    run = lambda *a: subprocess.run(['git', *a], cwd=repo, capture_output=True, text=True, errors='replace').stdout  # noqa: E731
    seen, out = set(), []
    for ln in run('log', '--all', '--reverse', '--format=%aN%x09%aE%n%cN%x09%cE').splitlines() + \
            run('for-each-ref', 'refs/tags', '--format=%(taggername)%09%(taggeremail:trim)').splitlines():
        if '\t' not in ln:
            continue
        n, e = ln.split('\t', 1)
        e = e.strip('<>')
        if (n, e) not in seen and (n or e):
            seen.add((n, e))
            out.append((n, e))
    return out


def plan(repo):
    """Name and e-mail maps for a repository: one Contributor number per person (linked by name or e-mail)."""
    ids = [(n, e) for n, e in identities(repo) if not BOT.search(n) and not BOT.search(e)]
    people = len({n.lower() for n, _ in ids})
    names = Names(4 if people > 999 else 3)
    for n, e in ids:
        names.get(n or e, alias=[e] if e else ())
    nm = {n: names.label[(n or e).lower()] for n, e in ids if n}
    em = {e: names.email(names.label[e.lower()]) for n, e in ids if e}
    return names, nm, em


def rewrite_repo(repo):
    """Rewrites the whole history of the bare clone at repo in place. Returns the Names used (len(names.order) people)."""
    names, nm, em = plan(repo)
    if not names.order:
        return names
    spec = Path(repo) / 'pseudonyms.json'
    spec.write_text(json.dumps({'names': nm, 'emails': em, 'known': names.known(), 'width': names.width}), encoding='utf-8')
    r = subprocess.run([sys.executable, '-I', __file__, str(repo), str(spec)], capture_output=True, text=True, errors='replace')
    spec.unlink(missing_ok=True)
    if r.returncode:
        raise RuntimeError('history rewrite failed: ' + (r.stderr or '')[-300:])
    return names


def _filter(repo, spec):
    """Runs git-filter-repo in the repository (separate process: filter-repo works on the current directory)."""
    import git_filter_repo as fr
    sp = json.loads(Path(spec).read_text(encoding='utf-8'))
    nm = {k.encode(): v.encode() for k, v in sp['names'].items()}
    em = {k.encode(): v.encode() for k, v in sp['emails'].items()}
    names = Names(sp['width'])
    names.label = {k: v for k, v in sp['known'].items()}
    names.order = sorted(set(names.label.values()))
    pats = [(re.compile(rb'(?i)(?<![\w@])' + re.escape(k.encode()) + rb'(?![\w])'), v.encode())
            for k, v in sorted(sp['known'].items(), key=lambda kv: -len(kv[0])) if ' ' in k]
    pats += [(re.compile(rb'(?i)(?<![\w.+-])' + re.escape(k) + rb'(?![\w.-])'), v) for k, v in em.items() if b'@' in k]
    handle_pats = [(re.compile(rb'(?i)(?<![\w@/])' + re.escape(k.encode()) + rb'(?![\w])'), v.encode())
                   for k, v in sp['known'].items() if ' ' not in k]
    credit = re.compile(rb'(?i)(?:^|/)(?:readme|authors?|contributors?|credits?|thanks|maintainers)(?:\.[^/]*)?$')
    memo = {}

    def sub(data, extra=()):
        for p, v in pats + list(extra):
            data = p.sub(v, data)
        return data

    def file_info(filename, mode, blob_id, value):
        if LICENCE_FILE.search(filename.decode('utf-8', 'replace')) or mode in (b'120000', b'160000'):
            return (filename, mode, blob_id)
        key = (blob_id, bool(credit.search(filename)))
        if key not in memo:
            data = value.get_contents_by_identifier(blob_id)
            if len(data) > 2 * 2**20 or b'\0' in data[:8192]:
                memo[key] = blob_id
            else:
                new = sub(data, handle_pats if key[1] else ())
                memo[key] = blob_id if new == data else value.insert_file_with_contents(new)
        return (filename, mode, memo[key])

    os.chdir(repo)
    args = fr.FilteringOptions.parse_args(['--force', '--quiet', '--partial', '--replace-refs', 'delete-no-add'])
    fr.RepoFilter(args, name_callback=lambda n: nm.get(n, n), email_callback=lambda e: em.get(e, e),
                  message_callback=lambda m: sub(m), file_info_callback=file_info).run()


# ---------------------------------------------------------------- documents
def document(path, ext, names, handles=False):
    """Pseudonymises a design document in place. Returns True when anything changed."""
    path, ext = Path(path), ext.lower().lstrip('.')
    if ext in ('md', 'txt', 'csv', 'markdown', 'rst'):
        raw = path.read_text(encoding='utf-8', errors='replace')
        new = text(raw, names, handles=handles)
        if new != raw:
            path.write_text(new, encoding='utf-8')
        return new != raw
    if ext == 'docx':
        changed, tmp = False, path.with_suffix('.tmp')
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
            for it in zin.infolist():
                data = zin.read(it.filename)
                if it.filename.startswith('word/') and it.filename.endswith('.xml') or it.filename == 'docProps/core.xml':
                    s = data.decode('utf-8', 'replace')
                    if it.filename == 'docProps/core.xml':
                        s = re.sub(r'(<(dc:creator|cp:lastModifiedBy)>)([^<]*)(</\2>)',
                                   lambda m: m.group(1) + (names.get(m.group(3)) if m.group(3).strip() else '') + m.group(4), s)
                    # text runs only (between tags), so the XML stays valid
                    s2 = re.sub(r'>([^<]+)<', lambda m: '>' + text(m.group(1), names, handles=handles) + '<', s)
                    changed |= s2 != data.decode('utf-8', 'replace')
                    data = s2.encode('utf-8')
                zout.writestr(it, data)
        tmp.replace(path)
        return changed
    if ext == 'pdf':
        import fitz
        doc = fitz.open(path)
        hits = 0
        for page in doc:
            found = {}
            t = page.get_text()
            text(t, names)  # registers the people in this page, in order
            for k, lab in names.known().items():
                if ' ' in k:
                    for rect in page.search_for(k):
                        found.setdefault(lab, []).append(rect)
            for e in set(EMAIL.findall(t)):
                for rect in page.search_for(e):
                    found.setdefault(names.email(names.label.get(e.lower()) or names.get(e)), []).append(rect)
            for lab, rects in found.items():
                for rect in rects:
                    page.add_redact_annot(rect, text=lab, fontsize=max(4, min(11, rect.height * 0.7)), fill=(1, 1, 1))
                    hits += 1
            if found:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        meta = doc.metadata or {}
        if meta.get('author'):
            meta['author'] = names.get(meta['author'])
            hits += 1
        if hits:
            doc.set_metadata(meta)
            tmp = path.with_suffix('.tmp.pdf')
            doc.save(tmp, garbage=3, deflate=True)
            doc.close()
            tmp.replace(path)
        else:
            doc.close()
        return bool(hits)
    return False


if __name__ == '__main__':
    _filter(sys.argv[1], sys.argv[2])
