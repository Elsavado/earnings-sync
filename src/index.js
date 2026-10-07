import { appendFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { loadConfig } from './config.js';
import { createContext, log } from './context.js';
import { createDriveStore, DATA_VERSION, hasDriveCredentials } from './drive.js';
import { SkipError } from './http.js';
import { periodLabel } from './periods.js';
import { mimeForExtension, resolveExtension, smartFileName, sourceKey } from './files.js';
import { Anonymizer, assignCodes, scrubHint } from './anonymize.js';
import { edgarItems } from './sources/edgar.js';
import { fmpItems } from './sources/fmp.js';
import { irItems } from './sources/ir.js';

const SOURCES = [
  { name: 'edgar', label: 'SEC EDGAR', collect: edgarItems },
  { name: 'fmp', label: 'Financial Modeling Prep', collect: fmpItems },
  { name: 'ir', label: 'IR pages', collect: irItems }
];

const STATE_SAVE_EVERY_MS = 5 * 60 * 1000;
const QUOTA_CHECK_EVERY = 25;
// Only documents reach Drive. HTML is printed to PDF; CSV, TXT and legacy Office files are converted.
const UPLOAD_TYPES = new Set(['pdf', 'xlsx', 'xlsm', 'docx', 'pptx']);

function truthy(value) {
  return /^(1|true|yes|on)$/i.test(String(value || '').trim());
}

function escapeCell(value) {
  return String(value).replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

function shardOf(ticker, count) {
  return createHash('sha1').update(ticker).digest().readUInt32BE(0) % count;
}

function formatBytes(n) {
  return n >= 1073741824 ? `${(n / 1073741824).toFixed(2)} GB` : `${(n / 1048576).toFixed(1)} MB`;
}

async function writeStepSummary(report, dryRun, shardLabel) {
  const path = process.env.GITHUB_STEP_SUMMARY;
  if (!path) return;
  const lines = [`## Earnings sync ${shardLabel}${dryRun ? ' (dry run)' : ''}`, ''];
  lines.push(
    `Uploaded: **${report.uploaded.length}** (${formatBytes(report.bytes)}) | Already in Drive: **${report.alreadyStored}** | Skipped: **${report.skipped.length}** | Errors: **${report.errors.length}**`,
    ''
  );
  if (report.stopReason) lines.push(`**Stopped early:** ${report.stopReason}`, '');
  const rows = dryRun ? report.planned : report.uploaded;
  if (rows.length) {
    lines.push(dryRun ? '### Would upload' : '### Uploaded', '', '| Ticker | Period | Type | Source | File |', '|---|---|---|---|---|');
    for (const r of rows.slice(0, 500)) {
      const file = r.link ? `[${escapeCell(r.name)}](${r.link})` : escapeCell(r.name);
      lines.push(`| ${r.ticker} | ${r.period} | ${r.docType} | ${r.source} | ${file} |`);
    }
    if (rows.length > 500) lines.push('', `...and ${rows.length - 500} more`);
    lines.push('');
  }
  if (report.skipped.length) {
    lines.push('### Skipped', '');
    for (const s of report.skipped.slice(0, 200)) lines.push(`- ${escapeCell(s)}`);
    lines.push('');
  }
  if (report.errors.length) {
    lines.push('### Errors', '');
    for (const e of report.errors.slice(0, 200)) lines.push(`- ${escapeCell(e)}`);
    lines.push('');
  }
  await appendFile(path, `${lines.join('\n')}\n`);
}

class Run {
  constructor({ settings, store, existingKeys, dryRun, anonymizer, ctx }) {
    this.settings = settings;
    this.ctx = ctx;
    this.store = store;
    this.existingKeys = existingKeys;
    this.dryRun = dryRun;
    this.anonymizer = anonymizer;
    this.hideCodes = settings.anonymize.enabled;
    this.report = { uploaded: [], planned: [], skipped: [], errors: [], alreadyStored: 0, bytes: 0, stopReason: null };
    this.deadline = settings.runBudgetMinutes ? Date.now() + settings.runBudgetMinutes * 60000 : Infinity;
    this.freeBytes = null;
    this.uploadsSinceQuotaCheck = QUOTA_CHECK_EVERY;
  }

  get stopped() {
    if (this.report.stopReason) return true;
    if (Date.now() > this.deadline) {
      this.report.stopReason = `time budget of ${this.settings.runBudgetMinutes} min reached; the next run continues`;
      log.info(this.report.stopReason);
      return true;
    }
    return false;
  }

  async roomFor(bytes) {
    if (this.uploadsSinceQuotaCheck >= QUOTA_CHECK_EVERY || this.freeBytes === null) {
      this.freeBytes = await this.store.freeBytes(this.settings.driveReserveMB * 1048576);
      this.uploadsSinceQuotaCheck = 0;
      if (this.freeBytes === null) this.freeBytes = Infinity;
    }
    if (this.freeBytes < bytes) {
      this.report.stopReason = `Google Drive is within ${this.settings.driveReserveMB} MB of full; uploads stopped`;
      log.error(this.report.stopReason);
      return false;
    }
    return true;
  }

  // Returns true when the item ended in a state that should not be retried
  // (stored, already stored, or skipped on purpose); false when it should be retried.
  async processItem(item, company) {
    const { report, settings } = this;
    const key = sourceKey(`${DATA_VERSION}|${item.source}`, item.sourceId);
    if (this.existingKeys.has(key)) {
      report.alreadyStored++;
      return true;
    }
    const period = periodLabel(item.period);

    if (this.dryRun) {
      this.existingKeys.add(key);
      report.planned.push({ ticker: company.ticker, period, docType: item.docType, source: item.source, name: item.sourceUrl });
      return true;
    }

    let file;
    try {
      file = await item.fetch();
    } catch (err) {
      if (err instanceof SkipError) {
        report.skipped.push(`${company.ticker}: ${err.message}`);
        return true;
      }
      report.errors.push(`${company.ticker} (${item.source}): ${err.message}`);
      log.error(`${company.ticker} (${item.source}): ${err.message}`);
      return false;
    }

    let ext = resolveExtension({ url: file.url, dispositionName: file.dispositionName, contentType: file.contentType });
    let buffer = file.buffer;
    let contentType = file.contentType;
    if (this.anonymizer) {
      try {
        const clean = await this.anonymizer.process(buffer, ext, company.ticker);
        if (clean.ext !== ext) contentType = '';
        ({ buffer, ext } = clean);
      } catch (err) {
        report.errors.push(`${company.ticker}: not uploaded, ${err.message} (${item.sourceUrl})`);
        log.error(`${company.ticker}: not uploaded, ${err.message}`);
        return /no anonymiser for/.test(err.message);
      }
    }

    if (ext === 'htm' || ext === 'html') {
      try {
        buffer = await this.ctx.htmlToPdf(buffer);
        ext = 'pdf';
        contentType = 'application/pdf';
      } catch (err) {
        report.errors.push(`${company.ticker}: not uploaded, PDF conversion failed: ${err.message} (${item.sourceUrl})`);
        log.error(`${company.ticker}: PDF conversion failed: ${err.message}`);
        return false;
      }
    }
    if (!UPLOAD_TYPES.has(ext)) {
      report.skipped.push(`${company.ticker}: .${ext} is not a document type that is uploaded (${item.sourceUrl})`);
      return true;
    }

    if (!(await this.roomFor(buffer.length))) return false;

    const name = smartFileName({
      code: company.code,
      periodLabel: period,
      docType: item.docType,
      date: item.date,
      hint: settings.anonymize.enabled ? scrubHint(item.hint, company) : item.hint,
      uid: key.slice(0, 6),
      ext
    });

    try {
      const tickerFolder = await this.store.ensureFolder(this.store.rootFolderId, company.code);
      const periodFolder = await this.store.ensureFolder(tickerFolder, period);
      const uploaded = await this.store.upload({
        folderId: periodFolder,
        name,
        buffer,
        mimeType: contentType && contentType !== 'application/octet-stream' ? contentType : mimeForExtension(ext),
        sourceKey: key,
        convertToGoogleDoc: false
      });
      this.existingKeys.add(key);
      this.freeBytes -= buffer.length;
      this.uploadsSinceQuotaCheck++;
      report.bytes += buffer.length;
      // Actions logs are public: never print a code next to its ticker.
      const shown = this.hideCodes ? `${period} ${item.docType} .${ext}` : `${company.code}/${period}/${uploaded.name}`;
      report.uploaded.push({ ticker: company.ticker, period, docType: item.docType, source: item.source, name: this.hideCodes ? `.${ext}` : uploaded.name, link: this.hideCodes ? null : uploaded.webViewLink });
      log.info(`${company.ticker}: uploaded ${shown} (${formatBytes(buffer.length)})`);
      return true;
    } catch (err) {
      const shown = this.hideCodes ? `${period} ${item.docType}` : name;
      report.errors.push(`${company.ticker}: Drive upload failed for ${shown}: ${err.message}`);
      log.error(`${company.ticker}: Drive upload failed for ${shown}: ${err.message}`);
      return false;
    }
  }
}

async function main() {
  const configPath = process.env.CONFIG_PATH || 'companies.json';
  const { settings, companies } = await loadConfig(configPath);
  const dryRun = truthy(process.env.DRY_RUN);
  const shardCount = Math.max(1, Number(process.env.SHARD_COUNT || 1));
  const shardIndex = Number(process.env.SHARD_INDEX || 0);
  const shardLabel = shardCount > 1 ? `shard ${shardIndex + 1}/${shardCount}` : '';

  const anonKey = process.env.ANON_KEY || '';
  if (settings.anonymize.enabled && !anonKey && !dryRun) {
    throw new Error('ANON_KEY is not set. Anonymisation needs it to turn tickers into private company codes');
  }
  assignCodes(companies, anonKey || 'dry-run');

  const tickerFilter = String(process.env.TICKERS || '')
    .split(/[\s,]+/)
    .filter(Boolean)
    .map((t) => t.toUpperCase());
  const selected = (tickerFilter.length ? companies.filter((c) => tickerFilter.includes(c.ticker)) : companies).filter(
    (c) => shardOf(c.ticker, shardCount) === shardIndex
  );
  if (tickerFilter.length && !companies.some((c) => tickerFilter.includes(c.ticker))) {
    throw new Error(`None of the requested tickers (${tickerFilter.join(', ')}) are in ${configPath}`);
  }
  log.info(`${shardLabel || 'Run'}: ${selected.length} compan${selected.length === 1 ? 'y' : 'ies'}: ${selected.map((c) => c.ticker).join(', ')}`);

  const ctx = createContext();
  ctx.stats = { filingsSkipped: 0 };
  let store = null;
  let existingKeys = new Set();
  // Run state lives on the runner and is carried between runs by the Actions cache,
  // so no bookkeeping files end up in Drive.
  const stateDir = process.env.STATE_DIR || '.state';
  const statePath = join(stateDir, `shard-${shardIndex + 1}-of-${shardCount}.json`);
  try {
    ctx.state = JSON.parse(await readFile(statePath, 'utf8'));
  } catch {
    ctx.state = {};
  }
  if (!dryRun || hasDriveCredentials()) {
    store = await createDriveStore(settings);
    existingKeys = await store.loadExistingSourceKeys();
    log.info(`Drive ready; ${existingKeys.size} file(s) already collected`);
  } else {
    log.info('Dry run without Drive credentials: everything found will be listed as new');
  }
  ctx.doneFilings = new Set(ctx.state.doneFilings || []);

  const saveState = async () => {
    if (!store || dryRun) return;
    ctx.state.doneFilings = [...ctx.doneFilings];
    ctx.state.savedAt = new Date().toISOString();
    try {
      await mkdir(stateDir, { recursive: true });
      await writeFile(statePath, JSON.stringify(ctx.state));
    } catch (err) {
      log.warn(`Could not save run state: ${err.message}`);
    }
  };

  if (store && !dryRun && settings.anonymize.enabled && shardIndex === 0) {
    const csv = [
      'code,ticker,name,cik,fictional_name,fictional_ticker',
      ...companies.map((c) => [c.code, c.ticker, `"${c.name.replace(/"/g, '""')}"`, c.ciks.join(' '), c.fake.name, c.fake.ticker].join(','))
    ].join('\n');
    const hash = createHash('sha1').update(csv).digest('hex');
    const privateFolder = await store.ensureFolder('root', settings.drivePrivateFolderName);
    if (await store.writeKeySheet(privateFolder, 'company-key', `${csv}\n`, hash)) {
      log.info(`Company code key written to the Google Sheet "${settings.drivePrivateFolderName}/company-key"`);
    }
  }

  const anonymizer =
    settings.anonymize.enabled && !dryRun
      ? new Anonymizer({
          companies,
          companyIdentity: settings.anonymize.companyIdentity,
          personalInfo: settings.anonymize.personalInfo,
          log
        })
      : null;
  if (anonymizer) await anonymizer.start();

  const run = new Run({ settings, store, existingKeys, dryRun, anonymizer, ctx });
  let sourceRuns = 0;
  let sourceFailures = 0;
  let lastSave = Date.now();

  try {
    outer: for (const company of selected) {
      log.info(`--- ${company.ticker} (${company.name}) ---`);
      for (const source of SOURCES) {
        if (run.stopped) break outer;
        if (!settings[source.name].enabled || !company.sources[source.name]) continue;
        if (source.name === 'ir' && company.irPages.length === 0) continue;
        sourceRuns++;
        let groupOk = true;
        try {
          const items = await source.collect(company, settings, ctx);
          for await (const item of items) {
            if (item.groupDone) {
              if (groupOk && !dryRun) ctx.doneFilings.add(item.groupDone);
              groupOk = true;
              if (Date.now() - lastSave > STATE_SAVE_EVERY_MS) {
                lastSave = Date.now();
                await saveState();
              }
              continue;
            }
            if (run.stopped) break outer;
            const ok = await run.processItem(item, company);
            if (!ok) groupOk = false;
          }
        } catch (err) {
          sourceFailures++;
          run.report.errors.push(`${company.ticker} (${source.label}): ${err.message}`);
          log.error(`${company.ticker} (${source.label}): ${err.message}`);
        }
      }
    }
  } finally {
    await ctx.close();
    await anonymizer?.close();
    await saveState();
  }

  const { report } = run;
  await writeStepSummary(report, dryRun, shardLabel);
  log.info(
    `Done. ${dryRun ? `Would upload ${report.planned.length}` : `Uploaded ${report.uploaded.length} (${formatBytes(report.bytes)})`}, already in Drive ${report.alreadyStored}, filings already complete ${ctx.stats.filingsSkipped}, skipped ${report.skipped.length}, errors ${report.errors.length}`
  );
  // Tells the workflow to start another run straight away: this shard stopped at its
  // time budget with work left and is making progress (so a stuck shard cannot loop).
  if (!dryRun && /time budget/.test(report.stopReason || '') && report.uploaded.length + report.skipped.length > 0) {
    await mkdir('.signal', { recursive: true });
    await writeFile(join('.signal', `more-work-${shardIndex}`), '1');
  }
  if (sourceRuns > 0 && sourceFailures === sourceRuns) {
    log.error('Every source failed for every company; check credentials and URLs');
    process.exitCode = 1;
  }
}

main().catch(async (err) => {
  log.error(err.message);
  const path = process.env.GITHUB_STEP_SUMMARY;
  if (path) await appendFile(path, `## Earnings sync failed\n\n${err.message}\n`).catch(() => {});
  process.exitCode = 1;
});
