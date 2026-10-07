// Counts the documents in Drive after each run and adds a row to the Google Sheet
// "<private folder>/progress" (newest first), so the totals can be followed as they grow.
// Public logs only show totals.
import { appendFile } from 'node:fs/promises';
import { Readable } from 'node:stream';
import { loadConfig } from './config.js';
import { log } from './context.js';
import { createDriveStore, DATA_VERSION } from './drive.js';

const SHEET = 'progress';
const HEADER = ['updated_at_utc', 'total_files', 'total_gb', 'companies_with_files', 'pdf', 'xlsx', 'docx', 'pptx', 'added_since_previous_row'];

const { settings } = await loadConfig(process.env.CONFIG_PATH || 'companies.json');
const store = await createDriveStore(settings);
const files = (await store.listAppFiles()).filter((f) => f.appProperties?.irApp === 'earnings-sync' && f.appProperties?.irVersion === DATA_VERSION);

const byExt = { pdf: 0, xlsx: 0, docx: 0, pptx: 0 };
const codes = new Set();
let bytes = 0;
for (const f of files) {
  const ext = f.name.split('.').pop().toLowerCase();
  byExt[ext === 'xlsm' ? 'xlsx' : ext] = (byExt[ext === 'xlsm' ? 'xlsx' : ext] || 0) + 1;
  codes.add(f.name.split('_')[0]);
  bytes += Number(f.size || 0);
}

const folder = await store.ensureFolder('root', settings.drivePrivateFolderName);
const existing = await store.findPrivateFile(folder, SHEET);
let previousRows = [];
if (existing) {
  try {
    const res = await store.drive.files.export({ fileId: existing.id, mimeType: 'text/csv' }, { responseType: 'text' });
    previousRows = String(res.data).trim().split(/\r?\n/).slice(1).filter(Boolean);
  } catch (err) {
    log.warn(`Could not read the existing progress sheet: ${err.message}`);
  }
}
const previousTotal = Number((previousRows[0] || '').split(',')[1]) || 0;
const row = [
  new Date().toISOString().replace('T', ' ').slice(0, 16),
  files.length,
  (bytes / 1073741824).toFixed(2),
  codes.size,
  byExt.pdf,
  byExt.xlsx,
  byExt.docx,
  byExt.pptx,
  previousRows.length ? files.length - previousTotal : files.length
];
const csv = [HEADER.join(','), row.join(','), ...previousRows.slice(0, 5000)].join('\n');

// Replace the sheet's content in place (Drive converts the CSV); create it the first time.
const media = { mimeType: 'text/csv', body: Readable.from(Buffer.from(`${csv}\n`, 'utf8')) };
let sheet;
if (existing) {
  sheet = (await store.drive.files.update({ fileId: existing.id, media, fields: 'id, webViewLink', supportsAllDrives: true })).data;
} else {
  sheet = (
    await store.drive.files.create({
      requestBody: { name: SHEET, parents: [folder], mimeType: 'application/vnd.google-apps.spreadsheet', appProperties: { irPrivate: '1' } },
      media,
      fields: 'id, webViewLink',
      supportsAllDrives: true
    })
  ).data;
}
// The link only opens for the Drive owner, so it is safe in the public log.
const where = `Google Drive > My Drive > ${settings.drivePrivateFolderName} > ${SHEET} (${sheet.webViewLink})`;

const line = `${files.length} files, ${row[2]} GB, ${codes.size} companies (PDF ${byExt.pdf}, Excel ${byExt.xlsx}, Word ${byExt.docx}, PowerPoint ${byExt.pptx}); +${row[8]} since the previous count`;
log.info(`Progress: ${line}`);
log.info(`Progress sheet: ${where}`);
if (process.env.GITHUB_STEP_SUMMARY) {
  await appendFile(process.env.GITHUB_STEP_SUMMARY, `## Files in Drive\n\n${line}\n`);
}
