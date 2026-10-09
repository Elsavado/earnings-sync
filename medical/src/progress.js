// The data counter. After each run it counts every file medical-sync has put in Drive and
// writes two Google Sheets in "<private folder>":
//   counter   the current breakdown: each data type and its sub-types, with file counts,
//             storage and share of the total, plus a TOTAL row per type and overall
//   progress  history, newest first: files and GB per data type at each count
// The same breakdown is printed to the run log and the Actions summary.
import { appendFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from './config.js';
import { log } from './context.js';
import { createDriveStore } from './drive.js';
import { CATEGORIES } from './files.js';

const TYPES = Object.keys(CATEGORIES);
const GB = 1073741824;

export function tally(files) {
  const types = Object.fromEntries(TYPES.map((t) => [t, { files: 0, bytes: 0, subtypes: new Map() }]));
  const total = { files: 0, bytes: 0 };
  for (const f of files) {
    const t = types[f.appProperties?.mdCategory];
    if (!t) continue;
    // Archive folders tagged as finished, and _SOURCE.txt files from older runs, are not data.
    if (f.mimeType === 'application/vnd.google-apps.folder' || f.name === '_SOURCE.txt') continue;
    const size = Number(f.size || 0);
    const subName = f.appProperties?.mdSubtype || '(none)';
    const sub = t.subtypes.get(subName) || { files: 0, bytes: 0 };
    sub.files++;
    sub.bytes += size;
    t.subtypes.set(subName, sub);
    t.files++;
    t.bytes += size;
    total.files++;
    total.bytes += size;
  }
  return { types, total };
}

export function formatSize(bytes) {
  if (bytes >= GB) return `${(bytes / GB).toFixed(2)} GB`;
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

function share(part, whole) {
  return whole ? `${((100 * part) / whole).toFixed(1)}%` : '0.0%';
}

function cell(v) {
  const s = String(v ?? '');
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function counterCsv({ types, total }, when) {
  const rows = [['data_type', 'sub_type', 'files', 'storage', 'storage_gb', 'share_of_storage', 'counted_at_utc']];
  for (const t of TYPES) {
    const entry = types[t];
    const subs = [...entry.subtypes.entries()].sort((a, b) => b[1].bytes - a[1].bytes);
    for (const [name, s] of subs) rows.push([CATEGORIES[t], name, s.files, formatSize(s.bytes), (s.bytes / GB).toFixed(3), share(s.bytes, total.bytes), when]);
    rows.push([CATEGORIES[t], 'TOTAL', entry.files, formatSize(entry.bytes), (entry.bytes / GB).toFixed(3), share(entry.bytes, total.bytes), when]);
  }
  rows.push(['ALL DATA TYPES', 'TOTAL', total.files, formatSize(total.bytes), (total.bytes / GB).toFixed(3), '100.0%', when]);
  return `${rows.map((r) => r.map(cell).join(',')).join('\n')}\n`;
}

export function counterMarkdown({ types, total }) {
  const lines = ['| Data type | Sub-type | Files | Storage |', '|---|---|---:|---:|'];
  for (const t of TYPES) {
    const entry = types[t];
    lines.push(`| **${CATEGORIES[t]}** | | **${entry.files}** | **${formatSize(entry.bytes)}** |`);
    for (const [name, s] of [...entry.subtypes.entries()].sort((a, b) => b[1].bytes - a[1].bytes)) {
      lines.push(`| | ${name.replace(/\|/g, '\\|')} | ${s.files} | ${formatSize(s.bytes)} |`);
    }
  }
  lines.push(`| **All data types** | | **${total.files}** | **${formatSize(total.bytes)}** |`);
  return lines.join('\n');
}

async function main() {
  const settings = await loadConfig(process.env.CONFIG_PATH || 'medical.json');
  const store = await createDriveStore(settings);
  const counts = tally(await store.listAppFiles());
  const when = new Date().toISOString().replace('T', ' ').slice(0, 16);
  const folder = await store.ensureFolder('root', settings.drivePrivateFolderName);

  const counter = await store.writeSheet(folder, 'counter', counterCsv(counts, when));

  const header = ['counted_at_utc', 'total_files', 'total_gb', ...TYPES.flatMap((t) => [`${t}_files`, `${t}_gb`]), 'files_added_since_previous'];
  const existing = await store.findFile(folder, 'progress');
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
    when,
    counts.total.files,
    (counts.total.bytes / GB).toFixed(3),
    ...TYPES.flatMap((t) => [counts.types[t].files, (counts.types[t].bytes / GB).toFixed(3)]),
    previousRows.length ? counts.total.files - previousTotal : counts.total.files
  ];
  await store.writeSheet(folder, 'progress', `${[header.join(','), row.join(','), ...previousRows.slice(0, 5000)].join('\n')}\n`);

  log.info(`Counter: ${counts.total.files} files, ${formatSize(counts.total.bytes)} in total`);
  for (const t of TYPES) log.info(`  ${CATEGORIES[t]}: ${counts.types[t].files} files, ${formatSize(counts.types[t].bytes)}`);
  log.info(`Counter sheet: Google Drive > ${settings.drivePrivateFolderName} > counter (${counter.webViewLink})`);
  if (process.env.GITHUB_STEP_SUMMARY) {
    await appendFile(process.env.GITHUB_STEP_SUMMARY, `## Data counter (${when} UTC)\n\n${counterMarkdown(counts)}\n\n+${row[row.length - 1]} files since the previous count\n`);
  }
}

// Runs when started directly (node src/progress.js); tests import the functions only.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((err) => {
    log.error(err.message);
    process.exitCode = 1;
  });
}
