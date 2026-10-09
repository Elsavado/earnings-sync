// "DICOM - Imaging": public collections of The Cancer Imaging Archive. Every series carries
// its licence; only series whose licence URI matches settings.tcia.licensePattern are taken.
// Each series is unpacked from the archive's zip and stored as a folder of DICOM files:
// <specialty>/<CT | MRI | X-ray | Ultrasound>/<collection>/<patient>/<series>/.
import { getJson } from '../http.js';
import { imagingModality, imagingSpecialty } from '../taxonomy.js';

const API = 'https://services.cancerimagingarchive.net/nbia-api/services/v1';

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
        // All of a patient's series sit together: .../<collection>/<patient>/<series>/.
        path: [imagingSpecialty(collection, s.BodyPartExamined), modality, collection, s.PatientID || 'Unknown patient'],
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
