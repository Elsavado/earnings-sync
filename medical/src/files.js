import { createHash } from 'node:crypto';
import { extname } from 'node:path';

// The eight data types, and only these. Each is a top-level folder under the Drive root.
export const CATEGORIES = {
  imaging: 'DICOM - Imaging',
  ehr: 'EHR',
  claims: 'Claims',
  wearables: 'Wearables',
  audio: 'Audio',
  genomics: 'Genomics',
  pathology: 'Pathology',
  other: 'Other'
};

const MIME_BY_EXT = {
  pdf: 'application/pdf',
  zip: 'application/zip',
  json: 'application/json',
  csv: 'text/csv',
  tsv: 'text/tab-separated-values',
  txt: 'text/plain',
  wav: 'audio/wav',
  mp3: 'audio/mpeg',
  svs: 'image/tiff',
  tif: 'image/tiff',
  tiff: 'image/tiff',
  gz: 'application/gzip',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
};

const EXT_BY_MIME = Object.fromEntries(Object.entries(MIME_BY_EXT).map(([ext, mime]) => [mime, ext]));
EXT_BY_MIME['audio/x-wav'] = 'wav';
EXT_BY_MIME['application/x-zip-compressed'] = 'zip';

function cleanExt(ext) {
  const e = String(ext || '').replace(/^\./, '').toLowerCase();
  return /^[a-z0-9]{1,5}$/.test(e) ? e : '';
}

export function extensionFromUrl(url) {
  try {
    return cleanExt(extname(new URL(url).pathname));
  } catch {
    return '';
  }
}

// Keeps double extensions such as .maf.gz and .tsv.gz readable.
export function extensionFromName(name) {
  const m = String(name || '').toLowerCase().match(/\.([a-z0-9]{1,5})(\.gz)?$/);
  if (!m) return '';
  return m[2] ? `${m[1]}.gz` : m[1];
}

export function resolveExtension({ ext, dispositionName, url, contentType }) {
  return cleanExt(ext) || extensionFromName(dispositionName) || EXT_BY_MIME[contentType] || extensionFromUrl(url) || 'bin';
}

export function mimeForExtension(ext) {
  return MIME_BY_EXT[String(ext).split('.').pop()] || 'application/octet-stream';
}

export function slugify(text, max = 60) {
  return String(text || '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, max)
    .replace(/-+$/g, '');
}

export function sourceKey(source, id) {
  return createHash('sha1').update(`${source}|${id}`).digest('hex');
}

// PMC1234567_gastric-metastases-from-breast-carcinoma_a3f9c2.pdf
export function fileName({ prefix, title, uid, ext }) {
  const parts = [prefix, slugify(title)].filter(Boolean);
  return `${parts.join('_') || 'file'}_${uid}.${ext}`;
}

// Text matched against these decides which of the eight types a company-website
// document belongs to; documents matching none are not collected.
export const CATEGORY_KEYWORDS = [
  ['pathology', /\b(patholog|histopatholog|cytolog|biops|whole[- ]slide|digital pathology|immunohisto|ihc\b|frozen section)/],
  ['genomics', /\b(genom|sequencing|\bngs\b|\bwgs\b|\bwes\b|exome|gene panel|molecular diagnost|variant|oncology panel|pharmacogen)/],
  ['imaging', /\b(dicom|radiolog|\bmri\b|\bct (scan|imaging|angiogra|colonograph)|computed tomograph|x-ray|ultrasound|echocardiogra|mammogra|\bpet\b|imaging)/],
  ['wearables', /\b(wearable|continuous glucose|\bcgm\b|remote (patient )?monitoring|holter|actigraph|smartwatch|biosensor)/],
  ['audio', /\b(dictation|speech recogni|clinical audio|ambient (clinical )?(documentation|listening)|voice)/],
  ['ehr', /\b(electronic health record|\behr\b|\bemr\b|medical record|fhir|hl7)/],
  ['claims', /\b(claims?|billing|reimbursement|coding guide|cpt code|icd-10|payer)/],
  ['other', /\b(case (study|report|series)|clinical (study|trial|evidence)|study protocol|patient report|educational case|white ?paper|validation study)/]
];

export function categorize(text) {
  const s = String(text || '').toLowerCase();
  for (const [category, re] of CATEGORY_KEYWORDS) if (re.test(s)) return category;
  return null;
}

// Archive entries that are not data: checksum lists, licence copies, and folders and files
// left behind by macOS and Windows.
const ARCHIVE_CLUTTER = /(^|\/)(__MACOSX\/|\.DS_Store$|Thumbs\.db$|desktop\.ini$|(SHA256|SHA1|MD5)SUMS(\.txt)?$|(LICEN[CS]E|COPYING)([-_. ][^/]*)?$)/i;

export function isArchiveClutter(name) {
  return ARCHIVE_CLUTTER.test(name) || name.endsWith('/');
}
