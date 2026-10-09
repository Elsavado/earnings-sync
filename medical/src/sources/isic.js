// "DICOM - Imaging" > Dermatology: the International Skin Imaging Collaboration archive of
// openly licensed skin images (CC-0, CC-BY, CC-BY-NC). Each image's clinical notes (diagnosis,
// body site, age, sex) are in its file name and description, so no metadata files are needed:
// Dermatology/<Dermoscopy | Clinical photos | ...>/ISIC/
//   <Patient IP_...>/<Lesion IL_... - diagnosis>/ISIC_0000000 - Nevus - Anterior abdomen - female, 55y.jpg
//   By diagnosis/<diagnosis>/...   for images not linked to a patient or lesion
import { getJson } from '../http.js';

const API = 'https://api.isic-archive.com/api/v2/images/';
const IMAGE_TYPE = { dermoscopic: 'Dermoscopy', 'clinical: close-up': 'Clinical photos', 'clinical: overview': 'Clinical photos', 'TBP tile: close-up': 'Total-body photography', 'TBP tile: overview': 'Total-body photography' };

function clean(text) {
  return String(text || '').replace(/[\/\\:*?"<>|]+/g, '-').replace(/\s+/g, ' ').trim();
}

// The most specific diagnosis recorded, e.g. "Nevus, Dysplastic" rather than "Benign".
export function diagnosisOf(clinical = {}) {
  for (const k of ['diagnosis_5', 'diagnosis_4', 'diagnosis_3', 'diagnosis_2', 'diagnosis_1']) if (clinical[k]) return clean(clinical[k]);
  return 'Undiagnosed';
}

export function isicPlacement(image) {
  const clinical = image.metadata?.clinical || {};
  const type = IMAGE_TYPE[image.metadata?.acquisition?.image_type] || 'Other skin images';
  const diagnosis = diagnosisOf(clinical);
  const site = clean(clinical.anatom_site_3 || clinical.anatom_site_2 || clinical.anatom_site_1 || clinical.anatom_site_general || '');
  const person = [clinical.sex, clinical.age_approx != null ? `${clinical.age_approx}y` : ''].filter(Boolean).join(', ');
  const name = [image.isic_id, diagnosis, site, person].filter(Boolean).join(' - ').slice(0, 150);
  const lesion = clinical.lesion_id ? `Lesion ${clean(clinical.lesion_id)} - ${diagnosis}` : null;
  const path = clinical.patient_id
    ? [type, 'ISIC', `Patient ${clean(clinical.patient_id)}`, ...(lesion ? [lesion] : [])]
    : lesion
      ? [type, 'ISIC', 'Lesions', lesion]
      : [type, 'ISIC', 'By diagnosis', diagnosis];
  return { path: ['Dermatology', ...path], name };
}

export async function* isicItems(settings, ctx) {
  const cfg = settings.isic;
  const licenseRe = new RegExp(cfg.licensePattern, 'i');
  const state = (ctx.state.isic ||= { next: null, done: false });
  if (state.done) return;
  let url = state.next || `${API}?limit=100`;
  let taken = 0;
  while (url && (!cfg.maxPerRun || taken < cfg.maxPerRun)) {
    const data = await getJson(url, { minIntervalMs: cfg.minIntervalMs, timeoutMs: 120000 });
    for (const image of data.results || []) {
      if (!image.public || !licenseRe.test(image.copyright_license || '')) {
        ctx.stats.licenseSkipped++;
        continue;
      }
      const file = image.files?.full;
      if (!file?.url) continue;
      const { path, name } = isicPlacement(image);
      const ext = (file.url.match(/\.(\w+)$/)?.[1] || 'jpg').toLowerCase();
      taken++;
      yield {
        source: 'isic',
        id: image.isic_id,
        category: 'imaging',
        path,
        title: name,
        fileName: `${name}.${ext}`,
        keepName: true,
        size: file.size || null,
        url: file.url,
        license: image.copyright_license,
        attribution: `ISIC Archive, ${image.isic_id}, ${image.attribution || 'Anonymous'}`,
        landing: `https://api.isic-archive.com/images/${image.isic_id}/`
      };
    }
    url = data.next || null;
    state.next = url;
  }
  if (!url) state.done = true;
}
