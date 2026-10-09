// Tidies what earlier versions put in Drive. Files that are not data go to the Drive trash
// (restorable for 30 days): each unpacked archive's _SOURCE.txt (its folder is tagged as
// finished instead), ClinicalTrials.gov study-record JSON files, dataset READMEs, licence
// copies, checksum lists and OS leftovers from archives, and leads.json. Data stored in the
// older layout is moved so that it sits with its notes: PriMock57 audio, transcripts and
// notes per consultation, GDC files per patient case, TCIA series per collection, patient and
// scan session with readable names. Safe to run often.
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from './config.js';
import { log } from './context.js';
import { createDriveStore } from './drive.js';
import { CATEGORIES, isArchiveClutter, sourceKey } from './files.js';
import { getJson } from './http.js';
import { API as TCIA_API, collectionPlace, seriesLayout } from './sources/tcia.js';
import { imagingModality, isImageNoteModality } from './taxonomy.js';

const FOLDER_MIME = 'application/vnd.google-apps.folder';
const NOTE_FOLDERS = new Set(['Clinical data', 'Annotations']);

export function isNotData(name) {
  return (
    name === '_SOURCE.txt' ||
    /^NCT\d+_study-record.*\.json$/i.test(name) ||
    /^[^_]+_readme_[0-9a-f]{6}\.(md|txt)$/i.test(name) ||
    name.startsWith('._') ||
    isArchiveClutter(name)
  );
}

// Where a file stored in an older layout belongs now, or null when it is already in place.
// `move: 'file'` puts the file into folder `into` under its parent (`under: 'parent'`) or
// grandparent (`under: 'grandparent'`); `move: 'tcia'` asks for the file's series folder to be
// checked against the collection's current layout (see tciaTargets).
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
    // A collection's clinical data and annotations are already where they belong.
    if (NOTE_FOLDERS.has(parentName) || NOTE_FOLDERS.has(grandName)) return null;
    const collection = description.match(/collection (.+?) \(/)?.[1];
    // Series folders from the oldest layout end in the first 6 characters of their key.
    const uid6 = parentName.match(/_([0-9a-f]{6})$/)?.[1] || null;
    return collection ? { move: 'tcia', collection, uid6 } : null;
  }
  return null;
}

async function main() {
  const settings = await loadConfig(process.env.CONFIG_PATH || 'medical.json');
  const store = await createDriveStore(settings);
  let trashed = 0;
  for (const f of await store.listAppFiles()) {
    if (f.mimeType === FOLDER_MIME || !isNotData(f.name)) continue;
    if (f.name === '_SOURCE.txt' && f.parents?.[0] && f.appProperties?.mdSourceKey) {
      await store.markFolderDone(f.parents[0], f.appProperties.mdSourceKey);
    }
    await store.trash(f.id);
    trashed++;
  }
  const moved = await relink(store, settings);
  const folder = await store.ensureFolder('root', settings.drivePrivateFolderName);
  const leads = await store.findFile(folder, 'leads.json');
  if (leads) {
    await store.trash(leads.id);
    trashed++;
  }
  log.info(`Cleanup: ${trashed} non-data file(s) moved to the Drive trash; ${moved} item(s) moved next to their notes`);
}

// Where every series of a collection belongs now, by full source key and by the 6-character
// suffix older folder names carry (a suffix two series share is not used).
async function tciaTargets(collection, settings, cache) {
  if (!cache.has(collection)) {
    const licenseRe = new RegExp(settings.tcia.licensePattern, 'i');
    const all = await getJson(`${TCIA_API}/getSeries?Collection=${encodeURIComponent(collection)}&format=json`, { timeoutMs: 180000 });
    const series = all.filter((s) => licenseRe.test(s.LicenseURI || '') && (imagingModality(s.Modality) || isImageNoteModality(s.Modality)));
    const place = collectionPlace(collection, series);
    const layout = seriesLayout(series);
    const byKey = new Map();
    const byUid6 = new Map();
    for (const s of series) {
      const where = layout.get(s.SeriesInstanceUID);
      const target = { path: [CATEGORIES.imaging, place.specialty, place.modality, collection, where.patient, where.study], name: where.name };
      const key = sourceKey('tcia', s.SeriesInstanceUID);
      byKey.set(key, target);
      byUid6.set(key.slice(0, 6), byUid6.has(key.slice(0, 6)) ? null : target);
    }
    cache.set(collection, place.modality ? { byKey, byUid6 } : null);
  }
  return cache.get(collection);
}

async function relink(store, settings) {
  const folders = new Map();
  const folder = async (id) => {
    if (!folders.has(id)) folders.set(id, await store.getFile(id));
    return folders.get(id);
  };
  const emptied = new Set();
  const tcia = new Map();
  const checkedFolders = new Set();
  let moved = 0;
  for (const f of await store.listAppFiles()) {
    if (f.mimeType === FOLDER_MIME || !f.parents?.[0]) continue;
    const parent = await folder(f.parents[0]);
    if (checkedFolders.has(parent.id) || !parent.parents?.[0]) continue;
    const grand = await folder(parent.parents[0]);
    const r = relocation(f, parent.name, grand.name);
    if (!r) continue;
    if (r.move === 'tcia') {
      checkedFolders.add(parent.id);
      const targets = await tciaTargets(r.collection, settings, tcia);
      const key = parent.appProperties?.mdSourceKey;
      const target = targets && ((key && targets.byKey.get(key)) || (r.uid6 && targets.byUid6.get(r.uid6)));
      if (!target) continue;
      const studyFolder = await store.ensurePath(target.path);
      if (grand.id === studyFolder && parent.name === target.name) continue;
      if (grand.id !== studyFolder) {
        await store.move(parent.id, grand.id, studyFolder);
        emptied.add(grand.id);
      }
      if (parent.name !== target.name) await store.rename(parent.id, target.name);
    } else {
      const base = r.under === 'grandparent' ? grand : parent;
      await store.move(f.id, parent.id, await store.ensureFolder(base.id, r.into));
      if (r.under === 'grandparent') emptied.add(parent.id);
    }
    moved++;
  }
  // Folders a move left empty go too, and their parents if those are now empty as well.
  for (let id of emptied) {
    for (let level = 0; level < 5 && id; level++) {
      const f = await store.getFile(id);
      if (Object.values(CATEGORIES).includes(f.name) || !(await store.isEmptyFolder(id))) break;
      await store.trash(id);
      id = f.parents?.[0];
    }
  }
  return moved;
}

if (resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
  main().catch((err) => {
    log.error(err.message);
    process.exit(1);
  });
}
