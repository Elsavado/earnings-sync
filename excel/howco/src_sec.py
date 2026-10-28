"""Banker board decks filed with the SEC: the discussion materials, special-committee presentations and fairness
opinion analyses that investment banks give a board during a merger or going-private deal (exhibit 99(c) to
Schedule 13E-3 and merger proxies), plus quality-of-earnings reports. These are the public counterpart of a
confidential information memorandum.

Discovery: SEC full-text search (fdocs.sources.sec, year by year). HTML exhibits become PDFs (Chrome); decks that
are only pictures are skipped. The filer and every other company and person get the made-up names every source
shares.

  Banker Board Decks (SEC)/Folder K (Decks a-b)/<n> - <made-up company> - <kind of deck> - <year>.pdf
"""
import hashlib
import re
import time

import requests

from fdocs import sources

QUERIES = [q for q in sources.SEC_QUERIES['cim'] if 'ABS-15G' not in (q[2] if len(q) > 2 else '')]
KIND = 'howco_decks'
PER_FOLDER = 20
LABELS = [(r'fairness opinion|fairness analysis', 'Fairness opinion analysis'),
          (r'special committee', 'Special committee presentation'),
          (r'preliminary', 'Preliminary discussion materials'),
          (r'quality of earnings', 'Quality of earnings report'),
          (r'discussion materials|presentation', 'Board discussion materials')]


def run(ctx, log):
    from fdocs.main import html_to_pdf, readable
    import pymupdf
    st = ctx.state
    for k in ('seen', 'queued'):
        st.setdefault(k, {})
    st.setdefault('queue', {})
    st.setdefault('cursors', {})
    st.setdefault('hashes', [])
    st.setdefault('n', 0)
    hashes = set(st['hashes'])
    sources.SEC_QUERIES[KIND] = QUERIES
    sources.DEADLINE = time.time() + min(900, ctx.left() / 4)
    s = sources.session()
    if len(st['queue'].get(KIND, [])) < 200:
        added = sources.sec(st, KIND, s, log, pages=6)
        log(f'search: {added} new exhibits queued')
    A = ctx.make_anon()
    q = st['queue'].setdefault(KIND, [])
    kept = 0
    while q and ctx.left() > 400:
        c = q.pop(0)
        st['queued'].pop(c['key'], None)
        st['seen'][c['key']] = 1
        try:
            r = s.get(c['url'], timeout=90)
            time.sleep(0.15)
        except requests.RequestException:
            continue
        if not r.ok or len(r.content) > 60 * 2**20:
            continue
        data = r.content
        h = hashlib.sha1(data).hexdigest()
        if h in hashes:
            continue
        hashes.add(h)
        src = ctx.work / f'in.{c["ext"]}'
        src.write_bytes(data)
        pdf = str(src)
        if data[:5] != b'%PDF-':
            if c['ext'] not in ('htm', 'html', 'txt'):
                continue
            if c['ext'] == 'txt':
                html = ctx.work / 'in.html'
                html.write_text('<pre>' + data.decode('utf-8', 'replace').replace('<', '&lt;') + '</pre>', encoding='utf-8')
                src = html
            pdf = html_to_pdf(str(src), str(ctx.work))
            if not pdf:
                continue
        try:
            if readable(pdf):
                continue
            with pymupdf.open(pdf) as d:
                text = ''.join(p.get_text() for p in d)
        except Exception:  # noqa: BLE001
            continue
        if len(text) < 3000 or not re.search(r'valuation|discounted cash flow|precedent transactions|comparable|'
                                             r'premium|EBITDA|fairness', text, re.I):
            continue
        A.start()
        # The filer is a company of this document even where its name is written oddly.
        filer = re.sub(r'\s*\((?:CIK [^)]*|[A-Z0-9.\-, ]{1,40})\)', '', (c.get('orgs') or [''])[0]).strip()
        from models.anonymize import core_tokens
        core = core_tokens(filer)
        if core:
            A.co._add(core, True)
            A.co.pseudo(core)
        dst = ctx.work / 'out.pdf'
        try:
            ok, out_text = A.file(pdf, str(dst), 'pdf')
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            continue
        leaks = A.leaks(out_text)
        label = next((lab for pat, lab in LABELS if re.search(pat, (c.get('desc') or '') + ' ' + text[:3000], re.I)),
                     'Board discussion materials')
        company = A.co.pseudo(core) if core else 'Company'
        st['n'] += 1
        n = st['n']
        k = (n - 1) // PER_FOLDER + 1
        folder = f'{ctx.folder}/Folder {k} (Decks {PER_FOLDER * (k - 1) + 1}-{PER_FOLDER * k})'
        year = (c.get('date') or '')[:4]
        name = re.sub(r'[\\/:*?"<>|]+', ' ', f'{n} - {company} - {label}{" - " + year if year else ""}.pdf')
        ctx.drive.upload(str(dst), folder, name, f'sec:{c["key"]}'[:100])
        kept += 1
        ctx.sample(dst, name, leaks)
        if ctx.dry and kept >= 10:
            break
        if kept % 10 == 0:
            st['hashes'] = sorted(hashes)
            ctx.save()
    st['hashes'] = sorted(hashes)
    log(f'this run: {kept} decks kept, {len(q)} still queued')
