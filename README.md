# Earnings Sync

Runs on GitHub Actions every hour (and back to back while a backfill is unfinished). For every company in `companies.json` it collects earnings and financial-analysis documents for every year EDGAR has, **anonymises them**, gives them consistent names and files them in Google Drive:

```
Earnings Calls/
  CO-3FA21C/                      (company code, not the ticker)
    FY2026-Q2/
      CO-3FA21C_FY2026-Q2_earnings-release_2026-07-14_ex991_a3f9c2.pdf
      CO-3FA21C_FY2026-Q2_financial-supplement_2026-07-14_ex992_07be41.pdf
      CO-3FA21C_FY2026-Q2_quarterly-report-10q_2026-08-01_5d20aa.pdf
      CO-3FA21C_FY2026-Q2_financial-statements-10q_2026-08-01_c81f09.xlsx
      CO-3FA21C_FY2026-Q2_investor-presentation_earnings_9e3b77.pdf
Earnings Sync - private/
  company-key                     (Google Sheet: code -> company -> fictional name)
```

| Source | What it gets |
|---|---|
| SEC EDGAR | Every 8-K under Item 2.02 (earnings release, supplements, slides as Exhibit 99.x), every 10-Q and 10-K, and the SEC's `Financial_Report.xlsx` workbook where the SEC has generated one. Older archive pages are followed, so history reaches back to 2020 even for heavy filers. |
| Company IR pages | PDF, XLS/XLSX/XLSM, CSV, DOC/DOCX, PPT/PPTX and TXT files linked from the page in `companies.json`. If that page is gone (404) the IR home page is searched for its results page. Most IR pages only list recent quarters; some block automated visitors. |
| Financial Modeling Prep | Call transcripts, only with an `FMP_API_KEY` on a paid plan. |

Quarters are **fiscal**, using each company's `fiscalYearEndMonth` (taken from SEC data). 52/53-week years are handled: a period ending in the first week of a month counts as the previous month.

## Anonymisation

Every file is pseudonymised **before** upload by `anonymizer/worker.py`: identifying details are replaced with consistent, imaginary ones rather than blanked out. If a file cannot be processed it is not uploaded.

| Real | Becomes |
|---|---|
| Company names and legal names | A fictional company of similar length ("Intel Corporation" -> "Calyx Corporation"); the same everywhere |
| Brands and subsidiaries listed in `aliases` | Invented brand names |
| Ticker, web domains, SEC CIK, EIN, commission file number | Fake ticker, `<name>.example`, fake numbers of the same shape |
| HQ street address, city/state/ZIP, press-release dateline | Fictional address and city |
| People (spaCy named-entity recognition) | Fictional people; first name and surname are mapped separately, so "Mr. Dimon" and "Jamie Dimon" stay consistent |
| E-mails and phone numbers | `investor.relations@<name>.example`, `(555) 555-01xx` (reserved for fiction) |
| Document metadata (author, title, company) | Removed or fictional |
| Header and footer logos in PDFs | Removed |

Names of the other listed companies get their own fictional names too. In PDFs the real words are removed from the page and the fictional text is written in their place. Everything is derived from the `ANON_KEY` secret, and the key Google Sheet `Earnings Sync - private/company-key` maps codes and fictional names back to the real companies.

Only documents are uploaded: SEC HTML is printed to PDF after pseudonymising, CSV and TXT become XLSX and DOCX, and legacy `.xls`, `.doc`, `.ppt` are converted with LibreOffice. Every file name ends with a short ID from its source, so names are unique.

Limits worth knowing: product names not in `aliases`, images inside the page body, figures and context can still let a knowledgeable reader guess a company; name detection is statistical and will miss some names.

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

The list has two tiers. The first 116 companies are curated (aliases, brands, domains, IR pages) and are processed first. They are followed by about 3,900 companies matched from the SEC's Official List of Section 13(f) Securities (Q1 2026) against the SEC's own ticker data (`"auto": true`: SEC filings only, names from SEC data, fiscal year from SEC data). Companies with listed options come first. Foreign filers are included through 20-F/40-F annual reports and 6-K exhibits whose text reads like a results release.


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
