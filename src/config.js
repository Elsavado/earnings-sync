import { readFile } from 'node:fs/promises';

export const DEFAULT_INCLUDE = [
  'transcript',
  'earnings',
  'results',
  'presentation',
  'slides',
  'webcast',
  'supplement',
  'prepared remarks',
  'press release',
  'quarter',
  'q1',
  'q2',
  'q3',
  'q4',
  'financial',
  'fact sheet',
  'factbook',
  'fact book',
  'statistical',
  'investor day',
  'guidance',
  'outlook',
  'metrics',
  'kpi',
  'shareholder letter',
  'letter to shareholders',
  'annual report',
  'quarterly report',
  'remarks',
  'commentary'
];

export const DEFAULT_EXCLUDE = [
  'proxy',
  'annual meeting',
  'esg',
  'sustainability',
  'governance',
  'charter',
  'code of conduct',
  'privacy',
  'cookie'
];

// Analysis documents only: every type here has an anonymiser (see anonymizer/worker.py).
export const DEFAULT_FILE_TYPES = ['pdf', 'xlsx', 'xlsm', 'xls', 'csv', 'docx', 'doc', 'pptx', 'ppt', 'txt'];

export const DEFAULT_DOWNLOAD_HINTS = ['static-files/', '/download', 'getfile', 'doc_financials', 'doc_downloads'];

function lowerList(value, fallback) {
  if (!Array.isArray(value) || value.length === 0) return [...fallback];
  return value.map((v) => String(v).toLowerCase().trim()).filter(Boolean);
}

function normalizeIrPage(page, ticker, index) {
  const entry = typeof page === 'string' ? { url: page } : page;
  if (!entry || typeof entry.url !== 'string') {
    throw new Error(`${ticker}: irPages[${index}] needs a "url"`);
  }
  try {
    const parsed = new URL(entry.url);
    if (!/^https?:$/.test(parsed.protocol)) throw new Error('bad protocol');
  } catch {
    throw new Error(`${ticker}: irPages[${index}].url is not a valid http(s) URL: ${entry.url}`);
  }
  return {
    url: entry.url,
    render: entry.render === true,
    include: lowerList(entry.include, DEFAULT_INCLUDE),
    exclude: lowerList(entry.exclude, DEFAULT_EXCLUDE),
    fileTypes: lowerList(entry.fileTypes, DEFAULT_FILE_TYPES).map((t) => t.replace(/^\./, '')),
    downloadHints: lowerList(entry.downloadHints, DEFAULT_DOWNLOAD_HINTS)
  };
}

function normalizeCompany(company, index) {
  if (!company || typeof company.ticker !== 'string' || !company.ticker.trim()) {
    throw new Error(`companies[${index}] is missing "ticker"`);
  }
  const ticker = company.ticker.trim().toUpperCase();
  const fyEnd = Number(company.fiscalYearEndMonth ?? 12);
  if (!Number.isInteger(fyEnd) || fyEnd < 1 || fyEnd > 12) {
    throw new Error(`${ticker}: fiscalYearEndMonth must be an integer from 1 to 12`);
  }
  const rawCiks = company.cik === undefined || company.cik === null ? [] : Array.isArray(company.cik) ? company.cik : [company.cik];
  const ciks = rawCiks.map((c) => String(c).replace(/\D/g, '').replace(/^0+/, '')).filter(Boolean);
  const sources = company.sources || {};
  return {
    ticker,
    name: company.name || ticker,
    fiscalYearEndMonth: fyEnd,
    cik: ciks[0] || null,
    ciks,
    aliases: (company.aliases || []).map(String).filter(Boolean),
    domains: (company.domains || []).map((d) => String(d).toLowerCase()).filter(Boolean),
    fmpSymbol: company.fmpSymbol ? String(company.fmpSymbol).toUpperCase() : ticker,
    sources: {
      edgar: sources.edgar !== false,
      fmp: sources.fmp !== false,
      ir: sources.ir !== false
    },
    irPages: (company.irPages || []).map((p, i) => normalizeIrPage(p, ticker, i))
  };
}

export function normalizeConfig(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('Config must be a JSON object');
  const s = raw.settings || {};
  const currentYear = new Date().getUTCFullYear();
  const sinceYear = Number(s.sinceYear ?? currentYear - 1);
  if (!Number.isInteger(sinceYear) || sinceYear < 1994 || sinceYear > currentYear + 2) {
    throw new Error('settings.sinceYear must be a four-digit year');
  }
  const maxFileSizeMB = Number(s.maxFileSizeMB ?? 200);
  if (!Number.isFinite(maxFileSizeMB) || maxFileSizeMB <= 0) {
    throw new Error('settings.maxFileSizeMB must be a positive number');
  }

  const settings = {
    sinceYear,
    maxFileBytes: Math.round(maxFileSizeMB * 1024 * 1024),
    driveRootFolderName: s.driveRootFolderName || 'Earnings Calls',
    drivePrivateFolderName: s.drivePrivateFolderName || 'Earnings Sync - private',
    driveReserveMB: Number(s.driveReserveMB ?? 1024),
    runBudgetMinutes: Number(process.env.RUN_BUDGET_MINUTES || s.runBudgetMinutes || 0),
    convertHtmlToGoogleDocs: s.convertHtmlToGoogleDocs === true,
    respectRobotsTxt: s.respectRobotsTxt !== false,
    anonymize: {
      enabled: s.anonymize?.enabled !== false,
      companyIdentity: s.anonymize?.companyIdentity !== false,
      personalInfo: s.anonymize?.personalInfo !== false
    },
    edgar: {
      enabled: s.edgar?.enabled !== false,
      // 0 means no cap.
      maxFilingsPerCompany: Number(s.edgar?.maxFilingsPerCompany ?? 0),
      forms: Array.isArray(s.edgar?.forms) ? s.edgar.forms.map(String) : ['8-K', '10-Q', '10-K'],
      financialReportXlsx: s.edgar?.financialReportXlsx !== false,
      minIntervalMs: Number(process.env.SEC_MIN_INTERVAL_MS || s.edgar?.minIntervalMs || 150)
    },
    fmp: {
      enabled: s.fmp?.enabled !== false,
      maxTranscriptsPerCompany: Number(s.fmp?.maxTranscriptsPerCompany ?? 4)
    },
    ir: {
      enabled: s.ir?.enabled !== false,
      maxFilesPerPage: Number(s.ir?.maxFilesPerPage ?? 0),
      minIntervalMs: Number(s.ir?.minIntervalMs ?? 1000)
    }
  };

  if (!Array.isArray(raw.companies) || raw.companies.length === 0) {
    throw new Error('Config needs a non-empty "companies" array');
  }
  const companies = raw.companies.map(normalizeCompany);
  const tickers = new Set();
  for (const c of companies) {
    if (tickers.has(c.ticker)) throw new Error(`Ticker ${c.ticker} is listed more than once`);
    tickers.add(c.ticker);
  }
  return { settings, companies };
}

export async function loadConfig(path) {
  let text;
  try {
    text = await readFile(path, 'utf8');
  } catch (err) {
    throw new Error(`Could not read config file ${path}: ${err.message}`);
  }
  let raw;
  try {
    raw = JSON.parse(text);
  } catch (err) {
    throw new Error(`Config file ${path} is not valid JSON: ${err.message}`);
  }
  return normalizeConfig(raw);
}
