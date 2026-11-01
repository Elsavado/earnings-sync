""""Last Minute Call" (user, 2026-11-01): quick-reference M&A, corporate finance & FP&A, investment analysis and
credit analysis documents, every company and person under a consistent made-up name (always anonymised, even when
HOWCO_ANON=false). One source per area, so the four run side by side:

  lmc_mna     merger agreements, fairness opinions and banker decks, merger proxies, tender offers, deal
              announcements and investor presentations, letters of intent and term sheets
  lmc_fpa     investor days and long-term targets, guidance and outlook, earnings presentations, management
              projections, operating plans and budgets
  lmc_invest  investment committee memos, activist and investment-thesis presentations, investor letters,
              valuation and appraisal reports
  lmc_credit  credit agreements, indentures and note terms, lender presentations, debt commitment letters,
              restructuring support agreements

Discovery is SEC full-text search (fdocs.sources.sec, year by year back to 2001). HTML exhibits become PDFs (Chrome);
decks that are only pictures are skipped.

  Last Minute Call/<area>/<kind>/Folder K (Docs a-b)/<n> - <made-up company> - <kind> - <year>.pdf
"""
import hashlib
import re
import time

import requests

from fdocs import sources

EX2, EX4, EX10, EX99 = r'EX-2', r'EX-4', r'EX-10', r'EX-99'
EX99C = sources.EX99C
VALUATION = r'valuation|discounted cash flow|precedent transactions|comparable|premium|EBITDA|fairness'
# area source: {kind folder: ([(query, exhibit types, forms, description filter)], text that must appear)}
AREAS = {
    'lmc_mna': {
        'Merger Agreements': ([('"agreement and plan of merger"', EX2, '8-K,8-K/A')], r'merger consideration|effective time'),
        'Fairness Opinions & Banker Decks': ([q for q in sources.SEC_QUERIES['cim'] if 'ABS-15G' not in (q[2] if len(q) > 2 else '')],
                                             VALUATION),
        'Merger Proxies (Background & Valuation)': ([('"background of the merger" "opinion of"', r'DEFM14A|PREM14A',
                                                      'DEFM14A,PREM14A')], r'background of the merger'),
        'Tender Offers': ([('"offer to purchase"', EX99, 'SC TO-T,SC TO-T/A,SC TO-I'),
                           ('"solicitation/recommendation statement"', r'SC 14D9', 'SC 14D9')], r'tender|offer'),
        'Deal Announcements & Investor Presentations': ([('"accretive" "synergies"', EX99 + '|425', '8-K,425'),
                                                         ('"transaction overview" "pro forma"', EX99 + '|425', '8-K,425')],
                                                        r'synerg|accreti|pro forma'),
        'Letters of Intent & Term Sheets': (sources.SEC_QUERIES['deals'], r'proposal|terms|confidential|purchase'),
    },
    'lmc_fpa': {
        'Investor Day & Long-Term Targets': ([('"investor day" "long-term"', EX99, '8-K')], r'target|outlook|guidance|framework'),
        'Guidance & Outlook': ([('"full year" guidance "free cash flow" outlook', EX99, '8-K')], r'guidance|outlook'),
        'Earnings Presentations': ([('"earnings presentation" "adjusted EBITDA"', EX99, '8-K')], r'EBITDA|margin'),
        'Management Projections': ([('"management projections" "unlevered free cash flow"', r'DEFM14A|SC 14D9|EX-99',
                                     'DEFM14A,SC 14D9,SC 13E3')], r'projections'),
        'Operating Plans & Budgets': ([('"annual operating plan" budget', EX99 + '|' + EX10),
                                       ('"capital allocation" "return on invested capital"', EX99, '8-K')],
                                      r'budget|plan|capital'),
    },
    'lmc_invest': {
        'Investment Committee Memos': (sources.SEC_QUERIES['memos'], r'investment|recommend'),
        'Activist & Investment Thesis Presentations': ([('"investment thesis"', r'EX-99|DFAN14A', 'DFAN14A,SC 13D,SC 13D/A'),
                                                        ('"undervalued" "shareholder value"', r'EX-99|DFAN14A', 'DFAN14A')],
                                                       r'valuation|value|EBITDA|board'),
        'Investor Letters': (sources.SEC_QUERIES['letters'], r'dear'),
        'Valuation & Appraisal Reports': ([('"valuation report" "fair market value"', EX99),
                                           ('"appraisal" "fair market value" "income approach"', EX99C + '|' + EX99)],
                                          r'fair market value|income approach|market approach'),
    },
    'lmc_credit': {
        'Credit Agreements': ([('"credit agreement" "consolidated leverage ratio"', EX10, '8-K,8-K/A,10-Q,10-K')],
                              r'leverage ratio|interest coverage|borrower'),
        'Indentures & Note Terms': ([('indenture "senior notes" "events of default"', EX4, '8-K,8-K/A')],
                                    r'indenture|events of default'),
        'Lender Presentations': ([('"lender presentation"', EX99, '8-K'), ('"lender meeting" "term loan"', EX99, '8-K')],
                                 r'loan|EBITDA|leverage|credit'),
        'Debt Commitment Letters': ([('"commitment letter" "term loan" lenders', r'EX-99|EX-10')], r'commitment|facility'),
        'Restructuring Support Agreements': ([('"restructuring support agreement"', EX10 + '|' + EX99, '8-K,8-K/A')],
                                             r'restructuring|creditor|chapter 11|plan'),
    },
}
AREA_FOLDERS = {'lmc_mna': 'M&A', 'lmc_fpa': 'Corporate Finance & FP&A', 'lmc_invest': 'Investment Analysis',
                'lmc_credit': 'Credit Analysis'}
PER_FOLDER = 50


def _kind_key(kind):
    return 'lmc:' + re.sub(r'\W+', '_', kind.lower())


def run(ctx, log):
    from fdocs.main import html_to_pdf, readable
    from models.anonymize import core_tokens
    import pymupdf
    st = ctx.state
    for k in ('seen', 'queued', 'queue', 'cursors', 'n'):
        st.setdefault(k, {})
    st.setdefault('hashes', [])
    hashes = set(st['hashes'])
    kinds = AREAS[ctx.source]
    s = sources.session()
    A = ctx.make_anon()
    total = 0
    # Kinds take turns, a slice of time each, until the run budget is spent.
    while ctx.left() > 600:
        progress = 0
        for kind, (queries, must) in kinds.items():
            if ctx.left() <= 600:
                break
            kk = _kind_key(kind)
            sources.SEC_QUERIES[kk] = queries
            q = st['queue'].setdefault(kk, [])
            if len(q) < 50:
                sources.DEADLINE = time.time() + min(300, ctx.left() / 8)
                added = sources.sec(st, kk, s, log, pages=4)
                log(f'{kind}: {added} new documents found')
            slice_end = time.time() + min(1800, max(300, ctx.left() / (2 * len(kinds))))
            kept = 0
            while q and time.time() < slice_end and ctx.left() > 600:
                c = q.pop(0)
                st['queued'].pop(c['key'], None)
                st['seen'][c['key']] = 1
                try:
                    r = s.get(c['url'], timeout=120)
                    time.sleep(0.15)
                except requests.RequestException:
                    continue
                if not r.ok or len(r.content) > 80 * 2**20:
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
                        html.write_text('<pre>' + data.decode('utf-8', 'replace').replace('<', '&lt;') + '</pre>',
                                        encoding='utf-8')
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
                if len(text) < 3000 or not re.search(must, text, re.I):
                    continue
                A.start()
                # Every filer named on the filing is a company of this document, however it is written.
                cores = []
                for org in c.get('orgs') or []:
                    core = core_tokens(re.sub(r'\s*\((?:CIK [^)]*|[A-Z0-9.\-, ]{1,40})\)', '', org).strip())
                    if core:
                        A.co._add(core, True)
                        A.co.pseudo(core)
                        cores.append(core)
                dst = ctx.work / 'out.pdf'
                try:
                    ok, out_text = A.file(pdf, str(dst), 'pdf')
                except Exception:  # noqa: BLE001
                    ok = False
                if not ok:
                    continue
                leaks = A.leaks(out_text)
                company = A.co.pseudo(cores[0]) if cores else 'Company'
                n = st['n'][kk] = st['n'].get(kk, 0) + 1
                f = (n - 1) // PER_FOLDER + 1
                folder = f'{ctx.folder}/{kind}/Folder {f} (Docs {PER_FOLDER * (f - 1) + 1}-{PER_FOLDER * f})'
                year = (c.get('date') or '')[:4]
                label = kind.split(' (')[0]
                name = re.sub(r'[\\/:*?"<>|]+', ' ', f'{n} - {company} - {label}{" - " + year if year else ""}.pdf')
                ctx.drive.upload(str(dst), folder, name, f'lmc:{c["key"]}'[:100])
                kept += 1
                ctx.sample(dst, name, leaks)
                if kept % 10 == 0:
                    st['hashes'] = sorted(hashes)
                    ctx.save()
                if ctx.dry and kept >= 3:
                    break
            log(f'{kind}: {kept} documents kept this turn, {len(q)} still queued')
            total += kept
            progress += kept
            st['hashes'] = sorted(hashes)
            ctx.save()
        if ctx.dry or not progress and all(not st['queue'].get(_kind_key(k)) for k in kinds):
            break
    log(f'this run: {total} documents')
