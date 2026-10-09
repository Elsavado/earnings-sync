// Removes what earlier versions put in Drive that is not data: each unpacked archive's
// _SOURCE.txt (its folder is tagged as finished instead), ClinicalTrials.gov study-record
// JSON files, licence copies, checksum lists and OS leftovers from archives, and leads.json.
// Files go to the Drive trash, so they can still be restored for 30 days. Safe to run often.
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from './config.js';
import { log } from './context.js';
import { createDriveStore } from './drive.js';
import { isArchiveClutter } from './files.js';

export function isNotData(name) {
  return name === '_SOURCE.txt' || /^NCT\d+_study-record.*\.json$/i.test(name) || name.startsWith('._') || isArchiveClutter(name);
}

async function main() {
  const settings = await loadConfig(process.env.CONFIG_PATH || 'medical.json');
  const store = await createDriveStore(settings);
  let trashed = 0;
  for (const f of await store.listAppFiles()) {
    if (f.mimeType === 'application/vnd.google-apps.folder' || !isNotData(f.name)) continue;
    if (f.name === '_SOURCE.txt' && f.parents?.[0] && f.appProperties?.mdSourceKey) {
      await store.markFolderDone(f.parents[0], f.appProperties.mdSourceKey);
    }
    await store.trash(f.id);
    trashed++;
  }
  const folder = await store.ensureFolder('root', settings.drivePrivateFolderName);
  const leads = await store.findFile(folder, 'leads.json');
  if (leads) {
    await store.trash(leads.id);
    trashed++;
  }
  log.info(`Cleanup: ${trashed} non-data file(s) moved to the Drive trash`);
}

if (resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
  main().catch((err) => {
    log.error(err.message);
    process.exit(1);
  });
}
