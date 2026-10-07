import * as cheerio from 'cheerio';
import { downloadBuffer, getJson, getText, SkipError } from '../http.js';
import { fiscalMonthFromSec, periodFromReportDate, reportedPeriodFromReleaseDate } from '../periods.js';
import { classifyDocType } from '../files.js';
import { normalizeIrPage } from '../config.js';

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
    if (base === '8-K') {
      const items = String(block.items?.[i] || '').split(',').map((s) => s.trim());
      if (want8k && items.includes('2.02')) kind = '8-K';
      // Regulation FD / other events: investor presentations, business updates, investor days.
      else if (forms.includes('8-K-IR') && (items.includes('7.01') || items.includes('8.01'))) kind = '8-K-IR';
    } else if (!isAmendment) {
      // 10-K405 and 10-KT are older/transition variants of the annual report;
      // foreign filers use 20-F or 40-F (annual) and 6-K (interim and results releases).
      // 424B4 is the final IPO prospectus, DEFM14A a merger proxy (with the bankers'
      // fairness analyses) and SC 13E3 a going-private filing (with banker presentations).
      const map = {
        '10-Q': '10-Q', '10-K': '10-K', '10-K405': '10-K', '10-KT': '10-K', '20-F': '20-F', '40-F': '20-F', '6-K': '6-K',
        '424B4': 'prospectus', DEFM14A: 'merger-proxy', 'SC 13E3': 'going-private'
      };
      if (map[base] && forms.includes(map[base])) kind = map[base];
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
  const sorted = rows
    .filter((r) => r.filingDate >= cutoff && !seen.has(r.accession) && seen.add(r.accession))
    .sort((a, b) => b.filingDate.localeCompare(a.filingDate));
  return {
    rows: sorted,
    fiscalYearEnd: submissions?.fiscalYearEnd,
    website: submissions?.investorWebsite || submissions?.website || ''
  };
}

function periodFor(row, company) {
  if (['10-Q', '10-K', '20-F'].includes(row.kind)) return periodFromReportDate(row.reportDate, company.fiscalYearEndMonth, row.kind);
  return reportedPeriodFromReleaseDate(row.reportDate || row.filingDate, company.fiscalYearEndMonth);
}

// 8-K items 7.01/8.01 cover anything from investor decks to routine notices; exhibits
// are kept only when their text reads like investor or analytical material.
const INVESTOR_RE = /investor\s+(day|presentation|update|conference|meeting)|analyst\s+day|capital\s+markets\s+day|business\s+update|corporate\s+(presentation|overview|update)|strategic\s+(update|plan|review)|(conference|earnings)\s+call|transcript|fireside|financial\s+outlook|guidance|(first|second|third|fourth)[-\s]+quarter|preliminary\s+(results|financial)|operating\s+(metrics|statistics|update)|supplemental\s+(information|data)/i;

function looksLike(file, re) {
  const head = file.buffer.subarray(0, 60000).toString('latin1').replace(/<[^>]+>/g, ' ').replace(/&nbsp;|&#160;/g, ' ');
  return file.contentType === 'application/pdf' || /\.pdf$/i.test(file.url) || re.test(head);
}

function checked(fetcher, re, what, url) {
  return async () => {
    const file = await fetcher();
    if (!looksLike(file, re)) throw new SkipError(`exhibit is not ${what} (${url})`);
    return file;
  };
}

// 6-Ks carry everything from results to routine notices; keep the results material.
// 6-K exhibits are labelled generically ("EX-99.1 ex99-1.htm"), so they are judged by
// their opening text: kept when it reads like results, skipped otherwise.
const RESULTS_6K = /(first|second|third|fourth|1st|2nd|3rd|4th)[-\s]+quarter|quarterly\s+results|(three|six|nine|twelve)\s+months\s+ended|half[-\s]+year|semi[-\s]?annual|interim\s+(?:(?:unaudited|condensed|consolidated)\s+)*(financial|results|report)|earnings\s+release|financial\s+(results|statements)|results\s+of\s+operations|trading\s+update|annual\s+results/i;

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
      // Older or non-XBRL filings have no Financial_Report.xlsx, and some old exhibits
      // listed in filing indexes no longer exist: both are permanent, so skip them.
      if (/HTTP 404/.test(err.message)) throw new SkipError(/\.xlsx$/i.test(name) ? `${url} has no financial report workbook` : `${url} no longer exists on EDGAR`);
      throw err;
    }
    if (file.contentType === 'text/html' && /\.xlsx$/i.test(name)) throw new SkipError(`${url} has no financial report workbook`);
    return { ...file, dispositionName: file.dispositionName || name, url };
  };
}

async function filingDocs(row, cik, company, settings, ctx) {
  const folder = `https://www.sec.gov/Archives/edgar/data/${cik}/${row.accession.replace(/-/g, '')}/`;
  const base = { source: 'edgar', period: periodFor(row, company), date: row.filingDate, form: row.kind };
  const readIndex = async () =>
    parseFilingIndex(
      await getText(`${folder}${row.accession}-index.htm`, { headers: secHeaders(ctx), minIntervalMs: settings.edgar.minIntervalMs }),
      'https://www.sec.gov'
    );
  const exhibit = (doc, docType, fetch) => ({
    ...base,
    sourceId: doc.url,
    sourceUrl: doc.url,
    docType,
    hint: doc.type.toLowerCase().replace(/[^a-z0-9]+/g, ''),
    fetch: fetch || download(doc.url, doc.name, ctx, settings)
  });
  const docFile = (d) => /\.(htm|html|pdf|txt)$/i.test(d.name);

  if (row.kind === '8-K' || row.kind === '6-K' || row.kind === '8-K-IR') {
    const docs = (await readIndex()).filter((d) => /^EX-99/i.test(d.type) && (row.kind === '8-K' || docFile(d)));
    return docs.map((doc) => {
      const label = `${doc.description} ${doc.name}`;
      if (row.kind === '8-K') return exhibit(doc, classifyDocType(label, /^EX-99\.1$/i.test(doc.type) ? 'press-release' : 'exhibit'));
      if (row.kind === '6-K') {
        return exhibit(doc, classifyDocType(label, 'results-release'), checked(download(doc.url, doc.name, ctx, settings), RESULTS_6K, 'a results release', doc.url));
      }
      return exhibit(doc, classifyDocType(label, 'investor-update'), checked(download(doc.url, doc.name, ctx, settings), INVESTOR_RE, 'investor material', doc.url));
    });
  }
  if (row.kind === 'going-private') {
    // Exhibits (c)(n) are the financial advisers' presentations and fairness analyses.
    const docs = (await readIndex()).filter((d) => /^EX-99\.?\(?C/i.test(d.type) && docFile(d));
    return docs.map((doc) => exhibit(doc, 'fairness-analysis'));
  }

  const items = [];
  if (row.primaryDocument) {
    const url = `${folder}${row.primaryDocument}`;
    items.push({
      ...base,
      sourceId: url,
      sourceUrl: url,
      docType: {
        '10-K': 'annual-report-10k',
        '10-Q': 'quarterly-report-10q',
        '20-F': 'annual-report-20f',
        prospectus: 'ipo-prospectus',
        'merger-proxy': 'merger-proxy-fairness-opinions'
      }[row.kind],
      hint: '',
      fetch: download(url, row.primaryDocument, ctx, settings)
    });
  }
  if (row.kind === 'prospectus' || row.kind === 'merger-proxy') return items;
  if (row.kind === '10-K') {
    // The glossy annual report to shareholders is often attached as Exhibit 13.
    try {
      for (const doc of (await readIndex()).filter((d) => /^EX-13/i.test(d.type) && docFile(d))) {
        items.push(exhibit(doc, 'annual-report-to-shareholders'));
      }
    } catch (err) {
      ctx.log.warn(`${company.ticker}: could not read the 10-K index ${row.accession}: ${err.message}`);
    }
  }
  if (settings.edgar.financialReportXlsx) {
    const url = `${folder}Financial_Report.xlsx`;
    items.push({
      ...base,
      sourceId: url,
      sourceUrl: url,
      docType: `financial-statements-${row.kind.replace('-', '').toLowerCase()}`,
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
    const { rows, fiscalYearEnd, website } = await listFilings(cik, settings, ctx);
    if (company.fiscalYearEndMonth === null) company.fiscalYearEndMonth = fiscalMonthFromSec(fiscalYearEnd);
    // Bulk-added companies have no curated IR page; use the investor site the SEC has on file.
    if (company.auto && !company.irPages.length && /^https?:\/\/|^www\./i.test(website)) {
      company.irPages = [normalizeIrPage({ url: /^https?:/i.test(website) ? website : `https://${website}`, render: true }, company.ticker, 0)];
      company.sources.ir = true;
    }
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
