"""Study library over the energy-trading company e-mail corpus that the "How Companies Work" collector uploads
(src_enron.py: '<corpus>/<mailbox owner>/Emails part NNN.zip', one .eml per message).

Each run (GitHub Actions, every 3 hours, .github/workflows/enron-study.yml):
  1. collects the Message Batches submitted by earlier runs that have ended (cost from each result's usage);
  2. writes, into each mailbox folder whose results changed, "Study index.csv" (one row per e-mail) and
     "How this mailbox works.md", and into the corpus folder "Study index - all mailboxes.csv" (updated in place);
  3. reads the e-mail zips that are new since the last run and submits one Haiku request per e-mail
     (business area, 2-4 topic tags, a one-line summary, what it shows about how the company works, whether it
     records a decision; structured JSON output); trivial e-mails are listed but not sent;
  4. submits a Sonnet request per mailbox whose e-mails are all tagged (chunk notes first for big mailboxes) for
     the "How <owner> works" page.

Cost control: the running total (from usage, at batch prices) and every batch id are kept in
'How Companies Work - private/enron-study.json.gz'. A batch is never submitted when the projected total (spent +
estimated cost of pending batches + this batch) would pass STUDY_BUDGET_USD (default 50); STUDY_RESERVE_USD of it
(default 12) is kept for the mailbox pages. New batches are submitted only before STUDY_END (default 2026-11-02, UTC;
the API credit expires then); later runs only log that the credit window has ended. So that the budget reaches every
mailbox, a first pass sends at most STUDY_MAILBOX_CAP e-mails (default 3000) per mailbox; the rest follows once no
mailbox under the cap is waiting, or from STUDY_UNCAP_AFTER (default 2026-11-01).

Environment: ANTHROPIC_API_KEY, GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN, SHARED_DRIVE_ID,
STUDY_BUDGET_USD, STUDY_RESERVE_USD, STUDY_END, STUDY_MAX_ITEMS (new e-mails per run), STUDY_RUN_MINUTES.
Never exits with an error (the user wants no failure e-mails): problems are logged, saved state carries over.
"""
import csv
import email
import email.policy
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import traceback
import zipfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

HAIKU = 'claude-haiku-5-5'
SONNET = 'claude-sonnet-5-5'
PRICE = {HAIKU: (0.05, 0.25), SONNET: (1.0, 5.0)}  # $ per million tokens, batch prices (input, output)
AREAS = ['trading', 'risk', 'legal/regulatory', 'accounting/finance', 'deals/M&A', 'operations', 'HR/people', 'IT',
         'external relations', 'personal/other']
CORPUS = 'Energy Trading Company Corpus'
STATE = 'enron-study.json.gz'  # in the private folder (not 'state-*': main.py reads those as collector states)
RESULTS = 'Enron study results'  # private sub-folder: <mailbox>.json.gz per mailbox
INDEX_NAME, PAGE_NAME, ALL_NAME = 'Study index.csv', 'How this mailbox works.md', 'Study index - all mailboxes.csv'
BODY_CHARS = 4000
QUOTED_CHARS = 1500  # of earlier, quoted messages when the e-mail has its own text
CHARS_PER_TOKEN = 3.2  # the 5.x tokenizer counts ~30% more tokens than the old ~4 characters per token
BATCH_ITEMS = 20000
CHUNK_LINES = int(os.environ.get('STUDY_CHUNK_LINES') or 750)  # e-mail lines per Sonnet request
MAX_LINES = int(os.environ.get('STUDY_MAX_LINES') or 1500)  # lines per mailbox page (decisions first, then spread)
SETTLE_HOURS = 3  # a mailbox page waits until its newest zip is this old (its other parts come in the same run)
START = time.time()

TAG_SYSTEM = """You catalogue e-mails from the Enron e-mail corpus (an energy-trading company, 1998-2002) for a study \
library on how companies work. For the e-mail given, fill in:
- area: the business area it belongs to. Use "personal/other" for private or social mail, newsletters, \
mass mailings and spam.
- tags: 2 to 4 short lowercase topic tags of 1-3 words (e.g. "gas trading", "credit limits", "california power \
crisis", "deal approval").
- summary: one line of at most 25 words saying what happens or who asks whom for what; keep concrete names, \
deals, places, amounts and dates.
- operations: one sentence on what the e-mail shows about how the company works (processes, controls, approvals, \
reporting lines, systems, culture); an empty string when it shows nothing of that.
- decision: true only when the e-mail records a decision or an approval actually made or given (not just asked \
for or discussed).
Write in plain English. Base everything on the e-mail only."""

TAG_SCHEMA = {
    'type': 'object',
    'properties': {
        'area': {'type': 'string', 'enum': AREAS},
        'tags': {'type': 'array', 'items': {'type': 'string'}},
        'summary': {'type': 'string'},
        'operations': {'type': 'string'},
        'decision': {'type': 'boolean'},
    },
    'required': ['area', 'tags', 'summary', 'operations', 'decision'],
    'additionalProperties': False,
}

PAGE_SYSTEM = """You write study notes on how people worked at Enron, from catalogued e-mails of one mailbox \
(each line: date | from | area | D when it records a decision | summary | what it shows about how the company \
works). Be factual and specific; give dates (month and year at least) for events and decisions; name people and \
desks as they appear; do not invent anything the lines do not support; say so when the evidence is thin."""

NOTES_TASK = """These are lines {first}-{last} of {total} from the mailbox of {owner}. Write compact notes (at most \
600 words, bullet points) for a later write-up: role and desk; main counterparts (inside and outside the company) \
and what they deal with; recurring processes and routines; decisions and approvals (with dates); notable events \
(with dates)."""

PAGE_TASK = """Write a Markdown page "How {owner} works" (one to two pages, 700-1100 words) about the mailbox of \
{owner} ({n} catalogued e-mails, {span}; areas: {areas}; {decisions} e-mails record a decision or approval). \
Sections: ## Role, ## Counterparts, ## Recurring processes, ## Decisions and approvals, ## Notable events \
(a dated list), ## What this mailbox shows about how the company works. Start with the "# How {owner} works" title \
and a one-sentence overview. Output only the Markdown."""

QUOTE = re.compile(r'^\s*(-{3,}\s*(Original Message|Forwarded by)|_{5,}|From: .+ on \d|>|On .+ wrote:)',
                   re.M | re.I)


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


# --- e-mails -----------------------------------------------------------------------------------------------------
def _clean(v, n=300):
    return re.sub(r'\s+', ' ', str(v or '')).strip()[:n]


def parse_eml(raw):
    """(headers dict, body text) of one .eml written by src_enron.py."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body = ''
    try:
        part = msg.get_body(preferencelist=('plain', 'html'))
        body = part.get_content() if part else ''
    except Exception:  # noqa: BLE001
        payload = msg.get_payload(decode=True) or b''
        body = payload.decode('utf-8', 'replace') if isinstance(payload, bytes) else str(payload)
    h = {k: _clean(msg.get(k), 600 if k in ('To', 'Cc') else 300) for k in
         ('From', 'To', 'Cc', 'Date', 'Subject', 'X-Attachments')}
    try:
        h['iso'] = parsedate_to_datetime(h['Date']).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M') \
            if h['Date'] else ''
    except Exception:  # noqa: BLE001
        h['iso'] = ''
    return h, body.replace('\r\n', '\n')


def cut_body(body):
    """The e-mail's own text first (up to BODY_CHARS), then some of the quoted earlier messages."""
    body = re.sub(r'\n{3,}', '\n\n', body.strip())
    m = QUOTE.search(body)
    own, quoted = (body[:m.start()], body[m.start():]) if m else (body, '')
    text = own[:BODY_CHARS]
    room = BODY_CHARS - len(text)
    if room > 0 and quoted:
        text += '\n' + quoted[:room if len(own.strip()) < 200 else min(room, QUOTED_CHARS)]
    return text.strip(), own.strip()


def trivial(h, body):
    """Nothing to study: an empty or near-empty e-mail without attachments ('thanks', 'ok', a bare forward)."""
    return len(re.findall(r'\w+', body)) < 5 and not h.get('X-Attachments')


def user_text(h, text):
    lines = [f'From: {h["From"]}', f'To: {h["To"]}']
    if h.get('Cc'):
        lines.append(f'Cc: {h["Cc"]}')
    lines += [f'Date: {h["Date"]}', f'Subject: {h["Subject"]}']
    if h.get('X-Attachments'):
        lines.append(f'Attachments: {h["X-Attachments"]}')
    return '\n'.join(lines) + '\n\n' + text


def mail_key(h, text):
    return hashlib.sha1(f'{h["From"]}|{h["Date"]}|{h["Subject"]}|{text}'.encode('utf-8', 'replace')).hexdigest()[:14]


def _natural(path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', path)]


def zip_items(path):
    """Every e-mail of a zip, in a fixed order: (path in zip, headers, cut body, is trivial)."""
    out = []
    with zipfile.ZipFile(path) as z:
        for name in sorted((n for n in z.namelist() if n.lower().endswith('.eml')), key=_natural):
            try:
                h, body = parse_eml(z.read(name))
            except Exception:  # noqa: BLE001
                continue
            text, own = cut_body(body)
            out.append((name, h, text, trivial(h, body)))
    return out


# --- requests and cost -------------------------------------------------------------------------------------------
def tag_params(utext):
    return {'model': HAIKU, 'max_tokens': 2000, 'system': TAG_SYSTEM,
            'output_config': {'effort': 'low', 'format': {'type': 'json_schema', 'schema': TAG_SCHEMA}},
            'messages': [{'role': 'user', 'content': utext}]}


def page_params(system_task, lines_text, max_tokens):
    return {'model': SONNET, 'max_tokens': max_tokens, 'system': PAGE_SYSTEM,
            'output_config': {'effort': 'medium'},
            'messages': [{'role': 'user', 'content': f'{system_task}\n\n<emails>\n{lines_text}\n</emails>'}]}


TAG_OVERHEAD = len(TAG_SYSTEM) + len(json.dumps(TAG_SCHEMA))  # characters
EST_OUT = {HAIKU: 180, SONNET: 4500}  # output tokens per request (thinking included), measured 2026-10-29


def estimate(params, calib=1.0):
    """Projected $ of one request: input at CHARS_PER_TOKEN characters a token, output at the measured average."""
    chars = len(params['system']) + sum(len(m['content']) for m in params['messages'])
    if params['model'] == HAIKU:
        chars += len(json.dumps(TAG_SCHEMA)) + 600  # structured-output system text
    pin, pout = PRICE[params['model']]
    return (chars / CHARS_PER_TOKEN * pin + EST_OUT[params['model']] * pout) / 1e6 * calib


def cost(model, usage):
    pin, pout = PRICE[model]
    u = lambda k: getattr(usage, k, 0) or 0  # noqa: E731
    return (u('input_tokens') * pin + u('cache_creation_input_tokens') * pin * 1.25
            + u('cache_read_input_tokens') * pin * 0.1 + u('output_tokens') * pout) / 1e6


def text_of(msg):
    return ''.join(b.text for b in msg.content if b.type == 'text')


def read_tags(msg):
    """The structured answer as a row fragment, or None when it is unusable (refusal, cut off)."""
    try:
        d = json.loads(text_of(msg))
    except (ValueError, TypeError):
        return None
    tags = [re.sub(r'\s+', ' ', str(t)).strip().lower() for t in d.get('tags') or [] if str(t).strip()][:4]
    return {'area': d.get('area') if d.get('area') in AREAS else 'personal/other', 'tags': tags,
            'summary': _clean(d.get('summary'), 400), 'ops': _clean(d.get('operations'), 500),
            'decision': bool(d.get('decision'))}


# --- mailbox pages ------------------------------------------------------------------------------------------------
def row_line(r):
    return ' | '.join([r['date'][:10] or '?', r['from'][:60], r['area'], 'D' if r['decision'] else '',
                       r['summary'], r['ops']])


def pick_lines(rows):
    """Tagged, non-personal rows for the page (all of them up to MAX_LINES: decisions and operations notes first,
    the rest spread evenly), in date order."""
    good = [r for r in rows if r.get('area') and r['area'] != 'personal/other']
    if len(good) > MAX_LINES:
        first = [r for r in good if r['decision'] or r['ops']]
        rest = [r for r in good if not (r['decision'] or r['ops'])]
        if len(first) > MAX_LINES:
            step = len(first) / MAX_LINES
            first = [first[int(i * step)] for i in range(MAX_LINES)]
        room = MAX_LINES - len(first)
        if room > 0 and rest:
            step = len(rest) / room
            rest = [rest[int(i * step)] for i in range(min(room, len(rest)))]
        else:
            rest = []
        good = first + rest
    return sorted(good, key=lambda r: (r['date'] or '9', r['part'], _natural(r['path'])))


def page_facts(owner, rows):
    tagged = [r for r in rows if r.get('area')]
    dates = sorted(r['date'][:7] for r in tagged if r['date'])
    span = f'{dates[0]} to {dates[-1]}' if dates else 'dates unknown'
    counts = {}
    for r in tagged:
        counts[r['area']] = counts.get(r['area'], 0) + 1
    areas = ', '.join(f'{a} {n}' for a, n in sorted(counts.items(), key=lambda x: -x[1]))
    return {'owner': owner, 'n': len(tagged), 'span': span, 'areas': areas or 'none',
            'decisions': sum(1 for r in tagged if r['decision'])}


# --- CSV ----------------------------------------------------------------------------------------------------------
COLS = ['zip part', 'file path in zip', 'date', 'from', 'subject', 'area', 'tags', 'summary', 'operations note',
        'decision']


def csv_rows(rows, mailbox=None):
    for r in sorted(rows, key=lambda r: (r['part'], _natural(r['path']))):
        v = [r['part'], r['path'], r['date'], r['from'], r['subject'], r.get('area', ''), '; '.join(r.get('tags', [])),
             r.get('summary', ''), r.get('ops', ''), 'yes' if r.get('decision') else '']
        yield ([mailbox] + v) if mailbox is not None else v


def write_csv(path, header, rows):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


# --- the run ------------------------------------------------------------------------------------------------------
class Study:
    def __init__(self):
        import anthropic
        from .drive import Drive
        self.client = anthropic.Anthropic(max_retries=4)
        self.drive = Drive('enron-study')
        self.svc = self.drive.svc
        self.st = self.drive.load(STATE, {})
        for k, v in (('spent', 0.0), ('batches', {}), ('done_batches', []), ('zips', {}), ('mail', {}),
                     ('seen', {}), ('retry', []), ('calib', {}), ('runs', [])):
            self.st.setdefault(k, v)
        self.results_folder = self.drive.folder(self.drive.private, RESULTS, create=True)
        self.cache = {}  # mailbox -> results dict (loaded on demand)
        self.dirty = set()
        self.budget = float(os.environ.get('STUDY_BUDGET_USD') or 50)
        self.reserve = float(os.environ.get('STUDY_RESERVE_USD') or 12)
        self.max_items = int(os.environ.get('STUDY_MAX_ITEMS') or 60000)
        # First pass: at most this many e-mails sent per mailbox, so the budget reaches every mailbox; the rest
        # once no mailbox under the cap is waiting (and nothing new came for SETTLE_HOURS), or from STUDY_UNCAP_AFTER.
        self.cap = int(os.environ.get('STUDY_MAILBOX_CAP') or 3000)
        self.uncap_after = os.environ.get('STUDY_UNCAP_AFTER') or '2026-11-01'
        self.uncapped = False
        self.minutes = float(os.environ.get('STUDY_RUN_MINUTES') or 80)
        self.work = tempfile.mkdtemp(prefix='enron_study_')
        self.run_log = {'at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'), 'collected': 0.0,
                        'submitted': 0}

    # state and per-mailbox results
    def save(self):
        """Saves the changed per-mailbox results, then the state (which points into them)."""
        for mbx in sorted(self.dirty):
            self.save_results(mbx)
        self.dirty.clear()
        self.drive.save(STATE, self.st)

    def results(self, mbx):
        if mbx not in self.cache:
            from .drive import _q
            from models.store import _retry
            q = f"name = '{_q(mbx)}.json.gz' and '{self.results_folder}' in parents and trashed = false"
            found = _retry(lambda: self.drive.drive.files().list(q=q, fields='files(id)').execute())['files']
            data = {'rows': [], 'notes': {}, 'page': ''}
            if found:
                self.cache.setdefault('_ids', {})[mbx] = found[0]['id']
                data = json.loads(gzip.decompress(_retry(
                    lambda: self.drive.drive.files().get_media(fileId=found[0]['id']).execute())))
            self.cache[mbx] = data
        return self.cache[mbx]

    def save_results(self, mbx):
        from googleapiclient.http import MediaIoBaseUpload
        from models.store import _retry
        raw = gzip.compress(json.dumps(self.cache[mbx], separators=(',', ':')).encode())
        media = MediaIoBaseUpload(io.BytesIO(raw), mimetype='application/gzip', resumable=False)
        fid = self.cache.setdefault('_ids', {}).get(mbx)
        if fid:
            _retry(lambda: self.drive.drive.files().update(fileId=fid, media_body=media).execute())
        else:
            self.cache['_ids'][mbx] = _retry(lambda: self.drive.drive.files().create(
                body={'name': f'{mbx}.json.gz', 'parents': [self.results_folder]}, media_body=media,
                fields='id').execute())['id']

    def projected(self):
        return self.st['spent'] + sum(b['est'] for b in self.st['batches'].values())

    def left(self):
        return self.minutes * 60 - (time.time() - START)

    # 1. collect ended batches
    def collect(self):
        for bid, b in list(self.st['batches'].items()):
            try:
                batch = self.client.messages.batches.retrieve(bid)
            except Exception as e:  # noqa: BLE001
                log(f'batch {bid}: could not check ({type(e).__name__}: {str(e)[:200]})')
                continue
            rc = batch.request_counts
            if batch.processing_status != 'ended':
                log(f'batch {bid} ({b["kind"]}, {len(b["items"])} requests): {batch.processing_status}, '
                    f'{rc.processing} processing, {rc.succeeded} succeeded')
                continue
            spent, ok, bad = 0.0, 0, 0
            for res in self.client.messages.batches.results(bid):
                meta = b['items'].get(res.custom_id)
                if meta is None:
                    continue
                if res.result.type == 'succeeded':
                    msg = res.result.message
                    spent += cost(msg.model if msg.model in PRICE else (HAIKU if b['kind'] == 'tag' else SONNET),
                                  msg.usage)
                    ok += self.apply(b['kind'], meta, msg)
                else:
                    bad += 1
                    if b['kind'] == 'tag' and not meta.get('retried'):
                        meta['retried'] = True
                        self.st['retry'].append(meta)
                    elif b['kind'] == 'tag':
                        self.apply_failed(meta, f'not tagged ({res.result.type})')
                    else:
                        self.st['mail'][meta['mbx']].pop('stage', None)  # the page is tried again next run
            est = b['est']
            if est > 0 and spent > 0:
                c = self.st['calib'].get(b['kind'], 1.0)
                self.st['calib'][b['kind']] = round(0.5 * c + 0.5 * spent / est * c, 4)
            self.st['spent'] = round(self.st['spent'] + spent, 6)
            self.run_log['collected'] += spent
            del self.st['batches'][bid]
            self.st['done_batches'].append({'id': bid, 'kind': b['kind'], 'n': len(b['items']),
                                            'est': round(est, 4), 'cost': round(spent, 4)})
            self.save()
            log(f'batch {bid} ({b["kind"]}): {ok} used, {bad} failed; cost ${spent:.4f} (estimated ${est:.4f})')

    def apply(self, kind, meta, msg):
        if kind == 'tag':
            got = read_tags(msg)
            if not got:
                self.apply_failed(meta, f'not tagged ({msg.stop_reason})')
                return 0
            for t in meta['t']:
                self.add_row(t, got)
            return 1
        mbx = meta['mbx']
        m = self.st['mail'][mbx]
        text = text_of(msg).strip()
        if msg.stop_reason != 'end_turn' or not text:
            m.pop('stage', None)
            return 0
        res = self.results(mbx)
        if kind == 'notes':
            res['notes'][str(meta['chunk'])] = text
            self.dirty.add(mbx)
            if len(res['notes']) >= meta['chunks']:
                m['stage'] = 'final'  # all chunk notes in: the page request goes out this run
            return 1
        res['page'] = text
        res['notes'] = {}
        m['paged_n'] = meta['n']
        m.pop('stage', None)
        m['page_dirty'] = True
        self.dirty.add(mbx)
        return 1

    def add_row(self, t, got):
        mbx = t['mbx']
        row = {k: t[k] for k in ('part', 'path', 'date', 'from', 'subject', 'k', 'zid')}
        row.update(got)
        self.results(mbx)['rows'].append(row)
        self.st['mail'][mbx]['index_dirty'] = True
        self.dirty.add(mbx)

    def apply_failed(self, meta, why):
        for t in meta['t']:
            self.add_row(t, {'area': '', 'tags': [], 'summary': f'({why})', 'ops': '', 'decision': False})

    # 2. publish
    def upload(self, local, parent, name, key, fid):
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
        from models.store import _retry
        mime = 'text/csv' if name.endswith('.csv') else 'text/markdown'
        big = os.path.getsize(local) > 5 * 2**20
        media = MediaFileUpload(local, mimetype=mime, resumable=big, chunksize=32 * 2**20 if big else -1)
        if not fid:  # an earlier upload whose id was lost
            from .drive import _q
            q = f"name = '{_q(name)}' and '{parent}' in parents and trashed = false"
            found = _retry(lambda: self.svc.files().list(q=q, fields='files(id)', supportsAllDrives=True,
                                                         includeItemsFromAllDrives=True).execute())['files']
            fid = found[0]['id'] if found else None
        if fid:
            try:
                meta = self.svc.files().get(fileId=fid, fields='trashed', supportsAllDrives=True).execute()
                if not meta.get('trashed'):
                    return _retry(lambda: self.svc.files().update(fileId=fid, media_body=media, fields='id',
                                                                  supportsAllDrives=True).execute())['id']
            except HttpError as e:
                if e.resp.status != 404:
                    raise
        body = {'name': name, 'parents': [parent],
                'appProperties': {'hcApp': 'howco', 'hcSrc': 'enron-study', 'hcKey': key[:100]}}
        return _retry(lambda: self.svc.files().create(body=body, media_body=media, fields='id',
                                                      supportsAllDrives=True).execute())['id']

    def publish(self):
        changed = False
        for mbx, m in sorted(self.st['mail'].items()):
            if not (m.get('index_dirty') or m.get('page_dirty')) or self.left() < 300:
                continue
            res = self.results(mbx)
            try:
                if m.get('index_dirty'):
                    p = os.path.join(self.work, 'index.csv')
                    write_csv(p, COLS, csv_rows(res['rows']))
                    m['index_id'] = self.upload(p, m['folder'], INDEX_NAME, f'study:{mbx}:index', m.get('index_id'))
                    m['index_dirty'] = False
                    changed = True
                if m.get('page_dirty') and res.get('page'):
                    p = os.path.join(self.work, 'page.md')
                    with open(p, 'w', encoding='utf-8') as f:
                        f.write(res['page'].rstrip() + f'\n\n---\n*Written by {SONNET} from {m.get("paged_n", 0)} '
                                f'catalogued e-mails of this mailbox (Study index.csv).*\n')
                    m['page_id'] = self.upload(p, m['folder'], PAGE_NAME, f'study:{mbx}:page', m.get('page_id'))
                    m['page_dirty'] = False
            except Exception as e:  # noqa: BLE001
                log(f'{mbx}: could not upload ({type(e).__name__}: {str(e)[:200]})')
        if changed or self.st.get('all_dirty'):
            self.st['all_dirty'] = True
            if self.left() < 600:
                log('corpus index: not enough time left; next run')
                return
            p = os.path.join(self.work, 'all.csv')
            n = 0
            with open(p, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(['mailbox'] + COLS)
                for mbx, m in sorted(self.st['mail'].items(), key=lambda x: x[1].get('owner', x[0])):
                    rows = self.results(mbx)['rows']
                    w.writerows(csv_rows(rows, m.get('owner', mbx)))
                    n += len(rows)
                    if mbx not in self.dirty:
                        self.cache.pop(mbx, None)  # keep memory low (saved already)
                        self.cache.get('_kidx', {}).pop(mbx, None)
            folder = self.st.get('corpus_folder')
            if folder:
                self.st['all_id'] = self.upload(p, folder, ALL_NAME, 'study:all', self.st.get('all_id'))
                self.st['all_dirty'] = False
                log(f'corpus index: {n:,} e-mails over {len(self.st["mail"])} mailboxes')
        self.save()

    # 3. new zips -> tagging batch
    def zips(self):
        from models.store import _retry
        from .drive import _SharedDrive
        q = ("appProperties has { key='hcApp' and value='howco' } and "
             "appProperties has { key='hcSrc' and value='enron' } and trashed = false and mimeType = 'application/zip'")
        out = []
        for d in self.drive.drive_ids():
            drv = self.drive.drive if d == self.drive.top else _SharedDrive(self.svc, d)
            token = None
            while True:
                res = _retry(lambda: drv.files().list(
                    q=q, pageSize=1000, pageToken=token,
                    fields='nextPageToken, files(id, name, parents, appProperties, md5Checksum, createdTime, size)'
                ).execute())
                for f in res.get('files', []):
                    k = f.get('appProperties', {}).get('hcKey', '')
                    if k.startswith('emails:'):
                        _, mbx, part = k.split(':', 2)
                        out.append(dict(f, mbx=mbx, part=part))
                token = res.get('nextPageToken')
                if not token:
                    break
        return sorted(out, key=lambda f: (f['mbx'], f['part']))

    def mailbox(self, f):
        m = self.st['mail'].get(f['mbx'])
        if not m:
            folder = f['parents'][0]
            meta = self.svc.files().get(fileId=folder, fields='name, parents', supportsAllDrives=True).execute()
            m = self.st['mail'][f['mbx']] = {'owner': meta['name'], 'folder': folder, 'id': len(self.st['mail'])}
            if not self.st.get('corpus_folder') and meta.get('parents'):
                self.st['corpus_folder'] = meta['parents'][0]
        m['newest'] = max(m.get('newest', ''), f['createdTime'])
        return m

    def forget_trashed(self, files):
        """Zips indexed earlier that are gone (trashed, replaced): their rows go."""
        live = {f['id']: f.get('md5Checksum') for f in files}
        gone = [z for z, info in self.st['zips'].items() if live.get(z, '-') != info.get('md5')]
        for z in gone:
            info = self.st['zips'].pop(z)
            mbx = info['mbx']
            if mbx in self.st['mail']:
                res = self.results(mbx)
                res['rows'] = [r for r in res['rows'] if r.get('zid') != z]
                self.st['mail'][mbx]['index_dirty'] = True
                self.dirty.add(mbx)
        if gone:
            log(f'{len(gone)} zip(s) indexed earlier are gone or changed: their rows were removed')

    def download(self, fid):
        """Every e-mail of a zip on the drive (see zip_items); the last one read is kept for this run."""
        if self.cache.get('_zip', (None,))[0] == fid:
            return self.cache['_zip'][1]
        from googleapiclient.http import MediaIoBaseDownload
        local = os.path.join(self.work, 'z.zip')
        with open(local, 'wb') as fh:
            dl = MediaIoBaseDownload(fh, self.svc.files().get_media(fileId=fid, supportsAllDrives=True),
                                     chunksize=32 * 2**20)
            done = False
            while not done:
                _, done = dl.next_chunk()
        items = zip_items(local)
        os.remove(local)
        self.cache['_zip'] = (fid, items)
        return items

    def tag_new(self, files, can_submit):
        pending_keys = {meta['k']: meta for b in self.st['batches'].values() if b['kind'] == 'tag'
                        for meta in b['items'].values()}
        limit_usd = self.budget - self.reserve
        calib = max(0.7, min(3.0, self.st['calib'].get('tag', 1.0)))
        cur = {'reqs': [], 'metas': {}, 'est': 0.0}
        stopped, n_trivial, n_dup = None, 0, 0

        def submit():
            if cur['reqs']:
                self.send('tag', cur['reqs'], cur['metas'], cur['est'])
            cur.update(reqs=[], metas={}, est=0.0)

        def add(cid, params, meta):
            e = estimate(params, calib)
            if self.projected() + cur['est'] + e > limit_usd:
                return False
            cur['reqs'].append({'custom_id': cid, 'params': params})
            cur['metas'][cid] = meta
            cur['est'] += e
            pending_keys[meta['k']] = meta
            if len(cur['reqs']) >= BATCH_ITEMS:
                submit()
            return True

        # requests that failed (or could not be submitted) earlier: read again from their zips
        retry, self.st['retry'] = self.st['retry'], []
        live = {f['id'] for f in files}
        for j, meta in enumerate(sorted(retry, key=lambda m: m['t'][0]['zid'])):
            t0 = meta['t'][0]
            if t0['zid'] not in live:
                continue
            if not can_submit or self.left() < 600:
                self.st['retry'].append(meta)
                continue
            try:
                item = next((x for x in self.download(t0['zid']) if x[0] == t0['path']), None)
            except Exception as e:  # noqa: BLE001
                log(f'retry: could not read a zip ({type(e).__name__})')
                self.st['retry'].append(meta)
                continue
            if not item:
                continue
            if not add(f'r{j}-{int(time.time())}', tag_params(user_text(item[1], item[2])), meta):
                self.st['retry'].append(meta)

        now = datetime.now(timezone.utc)
        waiting = [f for f in files if not (self.st['zips'].get(f['id']) and
                                            self.st['zips'][f['id']]['next'] >= self.st['zips'][f['id']]['n'])]
        under = [f for f in waiting if self.st['mail'].get(f['mbx'], {}).get('sent', 0) < self.cap]
        newest = max((f['createdTime'] for f in files), default='2000-01-01T00:00:00')
        quiet = (now - datetime.strptime(newest[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
                 ).total_seconds() > SETTLE_HOURS * 3600
        self.uncapped = now.strftime('%Y-%m-%d') >= self.uncap_after or (not under and quiet)
        held = 0
        for f in files:
            info = self.st['zips'].get(f['id'])
            if info and info['next'] >= info['n']:
                continue
            m = self.mailbox(f)
            if not self.uncapped and m.get('sent', 0) >= self.cap:
                held += 1
                continue
            if not can_submit:
                stopped = 'credit window or collector not ready'
                continue
            if self.left() < 600:
                stopped = 'run time'
                break
            if self.run_log['submitted'] + len(cur['reqs']) >= self.max_items:
                stopped = f'{self.max_items:,} e-mails a run'
                break
            try:
                items = self.download(f['id'])
            except Exception as e:  # noqa: BLE001
                log(f'{f["mbx"]} part {f["part"]}: could not read ({type(e).__name__}: {str(e)[:200]})')
                continue
            info = self.st['zips'].setdefault(f['id'], {'mbx': f['mbx'], 'part': f['part'],
                                                         'md5': f.get('md5Checksum'), 'n': len(items), 'next': 0})
            i = info['next']
            while i < len(items):
                path, h, text, triv = items[i]
                target = {'mbx': f['mbx'], 'part': f['part'], 'path': path, 'date': h['iso'], 'from': h['From'],
                          'subject': h['Subject'], 'zid': f['id'], 'k': ''}
                if triv:
                    self.add_row(target, {'area': '', 'tags': [], 'summary': '(short message, not tagged)',
                                          'ops': '', 'decision': False})
                    n_trivial += 1
                    i += 1
                    continue
                k = target['k'] = mail_key(h, text)
                if k in pending_keys:  # the same e-mail waits in a batch (from another mailbox)
                    pending_keys[k]['t'].append(target)
                    n_dup += 1
                    i += 1
                    continue
                seen = self.st['seen'].get(k)
                if seen and seen in self.st['mail']:
                    kidx = self.cache.setdefault('_kidx', {})
                    if seen not in kidx:
                        kidx[seen] = {r['k']: r for r in self.results(seen)['rows'] if r.get('k') and r.get('area')}
                    src = kidx[seen].get(k)
                    if src:
                        self.add_row(target, {x: src[x] for x in ('area', 'tags', 'summary', 'ops', 'decision')})
                        n_dup += 1
                        i += 1
                        continue
                if self.run_log['submitted'] + len(cur['reqs']) >= self.max_items:
                    stopped = f'{self.max_items:,} e-mails a run'
                    break
                if not self.uncapped and m.get('sent', 0) >= self.cap:
                    held += 1
                    break
                if not add(f't{m["id"]}-{f["part"][-3:]}-{i}', tag_params(user_text(h, text)),
                           {'k': k, 't': [target]}):
                    stopped = f'budget (${limit_usd:.2f} for tagging)'
                    break
                self.st['seen'][k] = f['mbx']
                m['sent'] = m.get('sent', 0) + 1
                i += 1
                info['next'] = i
            info['next'] = i
            if stopped:
                break
        submit()
        if held:
            log(f'{held} zip(s) wait: their mailbox has {self.cap:,} e-mails sent (first pass; '
                f'the rest follows when every mailbox is covered or from {self.uncap_after})')
        if stopped:
            log(f'tagging stopped this run: {stopped}')
        log(f'tagging: {self.run_log["submitted"]:,} e-mails sent this run; {n_trivial:,} trivial e-mails listed '
            f'untagged; {n_dup:,} repeats of e-mails tagged for another mailbox reused')

    def send(self, kind, reqs, metas, est):
        try:
            batch = self.client.messages.batches.create(requests=reqs)
        except Exception as e:  # noqa: BLE001
            log(f'{kind} batch of {len(reqs)} could not be submitted ({type(e).__name__}: {str(e)[:300]})')
            if kind == 'tag':
                self.st['retry'].extend(metas.values())  # read again from their zips next run
            else:
                for meta in metas.values():
                    self.st['mail'][meta['mbx']].pop('stage', None)
            self.save()
            return
        self.st['batches'][batch.id] = {'kind': kind, 'est': round(est, 6), 'items': metas,
                                        'at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}
        if kind == 'tag':
            self.run_log['submitted'] += len(reqs)
        self.save()
        log(f'submitted {kind} batch {batch.id}: {len(reqs)} requests, estimated ${est:.4f}; '
            f'projected total ${self.projected():.2f} of ${self.budget:.2f}')

    # 4. mailbox pages
    def pages(self, can_submit):
        if not can_submit:
            return
        busy = set()
        for b in self.st['batches'].values():
            for meta in b['items'].values():
                busy |= {t['mbx'] for t in meta['t']} if b['kind'] == 'tag' else {meta['mbx']}
        now = datetime.now(timezone.utc)
        reqs, metas, est_total = [], {}, 0.0
        calib = max(0.7, min(3.0, self.st['calib'].get('page', 1.0)))
        for mbx, m in sorted(self.st['mail'].items()):
            if mbx in busy or any(t['mbx'] == mbx for meta in self.st['retry'] for t in meta['t']):
                continue
            unread = any(z['mbx'] == mbx and z.get('next', 0) < z.get('n', 0) for z in self.st['zips'].values())                 and (self.uncapped or m.get('sent', 0) < self.cap)
            if unread:
                continue
            newest = datetime.strptime(m.get('newest', '2000-01-01T00:00:00')[:19], '%Y-%m-%dT%H:%M:%S').replace(
                tzinfo=timezone.utc)
            if (now - newest).total_seconds() < SETTLE_HOURS * 3600:
                continue
            res = self.results(mbx)
            rows = res['rows']
            n = sum(1 for r in rows if r.get('area'))
            if n == 0 or (m.get('paged_n') and n < m['paged_n'] * 1.1 and m.get('stage') != 'final'):
                continue
            lines = [row_line(r) for r in pick_lines(rows)]
            if not lines:
                continue
            facts = page_facts(m['owner'], rows)
            chunks = [lines[i:i + CHUNK_LINES] for i in range(0, len(lines), CHUNK_LINES)]
            if len(chunks) == 1 or m.get('stage') == 'final':
                if len(chunks) == 1:
                    body = '\n'.join(chunks[0])
                else:
                    body = '\n\n'.join(f'Notes on lines {int(c) * CHUNK_LINES + 1}-'
                                       f'{min(len(lines), (int(c) + 1) * CHUNK_LINES)}:\n{t}'
                                       for c, t in sorted(res['notes'].items(), key=lambda x: int(x[0])))
                params = page_params(PAGE_TASK.format(**facts), body, 16000)
                cid = f'p{m["id"]}'
                new = [(cid, params, {'mbx': mbx, 'n': n})]
            else:
                new = []
                for c, chunk in enumerate(chunks):
                    if str(c) in res['notes']:
                        continue
                    task = NOTES_TASK.format(first=c * CHUNK_LINES + 1, last=c * CHUNK_LINES + len(chunk),
                                             total=len(lines), owner=m['owner'])
                    new.append((f'n{m["id"]}-{c}', page_params(task, '\n'.join(chunk), 8000),
                                {'mbx': mbx, 'chunk': c, 'chunks': len(chunks), 'n': n}))
            if not new:  # every chunk has its notes: the page goes out next run
                m['stage'] = 'final'
                continue
            e = sum(estimate(p, calib) for _, p, _ in new)
            if self.projected() + est_total + e > self.budget:
                log(f'{m["owner"]}: page not requested (budget)')
                continue
            for cid, p, meta in new:
                reqs.append({'custom_id': cid, 'params': p})
                metas[cid] = meta
            m['stage'] = 'notes' if 'chunk' in new[0][2] else 'page'
            est_total += e
        if reqs:
            kinds = {('notes' if 'chunk' in mt else 'page') for mt in metas.values()}
            for kind in sorted(kinds):
                sub = {c: mt for c, mt in metas.items() if ('chunk' in mt) == (kind == 'notes')}
                rq = [r for r in reqs if r['custom_id'] in sub]
                self.send(kind, rq, sub, sum(estimate(r['params'], calib) for r in rq))

    def run(self):
        now = datetime.now(timezone.utc)
        end = datetime.strptime(os.environ.get('STUDY_END') or '2026-11-02', '%Y-%m-%d').replace(tzinfo=timezone.utc)
        can_submit = now < end
        log(f'spent so far ${self.st["spent"]:.4f}; {len(self.st["batches"])} batch(es) pending; '
            f'projected ${self.projected():.4f} of ${self.budget:.2f}' + ('' if can_submit else
                                                                       '; credit window ended: no new batches'))
        self.collect()
        self.publish()
        if can_submit and not self.collector_plain():
            log('the collector has not yet started its run without anonymising: waiting')
            can_submit = False
        files = self.zips()
        log(f'{len(files)} e-mail zips on the drive, {len(self.st["zips"])} read before')
        self.forget_trashed(files)
        self.tag_new(files, can_submit)
        self.pages(can_submit)
        self.publish()
        self.run_log['spent'] = round(self.st['spent'], 4)
        self.run_log['projected'] = round(self.projected(), 4)
        self.st['runs'] = (self.st['runs'] + [self.run_log])[-200:]
        self.save()
        msg = (f'SPEND: ${self.st["spent"]:.4f} spent in all (${self.run_log["collected"]:.4f} collected this run); '
               f'projected ${self.projected():.4f} with {len(self.st["batches"])} pending batch(es); '
               f'budget ${self.budget:.2f}')
        log(msg)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
                f.write(msg + '\n')

    def collector_plain(self):
        if os.environ.get('HOWCO_ANON', '').lower() != 'false' or self.st.get('plain_seen'):
            return True  # anonymised collection is the published one: index it as it is
        self.st['plain_seen'] = bool(self.drive.load('state-enron.json.gz', {}).get('plain'))
        return self.st['plain_seen']


def main():
    end = datetime.strptime(os.environ.get('STUDY_END') or '2026-11-02', '%Y-%m-%d').replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - end).days >= 1:
        log(f'the API credit window ended on {end:%Y-%m-%d}: nothing to do')
        return
    if not os.environ.get('ANTHROPIC_API_KEY'):
        log('ANTHROPIC_API_KEY is not set (repository secret): nothing to do')
        return
    try:
        Study().run()
    except Exception:  # noqa: BLE001 - logged; the saved state carries over
        log('problem:\n' + traceback.format_exc()[-3000:])


if __name__ == '__main__':
    main()
    sys.exit(0)
