// "DICOM - Imaging": public collections of The Cancer Imaging Archive. Every series carries
// its licence; only series whose licence URI matches settings.tcia.licensePattern are taken.
// Each series is unpacked from the archive's zip and kept whole in one folder of DICOM files.
// A collection is one folder, placed by its main specialty and modality, holding its patients'
// scan sessions (every modality of a session together, with its segmentations and reports)
// and the collection's clinical data and annotations:
// <specialty>/<modality>/<collection>/<patient>/<study date - study>/
//   Series 507 - <series description> (CT, 50 images)/
// <specialty>/<modality>/<collection>/Clinical data/ and .../Annotations/
import { getJson } from '../http.js';
import { imagingModality, imagingSpecialty, isImageNoteModality } from '../taxonomy.js';

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

const WP = 'https://www.cancerimagingarchive.net/api/v1/downloads/';
const WP_FIELDS = 'id,title,download_file,download_title,data_license,download_type,download_url,file_type,download_access';
const NOTE_FILE_TYPES = /^(CSV|TSV|XLSX?|PDF|DOCX?|TXT|ZIP|NIFTI|NRRD|MHA|DICOM)$/i;
const NOT_DATA_TITLE = /licen[cs]e|source ?code|example|template|mapping|readme/i;

// The most common value, e.g. the modality most of a collection's series have.
function mostCommon(values) {
  const counts = new Map();
  for (const v of values) if (v) counts.set(v, (counts.get(v) || 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))[0]?.[0] || null;
}

// One folder per collection, placed by the specialty and modality most of its images have,
// so a patient's CT, PET and segmentations from one session stay together.
export function collectionPlace(collection, series) {
  const images = series.filter((s) => imagingModality(s.Modality));
  return {
    specialty: mostCommon(images.map((s) => imagingSpecialty(collection, s.BodyPartExamined))) || imagingSpecialty(collection, ''),
    modality: mostCommon(images.map((s) => imagingModality(s.Modality)))
  };
}

// A collection's open clinical tables, data dictionaries and annotation files, as listed by
// TCIA's collection manager. Files only reachable through Aspera are left out.
export function collectionNoteFiles(downloads) {
  const byCollection = new Map();
  for (const d of downloads) {
    const url = d.download_url || d.download_file?.guid || '';
    const title = `${d.title?.rendered || ''} ${d.download_title || ''} ${decodeURIComponent(url.split('/').pop())}`;
    if (d.download_access !== 'Public' || !/^CC BY/.test(d.data_license || '')) continue;
    if (!/^https:\/\/(www|stage)\.cancerimagingarchive\.net\/wp-content\//.test(url)) continue;
    if (NOT_DATA_TITLE.test(title) || NOT_DATA_TITLE.test(url)) continue;
    if (!(d.file_type || []).some((t) => NOTE_FILE_TYPES.test(t))) continue;
    // .tcia files are download manifests, not data.
    if (/\.tcia$/i.test(url)) continue;
    // A data dictionary goes wherever the table it explains goes.
    let folder;
    if (d.download_type === 'Clinical Data') folder = 'Clinical data';
    else if (d.download_type === 'Image Annotations' || /annotat|segment|label|measurement|metadata/i.test(title)) folder = 'Annotations';
    else if (/dictionar|clinical|demograph|diagnos|follow|treatment|outcome|patholog/i.test(title)) folder = 'Clinical data';
    else continue;
    const collection = (d.title?.rendered || '').replace(/-DA-.*$/i, '').toUpperCase();
    const list = byCollection.get(collection) || [];
    list.push({ id: d.id, url, folder, title: d.download_title || d.title?.rendered, license: d.data_license, fileName: decodeURIComponent(url.split('/').pop()) });
    byCollection.set(collection, list);
  }
  return byCollection;
}

async function loadDownloads(cfg) {
  const all = [];
  for (let page = 1; page <= 50; page++) {
    let batch;
    try {
      batch = await getJson(`${WP}?per_page=100&page=${page}&_fields=${WP_FIELDS}`, { minIntervalMs: cfg.minIntervalMs, timeoutMs: 120000, retries: 6 });
    } catch (err) {
      if (/\b400\b/.test(err.message)) break; // past the last page
      throw err;
    }
    if (!Array.isArray(batch) || !batch.length) break;
    all.push(...batch);
    if (batch.length < 100) break;
  }
  return collectionNoteFiles(all);
}

export async function* tciaItems(settings, ctx) {
  const cfg = settings.tcia;
  const licenseRe = new RegExp(cfg.licensePattern, 'i');
  // Version 2 of the listing state: PET, nuclear medicine, segmentations and structured
  // reports are now collected too, so every collection is gone through again.
  const state = (ctx.state.tcia2 ||= { done: [] });
  const done = new Set(state.done);
  let collections = cfg.collections;
  if (!collections.length) {
    const all = await getJson(`${API}/getCollectionValues?format=json`, { minIntervalMs: cfg.minIntervalMs, retries: 6 });
    collections = all.map((c) => c.Collection).sort();
  }
  let notes = null;
  for (const collection of collections) {
    if (done.has(collection)) continue;
    const all = await getJson(`${API}/getSeries?Collection=${encodeURIComponent(collection)}&format=json`, {
      minIntervalMs: cfg.minIntervalMs,
      timeoutMs: 180000,
      retries: 6
    });
    const series = all.filter((s) => licenseRe.test(s.LicenseURI || '') && (imagingModality(s.Modality) || isImageNoteModality(s.Modality)));
    ctx.stats.licenseSkipped += all.filter((s) => !licenseRe.test(s.LicenseURI || '')).length;
    const place = collectionPlace(collection, series);
    if (!place.modality) {
      done.add(collection);
      state.done = [...done];
      continue;
    }
    const base = [place.specialty, place.modality, collection];
    const layout = seriesLayout(series);
    const first = series[0];
    const common = {
      source: 'tcia',
      category: 'imaging',
      attribution: `The Cancer Imaging Archive, collection ${collection} (${first.CollectionURI || 'n/a'})`,
      landing: first.CollectionURI || 'https://www.cancerimagingarchive.net/'
    };

    // The collection's clinical data, data dictionaries and annotations, beside its patients.
    notes ||= await loadDownloads(cfg);
    for (const f of notes.get(collection.toUpperCase()) || []) {
      const zip = /\.zip$/i.test(f.fileName);
      yield {
        ...common,
        id: `download/${f.id}/${f.url}`,
        path: [...base, f.folder],
        title: f.title,
        fileName: f.fileName,
        keepName: true,
        folderName: zip ? f.title : undefined,
        unzip: zip,
        url: f.url,
        license: f.license
      };
    }

    let taken = 0;
    for (const s of series) {
      if (cfg.maxSeriesPerCollection && taken >= cfg.maxSeriesPerCollection) break;
      const maxBytes = cfg.maxSeriesSizeMB * 1048576;
      if (s.FileSize && s.FileSize > maxBytes) {
        ctx.stats.sizeSkipped++;
        continue;
      }
      taken++;
      const where = layout.get(s.SeriesInstanceUID);
      yield {
        ...common,
        id: s.SeriesInstanceUID,
        path: [...base, where.patient, where.study],
        folderName: where.name,
        prefix: s.PatientID,
        title: `${s.Modality || ''} ${s.BodyPartExamined || ''} series ${s.SeriesNumber ?? ''}`,
        unzip: true,
        ext: 'zip',
        size: s.FileSize || null,
        url: `${API}/getImage?SeriesInstanceUID=${encodeURIComponent(s.SeriesInstanceUID)}`,
        maxBytes,
        license: s.LicenseName
      };
    }
    // A collection is marked finished only once every series in it has been handed over.
    done.add(collection);
    state.done = [...done];
  }
}
