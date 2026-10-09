// Tidies what earlier versions put in Drive. Files that are not data go to the Drive trash
// (restorable for 30 days): each unpacked archive's _SOURCE.txt (its folder is tagged as
// finished instead), ClinicalTrials.gov study-record JSON files, dataset READMEs, licence
// copies, checksum lists and OS leftovers from archives, and leads.json. Data stored in the
// older layout is moved so that it sits with its notes: PriMock57 audio, transcripts and
// notes per consultation, GDC files per patient case, TCIA series per patient. Safe to run often.
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from './config.js';
import { log } from './context.js';
import { createDriveStore } from './drive.js';
import { isArchiveClutter, sourceKey } from './files.js';
import { getJson } from './http.js';
import { API as TCIA_API, seriesLayout } from './sources/tcia.js';

const FOLDER_MIME = 'application/vnd.google-apps.folder';

export function isNotData(name) {
  return (
    name === '_SOURCE.txt' ||
    /^NCT\d+_study-record.*\.json$/i.test(name) ||
    /^[^_]+_readme_[0-9a-f]{6}\.(md|txt)$/i.test(name) ||
    name.startsWith('._') ||
    isArchiveClutter(name)
  );
}

// Where a file stored in the older layout belongs now, or null when it is already in place.
// `move: 'file'` puts the file into folder `into` under its parent (`under: 'parent'`) or
// grandparent (`under: 'grandparent'`); `move: 'parent'` moves the file's whole parent folder
// (an unpacked TCIA series) into folder `into` under the grandparent; `move: 'tcia'` moves a
// series folder to <collection>/<patient>/<study>/ and renames it (see tciaTarget).
export function relocation({ name, description = '' }, parentName, grandName) {
  if (grandName === 'PriMock57 mock consultations' && ['audio', 'transcripts', 'notes'].includes(parentName)) {
    const consultation = name.match(/day\d+_consultation\d+/i)?.[0];
    return consultation ? { move: 'file', under: 'grandparent', into: consultation } : null;
  }
  if (description.includes('NCI Genomic Data Commons')) {
    const kase = description.match(/, case ([^,]+), file /)?.[1];
    return kase && kase !== 'n/a' && parentName !== kase ? { move: 'file', under: 'parent', into: kase } : null;
  }
  if (description.includes('The Cancer Imaging Archive')) {
    // A series folder from an older layout ends in the first 6 characters of its source key.
    const collection = description.match(/collection (.+?) \(/)?.[1];
    const uid6 = parentName.match(/_([0-9a-f]{6})$/)?.[1];
    return collection && uid6 ? { move: 'tcia', collection, uid6 } : null;
  }
  return null;
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
  const moved = await relink(store);
  const folder = await store.ensureFolder('root', settings.drivePrivateFolderName);
  const leads = await store.findFile(folder, 'leads.json');
  if (leads) {
    await store.trash(leads.id);
    trashed++;
  }
  log.info(`Cleanup: ${trashed} non-data file(s) moved to the Drive trash; ${moved} item(s) moved next to their notes`);
}

// The new folder of an older-layout TCIA series, found by matching the 6-character key
// suffix against the collection's series list.
async function tciaTarget({ collection, uid6 }, cache) {
  if (!cache.has(collection)) {
    const series = await getJson(`${TCIA_API}/getSeries?Collection=${encodeURIComponent(collection)}&format=json`, { timeoutMs: 180000 });
    const layout = seriesLayout(series);
    const byUid6 = new Map();
    for (const s of series) {
      const k = sourceKey('tcia', s.SeriesInstanceUID).slice(0, 6);
      // Two series sharing a suffix cannot be told apart; such a folder is left where it is.
      byUid6.set(k, byUid6.has(k) ? null : layout.get(s.SeriesInstanceUID));
    }
    cache.set(collection, byUid6);
  }
  return cache.get(collection).get(uid6) || null;
}

async function relink(store) {
  const folders = new Map();
  const folder = async (id) => {
    if (!folders.has(id)) folders.set(id, await store.getFile(id));
    return folders.get(id);
  };
  const emptied = new Set();
  const tcia = new Map();
  const movedFolders = new Set();
  let moved = 0;
  for (const f of await store.listAppFiles()) {
    if (f.mimeType === FOLDER_MIME || !f.parents?.[0]) continue;
    const parent = await folder(f.parents[0]);
    if (movedFolders.has(parent.id) || !parent.parents?.[0]) continue;
    const grand = await folder(parent.parents[0]);
    const r = relocation(f, parent.name, grand.name);
    if (!r) continue;
    if (r.move === 'tcia') {
      const target = await tciaTarget(r, tcia);
      if (!target) continue;
      // The collection folder is the grandparent (oldest layout) or the one above it.
      const collectionFolder = grand.name === r.collection ? grand : await folder(grand.parents?.[0]);
      if (!collectionFolder || collectionFolder.name !== r.collection) continue;
      const studyFolder = await store.ensureFolder(await store.ensureFolder(collectionFolder.id, target.patient), target.study);
      await store.move(parent.id, grand.id, studyFolder);
      await store.rename(parent.id, target.name);
      movedFolders.add(parent.id);
      if (grand.id !== collectionFolder.id) emptied.add(grand.id);
    } else if (r.move === 'parent') {
      await store.move(parent.id, grand.id, await store.ensureFolder(grand.id, r.into));
      movedFolders.add(parent.id);
    } else {
      const base = r.under === 'grandparent' ? grand : parent;
      await store.move(f.id, parent.id, await store.ensureFolder(base.id, r.into));
      if (r.under === 'grandparent') emptied.add(parent.id);
    }
    moved++;
  }
  for (const id of emptied) if (await store.isEmptyFolder(id)) await store.trash(id);
  return moved;
}

if (resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
  main().catch((err) => {
    log.error(err.message);
    process.exit(1);
  });
}
