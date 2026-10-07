import { appendFile } from 'node:fs/promises';
import { loadConfig } from './config.js';
import { createContext, log } from './context.js';
import { createDriveStore, hasDriveCredentials } from './drive.js';
import { SkipError } from './http.js';
import { periodLabel } from './periods.js';
import { buildFileName, mimeForExtension, resolveExtension, sourceKey } from './files.js';
import { edgarItems } from './sources/edgar.js';
import { fmpItems } from './sources/fmp.js';
import { irItems } from './sources/ir.js';

const SOURCES = [
  { name: 'edgar', label: 'SEC EDGAR', collect: edgarItems },
  { name: 'fmp', label: 'Financial Modeling Prep', collect: fmpItems },
  { name: 'ir', label: 'IR pages', collect: irItems }
];

function truthy(value) {
  return /^(1|true|yes|on)$/i.test(String(value || '').trim());
}

function escapeCell(value) {
  return String(value).replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

async function writeStepSummary(report, dryRun) {
  const path = process.env.GITHUB_STEP_SUMMARY;
  if (!path) return;
  const lines = [`## Earnings sync ${dryRun ? '(dry run)' : ''}`, ''];
  lines.push(
    `Uploaded: **${report.uploaded.length}** | Already in Drive: **${report.alreadyStored}** | Skipped: **${report.skipped.length}** | Errors: **${report.errors.length}**`,
    ''
  );
  const rows = dryRun ? report.planned : report.uploaded;
  if (rows.length) {
    lines.push(dryRun ? '### Would upload' : '### Uploaded', '', '| Ticker | Period | Type | Source | File |', '|---|---|---|---|---|');
    for (const r of rows) {
      const file = r.link ? `[${escapeCell(r.name)}](${r.link})` : escapeCell(r.name);
      lines.push(`| ${r.ticker} | ${r.period} | ${r.docType} | ${r.source} | ${file} |`);
    }
    lines.push('');
  }
  if (report.skipped.length) {
    lines.push('### Skipped', '');
    for (const s of report.skipped) lines.push(`- ${escapeCell(s)}`);
    lines.push('');
  }
  if (report.errors.length) {
    lines.push('### Errors', '');
    for (const e of report.errors) lines.push(`- ${escapeCell(e)}`);
    lines.push('');
  }
  await appendFile(path, `${lines.join('\n')}\n`);
}

async function processItem({ item, company, settings, store, existingKeys, report, dryRun }) {
  const key = sourceKey(item.source, item.sourceId);
  if (existingKeys.has(key)) {
    report.alreadyStored++;
    return;
  }
  existingKeys.add(key);
  const period = periodLabel(item.period);

  if (dryRun) {
    report.planned.push({
      ticker: company.ticker,
      period,
      docType: item.docType,
      source: item.source,
      name: item.sourceUrl
    });
    return;
  }

  let file;
  try {
    file = await item.fetch();
  } catch (err) {
    existingKeys.delete(key);
    if (err instanceof SkipError) {
      report.skipped.push(`${company.ticker}: ${err.message}`);
      log.info(`${company.ticker}: skipped - ${err.message}`);
    } else {
      report.errors.push(`${company.ticker} (${item.source}): ${err.message}`);
      log.error(`${company.ticker} (${item.source}): ${err.message}`);
    }
    return;
  }

  const ext = resolveExtension({ url: file.url, dispositionName: file.dispositionName, contentType: file.contentType });
  const convertToGoogleDoc = settings.convertHtmlToGoogleDocs && (ext === 'htm' || ext === 'html');
  const name = buildFileName({
    ticker: company.ticker,
    periodLabel: period,
    docType: item.docType,
    hint: item.hint,
    ext: convertToGoogleDoc ? '' : ext
  });

  try {
    const tickerFolder = await store.ensureFolder(store.rootFolderId, company.ticker);
    const periodFolder = await store.ensureFolder(tickerFolder, period);
    const uploaded = await store.upload({
      folderId: periodFolder,
      name,
      buffer: file.buffer,
      mimeType: file.contentType && file.contentType !== 'application/octet-stream' ? file.contentType : mimeForExtension(ext),
      sourceKey: key,
      sourceUrl: item.sourceUrl,
      convertToGoogleDoc
    });
    report.uploaded.push({
      ticker: company.ticker,
      period,
      docType: item.docType,
      source: item.source,
      name: uploaded.name,
      link: uploaded.webViewLink
    });
    log.info(`${company.ticker}: uploaded ${company.ticker}/${period}/${uploaded.name}`);
  } catch (err) {
    existingKeys.delete(key);
    report.errors.push(`${company.ticker}: Drive upload failed for ${name}: ${err.message}`);
    log.error(`${company.ticker}: Drive upload failed for ${name}: ${err.message}`);
  }
}

async function main() {
  const configPath = process.env.CONFIG_PATH || 'companies.json';
  const { settings, companies } = await loadConfig(configPath);
  const dryRun = truthy(process.env.DRY_RUN);
  const tickerFilter = String(process.env.TICKERS || '')
    .split(/[\s,]+/)
    .filter(Boolean)
    .map((t) => t.toUpperCase());
  const selected = tickerFilter.length ? companies.filter((c) => tickerFilter.includes(c.ticker)) : companies;
  if (selected.length === 0) throw new Error(`None of the requested tickers (${tickerFilter.join(', ')}) are in ${configPath}`);

  const ctx = createContext();
  let store = null;
  let existingKeys = new Set();
  if (!dryRun || hasDriveCredentials()) {
    store = await createDriveStore(settings);
    existingKeys = await store.loadExistingSourceKeys();
    log.info(`Drive ready; ${existingKeys.size} file(s) already collected`);
  } else {
    log.info('Dry run without Drive credentials: everything found will be listed as new');
  }

  const report = { uploaded: [], planned: [], skipped: [], errors: [], alreadyStored: 0 };
  let sourceRuns = 0;
  let sourceFailures = 0;

  try {
    for (const company of selected) {
      log.info(`--- ${company.ticker} (${company.name}) ---`);
      for (const source of SOURCES) {
        if (!settings[source.name].enabled || !company.sources[source.name]) continue;
        if (source.name === 'ir' && company.irPages.length === 0) continue;
        sourceRuns++;
        let items;
        try {
          items = await source.collect(company, settings, ctx);
        } catch (err) {
          sourceFailures++;
          report.errors.push(`${company.ticker} (${source.label}): ${err.message}`);
          log.error(`${company.ticker} (${source.label}): ${err.message}`);
          continue;
        }
        for (const item of items) {
          await processItem({ item, company, settings, store, existingKeys, report, dryRun });
        }
      }
    }
  } finally {
    await ctx.close();
  }

  await writeStepSummary(report, dryRun);
  log.info(
    `Done. ${dryRun ? `Would upload ${report.planned.length}` : `Uploaded ${report.uploaded.length}`}, already in Drive ${report.alreadyStored}, skipped ${report.skipped.length}, errors ${report.errors.length}`
  );
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
