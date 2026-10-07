import * as cheerio from 'cheerio';
import { downloadBuffer, getJson, getText } from '../http.js';
import { reportedPeriodFromReleaseDate } from '../periods.js';
import { classifyDocType } from '../files.js';

const SEC_INTERVAL_MS = 150;
let tickerMapPromise = null;

function secHeaders(ctx) {
  return { 'User-Agent': ctx.secUserAgent };
}

async function tickerToCik(ticker, ctx) {
  if (!tickerMapPromise) {
    tickerMapPromise = getJson('https://www.sec.gov/files/company_tickers.json', {
      headers: secHeaders(ctx),
      minIntervalMs: SEC_INTERVAL_MS
    }).then((data) => {
      const map = new Map();
      for (const row of Object.values(data)) map.set(String(row.ticker).toUpperCase(), String(row.cik_str));
      return map;
    });
    tickerMapPromise.catch(() => {
      tickerMapPromise = null;
    });
  }
  const map = await tickerMapPromise;
  return map.get(ticker.replace('.', '-')) || map.get(ticker) || null;
}

export function parseFilingIndex(html, baseUrl) {
  const $ = cheerio.load(html);
  const docs = [];
  $('table.tableFile tr').each((_, tr) => {
    const cells = $(tr).find('td');
    if (cells.length < 4) return;
    const description = cells.eq(1).text().replace(/\s+/g, ' ').trim();
    const link = cells.eq(2).find('a').first();
    const type = cells.eq(3).text().trim();
    let href = link.attr('href');
    if (!href) return;
    href = href.replace(/^\/ix\?doc=/, '');
    docs.push({
      description,
      type,
      name: link.text().trim(),
      url: new URL(href, baseUrl).toString()
    });
  });
  return docs;
}

export async function edgarItems(company, settings, ctx) {
  if (!ctx.secUserAgent) {
    ctx.warnOnce('sec-ua', 'SEC_USER_AGENT is not set, so SEC EDGAR is skipped. Set it to "Your Name your@email.com"');
    return [];
  }
  const cik = company.cik ? company.cik.replace(/^0+/, '') : await tickerToCik(company.ticker, ctx);
  if (!cik) {
    ctx.log.warn(`${company.ticker}: no SEC CIK found; add "cik" to this company in companies.json`);
    return [];
  }

  const submissions = await getJson(`https://data.sec.gov/submissions/CIK${cik.padStart(10, '0')}.json`, {
    headers: secHeaders(ctx),
    minIntervalMs: SEC_INTERVAL_MS
  });
  const recent = submissions?.filings?.recent;
  if (!recent?.accessionNumber) return [];

  const filings = [];
  for (let i = 0; i < recent.accessionNumber.length && filings.length < settings.edgar.maxFilingsPerCompany; i++) {
    const filingDate = recent.filingDate[i];
    if (Number(String(filingDate).slice(0, 4)) < settings.sinceYear - 1) break;
    const form = recent.form[i];
    if (form !== '8-K' && form !== '8-K/A') continue;
    const items = String(recent.items?.[i] || '')
      .split(',')
      .map((s) => s.trim());
    if (!items.includes('2.02')) continue;
    const eventDate = recent.reportDate?.[i] || filingDate;
    const period = reportedPeriodFromReleaseDate(eventDate, company.fiscalYearEndMonth);
    if (period && period.fiscalYear < settings.sinceYear) continue;
    filings.push({ accession: recent.accessionNumber[i], period, form });
  }

  const out = [];
  for (const filing of filings) {
    const folder = `https://www.sec.gov/Archives/edgar/data/${cik}/${filing.accession.replace(/-/g, '')}/`;
    const indexUrl = `${folder}${filing.accession}-index.htm`;
    let docs;
    try {
      docs = parseFilingIndex(
        await getText(indexUrl, { headers: secHeaders(ctx), minIntervalMs: SEC_INTERVAL_MS }),
        'https://www.sec.gov'
      );
    } catch (err) {
      ctx.log.warn(`${company.ticker}: could not read EDGAR index ${indexUrl}: ${err.message}`);
      continue;
    }
    for (const doc of docs.filter((d) => /^EX-99/i.test(d.type))) {
      const fallback = /^EX-99\.1$/i.test(doc.type) ? 'press-release' : 'exhibit';
      out.push({
        source: 'edgar',
        sourceId: doc.url,
        sourceUrl: doc.url,
        period: filing.period,
        docType: classifyDocType(`${doc.description} ${doc.name}`, fallback),
        hint: `${doc.type} ${filing.accession}`,
        async fetch() {
          const file = await downloadBuffer(doc.url, {
            headers: secHeaders(ctx),
            maxBytes: settings.maxFileBytes,
            minIntervalMs: SEC_INTERVAL_MS
          });
          return { ...file, dispositionName: file.dispositionName || doc.name, url: doc.url };
        }
      });
    }
  }
  return out;
}
