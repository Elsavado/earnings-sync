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
export function companyCode(ticker, key, length = 6) {
  return `CO-${createHmac('sha256', key).update(ticker).digest('hex').slice(0, length).toUpperCase()}`;
}

// Invented one-word names of every length from 4 to 12 letters, so each company can get
// a name about as long as its real one (replacements then fit in place inside PDFs).
const NAME_WORDS = `
  Arlo Brio Cova Delo Elva Fyra Kael Lumo Mova Nira Orla Pava Sora Tavo Vyra Zeno
  Aveta Brivo Calyx Doria Elmar Fenra Galvo Halor Ivora Kelso Lumar Morva Nexor Orvia Pyron Ravel Solva Torin Velin Wyndo Zarel
  Aldren Bravia Corvex Dravia Elmora Farell Galden Halvex Ivoran Kestra Lumora Marvon Norvik Orlana Pellar Quinar Ravena Solmar Torvex Velara Wexley Zorana
  Alderan Brennan Calvora Dorivan Elmsley Falcora Galvane Halcyra Ivernet Lumaris Marlowe Norland Pellion Quintar Ravenor Solvane Torland Velmont Westmar Zephora
  Alderwyn Caldoria Dravonis Elmscott Fernmont Galvaris Halvoran Ivermont Kingsley Lumivore Marlwood Orlevant Quinmore Ravenhal Solveran Torridon Velantis Westholm Zephyral
  Ashbourne Brookmere Calverton Dunsworth Elmsworth Fernhaven Glenmoray Hartfield Ivorstone Kingsmere Marlstone Northgate Pembridge Quarrydon Ravenwood Silverend Thornbury Valebrook Wyndhaven
  Amberfield Blackthorn Brightwell Caldermont Driftmoore Emberstone Glenhallow Harrowgate Ironbridge Kestrelton Larchmount Maplecrest Northbrook Oakenshire Pinehollow Ravensdale Silverline Wintermere
  Amberbridge Brightwater Cinderfield Falconridge Granitefall Hollowbrook Juniperdale Kingsbridge Lanternhill Marblestone Nettlefield Quarryfield Stonebridge Willowmeade
  Brightmeadow Thornborough Silverbrooke Ravensbourne
`.trim().split(/\s+/);
const NAME_SECOND = ['Dynamics', 'Industries', 'Systems', 'Holdings', 'Group', 'Works', 'Enterprises', 'Partners', 'Global', 'Ventures', 'Collective', 'Alliance'];
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

// Natural-sounding compound names for bulk-added companies ("Cedarbrook", "Ravenmoor").
const PARTS_A = ['Alder', 'Amber', 'Ash', 'Birch', 'Bright', 'Cedar', 'Cobalt', 'Copper', 'Crest', 'Dune', 'Elm', 'Ember', 'Fair', 'Falcon', 'Fern', 'Glen', 'Granite', 'Harbor', 'Hazel', 'Iron', 'Juniper', 'Lark', 'Laurel', 'Maple', 'Marble', 'Meadow', 'Moss', 'North', 'Oak', 'Opal', 'Pine', 'Quarry', 'Raven', 'Rowan', 'Sable', 'Silver', 'Stone', 'Summit', 'Thorn', 'Vale', 'West', 'Willow', 'Wren', 'Briar', 'Clover', 'Dover', 'Easton', 'Fox', 'Gold', 'Heron'];
const PARTS_B = ['brook', 'field', 'gate', 'haven', 'ridge', 'stone', 'wood', 'worth', 'mont', 'vale', 'crest', 'ford', 'ton', 'well', 'more', 'dale', 'hurst', 'mere', 'wick', 'shire', 'port', 'point', 'bridge', 'view', 'land', 'holm', 'stead', 'combe', 'ley', 'bury', 'cliff', 'fall', 'moor', 'rock', 'side', 'star', 'bay', 'run', 'field', 'grove'];

function inventWord(d, target) {
  let best = null;
  for (let i = 0; i < 12; i++) {
    const w = PARTS_A[d[i * 2] % PARTS_A.length] + PARTS_B[d[i * 2 + 1] % PARTS_B.length];
    if (!best || Math.abs(w.length - target) < Math.abs(best.length - target)) best = w;
  }
  return best;
}

function digest(key, label) {
  return createHmac('sha256', key).update(label).digest();
}

// Imaginary identity used inside documents: "Northwind Dynamics", ticker "NWDQ",
// northwinddynamics.example. Derived from ANON_KEY, unique within the list.
export function assignPseudonyms(companies, key) {
  // Curated companies are assigned exactly as before bulk additions existed, so their
  // fictional names never change; bulk-added companies come after and avoid them.
  const curated = companies.filter((c) => !c.auto);
  const realTickers = new Set(curated.map((c) => c.ticker));
  const allRealTickers = new Set(companies.map((c) => c.ticker));
  const names = new Set();
  const tickers = new Set();
  const seed = digest(key, 'pseudonyms').toString('hex');
  for (const c of companies.filter((x) => x.auto)) c.fake = null;
  for (const c of curated) {
    const core = c.name.replace(/^The\s+/, '').split(/[\s,]+/)[0].replace(/[^A-Za-z0-9]/g, '');
    const target = Math.min(12, Math.max(4, core.length));
    let n = 0;
    let name;
    let ticker;
    let word;
    do {
      const d = digest(key, `company|${c.ticker}|${n++}`);
      const slack = 1 + Math.floor(n / 25);
      const pool = NAME_WORDS.filter((w) => Math.abs(w.length - target) <= slack);
      word = pool[d.readUInt16BE(0) % pool.length];
      name = `${word} ${NAME_SECOND[d[2] % NAME_SECOND.length]}`;
      ticker = Array.from({ length: 4 }, (_, i) => LETTERS[d[3 + i] % 26]).join('');
      // The one-word short form ("Kestra") must be unique as well as the full name.
    } while (names.has(word) || tickers.has(ticker) || realTickers.has(ticker));
    names.add(word);
    tickers.add(ticker);
    const d = digest(key, `ids|${c.ticker}`);
    c.fake = {
      name,
      ticker,
      domain: `${name.toLowerCase().replace(/[^a-z]/g, '')}.example`,
      cik: String(1000000 + (d.readUInt32BE(0) % 8999999)),
      seed
    };
  }
  // Bulk-added names only appear in their own documents, so the full name must be
  // unique and the short word must not clash with a curated company's.
  const fullNames = new Set();
  for (const c of companies.filter((x) => x.auto)) {
    const core = c.name.replace(/^The\s+/i, '').split(/[\s,]+/)[0].replace(/[^A-Za-z0-9]/g, '');
    const target = Math.min(12, Math.max(6, core.length));
    let n = 0;
    let word;
    let ticker;
    let name;
    do {
      const d = digest(key, `auto|${c.ticker}|${n++}`);
      word = inventWord(d, target);
      name = `${word} ${NAME_SECOND[d[30] % NAME_SECOND.length]}`;
      ticker = Array.from({ length: 4 }, (_, i) => LETTERS[d[24 + i] % 26]).join('');
    } while ((names.has(word) || fullNames.has(name) || tickers.has(ticker) || allRealTickers.has(ticker)) && n < 1000);
    if (fullNames.has(name)) throw new Error(`Could not find a unique fictional name for ${c.ticker}`);
    fullNames.add(name);
    tickers.add(ticker);
    const d = digest(key, `ids|${c.ticker}`);
    c.fake = {
      name,
      ticker,
      domain: `${name.toLowerCase().replace(/[^a-z]/g, '')}.example`,
      cik: String(1000000 + (d.readUInt32BE(0) % 8999999)),
      seed
    };
  }
}

export function assignCodes(companies, key) {
  const seen = new Map();
  for (const c of companies) {
    // Codes stay six characters; a later company whose code is taken gets a longer one.
    let length = 6;
    c.code = companyCode(c.ticker, key, length);
    while (seen.has(c.code) && length < 16) c.code = companyCode(c.ticker, key, (length += 2));
    if (seen.has(c.code)) throw new Error(`Company codes collide for ${seen.get(c.code)} and ${c.ticker}; change ANON_KEY`);
    seen.set(c.code, c.ticker);
  }
  assignPseudonyms(companies, key);
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
        ciks: c.ciks,
        auto: c.auto,
        fake: c.fake
      })),
      seed: companies[0]?.fake?.seed || ''
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
