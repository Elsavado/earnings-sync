// "DICOM - Imaging": public collections of The Cancer Imaging Archive. Every series carries
// its licence; only series whose licence URI matches settings.tcia.licensePattern are taken.
// Each series is unpacked from the archive's zip and kept whole in one folder of DICOM files,
// grouped by patient and scan session:
// <specialty>/<CT | MRI | X-ray | Ultrasound>/<collection>/<patient>/<study date - study>/
//   Series 507 - <series description> (CT, 50 images)/
import { getJson } from '../http.js';
import { imagingModality, imagingSpecialty } from '../taxonomy.js';

export const API = 'https://services.cancerimagingarchive.net/nbia-api/services/v1';

function clean(text) {
  return String(text || '').replace(/\^/g, ' ').replace(/[\/\:*?"<>|]+/g, '-').replace(/\s+/g, ' ').trim();
}

function day(date) {
  return String(date || '').slice(0, 10);
}

// Gives names that would clash a "(<word> i of n)" label, in a fixed order.
function numbered(items, baseOf, word) {
  const groups = new Map();
  for (const it of items) {
    const base = baseOf(it);
    groups.set(base, [...(groups.get(base) || []), it]);
  }
  const names = new Map();
  for (const [base, list] of groups) {
    list.forEach((it, i) => names.set(it, list.length > 1 ? `${base} (${word} ${i + 1} of ${list.length})` : base));
  }
  return names;
}

// Readable, unique folder names for every series of a collection: the patient, the scan
// session (study) and the series. Sessions or series that would share a name are numbered
// "(scan 1 of 2)", "(scan 2 of 2)" in a fixed order, so a series always gets the same folder.
export function seriesLayout(series) {
  const layout = new Map();
  const byPatient = new Map();
  for (const s of series) byPatient.set(s.PatientID, [...(byPatient.get(s.PatientID) || []), s]);
  const byUid = (a, b) => String(a).localeCompare(String(b));
  for (const [patientId, list] of byPatient) {
    const patient = clean(patientId) || 'Unknown patient';
    const studies = [...new Set(list.map((s) => s.StudyInstanceUID))].sort(byUid);
    const first = (uid) => list.find((x) => x.StudyInstanceUID === uid);
    const studyNames = numbered(studies, (uid) => [day(first(uid).StudyDate || first(uid).SeriesDate), clean(first(uid).StudyDesc)].filter(Boolean).join(' - ') || 'Study', 'scan');
    const sorted = [...list].sort((a, b) => byUid(a.SeriesInstanceUID, b.SeriesInstanceUID));
    const seriesBase = (s) => {
      const desc = clean(s.SeriesDescription || s.ProtocolName);
      const images = s.ImageCount ? `${s.ImageCount} image${s.ImageCount === 1 ? '' : 's'}` : '';
      return `${studyNames.get(s.StudyInstanceUID)}|Series ${s.SeriesNumber ?? '?'}${desc ? ` - ${desc}` : ''} (${[s.Modality, images].filter(Boolean).join(', ')})`.slice(0, 220);
    };
    const seriesNames = numbered(sorted, seriesBase, 'copy');
    for (const s of sorted) {
      layout.set(s.SeriesInstanceUID, { patient, study: studyNames.get(s.StudyInstanceUID), name: seriesNames.get(s).split('|')[1] });
    }
  }
  return layout;
}

export async function* tciaItems(settings, ctx) {
  const cfg = settings.tcia;
  const licenseRe = new RegExp(cfg.licensePattern, 'i');
  const state = (ctx.state.tcia ||= { done: [] });
  const done = new Set(state.done);
  let collections = cfg.collections;
  if (!collections.length) {
    const all = await getJson(`${API}/getCollectionValues?format=json`, { minIntervalMs: cfg.minIntervalMs });
    collections = all.map((c) => c.Collection).sort();
  }
  for (const collection of collections) {
    if (done.has(collection)) continue;
    const series = await getJson(`${API}/getSeries?Collection=${encodeURIComponent(collection)}&format=json`, {
      minIntervalMs: cfg.minIntervalMs,
      timeoutMs: 180000
    });
    const layout = seriesLayout(series);
    let taken = 0;
    for (const s of series) {
      if (cfg.maxSeriesPerCollection && taken >= cfg.maxSeriesPerCollection) break;
      if (!licenseRe.test(s.LicenseURI || '')) {
        ctx.stats.licenseSkipped++;
        continue;
      }
      // Only CT, MRI, X-ray and ultrasound; PET, segmentations and RT structures are not collected.
      const modality = imagingModality(s.Modality);
      if (!modality) continue;
      const maxBytes = cfg.maxSeriesSizeMB * 1048576;
      if (s.FileSize && s.FileSize > maxBytes) {
        ctx.stats.sizeSkipped++;
        continue;
      }
      taken++;
      yield {
        source: 'tcia',
        id: s.SeriesInstanceUID,
        category: 'imaging',
        path: [imagingSpecialty(collection, s.BodyPartExamined), modality, collection, layout.get(s.SeriesInstanceUID).patient, layout.get(s.SeriesInstanceUID).study],
        folderName: layout.get(s.SeriesInstanceUID).name,
        prefix: s.PatientID,
        title: `${s.Modality || ''} ${s.BodyPartExamined || ''} series ${s.SeriesNumber ?? ''}`,
        unzip: true,
        ext: 'zip',
        size: s.FileSize || null,
        url: `${API}/getImage?SeriesInstanceUID=${encodeURIComponent(s.SeriesInstanceUID)}`,
        maxBytes,
        license: s.LicenseName,
        attribution: `The Cancer Imaging Archive, collection ${collection} (${s.CollectionURI || 'n/a'})`,
        landing: s.CollectionURI || 'https://www.cancerimagingarchive.net/'
      };
    }
    // A collection is marked finished only once every series in it has been handed over.
    done.add(collection);
    state.done = [...done];
  }
}
