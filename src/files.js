import { createHash } from 'node:crypto';
import { extname } from 'node:path';

const MIME_BY_EXT = {
  pdf: 'application/pdf',
  htm: 'text/html',
  html: 'text/html',
  txt: 'text/plain',
  csv: 'text/csv',
  mp3: 'audio/mpeg',
  m4a: 'audio/mp4',
  mp4: 'video/mp4',
  xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
};

const EXT_BY_MIME = Object.fromEntries(
  Object.entries(MIME_BY_EXT)
    .filter(([ext]) => ext !== 'htm')
    .map(([ext, mime]) => [mime, ext])
);
EXT_BY_MIME['audio/mp3'] = 'mp3';
EXT_BY_MIME['audio/x-m4a'] = 'm4a';

const DOC_TYPE_RULES = [
  ['transcript', /transcript/],
  ['prepared-remarks', /prepared remarks|call remarks|scripted remarks|cfo commentary|management commentary/],
  ['shareholder-letter', /letter to (share|stock)holders|(share|stock)holder letter/],
  ['presentation', /presentation|slides|slide deck|investor deck/],
  ['webcast', /webcast|replay|audio|\.mp3|\.m4a|\.mp4/],
  ['supplement', /supplement|financial data|data sheet|fact sheet|metrics|financial tables/],
  ['press-release', /press release|news release|earnings release|results|ex-?99/]
];

export function classifyDocType(text, fallback = 'document') {
  const s = String(text || '').toLowerCase();
  for (const [type, re] of DOC_TYPE_RULES) {
    if (re.test(s)) return type;
  }
  return fallback;
}

export function extensionFromUrl(url) {
  try {
    const ext = extname(new URL(url).pathname).replace(/^\./, '').toLowerCase();
    return /^[a-z0-9]{1,5}$/.test(ext) ? ext : '';
  } catch {
    return '';
  }
}

export function extensionFromName(name) {
  const ext = extname(String(name || '')).replace(/^\./, '').toLowerCase();
  return /^[a-z0-9]{1,5}$/.test(ext) ? ext : '';
}

export function resolveExtension({ url, dispositionName, contentType }) {
  return extensionFromName(dispositionName) || EXT_BY_MIME[contentType] || extensionFromUrl(url) || 'bin';
}

export function mimeForExtension(ext) {
  return MIME_BY_EXT[ext] || 'application/octet-stream';
}

export function slugify(text, max = 50) {
  return String(text || '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, max)
    .replace(/-+$/g, '');
}

export function buildFileName({ ticker, periodLabel, docType, hint, ext }) {
  const slug = slugify(hint);
  const base = [ticker, periodLabel, docType, slug].filter(Boolean).join('_');
  return ext ? `${base}.${ext}` : base;
}

export function sourceKey(source, sourceId) {
  return createHash('sha1').update(`${source}|${sourceId}`).digest('hex');
}

const FRIENDLY_TYPES = {
  'press-release': 'earnings-release',
  supplement: 'financial-supplement',
  presentation: 'investor-presentation',
  transcript: 'earnings-call-transcript',
  webcast: 'webcast'
};

const NOISE_WORDS = new Set(['pdf', 'xlsx', 'xls', 'doc', 'docx', 'ppt', 'pptx', 'csv', 'download', 'opens', 'in', 'new', 'window', 'link', 'file', 'the', 'of', 'and', 'kb', 'mb']);

// Short, readable slug for the part of the name that tells files of the same type apart.
export function descriptor(hint, { docType, periodLabel } = {}) {
  let text = String(hint || '')
    .replace(/\b(19|20)\d{2}\b/g, ' ')
    .replace(/\b(f?q[1-4]|fy\s?\d{2}|first|second|third|fourth|quarter|fiscal)\b/gi, ' ')
    .replace(/\bCO-[0-9A-F]{6}\b/gi, ' ')
    .replace(/\b\d+(\.\d+)?\s*(kb|mb)\b/gi, ' ');
  const words = slugify(text, 80)
    .split('-')
    .filter((w) => w && !NOISE_WORDS.has(w));
  const typeWords = new Set(String(docType || '').split('-'));
  const slug = words.filter((w) => !typeWords.has(w)).slice(0, 6).join('-');
  if (!slug || slug === slugify(periodLabel)) return '';
  return slug.slice(0, 40).replace(/-+$/g, '');
}

// CODE_FY2026-Q2_earnings-release_2026-07-14_ex991.htm
export function smartFileName({ code, periodLabel, docType, date, hint, ext }) {
  const type = FRIENDLY_TYPES[docType] || docType || 'document';
  const parts = [code, periodLabel, type, date || '', descriptor(hint, { docType: type, periodLabel })].filter(Boolean);
  return ext ? `${parts.join('_')}.${ext}` : parts.join('_');
}
