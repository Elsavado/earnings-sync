import { appendFile, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadConfig } from './config.js';
import { createContext, log } from './context.js';
import { createDriveStore, hasDriveCredentials } from './drive.js';
import { downloadToFile, SkipError } from './http.js';
import { CATEGORIES, extensionFromName, fileName, isArchiveClutter, mimeForExtension, resolveExtension, sourceKey } from './files.js';
import { forEachZipEntry, listZipFiles, stripCommonRoot } from './unzip.js';
import { buildLeads, leadsCsv, leadSitesFromCsv } from './leads.js';
import { europepmcItems } from './sources/europepmc.js';
import { ctgovItems } from './sources/ctgov.js';
import { tciaItems } from './sources/tcia.js';
import { isicItems } from './sources/isic.js';
import { gdcItems } from './sources/gdc.js';
import { physionetItems } from './sources/physionet.js';
import { githubItems } from './sources/github.js';
import { fileListItems } from './sources/files.js';
import { bucketItems } from './sources/buckets.js';
import { websiteItems } from './sources/websites.js';

const SOURCES = {
  europepmc: europepmcItems,
  ctgov: ctgovItems,
  tcia: tciaItems,
  isic: isicItems,
  gdc: gdcItems,
  physionet: physionetItems,
  github: githubItems,
  files: fileListItems,
  buckets: bucketItems,
  websites: websiteItems
};

const QUOTA_CHECK_EVERY = 25;

function truthy(value) {
  return /^(1|true|yes|on)$/i.test(String(value || '').trim());
}

function formatBytes(n) {
  return n >= 1073741824 ? `${(n / 1073741824).toFixed(2)} GB` : `${(n / 1048576).toFixed(1)} MB`;
}

function escapeCell(value) {
  return String(value).replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

function describe(item) {
  return [`Source: ${item.landing || item.url || ''}`, `Licence: ${item.license}`, `Attribution: ${item.attribution}`, 'Collected by medical-sync'].join('\n');
}

class Run {
  constructor({ settings, store, existingKeys, dryRun, ctx }) {
    this.settings = settings;
    this.store = store;
    this.existingKeys = existingKeys;
    this.dryRun = dryRun;
    this.ctx = ctx;
    this.report = ctx.report;
    const started = Number(process.env.JOB_STARTED) * 1000 || Date.now();
    this.deadline = settings.runBudgetMinutes ? started + settings.runBudgetMinutes * 60000 : Infinity;
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
      this.freeBytes = (await this.store.freeBytes(this.settings.driveReserveMB * 1048576)) ?? Infinity;
      this.uploadsSinceQuotaCheck = 0;
    }
    if (this.freeBytes < bytes) {
      this.report.stopReason = `Google Drive is within ${this.settings.driveReserveMB} MB of full; uploads stopped`;
      log.error(this.report.stopReason);
      return false;
    }
    return true;
  }

  async put({ path, name, filePath, buffer, stream, ext, key, item, bytes }) {
    const folderId = await this.store.ensurePath(path);
    const uploaded = await this.store.upload({
      folderId,
      name,
      filePath,
      buffer,
      stream,
      mimeType: mimeForExtension(ext),
      sourceKey: key,
      category: item.category,
      // The first folder below the data type, e.g. "Whole-slide images" or "Apple Watch".
      subtype: path[1] || '',
      description: describe(item)
    });
    this.existingKeys.add(key);
    this.freeBytes -= bytes;
    this.uploadsSinceQuotaCheck++;
    this.report.bytes += bytes;
    this.report.uploaded.push({ category: item.category, source: item.source, name: uploaded.name, path: path.join(' / '), link: uploaded.webViewLink });
    return uploaded;
  }

  // Unpacks a downloaded archive into <path>/<item folder>/..., one Drive file per entry.
  // Checksum lists, licence copies and OS leftovers are not data and are left out. Once every
  // entry is stored, the folder itself is tagged with the item's key, so a later run skips
  // the archive without downloading it again.
  async putArchive(item, key, zipPath, basePath) {
    const names = (await listZipFiles(zipPath)).filter((n) => !isArchiveClutter(n));
    const root = stripCommonRoot(names);
    let stored = 0;
    let complete = true;
    await forEachZipEntry(zipPath, async (entry, open) => {
      if (this.stopped) {
        complete = false;
        return false;
      }
      if (isArchiveClutter(entry.fileName)) return true;
      const entryKey = sourceKey(item.source, `${item.id}#${entry.fileName}`);
      if (this.existingKeys.has(entryKey)) return true;
      if (!(await this.roomFor(entry.uncompressedSize))) {
        complete = false;
        return false;
      }
      const rel = entry.fileName.slice(root.length).split('/');
      const name = rel.pop();
      const stream = await open();
      try {
        await this.put({ path: [...basePath, ...rel], name, stream, ext: extensionFromName(name), key: entryKey, item, bytes: entry.uncompressedSize });
        stored++;
      } catch (err) {
        complete = false;
        this.report.errors.push(`${item.source}: upload failed for ${entry.fileName}: ${err.message}`);
        log.error(`${item.source}: upload failed for ${entry.fileName}: ${err.message}`);
      }
      return true;
    });
    if (complete) {
      await this.store.markFolderDone(await this.store.ensurePath(basePath), key);
      this.existingKeys.add(key);
    }
    log.info(`${item.source}: ${basePath.join(' / ')}: ${stored} file(s) stored${complete ? '' : ', archive not finished; the next run continues'}`);
    return complete;
  }

  async processItem(item) {
    const { report, settings } = this;
    const key = sourceKey(item.source, item.id);
    if (this.existingKeys.has(key)) {
      report.alreadyStored++;
      return;
    }
    const top = CATEGORIES[item.category];
    if (!top) {
      report.skipped.push(`${item.source} ${item.id}: not one of the eight data types`);
      return;
    }
    const uid = key.slice(0, 6);
    if (this.dryRun) {
      this.existingKeys.add(key);
      report.planned.push({ category: item.category, source: item.source, name: item.title || item.id, path: [top, ...item.path].join(' / '), link: item.landing || item.url });
      return;
    }

    if (item.content) {
      if (!(await this.roomFor(item.content.length))) return;
      const name = fileName({ prefix: item.prefix, title: item.title, uid, ext: item.ext });
      await this.put({ path: [top, ...item.path], name, buffer: item.content, ext: item.ext, key, item, bytes: item.content.length });
      return;
    }

    if (item.size && !(await this.roomFor(item.size))) return;
    const tmp = join(tmpdir(), `medical-sync-${key}`);
    try {
      let file;
      try {
        file = await downloadToFile(item.url, tmp, {
          headers: item.headers,
          maxBytes: item.maxBytes || settings.maxFileSizeMB * 1048576,
          minIntervalMs: item.minIntervalMs
        });
      } catch (err) {
        if (err instanceof SkipError) report.skipped.push(`${item.source}: ${err.message}`);
        else {
          report.errors.push(`${item.source} ${item.id}: ${err.message}`);
          log.error(`${item.source} ${item.id}: ${err.message}`);
        }
        return;
      }
      if (item.expectType && !file.contentType.includes(item.expectType.split('/')[1])) {
        report.skipped.push(`${item.source} ${item.id}: served ${file.contentType || 'unknown type'}, not ${item.expectType}`);
        return;
      }
      const ext = extensionFromName(item.fileName) || resolveExtension({ ext: item.ext, dispositionName: file.dispositionName, url: file.finalUrl, contentType: file.contentType });
      // Files whose own name already says what they are (e.g. a collection's clinical table) keep it.
      const name = item.keepName && item.fileName ? item.fileName : fileName({ prefix: item.prefix, title: item.title, uid, ext });
      if (item.unzip && ext === 'zip') {
        await this.putArchive(item, key, tmp, [top, ...item.path, item.folderName || name.replace(/\.zip$/, '')]);
        return;
      }
      if (!(await this.roomFor(file.bytes))) return;
      await this.put({ path: [top, ...item.path], name, filePath: tmp, ext, key, item, bytes: file.bytes });
    } catch (err) {
      report.errors.push(`${item.source} ${item.id}: ${err.message}`);
      log.error(`${item.source} ${item.id}: ${err.message}`);
    } finally {
      await rm(tmp, { force: true }).catch(() => {});
    }
  }
}

async function writeStepSummary(report, dryRun, label) {
  const path = process.env.GITHUB_STEP_SUMMARY;
  if (!path) return;
  const lines = [`## Medical sync: ${label}${dryRun ? ' (dry run)' : ''}`, ''];
  lines.push(
    `${dryRun ? 'Would upload' : 'Uploaded'}: **${dryRun ? report.planned.length : report.uploaded.length}**${dryRun ? '' : ` (${formatBytes(report.bytes)})`} | Already in Drive: **${report.alreadyStored}** | Skipped: **${report.skipped.length}** | Errors: **${report.errors.length}**`,
    ''
  );
  if (report.stopReason) lines.push(`**Stopped early:** ${report.stopReason}`, '');
  const rows = dryRun ? report.planned : report.uploaded;
  if (rows.length) {
    lines.push('| Type | Folder | File |', '|---|---|---|');
    for (const r of rows.slice(0, 300)) lines.push(`| ${r.category} | ${escapeCell(r.path)} | ${r.link ? `[${escapeCell(r.name)}](${r.link})` : escapeCell(r.name)} |`);
    if (rows.length > 300) lines.push('', `...and ${rows.length - 300} more`);
    lines.push('');
  }
  for (const [title, list] of [['Skipped', report.skipped], ['Errors', report.errors]]) {
    if (!list.length) continue;
    lines.push(`### ${title}`, '', ...list.slice(0, 200).map((s) => `- ${escapeCell(s)}`), '');
  }
  await appendFile(path, `${lines.join('\n')}\n`);
}

async function runLeads(settings, store, ctx, dryRun) {
  const rows = await buildLeads(settings, ctx);
  log.info(`Company leads: ${rows.length} healthcare companies mention one or more of the data types`);
  if (!store || dryRun) {
    for (const r of rows.slice(0, 40)) log.info(`  ${r.ticker || '-'} ${r.name}: ${[...r.categories, ...r.conferences].join(', ')}; next call ${r.nextCall || 'n/a'}`);
    return;
  }
  const folder = await store.ensureFolder('root', settings.drivePrivateFolderName);
  const sheet = await store.writeSheet(folder, 'company-leads', leadsCsv(rows));
  log.info(`Company leads written to Google Drive > ${settings.drivePrivateFolderName} > company-leads (${sheet.webViewLink})`);
  if (process.env.GITHUB_STEP_SUMMARY) {
    await appendFile(process.env.GITHUB_STEP_SUMMARY, `## Company leads\n\n${rows.length} companies; sheet: ${settings.drivePrivateFolderName}/company-leads\n`);
  }
}

async function leadSites(settings, store) {
  if (!store || !settings.websites.fromLeads) return [];
  const folder = await store.ensureFolder('root', settings.drivePrivateFolderName);
  // The company websites are read straight from the company-leads sheet.
  const csv = await store.readSheetCsv(folder, 'company-leads');
  return csv ? leadSitesFromCsv(csv).slice(0, settings.websites.maxLeadSites) : [];
}

async function main() {
  const settings = await loadConfig(process.env.CONFIG_PATH || 'medical.json');
  const dryRun = truthy(process.env.DRY_RUN);
  const wanted = String(process.env.SOURCE || 'all').split(/[\s,]+/).filter(Boolean);
  const names = wanted.includes('all') ? ['leads', ...Object.keys(SOURCES)] : wanted;
  for (const n of names) if (n !== 'leads' && !SOURCES[n]) throw new Error(`Unknown source "${n}"; use one of leads, ${Object.keys(SOURCES).join(', ')}`);
  const label = names.join(', ');

  const ctx = createContext();
  ctx.report = { uploaded: [], planned: [], skipped: [], errors: [], alreadyStored: 0, bytes: 0, stopReason: null };
  ctx.stats = { licenseSkipped: 0, sizeSkipped: 0 };

  let store = null;
  let existingKeys = new Set();
  if (!dryRun || hasDriveCredentials()) {
    store = await createDriveStore(settings);
    existingKeys = await store.loadExistingSourceKeys();
    log.info(`Drive ready; ${existingKeys.size} file(s) already collected`);
  } else {
    log.info('Dry run without Drive credentials: everything found is listed as new');
  }

  const stateDir = process.env.STATE_DIR || '.state';
  const statePath = join(stateDir, `${names.join('+')}.json`);
  try {
    ctx.state = JSON.parse(await readFile(statePath, 'utf8'));
  } catch {
    ctx.state = {};
  }
  // Restart every listing from the top now and then, to pick up new studies, papers and series.
  if (!ctx.state.startedAt || Date.now() - ctx.state.startedAt > settings.rescanDays * 86400000) ctx.state = { startedAt: Date.now() };
  const saveState = async () => {
    if (dryRun) return;
    try {
      await mkdir(stateDir, { recursive: true });
      await writeFile(statePath, JSON.stringify(ctx.state));
    } catch (err) {
      log.warn(`Could not save run state: ${err.message}`);
    }
  };

  const run = new Run({ settings, store, existingKeys, dryRun, ctx });
  const dryLimit = Number(process.env.DRY_RUN_LIMIT || 25);
  try {
    for (const name of names) {
      if (run.stopped) break;
      if (!settings[name].enabled) continue;
      if (name === 'leads') {
        try {
          await runLeads(settings, store, ctx, dryRun);
        } catch (err) {
          ctx.report.errors.push(`leads: ${err.message}`);
          log.error(`leads: ${err.message}`);
        }
        continue;
      }
      log.info(`--- ${name} ---`);
      if (name === 'websites') settings.websites.sites = [...settings.websites.sites, ...(await leadSites(settings, store))];
      const before = ctx.report.planned.length;
      try {
        for await (const item of SOURCES[name](settings, ctx)) {
          if (run.stopped) break;
          await run.processItem(item);
          if (dryRun && ctx.report.planned.length - before >= dryLimit) break;
        }
      } catch (err) {
        ctx.report.errors.push(`${name}: ${err.message}`);
        log.error(`${name}: ${err.message}`);
      }
      await saveState();
    }
  } finally {
    await ctx.close();
    await saveState();
  }

  const { report } = ctx;
  if (dryRun) for (const p of report.planned) log.info(`would upload: ${p.path} :: ${p.name}`);
  await writeStepSummary(report, dryRun, label);
  log.info(
    `Done. ${dryRun ? `Would upload ${report.planned.length}` : `Uploaded ${report.uploaded.length} (${formatBytes(report.bytes)})`}, already in Drive ${report.alreadyStored}, skipped ${report.skipped.length} (+${ctx.stats.licenseSkipped} by licence, ${ctx.stats.sizeSkipped} by size), errors ${report.errors.length}`
  );
  for (const s of report.skipped.slice(0, 20)) log.info(`skipped: ${s}`);
  for (const e of report.errors.slice(0, 20)) log.info(`error: ${e}`);
  if (!dryRun && /time budget/.test(report.stopReason || '') && report.uploaded.length > 0) {
    await mkdir('.signal', { recursive: true });
    await writeFile(join('.signal', `more-work-${names.join('+')}`), '1');
  }
}

main().catch(async (err) => {
  log.error(err.message);
  if (process.env.GITHUB_STEP_SUMMARY) await appendFile(process.env.GITHUB_STEP_SUMMARY, `## Medical sync failed\n\n${err.message}\n`).catch(() => {});
  process.exitCode = 1;
});
