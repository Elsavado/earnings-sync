// Openly licensed datasets kept in GitHub repositories, e.g. "Audio": the PriMock57 mock
// primary-care consultations (CC BY 4.0). Files stored with Git LFS are fetched from the
// LFS media host, not as pointer files.
import { getJson } from '../http.js';

const LFS_POINTER_MAX = 200;

function apiHeaders() {
  const h = { 'User-Agent': 'medical-sync', Accept: 'application/vnd.github+json' };
  if (process.env.GITHUB_TOKEN) h.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
  return h;
}

async function* walk(repo, branch, dir, cfg) {
  const entries = await getJson(`https://api.github.com/repos/${repo}/contents/${dir}?ref=${branch}`, {
    headers: apiHeaders(),
    minIntervalMs: cfg.minIntervalMs
  });
  for (const e of entries) {
    if (e.type === 'dir') yield* walk(repo, branch, e.path, cfg);
    else if (e.type === 'file') yield e;
  }
}

export function downloadUrlFor(repo, branch, entry) {
  // An LFS pointer is a tiny text file; the real content lives on the media host.
  if (entry.size <= LFS_POINTER_MAX && /\.(wav|mp3|flac|m4a|ogg)$/i.test(entry.name)) {
    return `https://media.githubusercontent.com/media/${repo}/${branch}/${entry.path}`;
  }
  return entry.download_url;
}

// Files that belong together (e.g. one consultation's audio, transcripts and clinical note)
// share a folder named by the part of the file name that set.groupBy matches.
export function groupFolder(set, name) {
  if (!set.groupBy) return null;
  return name.match(new RegExp(set.groupBy, 'i'))?.[0] || null;
}

export async function* githubItems(settings, ctx) {
  const cfg = settings.github;
  for (const set of cfg.datasets) {
    const branch = set.branch || 'main';
    for (const dir of set.dirs) {
      for await (const entry of walk(set.repo, branch, dir, cfg)) {
        if (set.extensions?.length && !set.extensions.some((x) => entry.name.toLowerCase().endsWith(`.${x}`))) continue;
        // Format descriptions are not data.
        if (/^readme(\.|$)/i.test(entry.name)) continue;
        yield {
          source: 'github',
          id: `${set.repo}/${entry.path}@${entry.sha}`,
          category: set.category,
          path: [...set.folder, groupFolder(set, entry.name) || dir],
          prefix: set.prefix,
          title: entry.name.replace(/\.[^.]+$/, ''),
          fileName: entry.name,
          url: downloadUrlFor(set.repo, branch, entry),
          license: set.license,
          attribution: set.attribution,
          landing: `https://github.com/${set.repo}`
        };
      }
    }
  }
}
