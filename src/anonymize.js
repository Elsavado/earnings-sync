import { spawn } from 'node:child_process';
import { createHmac } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const WORKER = fileURLToPath(new URL('../anonymizer/worker.py', import.meta.url));
const JOB_TIMEOUT_MS = 5 * 60 * 1000;

// Stable code per company. Without ANON_KEY nobody can map a code back to a ticker,
// even though companies.json (and so the ticker list) is public.
export function companyCode(ticker, key) {
  return `CO-${createHmac('sha256', key).update(ticker).digest('hex').slice(0, 6).toUpperCase()}`;
}

export function assignCodes(companies, key) {
  const seen = new Map();
  for (const c of companies) {
    c.code = companyCode(c.ticker, key);
    if (seen.has(c.code)) throw new Error(`Company codes collide for ${seen.get(c.code)} and ${c.ticker}; change ANON_KEY`);
    seen.set(c.code, c.ticker);
  }
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Removes company names from short strings such as link text before they go into file names.
export function scrubHint(text, company) {
  let out = String(text || '');
  const terms = [...company.aliases, company.name, company.ticker.length >= 3 ? company.ticker : null]
    .filter(Boolean)
    .sort((a, b) => b.length - a.length);
  for (const term of terms) out = out.replace(new RegExp(`(?<![\\w])${escapeRegex(term)}(?![\\w])`, 'gi'), ' ');
  for (const d of company.domains) out = out.replace(new RegExp(escapeRegex(d), 'gi'), ' ');
  return out;
}

export class Anonymizer {
  constructor({ companies, companyIdentity, personalInfo, log }) {
    this.config = {
      type: 'config',
      company: companyIdentity,
      personal: personalInfo,
      companies: companies.map((c) => ({
        ticker: c.ticker,
        code: c.code,
        name: c.name,
        aliases: c.aliases,
        domains: c.domains,
        ciks: c.ciks
      }))
    };
    this.log = log;
    this.proc = null;
    this.nextId = 1;
    this.pending = new Map();
    this.queue = Promise.resolve();
  }

  async start() {
    if (this.proc) return;
    const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
    const proc = spawn(python, [WORKER], { stdio: ['pipe', 'pipe', 'inherit'] });
    this.proc = proc;
    let buffer = '';
    let ready;
    const readyPromise = new Promise((resolve, reject) => {
      ready = resolve;
      proc.once('error', (err) => reject(new Error(`Could not start the anonymiser (${python}): ${err.message}`)));
    });
    proc.stdout.on('data', (chunk) => {
      buffer += chunk.toString('utf8');
      let nl;
      while ((nl = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        let msg;
        try {
          msg = JSON.parse(line);
        } catch {
          continue;
        }
        if (msg.type === 'ready') ready();
        const waiter = this.pending.get(msg.id);
        if (waiter) {
          this.pending.delete(msg.id);
          waiter(msg);
        }
      }
    });
    proc.on('exit', (code) => {
      if (this.proc === proc) this.proc = null;
      for (const waiter of this.pending.values()) waiter({ ok: false, error: `anonymiser exited (code ${code})` });
      this.pending.clear();
    });
    proc.stdin.write(`${JSON.stringify(this.config)}\n`);
    await Promise.race([
      readyPromise,
      new Promise((_, reject) => setTimeout(() => reject(new Error('Anonymiser did not start within 120 s')), 120000))
    ]);
  }

  // Jobs run one at a time; returns { buffer, ext, stats }. Throws rather than ever
  // returning the original bytes, so a failure can never upload an unredacted file.
  process(buffer, ext, ticker) {
    const run = async () => {
      await this.start();
      const dir = await mkdtemp(join(tmpdir(), 'anon-'));
      const input = join(dir, `in.${ext}`);
      const output = join(dir, 'out.bin');
      try {
        await writeFile(input, buffer);
        const id = this.nextId++;
        const reply = await new Promise((resolve) => {
          const timer = setTimeout(() => {
            this.pending.delete(id);
            this.proc?.kill();
            resolve({ ok: false, error: 'anonymiser timed out' });
          }, JOB_TIMEOUT_MS);
          this.pending.set(id, (msg) => {
            clearTimeout(timer);
            resolve(msg);
          });
          this.proc.stdin.write(`${JSON.stringify({ id, in: input, out: output, ext, ticker })}\n`);
        });
        if (!reply.ok) throw new Error(`anonymising failed: ${reply.error}`);
        return { buffer: await readFile(output), ext: reply.ext, stats: reply.stats };
      } finally {
        await rm(dir, { recursive: true, force: true });
      }
    };
    const result = this.queue.then(run, run);
    this.queue = result.catch(() => {});
    return result;
  }

  async close() {
    if (!this.proc) return;
    this.proc.stdin.end();
    await new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.proc?.kill();
        resolve();
      }, 5000);
      this.proc.once('exit', () => {
        clearTimeout(timer);
        resolve();
      });
    });
  }
}
