// Samples files already in Drive and checks them for real company identifiers that
// survived anonymisation (anonymizer/audit.py does the text checks). Public logs only
// show totals per document type and the leaked terms, never file names or codes.
import { execFile } from 'node:child_process';
import { appendFile, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { loadConfig } from './config.js';
import { log } from './context.js';
import { createDriveStore, DATA_VERSION } from './drive.js';
import { assignCodes } from './anonymize.js';

const SAMPLE = Number(process.env.AUDIT_SAMPLE || 300);
const AUDIT = fileURLToPath(new URL('../anonymizer/audit.py', import.meta.url));

const { settings, companies } = await loadConfig(process.env.CONFIG_PATH || 'companies.json');
assignCodes(companies, process.env.ANON_KEY || '');
const byCode = Object.fromEntries(
  companies.map((c) => [c.code, { aliases: [...c.aliases, c.name], ticker: c.ticker, domains: c.domains }])
);

const store = await createDriveStore(settings);
const files = (await store.listAppFiles()).filter(
  (f) => f.appProperties?.irVersion === DATA_VERSION && /\.(pdf|xlsx|xlsm|docx|pptx)$/i.test(f.name)
);
// Random sample, so every source and document type has a chance to show up.
for (let i = files.length - 1; i > 0; i--) {
  const j = Math.floor(Math.random() * (i + 1));
  [files[i], files[j]] = [files[j], files[i]];
}
const sample = files.slice(0, SAMPLE);
log.info(`Auditing ${sample.length} of ${files.length} file(s)`);

const dir = await mkdtemp(join(tmpdir(), 'audit-'));
const manifest = { companies: byCode, files: [] };
try {
  for (const [i, f] of sample.entries()) {
    const parts = f.name.split('_');
    const ext = f.name.split('.').pop().toLowerCase();
    const path = join(dir, `${i}.${ext}`);
    const res = await store.drive.files.get({ fileId: f.id, alt: 'media', supportsAllDrives: true }, { responseType: 'arraybuffer' });
    await writeFile(path, Buffer.from(res.data));
    manifest.files.push({ path, ext, code: parts[0], docType: parts[2] || 'unknown', source: 'file' });
  }
  const manifestPath = join(dir, 'manifest.json');
  await writeFile(manifestPath, JSON.stringify(manifest));
  const python = process.env.PYTHON || 'python3';
  const { stdout } = await promisify(execFile)(python, [AUDIT, manifestPath], { maxBuffer: 64 * 1024 * 1024 });
  const result = JSON.parse(stdout);
  log.info(JSON.stringify(result));
  const summary = process.env.GITHUB_STEP_SUMMARY;
  if (summary) {
    const lines = ['## Anonymisation audit', '', `Files checked: **${result.checked}** (unreadable: ${result.unreadable})`, '', '| Document type | Files | With leaks | PDFs without text |', '|---|---|---|---|'];
    for (const [type, s] of Object.entries(result.by_type)) lines.push(`| ${type.replace(/^file:/, '')} | ${s.files} | ${s.with_leaks} | ${s.no_text_pdfs} |`);
    lines.push('', '### Leaked terms', '', ...(result.leaked_terms.length ? result.leaked_terms.map(([t, n]) => `- ${t}: ${n}`) : ['None found']));
    if (Object.keys(result.old_placeholders).length) lines.push('', `Old placeholder tags still present: ${JSON.stringify(result.old_placeholders)}`);
    await appendFile(summary, `${lines.join('\n')}\n`);
  }
} finally {
  await rm(dir, { recursive: true, force: true });
}
