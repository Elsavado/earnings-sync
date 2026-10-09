// Company leads: healthcare companies whose recent SEC filings say they hold or work with
// one of the eight data types, with their next earnings call from the Nasdaq calendar.
// Written to the Google Sheet "<private folder>/company-leads"; the companies' websites are
// also saved (leads.json) for the website crawler. Nothing is downloaded from the companies
// here: this is a list to follow up on.
import { getJson } from './http.js';
import { log } from './context.js';

const EFTS = 'https://efts.sec.gov/LATEST/search-index';
const NASDAQ = 'https://api.nasdaq.com/api/calendar/earnings';

// SIC codes: drugs and biologics, diagnostics, lab instruments, medical devices, health
// insurers, health services, medical labs, research, plus software/data services (kept only
// when a filing uses one of the specific phrases below).
const HEALTH_SIC = /^(283[3-6]|3826|384[1-5]|3851|5047|5122|6324|80\d\d|8731|737[0-4])$/;

// Companies that present at investment-bank healthcare conferences are kept when they are in
// diagnostics, lab instruments, devices, labs and health services, research, or health data
// and software; drug makers and insurers are left out.
const CONFERENCE_SIC = /^(2835|3826|384[1-5]|3851|5047|80\d\d|8731|737[0-4])$/;

export function parseDisplayName(display) {
  const m = String(display || '').match(/^(.*?)\s*(?:\(([^)]+)\))?\s*\(CIK (\d+)\)\s*$/);
  if (!m) return { name: String(display || '').trim(), ticker: '', cik: '' };
  return { name: m[1].trim(), ticker: (m[2] || '').split(',')[0].trim(), cik: String(Number(m[3])) };
}

export function filingUrl(cik, id) {
  const [adsh, file] = String(id).split(':');
  return `https://www.sec.gov/Archives/edgar/data/${cik}/${adsh.replace(/-/g, '')}/${file}`;
}

async function searchPhrase(phrase, cfg, userAgent, maxPages = cfg.maxPagesPerPhrase) {
  const end = new Date().toISOString().slice(0, 10);
  const start = new Date(Date.now() - cfg.lookbackDays * 86400000).toISOString().slice(0, 10);
  const hits = [];
  for (let page = 0; page < maxPages; page++) {
    const params = new URLSearchParams({ q: `"${phrase}"`, forms: cfg.forms.join(','), dateRange: 'custom', startdt: start, enddt: end, from: String(page * 100) });
    const data = await getJson(`${EFTS}?${params}`, { headers: { 'User-Agent': userAgent }, minIntervalMs: cfg.secMinIntervalMs });
    const batch = data.hits?.hits || [];
    hits.push(...batch);
    if (batch.length < 100) break;
  }
  return hits;
}

async function earningsCalendar(days, minIntervalMs) {
  const next = new Map();
  for (let d = 0; d < days; d++) {
    const date = new Date(Date.now() + d * 86400000).toISOString().slice(0, 10);
    try {
      const data = await getJson(`${NASDAQ}?date=${date}`, { headers: { 'User-Agent': 'Mozilla/5.0', Accept: 'application/json' }, minIntervalMs, retries: 1 });
      for (const row of data.data?.rows || []) {
        if (!next.has(row.symbol)) next.set(row.symbol, { date, time: String(row.time || '').replace('time-', '') });
      }
    } catch (err) {
      log.warn(`Earnings calendar ${date}: ${err.message}`);
    }
  }
  return next;
}

async function companyWebsite(cik, userAgent, minIntervalMs) {
  try {
    const data = await getJson(`https://data.sec.gov/submissions/CIK${cik.padStart(10, '0')}.json`, { headers: { 'User-Agent': userAgent }, minIntervalMs, retries: 1 });
    const site = data.website || data.investorWebsite || '';
    return site && !/^https?:\/\//.test(site) ? `https://${site}` : site;
  } catch {
    return '';
  }
}

function newCompany(cik, name, ticker, sic) {
  return { cik, name, ticker, sic, categories: new Set(), phrases: new Set(), conferences: new Set(), filings: 0, latest: null };
}

export async function buildLeads(settings, ctx) {
  const cfg = settings.leads;
  const ua = ctx.secUserAgent;
  if (!ua) throw new Error('SEC_USER_AGENT is not set; the SEC requires a name and e-mail on every request');
  const companies = new Map();
  for (const [category, phrases] of Object.entries(cfg.phrases)) {
    for (const phrase of phrases) {
      let hits;
      try {
        hits = await searchPhrase(phrase, cfg, ua);
      } catch (err) {
        ctx.report.errors.push(`SEC search "${phrase}": ${err.message}`);
        continue;
      }
      for (const h of hits) {
        const s = h._source || {};
        const sic = String(s.sics?.[0] || '');
        if (!HEALTH_SIC.test(sic)) continue;
        const { name, ticker, cik } = parseDisplayName(s.display_names?.[0]);
        if (!cik) continue;
        const c = companies.get(cik) || newCompany(cik, name, ticker, sic);
        c.categories.add(category);
        c.phrases.add(phrase);
        c.filings++;
        if (!c.latest || s.file_date > c.latest.date) c.latest = { date: s.file_date, form: s.form, url: filingUrl(cik, h._id) };
        companies.set(cik, c);
      }
      log.info(`SEC "${phrase}": ${hits.length} filing(s); ${companies.size} healthcare companies so far`);
    }
  }

  // Presenters at investment-bank healthcare conferences (J.P. Morgan, Morgan Stanley, Citi, ...),
  // found through the 8-Ks and reports in which they announce or file their presentations.
  for (const conference of cfg.conferences || []) {
    let hits;
    try {
      hits = await searchPhrase(conference, cfg, ua, cfg.maxPagesPerConference || cfg.maxPagesPerPhrase);
    } catch (err) {
      ctx.report.errors.push(`SEC search "${conference}": ${err.message}`);
      continue;
    }
    let found = 0;
    for (const h of hits) {
      const s = h._source || {};
      const sic = String(s.sics?.[0] || '');
      if (!CONFERENCE_SIC.test(sic)) continue;
      const { name, ticker, cik } = parseDisplayName(s.display_names?.[0]);
      if (!cik) continue;
      const c = companies.get(cik) || newCompany(cik, name, ticker, sic);
      if (!c.conferences.has(conference)) found++;
      c.conferences.add(conference);
      c.filings++;
      if (!c.latest || s.file_date > c.latest.date) c.latest = { date: s.file_date, form: s.form, url: filingUrl(cik, h._id) };
      companies.set(cik, c);
    }
    log.info(`SEC "${conference}": ${hits.length} filing(s), ${found} company(ies); ${companies.size} companies so far`);
  }

  const calendar = await earningsCalendar(cfg.earningsDaysAhead, cfg.nasdaqMinIntervalMs);
  const rows = [];
  for (const c of companies.values()) {
    const call = c.ticker ? calendar.get(c.ticker) : null;
    const website = cfg.lookupWebsites ? await companyWebsite(c.cik, ua, cfg.secMinIntervalMs) : '';
    rows.push({ ...c, categories: [...c.categories], phrases: [...c.phrases], conferences: [...c.conferences], nextCall: call?.date || '', callTime: call?.time || '', website });
  }
  rows.sort((a, b) => b.categories.length - a.categories.length || b.conferences.length - a.conferences.length || b.filings - a.filings);
  return rows;
}

function cell(v) {
  const s = String(v ?? '');
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function leadsCsv(rows) {
  const header = ['ticker', 'company', 'cik', 'sic', 'data_types', 'phrases_found', 'conferences', 'filings_mentioning', 'latest_filing_date', 'latest_filing_form', 'latest_filing_url', 'next_earnings_call', 'call_time', 'website'];
  const lines = rows.map((r) =>
    [r.ticker, r.name, r.cik, r.sic, r.categories.join('; '), r.phrases.join('; '), (r.conferences || []).join('; '), r.filings, r.latest?.date, r.latest?.form, r.latest?.url, r.nextCall, r.callTime, r.website].map(cell).join(',')
  );
  return `${[header.join(','), ...lines].join('\n')}\n`;
}

// Splits CSV text (quoted fields, doubled quotes, commas and line breaks inside quotes) into rows.
export function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') {
      row.push(field);
      field = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else field += ch;
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

// The company websites listed in the company-leads sheet, for the website crawler.
export function leadSitesFromCsv(csv) {
  const [header, ...rows] = parseCsv(csv);
  const col = (name) => header.indexOf(name);
  const [ticker, company, website] = [col('ticker'), col('company'), col('website')];
  if (website < 0) return [];
  return rows.filter((r) => r[website]).map((r) => ({ name: r[ticker] || r[company], startUrls: [r[website]] }));
}
