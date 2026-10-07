# Earnings Sync

Runs on GitHub Actions every hour. For every company in `companies.json` it collects earnings and financial-analysis documents from fiscal 2020 onward, **anonymises them**, gives them consistent names and files them in Google Drive:

```
Earnings Calls/
  CO-3FA21C/                      (company code, not the ticker)
    FY2026-Q2/
      CO-3FA21C_FY2026-Q2_earnings-release_2026-07-14_ex991.htm
      CO-3FA21C_FY2026-Q2_financial-supplement_2026-07-14_ex992.htm
      CO-3FA21C_FY2026-Q2_quarterly-report-10q_2026-08-01.htm
      CO-3FA21C_FY2026-Q2_financial-statements-10q_2026-08-01.xlsx
      CO-3FA21C_FY2026-Q2_investor-presentation_earnings.pdf
Earnings Sync - private/
  company-key.csv                 (code -> ticker; keep this private)
  state-shard-N-of-4.json         (run bookkeeping)
```

| Source | What it gets |
|---|---|
| SEC EDGAR | Every 8-K under Item 2.02 (earnings release, supplements, slides as Exhibit 99.x), every 10-Q and 10-K, and the SEC's `Financial_Report.xlsx` workbook where the SEC has generated one. Older archive pages are followed, so history reaches back to 2020 even for heavy filers. |
| Company IR pages | PDF, XLS/XLSX/XLSM, CSV, DOC/DOCX, PPT/PPTX and TXT files linked from the page in `companies.json`. If that page is gone (404) the IR home page is searched for its results page. Most IR pages only list recent quarters; some block automated visitors. |
| Financial Modeling Prep | Call transcripts, only with an `FMP_API_KEY` on a paid plan. |

Quarters are **fiscal**, using each company's `fiscalYearEndMonth` (taken from SEC data). 52/53-week years are handled: a period ending in the first week of a month counts as the previous month.

## Anonymisation

Every file is anonymised **before** upload by `anonymizer/worker.py`. If a file cannot be anonymised it is not uploaded.

- **Company identity**: the company's names, brands and aliases (`aliases` in `companies.json`), its ticker in safe forms (`NYSE: XYZ`, XBRL prefixes, file names), web domains, SEC CIK, commission file number and EIN become the company code or a tag. Names of the other listed companies become their codes too.
- **Personal data**: e-mail addresses and phone numbers, people's names found by spaCy named-entity recognition, and author/creator metadata.
- **PDFs are redacted properly**: matching words are removed from the page, not just covered, and document metadata, links and outlines are stripped.
- **Legacy `.xls`, `.doc`, `.ppt`** are converted to `.xlsx`, `.docx`, `.pptx` with LibreOffice first.

Codes are `CO-` plus six hex characters of an HMAC of the ticker with the `ANON_KEY` secret, so the public ticker list does not reveal which code is which. The mapping is written to `Earnings Sync - private/company-key.csv` in your Drive.

Limits worth knowing: logos and other images are not changed; product names that are not in `aliases` stay; figures, segment names and context can still let a knowledgeable reader guess a company; name detection is statistical and will miss some names and catch some non-names.

## Running

- **Schedule**: hourly at :07, split into 4 parallel shards. Each run works for up to 45 minutes and the next run continues where it stopped, so the backfill takes several hours.
- **Rate limits**: SEC requests are spaced so the four shards together stay under the SEC's 10 requests per second; IR sites get one request per second.
- **Drive space**: uploads stop when Drive is within `driveReserveMB` (default 1 GB) of full.
- **Re-runs**: each file is tagged with a hash of where it came from, and finished filings are remembered, so nothing is collected twice.

Manual run: **Actions > Earnings sync > Run workflow**, optionally with tickers and **dry run** (lists what would be collected, no downloads).

## Secrets

| Secret | Value |
|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | OAuth client (Desktop app) from Google Cloud |
| `GOOGLE_REFRESH_TOKEN` | From a local OAuth sign-in with the `drive.file` scope. In "Testing" publishing status Google expires it after 7 days. |
| `SEC_USER_AGENT` | Your name and e-mail, e.g. `Jane Doe jane@example.com`. The SEC blocks requests without one. |
| `ANON_KEY` | Long random string. Changing it changes every company code. |
| `FMP_API_KEY` | Optional |

## `companies.json`

| Field | Meaning |
|---|---|
| `ticker` | Required. |
| `name`, `aliases` | Names to anonymise, case-sensitive. Avoid plain English words ("Target", "Southern"). |
| `domains` | Company web domains to anonymise. |
| `cik` | SEC CIK, or a list when the company changed CIK (ExxonMobil). |
| `fiscalYearEndMonth` | 1-12. |
| `irPages[].url`, `render` | Results page; `render: true` loads it in headless Chromium. |
| `sources` | e.g. `{ "ir": false }` |

Settings: `sinceYear`, `maxFileSizeMB`, `runBudgetMinutes`, `driveReserveMB`, `anonymize`, `edgar.forms`, `edgar.financialReportXlsx`, and per-run caps (`0` = no cap).
