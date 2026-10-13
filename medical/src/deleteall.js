// Removes every medical-sync item from Drive: the "Medical Data" and "Medical Sync - private"
// folders in My Drive (with everything inside them) and any file or folder the app tagged,
// including tagged items already sitting in the trash. Deletion is permanent, because trashed
// files still count against the storage quota. Nothing outside those folders and tags is touched.
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

async function listAll(drive, q, fields = 'id, name, size, mimeType, trashed') {
  const out = [];
  let pageToken;
  do {
    const res = await drive.files.list({ q, fields: `nextPageToken, files(${fields})`, pageSize: 1000, pageToken });
    out.push(...(res.data.files || []));
    pageToken = res.data.nextPageToken;
  } while (pageToken);
  return out;
}

// Counts files and bytes under a folder, so the dry run shows what deleting it removes.
async function measure(drive, folderId) {
  let files = 0;
  let bytes = 0;
  const pending = [folderId];
  while (pending.length) {
    const id = pending.pop();
    for (const f of await listAll(drive, `'${id}' in parents and trashed = false`)) {
      if (f.mimeType === FOLDER_MIME) pending.push(f.id);
      else {
        files++;
        bytes += Number(f.size || 0);
      }
    }
  }
  return { files, bytes };
}

async function main() {
  const dryRun = process.env.DRY_RUN !== 'false';
  const settings = await loadConfig(process.env.CONFIG_PATH || 'medical.json');
  const store = await createDriveStore(settings);
  const drive = store.drive;
  log.info(`Before: ${await quota(drive)}`);
  if (process.env.DRIVE_ROOT_FOLDER_ID) log.info(`DRIVE_ROOT_FOLDER_ID is set (${process.env.DRIVE_ROOT_FOLDER_ID}); it is only removed if it is named "${settings.driveRootFolderName}"`);

  const names = [settings.driveRootFolderName, settings.drivePrivateFolderName];
  const roots = [];
  for (const name of names) {
    const q = `name = '${name.replace(/'/g, "\\'")}' and mimeType = '${FOLDER_MIME}' and 'root' in parents and trashed = false`;
    roots.push(...(await listAll(drive, q)));
  }
  if (process.env.DRIVE_ROOT_FOLDER_ID && !roots.some((r) => r.id === process.env.DRIVE_ROOT_FOLDER_ID)) {
    const r = (await drive.files.get({ fileId: process.env.DRIVE_ROOT_FOLDER_ID, fields: 'id, name, mimeType' })).data;
    if (r.name === settings.driveRootFolderName && r.mimeType === FOLDER_MIME) roots.push(r);
  }

  let totalFiles = 0;
  let totalBytes = 0;
  for (const r of roots) {
    const m = await measure(drive, r.id);
    totalFiles += m.files;
    totalBytes += m.bytes;
    log.info(`Folder "${r.name}" (${r.id}): ${m.files} file(s), ${(m.bytes / GB).toFixed(2)} GB`);
  }

  // Tagged items that live outside those folders, or are already in the trash.
  const tagged = await listAll(drive, `appProperties has { key='${APP_KEY}' and value='${APP_VALUE}' }`, 'id, name, size, mimeType, trashed');
  log.info(`Tagged medical-sync items anywhere (incl. trash): ${tagged.length}, ${(tagged.reduce((s, f) => s + Number(f.size || 0), 0) / GB).toFixed(2)} GB, of which ${tagged.filter((f) => f.trashed).length} in trash`);
  log.info(`Inside the folders above: ${totalFiles} file(s), ${(totalBytes / GB).toFixed(2)} GB`);

  if (dryRun) {
    log.info('Dry run: nothing deleted. Re-run with dry_run unchecked to delete.');
    return;
  }

  // Delete one item at a time, files before folders and deepest folders first, because the
  // app may not be allowed to delete a folder whole when it lacks access to some children.
  const blocked = [];
  const tryDelete = async (f) => {
    try {
      await drive.files.delete({ fileId: f.id });
      return true;
    } catch (err) {
      if (err.code === 404) return true;
      blocked.push(`${f.name} (${f.id}): ${err.message}`);
      return false;
    }
  };
  let deletedFiles = 0;
  let deletedFolders = 0;
  for (const r of roots) {
    const folders = [];
    const pending = [r];
    while (pending.length) {
      const dir = pending.pop();
      folders.push(dir);
      for (const f of await listAll(drive, `'${dir.id}' in parents and trashed = false`)) {
        if (f.mimeType === FOLDER_MIME) pending.push(f);
        else if (await tryDelete(f)) deletedFiles++;
      }
    }
    for (const dir of folders.reverse()) if (await tryDelete(dir)) deletedFolders++;
    log.info(`"${r.name}" (${r.id}): done`);
  }
  for (const f of tagged) if (await tryDelete(f)) deletedFiles++;
  log.info(`Deleted ${deletedFiles} file(s) and ${deletedFolders} folder(s); ${blocked.length} item(s) could not be deleted`);
  for (const b of blocked.slice(0, 100)) log.warn(`  not deleted: ${b}`);
  log.info(`After: ${await quota(drive)}`);
}

main().catch((err) => {
  log.error(err.stack || String(err));
  process.exit(1);
});
