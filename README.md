# Earnings Sync

Runs on GitHub Actions twice a day. For every company in `companies.json` it collects new earnings material and files it in Google Drive:

```
Earnings Calls/
  AAPL/
    FY2026-Q4/
      AAPL_FY2026-Q4_transcript_fmp.txt
      AAPL_FY2026-Q4_press-release_ex-99-1-0000320193-26-000071   (Google Doc)
      AAPL_FY2026-Q4_presentation_q4-fy26-slides.pdf
```

| Source | What it gets | Needs |
|---|---|---|
| SEC EDGAR | Exhibit 99.x of every 8-K filed under Item 2.02 (earnings release, often slides or supplements) | `SEC_USER_AGENT` secret |
| Financial Modeling Prep | Full call transcripts | `FMP_API_KEY` secret (transcripts require a paid FMP plan) |
| Company IR pages | PDFs, slides, audio and spreadsheets linked from the pages you list | URLs in `companies.json` |

Each file is tagged in Drive with a hash of where it came from, so nothing is downloaded twice. Delete a file from Drive (and empty the trash) to make it download again.

Quarters are **fiscal**, using each company's `fiscalYearEndMonth`. Apple's December quarter therefore lands in `FY2026-Q1`.

---

## Setup (browser only, about 20 minutes)

### 1. Put the code in a GitHub repository

1. On GitHub, create a new **private** repository, for example `earnings-sync`.
2. Click **Add file > Upload files**, drag in everything from this folder **except** the `.github` folder, and commit.
3. Click **Add file > Create new file**, type the name `.github/workflows/earnings-sync.yml`, paste the contents of that file, and commit. (Uploading hidden folders through the browser is unreliable, so create this one by hand.)

### 2. Create Google credentials

1. Go to <https://console.cloud.google.com/>, create a project, then open **APIs & Services > Library**, search **Google Drive API** and click **Enable**.
2. **APIs & Services > OAuth consent screen**: choose **External**, fill in the app name and your email, and save. Add your own Gmail address as a test user, then click **Publish app** so it moves to **In production**. (Apps left in Testing issue tokens that expire after 7 days, which would break the nightly run. You'll see an "unverified app" warning when you sign in; that's expected for a personal tool.)
3. **APIs & Services > Credentials > Create credentials > OAuth client ID**: type **Web application**, and under **Authorized redirect URIs** add `https://developers.google.com/oauthplayground`. Create it and copy the **Client ID** and **Client secret**.

### 3. Get a refresh token (OAuth Playground)

1. Open <https://developers.google.com/oauthplayground>.
2. Click the gear icon (top right), tick **Use your own OAuth credentials**, and paste your Client ID and Client secret.
3. In the box under the API list on the left, type `https://www.googleapis.com/auth/drive.file` and click **Authorize APIs**. Sign in with the Google account whose Drive should receive the files and allow access.
4. Click **Exchange authorization code for tokens** and copy the **Refresh token**.

`drive.file` only lets this tool see files it created itself. It creates the `Earnings Calls` folder in your My Drive on the first run; leave `DRIVE_ROOT_FOLDER_ID` unset in this mode.

### 4. Add repository secrets

In the repository: **Settings > Secrets and variables > Actions > New repository secret**.

| Secret | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | From step 2 |
| `GOOGLE_CLIENT_SECRET` | From step 2 |
| `GOOGLE_REFRESH_TOKEN` | From step 3 |
| `SEC_USER_AGENT` | Your name and email, e.g. `Salvaa Ops salvaa@example.com`. The SEC blocks requests without one. |
| `FMP_API_KEY` | From <https://site.financialmodelingprep.com/developer/docs> (optional) |

**Shared Drive instead (Google Workspace):** create a service account in the same Cloud project, download its JSON key, add the service account as a Content manager on a Shared Drive folder, then set `GOOGLE_SERVICE_ACCOUNT_JSON` (the whole key file) and `DRIVE_ROOT_FOLDER_ID` (the folder ID from its URL) instead of the three OAuth secrets. Service accounts can't use a personal My Drive because they have no storage quota.

### 5. Test it

1. **Actions** tab > **Earnings sync** > **Run workflow**. Tick **dry run**, enter `JPM` as the ticker, and run.
2. Open the finished run: the summary lists everything it would download.
3. Run again without dry run. Files appear in Drive under `Earnings Calls/JPM/`.
4. Run with no ticker to process the whole list. After that, the schedule takes over.

GitHub emails you if a run fails.

---

## Editing `companies.json`

Edit it in the GitHub web editor (pencil icon); the next run picks it up.

```json
{
  "ticker": "NVDA",
  "name": "NVIDIA",
  "fiscalYearEndMonth": 1,
  "irPages": [
    { "url": "https://investor.nvidia.com/financial-info/quarterly-results/default.aspx", "render": true }
  ]
}
```

| Field | Meaning |
|---|---|
| `ticker` | Required. Used for folders and EDGAR lookup. |
| `fiscalYearEndMonth` | 1-12, month the fiscal year ends (Apple 9, Microsoft 6, NVIDIA 1). Default 12. |
| `cik` | SEC CIK, only if the ticker lookup fails (foreign or renamed companies). |
| `fmpSymbol` | Symbol FMP uses, if different from `ticker`. |
| `sources` | Turn sources off per company, e.g. `{ "ir": false }`. |
| `irPages[].url` | Page that links to the quarterly materials. The quarterly-results page is usually better than the IR home page. |
| `irPages[].render` | `true` for sites that build their links with JavaScript (most Q4 and Notified IR sites). Installs a headless Chromium on the run. |
| `irPages[].include` | Words a link (text, URL or surrounding text) must contain. Defaults cover transcript, earnings, results, presentation, webcast, supplement, Q1-Q4. |
| `irPages[].exclude` | Words that rule a link out (default: proxy, 10-K, 10-Q, ESG, governance and similar). |
| `irPages[].fileTypes` | Extensions to download. Default: pdf, mp3, m4a, mp4, xlsx, xls, pptx, docx, txt, csv. |

Global `settings`:

| Setting | Meaning |
|---|---|
| `sinceYear` | Ignore fiscal years before this. Keep it recent so the first run isn't huge. |
| `maxFileSizeMB` | Larger files (often webcast video) are skipped. |
| `convertHtmlToGoogleDocs` | EDGAR exhibits are HTML; this stores them as Google Docs. |
| `respectRobotsTxt` | Skips IR pages and files a site's robots.txt disallows. |
| `*.maxFilingsPerCompany`, `maxTranscriptsPerCompany`, `maxFilesPerPage` | Per-run caps per company. |

## Notes

- IR sites differ a lot. If a company's files land in `Unsorted`, the link text and URL didn't name the quarter; the file is still saved. If nothing is found, try the quarterly-results page URL and `"render": true`.
- Aggregator sites (Seeking Alpha, Motley Fool and similar) are deliberately not supported: their terms forbid scraping and their transcripts are copyrighted. FMP is the licensed route for transcripts.
- Some IR sites block automated traffic. Those pages show as errors in the run summary; EDGAR and FMP still cover the company.
