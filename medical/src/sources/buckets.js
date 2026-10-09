// Open datasets in public cloud buckets (AWS Open Data), read with the plain S3 listing API:
//  - "mirror" datasets keep their own folder layout, or group files that belong together by
//    a name pattern (CAMELYON: each slide with its tumour annotation and mask).
//  - "openneuro": every OpenNeuro dataset (brain MRI, EEG/MEG; CC0) as one folder named by its
//    title, with its participants table and the per-subject BIDS folders. JSON sidecars,
//    READMEs, licence files, code and derived results are not data and are left out.
import { getJson, getText } from '../http.js';

const NOT_DATA = /(^|\/)(readme|changes|licen[cs]e|copying)[^/]*$|\.(json|md|py|m|ipynb|sh|txt)$|(^|\/)(code|derivatives|\.git[^/]*)\//i;

function clean(text) {
  return String(text || '').replace(/[\/\\:*?"<>|]+/g, '-').replace(/\s+/g, ' ').trim();
}

function decodeXml(s) {
  return s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'");
}

// One page of an S3 listing: files (key, size), sub-folders, and the token for the next page.
export function parseListing(xml) {
  const files = [...xml.matchAll(/<Contents>([\s\S]*?)<\/Contents>/g)].map((m) => ({
    key: decodeXml(m[1].match(/<Key>([^<]*)<\/Key>/)?.[1] || ''),
    size: Number(m[1].match(/<Size>(\d+)<\/Size>/)?.[1] || 0)
  }));
  const folders = [...xml.matchAll(/<CommonPrefixes>\s*<Prefix>([^<]*)<\/Prefix>/g)].map((m) => decodeXml(m[1]));
  const next = xml.match(/<NextContinuationToken>([^<]*)<\/NextContinuationToken>/)?.[1] || null;
  return { files, folders, next: next ? decodeXml(next) : null };
}

async function* listBucket(base, prefix, cfg, { delimiter = '' } = {}) {
  let token = null;
  do {
    const params = new URLSearchParams({ 'list-type': '2', prefix, 'max-keys': '1000' });
    if (delimiter) params.set('delimiter', delimiter);
    if (token) params.set('continuation-token', token);
    const { text } = await getText(`${base}/?${params}`, { minIntervalMs: cfg.minIntervalMs, timeoutMs: 120000, retries: 5 });
    const page = parseListing(text);
    yield page;
    token = page.next;
  } while (token);
}

// The folder for a file of a "mirror" dataset: a group named by set.groupBy, or its own path.
export function mirrorPath(set, key) {
  const rel = key.slice(set.prefix.length);
  const parts = rel.split('/');
  const name = parts.pop();
  const group = set.groupBy ? name.match(new RegExp(set.groupBy, 'i'))?.[0] : null;
  return { path: [...set.folder, ...(group ? [clean(group)] : parts.map(clean))], name };
}

async function* mirrorItems(set, cfg, ctx, state) {
  const ds = (state[set.name] ||= { token: null, done: false });
  if (ds.done) return;
  const include = set.include ? new RegExp(set.include, 'i') : null;
  const exclude = set.exclude ? new RegExp(set.exclude, 'i') : null;
  let taken = 0;
  for await (const page of listBucket(set.base, set.prefix, cfg)) {
    for (const f of page.files) {
      if (f.key.endsWith('/') || NOT_DATA.test(f.key) || (include && !include.test(f.key)) || (exclude && exclude.test(f.key))) continue;
      if (f.size > cfg.maxFileSizeMB * 1048576) {
        ctx.stats.sizeSkipped++;
        continue;
      }
      const { path, name } = mirrorPath(set, f.key);
      taken++;
      yield { source: 'buckets', id: `${set.base}/${f.key}`, category: set.category, path, title: name, fileName: name, keepName: true, size: f.size, url: `${set.base}/${encodeURI(f.key)}`, maxBytes: cfg.maxFileSizeMB * 1048576, license: set.license, attribution: set.attribution, landing: set.landing };
    }
    if (set.maxPerRun && taken >= set.maxPerRun) return;
  }
  ds.done = true;
}

// Imaging (MRI, PET) or brain signals (EEG, MEG, iEEG), from the BIDS data-type folders.
export function openneuroKind(keys) {
  let imaging = 0;
  let signals = 0;
  for (const k of keys) {
    if (/\/(anat|func|dwi|fmap|perf|pet)\//.test(k)) imaging++;
    else if (/\/(eeg|ieeg|meg|nirs)\//.test(k)) signals++;
  }
  if (!imaging && !signals) return null;
  return imaging >= signals ? 'imaging' : 'signals';
}

async function* openneuroItems(set, cfg, ctx, state) {
  const on = (state[set.name] ||= { after: '', done: false });
  if (on.done) return;
  const allowed = new RegExp(set.licensePattern, 'i');
  let datasets = 0;
  for await (const page of listBucket(set.base, '', cfg, { delimiter: '/' })) {
    for (const prefix of page.folders) {
      const id = prefix.replace(/\/$/, '');
      if (!/^ds\d+$/.test(id) || id <= on.after) continue;
      if (set.maxDatasetsPerRun && datasets >= set.maxDatasetsPerRun) return;
      datasets++;
      let meta = {};
      try {
        meta = await getJson(`${set.base}/${id}/dataset_description.json`, { minIntervalMs: cfg.minIntervalMs, retries: 2 });
      } catch {
        meta = {};
      }
      const license = String(meta.License || 'CC0');
      if (!allowed.test(license)) {
        ctx.stats.licenseSkipped++;
        on.after = id;
        continue;
      }
      const files = [];
      for await (const p of listBucket(set.base, prefix, cfg)) files.push(...p.files);
      const kind = openneuroKind(files.map((f) => f.key));
      const title = `${id} - ${clean(meta.Name || 'Untitled')}`.slice(0, 120);
      const base = kind === 'signals' ? { category: 'wearables', folder: ['EEG & brain signals', 'OpenNeuro', title] } : { category: 'imaging', folder: ['Neurology', 'MRI', 'OpenNeuro', title] };
      if (kind) {
        for (const f of files) {
          const rel = f.key.slice(prefix.length);
          if (f.key.endsWith('/') || NOT_DATA.test(rel) || rel.startsWith('sourcedata/')) continue;
          if (f.size > cfg.maxFileSizeMB * 1048576) {
            ctx.stats.sizeSkipped++;
            continue;
          }
          const parts = rel.split('/');
          const name = parts.pop();
          yield { source: 'buckets', id: `${set.base}/${f.key}`, category: base.category, path: [...base.folder, ...parts.map(clean)], title: name, fileName: name, keepName: true, size: f.size, url: `${set.base}/${encodeURI(f.key)}`, maxBytes: cfg.maxFileSizeMB * 1048576, license, attribution: `OpenNeuro ${id}: ${meta.Name || ''}${meta.Authors ? `, ${[].concat(meta.Authors).slice(0, 3).join(', ')}` : ''}`, landing: `https://openneuro.org/datasets/${id}` };
        }
      }
      // A dataset counts as done once all its files have been handed over.
      on.after = id;
    }
  }
  on.done = true;
}

export async function* bucketItems(settings, ctx) {
  const cfg = settings.buckets;
  const state = (ctx.state.buckets ||= {});
  for (const set of cfg.datasets) {
    if (set.kind === 'openneuro') yield* openneuroItems(set, cfg, ctx, state);
    else yield* mirrorItems(set, cfg, ctx, state);
  }
}
