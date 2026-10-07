import * as cheerio from 'cheerio';
import { downloadBuffer, getJson, getText, SkipError } from '../http.js';
import { periodFromReportDate, reportedPeriodFromReleaseDate } from '../periods.js';
import { classifyDocType } from '../files.js';

let tickerMapPromise = null;

function secHeaders(ctx) {
  return { 'User-Agent': ctx.secUserAgent };
}

function secGet(url, ctx, settings) {
  return getJson(url, { headers: secHeaders(ctx), minIntervalMs: settings.edgar.minIntervalMs });
}

async function tickerToCik(ticker, ctx, settings) {
  if (!tickerMapPromise) {
    tickerMapPromise = secGet('https://www.sec.gov/files/company_tickers.json', ctx, settings).then((data) => {
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

// Turns the column-oriented "filings" block of the submissions API into rows we care about.
export function relevantRows(block, forms) {
  const rows = [];
  if (!block?.accessionNumber) return rows;
  const want8k = forms.includes('8-K');
  for (let i = 0; i < block.accessionNumber.length; i++) {
    const form = block.form[i];
    const base = form.replace(/\/A$/, '');
    const isAmendment = form.endsWith('/A');
    let kind = null;
    if (want8k && base === '8-K') {
      const items = String(block.items?.[i] || '').split(',').map((s) => s.trim());
      if (items.includes('2.02')) kind = '8-K';
    } else if (!isAmendment && (base === '10-Q' || base === '10-K' || base === '10-KT') && forms.includes(base === '10-KT' ? '10-K' : base)) {
      kind = base === '10-KT' ? '10-K' : base;
    }
    if (!kind) continue;
    rows.push({
      accession: block.accessionNumber[i],
      form,
      kind,
      filingDate: block.filingDate[i],
      reportDate: block.reportDate?.[i] || '',
      primaryDocument: block.primaryDocument?.[i] || ''
    });
  }
  return rows;
}

// Every relevant filing for one CIK since the cutoff, newest first. Older archive
// pages never change, so their filtered rows are cached in the run state.
async function listFilings(cik, settings, ctx) {
  const padded = cik.padStart(10, '0');
  const submissions = await secGet(`https://data.sec.gov/submissions/CIK${padded}.json`, ctx, settings);
  const cutoff = `${settings.sinceYear - 1}-01-01`;
  const rows = relevantRows(submissions?.filings?.recent, settings.edgar.forms);
  const cache = (ctx.state.edgarPages ||= {});
  for (const file of submissions?.filings?.files || []) {
    if (file.filingTo && file.filingTo < cutoff) continue;
    const key = `${file.name}|${settings.edgar.forms.join(',')}`;
    if (!cache[key]) {
      const page = await secGet(`https://data.sec.gov/submissions/${file.name}`, ctx, settings);
      cache[key] = relevantRows(page, settings.edgar.forms);
    }
    rows.push(...cache[key]);
  }
  const seen = new Set();
  return rows
    .filter((r) => r.filingDate >= cutoff && !seen.has(r.accession) && seen.add(r.accession))
    .sort((a, b) => b.filingDate.localeCompare(a.filingDate));
}

function periodFor(row, company) {
  if (row.kind === '8-K') return reportedPeriodFromReleaseDate(row.reportDate || row.filingDate, company.fiscalYearEndMonth);
  return periodFromReportDate(row.reportDate, company.fiscalYearEndMonth, row.kind);
}

function download(url, name, ctx, settings) {
  return async () => {
    let file;
    try {
      file = await downloadBuffer(url, {
        headers: secHeaders(ctx),
        maxBytes: settings.maxFileBytes,
        minIntervalMs: settings.edgar.minIntervalMs
      });
    } catch (err) {
      // Older or non-XBRL filings have no Financial_Report.xlsx.
      if (/HTTP 404/.test(err.message) && /\.xlsx$/i.test(name)) throw new SkipError(`${url} has no financial report workbook`);
      throw err;
    }
    if (file.contentType === 'text/html' && /\.xlsx$/i.test(name)) throw new SkipError(`${url} has no financial report workbook`);
    return { ...file, dispositionName: file.dispositionName || name, url };
  };
}

async function filingDocs(row, cik, company, settings, ctx) {
  const folder = `https://www.sec.gov/Archives/edgar/data/${cik}/${row.accession.replace(/-/g, '')}/`;
  const base = { source: 'edgar', period: periodFor(row, company), date: row.filingDate, form: row.kind };
  if (row.kind === '8-K') {
    const indexUrl = `${folder}${row.accession}-index.htm`;
    const docs = parseFilingIndex(await getText(indexUrl, { headers: secHeaders(ctx), minIntervalMs: settings.edgar.minIntervalMs }), 'https://www.sec.gov');
    return docs
      .filter((d) => /^EX-99/i.test(d.type))
      .map((doc) => ({
        ...base,
        sourceId: doc.url,
        sourceUrl: doc.url,
        docType: classifyDocType(`${doc.description} ${doc.name}`, /^EX-99\.1$/i.test(doc.type) ? 'press-release' : 'exhibit'),
        hint: doc.type.toLowerCase().replace(/[^a-z0-9]+/g, ''),
        fetch: download(doc.url, doc.name, ctx, settings)
      }));
  }
  const items = [];
  if (row.primaryDocument) {
    const url = `${folder}${row.primaryDocument}`;
    items.push({
      ...base,
      sourceId: url,
      sourceUrl: url,
      docType: row.kind === '10-K' ? 'annual-report-10k' : 'quarterly-report-10q',
      hint: '',
      fetch: download(url, row.primaryDocument, ctx, settings)
    });
  }
  if (settings.edgar.financialReportXlsx) {
    const url = `${folder}Financial_Report.xlsx`;
    items.push({
      ...base,
      sourceId: url,
      sourceUrl: url,
      docType: `financial-statements-${row.kind === '10-K' ? '10k' : '10q'}`,
      hint: '',
      fetch: download(url, 'Financial_Report.xlsx', ctx, settings)
    });
  }
  return items;
}

// Yields documents one filing at a time, then a { groupDone } marker so the caller
// can remember fully processed filings and skip their index pages next run.
export async function* edgarItems(company, settings, ctx) {
  if (!ctx.secUserAgent) {
    ctx.warnOnce('sec-ua', 'SEC_USER_AGENT is not set, so SEC EDGAR is skipped. Set it to "Your Name your@email.com"');
    return;
  }
  const ciks = company.ciks.length ? company.ciks : [await tickerToCik(company.ticker, ctx, settings)].filter(Boolean);
  if (!ciks.length) {
    ctx.log.warn(`${company.ticker}: no SEC CIK found; add "cik" to this company in companies.json`);
    return;
  }
  const done = ctx.doneFilings;
  let count = 0;
  for (const cik of ciks) {
    const rows = await listFilings(cik, settings, ctx);
    for (const row of rows) {
      const period = periodFor(row, company);
      if (period && period.fiscalYear < settings.sinceYear) continue;
      if (settings.edgar.maxFilingsPerCompany && ++count > settings.edgar.maxFilingsPerCompany) return;
      if (done.has(row.accession)) {
        ctx.stats.filingsSkipped++;
        continue;
      }
      let docs;
      try {
        docs = await filingDocs(row, cik, company, settings, ctx);
      } catch (err) {
        ctx.log.warn(`${company.ticker}: could not read EDGAR filing ${row.accession}: ${err.message}`);
        continue;
      }
      for (const doc of docs) yield doc;
      yield { groupDone: row.accession };
    }
  }
}
