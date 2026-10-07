// One-off cleanup: removes files this app put in Drive that are not documents
// (HTML, CSV, JSON, TXT, Google Docs converted from HTML), then folders left empty.
// The sync collects those sources again as PDF/XLSX/DOCX. It only ever sees files
// the app created itself (drive.file scope). Logs show counts, never file names.
import { loadConfig } from './config.js';
import { log } from './context.js';
import { createDriveStore, DATA_VERSION } from './drive.js';

const FOLDER = 'application/vnd.google-apps.folder';
const GOOGLE_DOC = 'application/vnd.google-apps.document';
const UNWANTED_EXT = /\.(htm|html|csv|json|txt)$/i;

function unwanted(file) {
  if (file.mimeType === FOLDER) return false;
  if (file.appProperties?.irPrivate === '1' && file.mimeType === 'application/vnd.google-apps.spreadsheet') return false;
  // Documents from an older naming/anonymisation version are collected again in the current one.
  if (file.appProperties?.irApp === 'earnings-sync' && file.appProperties?.irVersion !== DATA_VERSION) return true;
  return UNWANTED_EXT.test(file.name) || file.mimeType === GOOGLE_DOC || file.mimeType === 'text/html' || file.mimeType === 'text/csv' || file.mimeType === 'application/json';
}

const dryRun = /^(1|true|yes)$/i.test(process.env.DRY_RUN || '');
const { settings } = await loadConfig(process.env.CONFIG_PATH || 'companies.json');
const store = await createDriveStore(settings);
const files = await store.listAppFiles();
const doomed = files.filter(unwanted);

const byType = {};
let bytes = 0;
for (const f of doomed) {
  const old = f.appProperties?.irApp === 'earnings-sync' && f.appProperties?.irVersion !== DATA_VERSION;
  const type = old ? 'older-version' : f.mimeType === GOOGLE_DOC ? 'google-doc' : (f.name.match(UNWANTED_EXT)?.[1] || f.mimeType).toLowerCase();
  byType[type] = (byType[type] || 0) + 1;
  bytes += Number(f.size || 0);
}
log.info(`${files.length} app file(s) in Drive; ${doomed.length} to remove (${(bytes / 1048576).toFixed(1)} MB): ${JSON.stringify(byType)}`);

let deleted = 0;
if (!dryRun) {
  for (const f of doomed) {
    try {
      await store.deleteFile(f.id);
      deleted++;
    } catch (err) {
      log.warn(`Could not delete one file: ${err.message}`);
    }
  }
}

// Remove folders that are now empty (for example the old ticker-named JPM folder),
// but never the dataset root or the private folder.
const gone = new Set(dryRun ? [] : doomed.map((f) => f.id));
const keep = new Set([store.rootFolderId]);
const remaining = files.filter((f) => !gone.has(f.id));
let foldersRemoved = 0;
for (let pass = 0; pass < 4; pass++) {
  const parents = new Set(remaining.filter((f) => !gone.has(f.id)).flatMap((f) => f.parents || []));
  const empty = remaining.filter(
    (f) => f.mimeType === FOLDER && !gone.has(f.id) && !keep.has(f.id) && !parents.has(f.id) && f.name !== settings.drivePrivateFolderName
  );
  if (!empty.length) break;
  for (const f of empty) {
    if (!dryRun) {
      try {
        await store.deleteFile(f.id);
      } catch (err) {
        log.warn(`Could not delete one folder: ${err.message}`);
        continue;
      }
    }
    gone.add(f.id);
    foldersRemoved++;
  }
  if (dryRun) break;
}
log.info(`${dryRun ? 'Dry run: would remove' : 'Removed'} ${dryRun ? doomed.length : deleted} file(s) and ${foldersRemoved} empty folder(s)`);
const summary = process.env.GITHUB_STEP_SUMMARY;
if (summary) {
  const { appendFile } = await import('node:fs/promises');
  await appendFile(
    summary,
    `## Drive cleanup${dryRun ? ' (dry run)' : ''}\n\nNon-document files ${dryRun ? 'found' : 'removed'}: **${dryRun ? doomed.length : deleted}** (${(bytes / 1048576).toFixed(1)} MB) ${JSON.stringify(byType)}\n\nEmpty folders: **${foldersRemoved}**\n`
  );
}
