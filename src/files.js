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
  ['transcript', /transcript|prepared remarks|call remarks|scripted remarks/],
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
