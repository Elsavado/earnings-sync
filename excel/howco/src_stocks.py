"""Open Stock Reports (Hugging Face almogtavor/open-stock-reports-dataset, Apache-2.0): quarterly price, market
value, revenue, net income and free cash flow, with growth rates, for 3,000+ US companies (2019 onwards).
Tickers are replaced by the made-up tickers every source shares (companies.py), so no company is named.
Uploaded as CSV and XLSX; replaced in place when the upstream file changes.
"""
import pandas as pd
import requests

REPO = 'almogtavor/open-stock-reports-dataset'
FILE = 'stocks_dataset.csv'
NOTE = ('Source: Open Stock Reports Dataset (https://huggingface.co/datasets/almogtavor/open-stock-reports-dataset), '
        'Apache License 2.0. Modified: every ticker is replaced by a made-up ticker (the same company always gets the '
        'same one). Columns: report date, price, volume, market cap, enterprise value, revenue, net income, free cash '
        'flow (total and per share) and their 6-month to 3-year growth rates.\n')


def run(ctx, log):
    st = ctx.state
    info = requests.get(f'https://huggingface.co/api/datasets/{REPO}', timeout=60).json()
    sha = info.get('sha', '')
    if st.get('sha') == sha and not ctx.dry:
        log('unchanged upstream')
        return
    A = ctx.make_anon()
    src = ctx.work / FILE
    with requests.get(f'https://huggingface.co/datasets/{REPO}/resolve/main/{FILE}', stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(src, 'wb') as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    df = pd.read_csv(src)
    tick = df.columns[0]
    df[tick] = df[tick].astype(str).map(lambda t: A.co.ticker(t.strip().upper()))
    df = df.sort_values([tick, df.columns[1]])
    csv = ctx.work / 'Quarterly fundamentals - 3,000 US companies.csv'
    xlsx = ctx.work / 'Quarterly fundamentals - 3,000 US companies.xlsx'
    df.to_csv(csv, index=False)
    with pd.ExcelWriter(xlsx, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='Quarterly data')
        w.sheets['Quarterly data'].freeze_panes = 'C2'
    note = ctx.work / 'About this dataset (licence).txt'
    note.write_text(NOTE, encoding='utf-8')
    up = ctx.drive.uploaded()
    for p, key in ((csv, 'csv'), (xlsx, 'xlsx'), (note, 'note')):
        ctx.drive.upload(str(p), ctx.folder, p.name, key, replace=up.get(key))
    if ctx.dry:
        ctx.sample(csv, csv.name)
    st['sha'] = sha
    log(f'{len(df)} rows, {df[tick].nunique()} companies (made-up tickers)')
