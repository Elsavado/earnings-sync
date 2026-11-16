"""Overnight public-data build (user, 2026-11-17: 'build the overnight job').

Sources (City of Chicago open data, public):
  budget   x394-e874  2024 Budget Ordinance Appropriations -> one 5-tab Google Sheet per department
  permits  ydr8-5enu  Building permits -> one 4-tab Google Sheet and one 4-slide Google Slides deck per ward
Each file is created directly in Drive as a Google type (Drive converts the uploaded Office bytes on upload).
Files already in the target folder (matched by name) are skipped, so runs resume.
Env: RUN_MINUTES (default 330), FOLDER_ID, RCLONE_REMOTE (default shintiru), DRY_RUN.
"""
import collections, io, json, os, re, time, urllib.parse, urllib.request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pptx import Presentation
from pptx.util import Inches, Pt
from models.store import RcloneCredentials

FOLDER = os.environ.get('FOLDER_ID', '10ZsSudGMgE47x3TZcqyxRRV1T1d_afhR')
END = time.time() + float(os.environ.get('RUN_MINUTES', '330')) * 60
DRY = os.environ.get('DRY_RUN', '').lower() == 'true'
SOCRATA = 'https://data.cityofchicago.org/resource/'
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
PPTX = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
GSHEET, GSLIDE = 'application/vnd.google-apps.spreadsheet', 'application/vnd.google-apps.presentation'
HDR = PatternFill('solid', fgColor='1F4E78')
WH = Font(bold=True, color='FFFFFF')
BOLD = Font(bold=True)
stats = collections.Counter()


def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def soda(dataset, **q):
    url = SOCRATA + dataset + '.json?' + urllib.parse.urlencode(q)
    for i in range(5):
        try:
            return json.load(urllib.request.urlopen(url, timeout=180))
        except Exception as e:
            log(f'socrata retry {i}: {e}')
            time.sleep(10 * (i + 1))
    raise RuntimeError('socrata failed')


def money(v):
    return f'${v/1e9:,.2f}B' if v >= 1e9 else f'${v/1e6:,.1f}M'


def clean(t):
    return (t or '').replace('–', '-').strip()


def fname(s):
    return re.sub(r'[\\/:*?"<>|]', '-', s).strip()[:120]


drive = build('drive', 'v3', credentials=RcloneCredentials(os.environ.get('RCLONE_REMOTE', 'shintiru')), cache_discovery=False)


def existing_names():
    names, tok = set(), None
    while True:
        r = drive.files().list(q=f"'{FOLDER}' in parents and trashed=false", pageSize=1000, pageToken=tok,
                               fields='nextPageToken, files(name)').execute()
        for f in r['files']:
            # Google-native files have no extension; keep both spellings so nothing is duplicated
            names.add(f['name'])
            base = re.sub(r'\.(xlsx|pptx)$', '', f['name'])
            names.add(base + '.xlsx')
            names.add(base + '.pptx')
        tok = r.get('nextPageToken')
        if not tok:
            return names


def upload(name, data, src_mime, dst_mime, names):
    if name in names:
        stats['skipped_existing'] += 1
        return
    if DRY:
        stats['dry_run_not_uploaded'] += 1
        return
    body = {'name': name, 'mimeType': dst_mime, 'parents': [FOLDER]}
    for attempt in range(10):
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=src_mime, resumable=False)
        try:
            drive.files().create(body=body, media_body=media, fields='id').execute()
            names.add(name)
            stats['created'] += 1
            time.sleep(4)
            return
        except HttpError as e:
            if e.resp.status in (403, 429, 500, 503):
                log(f'drive {e.resp.status} on {name}; waiting {30 * (attempt + 1)}s')
                time.sleep(30 * (attempt + 1))
            else:
                stats['failed'] += 1
                log(f'failed {name}: {e}')
                return
    stats['failed'] += 1


def to_bytes(obj):
    b = io.BytesIO()
    obj.save(b)
    return b.getvalue()


def add_table(ws, headers, rows, widths=None):
    ws.append(headers)
    for c in ws[ws.max_row]:
        c.font = WH
        c.fill = HDR
    for r in rows:
        ws.append(r)
    for col, w in (widths or {}).items():
        ws.column_dimensions[col].width = w


def notes_sheet(wb, lines):
    nt = wb.create_sheet('Notes')
    for line in lines:
        nt.append([line])
    nt.column_dimensions['A'].width = 100


# ---------------- budget trackers (5 tabs each) ----------------
def budget_trackers(names):
    rows = soda('x394-e874', **{'$limit': '50000'})
    depts = collections.OrderedDict()
    for r in rows:
        depts.setdefault((r.get('department_number', ''), r.get('department_description', 'Unknown')), []).append(r)
    for (num, name), items in depts.items():
        fn = fname(f'Chicago FY2024 Budget - {num} {name}') + '.xlsx'
        if fn in names:
            stats['skipped_existing'] += 1
            continue
        n = len(items)
        start = 5
        last = start + n - 1
        tot = last + 1
        wb = Workbook()
        wb.remove(wb.active)

        sm = wb.create_sheet('Summary')
        sm['A1'] = f'Chicago FY2024 budget tracker - Department {num} {name}'
        sm['A1'].font = Font(bold=True, size=14)
        sm['A2'] = 'Source: City of Chicago open data, 2024 Budget Ordinance Appropriations (x394-e874).'
        add_table(sm, ['Metric', 'Value'], [
            ['Appropriation accounts', n],
            ['Funds', len({r.get('fund_description', '') for r in items})],
            ['Total budget (ordinance)', f"='Budget Tracker'!D{tot}"],
            ['Total actual (entered)', f"='Budget Tracker'!E{tot}"],
            ['Variance', f"='Budget Tracker'!F{tot}"],
            ['% used', f"='Budget Tracker'!G{tot}"],
            ['Monthly actuals YTD', f"='Monthly Actuals'!O{tot}"]], {'A': 30, 'B': 22})
        for r in range(7, 11):
            sm[f'B{r}'].number_format = '#,##0'
        sm['B12'].number_format = '0.0%'

        bt = wb.create_sheet('Budget Tracker')
        bt['A1'] = f'Department {num} {name} - budget by account'
        bt['A1'].font = Font(bold=True, size=13)
        bt['A2'] = 'Enter actuals in column E, or use the Monthly Actuals tab.'
        bt.append([])
        bt.append(['Fund', 'Appropriation account', 'Account description', 'Budget (ordinance)', 'Actual spend (enter)', 'Variance', '% used'])
        for c in bt[4]:
            c.font = WH
            c.fill = HDR
        for i, r in enumerate(items):
            k = start + i
            bt.append([r.get('fund_description', ''), r.get('appropriation_account', ''), r.get('appropriation_account_description', ''),
                       float(r.get('_ordinance_amount_') or 0), None,
                       f'=IF(E{k}="","",D{k}-E{k})', f'=IF(OR(E{k}="",D{k}=0),"",E{k}/D{k})'])
        bt.append(['TOTAL', '', '', f'=SUM(D{start}:D{last})', f'=SUM(E{start}:E{last})', f'=D{tot}-E{tot}', f'=IF(D{tot}=0,"",E{tot}/D{tot})'])
        for c in bt[tot]:
            c.font = BOLD
        for row in bt.iter_rows(min_row=start, max_row=tot):
            for c in row[3:6]:
                c.number_format = '#,##0'
            row[6].number_format = '0.0%'
        for col, w in zip('ABCDEFG', [24, 14, 48, 20, 20, 18, 10]):
            bt.column_dimensions[col].width = w
        bt.freeze_panes = 'A5'

        bf = wb.create_sheet('By Fund')
        bf['A1'] = 'Budget by fund (formulas read the Budget Tracker tab)'
        bf['A1'].font = Font(bold=True, size=13)
        bf.append([])
        bf.append(['Fund', 'Budget', 'Actual', 'Variance', 'Accounts'])
        for c in bf[4]:
            c.font = WH
            c.fill = HDR
        funds = collections.OrderedDict()
        for r in items:
            f = r.get('fund_description', '')
            funds[f] = funds.get(f, 0) + 1
        rng = f"'Budget Tracker'!$A${start}:$A${last}"
        for i, f in enumerate(funds):
            k = 5 + i
            bf.append([f, f"=SUMIF({rng},A{k},'Budget Tracker'!$D${start}:$D${last})",
                       f"=SUMIF({rng},A{k},'Budget Tracker'!$E${start}:$E${last})", f'=B{k}-C{k}', f'=COUNTIF({rng},A{k})'])
            for c in bf[k][1:4]:
                c.number_format = '#,##0'
        fl = 4 + len(funds)
        bf.append(['TOTAL', f'=SUM(B5:B{fl})', f'=SUM(C5:C{fl})', f'=SUM(D5:D{fl})', f'=SUM(E5:E{fl})'])
        for c in bf[fl + 1]:
            c.font = BOLD
        for col, w in zip('ABCDE', [44, 20, 20, 20, 12]):
            bf.column_dimensions[col].width = w

        ma = wb.create_sheet('Monthly Actuals')
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        ma['A1'] = 'Enter monthly actuals in columns C:N. YTD, budget and remaining are formulas.'
        ma['A1'].font = BOLD
        ma.append([])
        ma.append(['Account', 'Account description'] + months + ['YTD actual', 'Budget', 'Remaining'])
        for c in ma[4]:
            c.font = WH
            c.fill = HDR
        for i, r in enumerate(items):
            k = start + i
            ma.append([r.get('appropriation_account', ''), r.get('appropriation_account_description', '')] + [None] * 12 +
                      [f'=SUM(C{k}:N{k})', f"='Budget Tracker'!D{k}", f'=O{k}-P{k}'])
        ma.append(['TOTAL', ''] + [f'=SUM({c}{start}:{c}{last})' for c in 'CDEFGHIJKLMNOPQ'])
        for c in ma[tot]:
            c.font = BOLD
        ma.column_dimensions['B'].width = 44
        ma.freeze_panes = 'C5'

        notes_sheet(wb, ['Source: City of Chicago open data - 2024 Budget Ordinance Appropriations (x394-e874).',
                         'Budget values are the ordinance amounts in the source data.',
                         'Actuals are blank: enter them in Budget Tracker column E or Monthly Actuals.',
                         'Built from public data; not an official City financial report.'])
        upload(fn, to_bytes(wb), XLSX, GSHEET, names)


# ---------------- ward permit trackers and decks ----------------
def ward_data():
    rows = soda('ydr8-5enu', **{
        '$select': 'ward,permit_type,date_extract_y(issue_date) as yr,count(*) as n,sum(reported_cost) as cost',
        '$where': "issue_date > '2019-01-01T00:00:00' AND ward IS NOT NULL",
        '$group': 'ward,permit_type,yr', '$limit': '50000'})
    wards = collections.defaultdict(list)
    for r in rows:
        wards[str(r['ward'])].append((clean(r.get('permit_type')), str(r.get('yr', '')),
                                      int(float(r.get('n', 0))), float(r.get('cost') or 0)))
    return wards


def ward_outputs(names):
    wards = ward_data()
    log(f'wards with data: {len(wards)}')
    for w in sorted(wards, key=lambda x: int(x)):
        recs = wards[w]
        years = sorted({y for _, y, _, _ in recs})
        types = sorted({t for t, _, _, _ in recs}, key=lambda t: -sum(n for tt, _, n, _ in recs if tt == t))
        tot_n = sum(n for _, _, n, _ in recs)
        tot_c = sum(c for _, _, _, c in recs)
        base = fname(f'Chicago Ward {int(w):02d} Permits 2019-2025')

        if base + '.xlsx' not in names:
            wb = Workbook()
            wb.remove(wb.active)
            sm = wb.create_sheet('Summary')
            sm['A1'] = f'Chicago ward {w} building permit tracker (2019 onward)'
            sm['A1'].font = Font(bold=True, size=14)
            sm['A2'] = 'Source: City of Chicago Building Permits (ydr8-5enu). Reported cost is the applicant figure.'
            add_table(sm, ['Metric', 'Value'], [
                ['Permits', tot_n], ['Reported cost', round(tot_c, 2)], ['Permit types', len(types)],
                ['Years', ', '.join(years)], ['Average cost per permit', round(tot_c / tot_n, 2) if tot_n else 0]],
                {'A': 30, 'B': 22})
            sm['B5'].number_format = '#,##0'
            sm['B6'].number_format = '#,##0'
            bt = wb.create_sheet('By Type')
            add_table(bt, ['Permit type', 'Permits', 'Reported cost', 'Share of permits'],
                      [[t, sum(n for tt, _, n, _ in recs if tt == t),
                        round(sum(c for tt, _, _, c in recs if tt == t), 2),
                        (sum(n for tt, _, n, _ in recs if tt == t) / tot_n) if tot_n else 0] for t in types],
                      {'A': 44, 'B': 14, 'C': 22, 'D': 18})
            for row in bt.iter_rows(min_row=2):
                row[1].number_format = '#,##0'
                row[2].number_format = '#,##0'
                row[3].number_format = '0.0%'
            by = wb.create_sheet('By Year')
            add_table(by, ['Year', 'Permits', 'Reported cost'],
                      [[y, sum(n for _, yy, n, _ in recs if yy == y), round(sum(c for _, yy, _, c in recs if yy == y), 2)]
                       for y in years], {'A': 12, 'B': 14, 'C': 22})
            for row in by.iter_rows(min_row=2):
                row[1].number_format = '#,##0'
                row[2].number_format = '#,##0'
            notes_sheet(wb, ['Source: City of Chicago Building Permits, public open data (ydr8-5enu).',
                             'Counts and cost are grouped by ward, permit type and issue year.',
                             'Reported cost is the applicant figure, not audited spend.',
                             'Individual owners and contacts are not shown.'])
            upload(base + '.xlsx', to_bytes(wb), XLSX, GSHEET, names)

        if base + '.pptx' not in names:
            prs = Presentation()
            prs.slide_width = Inches(13.333)
            prs.slide_height = Inches(7.5)
            s = prs.slides.add_slide(prs.slide_layouts[0])
            s.shapes.title.text = f'Chicago ward {w}: building permits'
            s.placeholders[1].text = f'2019 onward | {tot_n:,} permits | {money(tot_c)} reported cost'

            def table_slide(title, headers, rows):
                sl = prs.slides.add_slide(prs.slide_layouts[5])
                sl.shapes.title.text = title
                tb = sl.shapes.add_table(len(rows) + 1, len(headers), Inches(0.6), Inches(1.6),
                                         Inches(12.1), Inches(0.4 * (len(rows) + 1))).table
                for j, h in enumerate(headers):
                    tb.cell(0, j).text = h
                for i, row in enumerate(rows, 1):
                    for j, v in enumerate(row):
                        tb.cell(i, j).text = str(v)
                for r_ in tb.rows:
                    for c in r_.cells:
                        for p in c.text_frame.paragraphs:
                            for run in p.runs:
                                run.font.size = Pt(13)

            top = types[:10]
            table_slide('Top permit types', ['Permit type', 'Permits', 'Reported cost'],
                        [[t[:60], f'{sum(n for tt, _, n, _ in recs if tt == t):,}',
                          money(sum(c for tt, _, _, c in recs if tt == t))] for t in top])
            table_slide('Issuance by year', ['Year', 'Permits', 'Reported cost'],
                        [[y, f'{sum(n for _, yy, n, _ in recs if yy == y):,}',
                          money(sum(c for _, yy, _, c in recs if yy == y))] for y in years])
            table_slide('Share of ward permits by type (top 10)', ['Permit type', 'Share of permits'],
                        [[t[:60], f'{(sum(n for tt, _, n, _ in recs if tt == t) / tot_n * 100 if tot_n else 0):.1f}%']
                         for t in top])
            nt = prs.slides.add_slide(prs.slide_layouts[1])
            nt.shapes.title.text = 'Notes and method'
            nt.placeholders[1].text = ('Source: City of Chicago Building Permits (ydr8-5enu), public open data.\n'
                                       'Costs are applicant-reported, not audited.\n'
                                       'Individual owners and contacts are not shown.')
            upload(base + '.pptx', to_bytes(prs), PPTX, GSLIDE, names)


def main():
    names = existing_names()
    log(f'existing files in folder: {len(names)}')
    for step in (budget_trackers, ward_outputs):
        if time.time() > END:
            log('time budget reached; stopping before', step.__name__)
            break
        step(names)
        log(f'after {step.__name__}: {dict(stats)}')
    log(f'FINAL {dict(stats)}')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write('## Overnight public build\n' + '\n'.join(f'- {k}: {v}' for k, v in stats.items()) + '\n')


if __name__ == '__main__':
    main()
