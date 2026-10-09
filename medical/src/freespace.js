// Frees Drive storage by PERMANENTLY deleting the most recently uploaded data files (newest
// first) until at least FREE_GB has been removed. Deleted files skip the Drive trash, because
// trashed files still count against the storage quota. Folders left empty are removed too.
// DRY_RUN=true only lists what would go.
import { loadConfig } from './config.js';
import { log } from './context.js';
import { APP_KEY, APP_VALUE, createDriveStore } from './drive.js';

const FOLDER_MIME = 'application/vnd.google-apps.folder';
const GB = 1024 ** 3;

async function quota(drive) {
  const q = (await drive.about.get({ fields: 'storageQuota' })).data.storageQuota;
  return `${(Number(q.usage) / GB).toFixed(2)} GB used of ${(Number(q.limit) / GB).toFixed(2)} GB`;
}

async function main() {
  const target = Number(process.env.FREE_GB || 5) * GB;
  const dryRun = process.env.DRY_RUN === 'true';
  const settings = await loadConfig(process.env.CONFIG_PATH || 'medical.json');
  const store = await createDriveStore(settings);
  const drive = store.drive;
  log.info(`Before: ${await quota(drive)}`);

  const victims = [];
  let freed = 0;
  let pageToken;
  outer: do {
    const res = await drive.files.list({
      q: `appProperties has { key='${APP_KEY}' and value='${APP_VALUE}' } and trashed = false and mimeType != '${FOLDER_MIME}'`,
      fields: 'nextPageToken, files(id, name, size, createdTime, parents)',
      orderBy: 'createdTime desc',
      pageSize: 1000,
      pageToken
    });
    for (const f of res.data.files || []) {
      const size = Number(f.size || 0);
      if (!size) continue;
      victims.push(f);
      freed += size;
      if (freed >= target) break outer;
    }
    pageToken = res.data.nextPageToken;
  } while (pageToken);

  const oldest = victims.at(-1)?.createdTime;
  log.info(`${victims.length} file(s), ${(freed / GB).toFixed(2)} GB, uploaded ${oldest} or later`);
  if (dryRun) {
    for (const f of victims.slice(0, 50)) log.info(`  would delete ${f.createdTime} ${(Number(f.size) / 1024 ** 2).toFixed(1)} MB ${f.name}`);
    return;
  }

  const parents = new Set();
  for (const f of victims) {
    await drive.files.delete({ fileId: f.id });
    for (const p of f.parents || []) parents.add(p);
  }

  // Remove folders the deletions left empty, walking up but never past the root folder.
  let removedFolders = 0;
  const pending = [...parents];
  while (pending.length) {
    const id = pending.pop();
    if (id === store.rootFolderId) continue;
    const kids = await drive.files.list({ q: `'${id}' in parents and trashed = false`, fields: 'files(id)', pageSize: 1 });
    if (kids.data.files?.length) continue;
    const folder = (await drive.files.get({ fileId: id, fields: 'id, parents, mimeType' })).data;
    if (folder.mimeType !== FOLDER_MIME) continue;
    await drive.files.delete({ fileId: id });
    removedFolders++;
    pending.push(...(folder.parents || []));
  }
  log.info(`Deleted ${victims.length} file(s) (${(freed / GB).toFixed(2)} GB) and ${removedFolders} empty folder(s)`);
  log.info(`After: ${await quota(drive)}`);
}

main().catch((err) => {
  log.error(err.stack || String(err));
  process.exit(1);
});
