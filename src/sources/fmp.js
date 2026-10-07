import { getJson } from '../http.js';

const BASE = 'https://financialmodelingprep.com/stable';

function apiError(data) {
  if (data && !Array.isArray(data) && typeof data === 'object') {
    return data['Error Message'] || data.error || data.message || JSON.stringify(data).slice(0, 200);
  }
  return null;
}

export function normalizeTranscriptDates(data) {
  if (!Array.isArray(data)) return [];
  return data
    .map((d) => ({
      fiscalYear: Number(d.fiscalYear ?? d.year),
      quarter: Number(d.quarter ?? String(d.period || '').replace(/\D/g, '')),
      date: d.date || null
    }))
    .filter((d) => Number.isInteger(d.fiscalYear) && d.quarter >= 1 && d.quarter <= 4)
    .sort((a, b) => b.fiscalYear - a.fiscalYear || b.quarter - a.quarter);
}

export function formatTranscript(company, period, record) {
  const header = [
    `${company.name} (${company.ticker})`,
    `Earnings call transcript - fiscal ${period.fiscalYear} Q${period.quarter}`,
    record.date ? `Call date: ${record.date}` : null,
    'Source: Financial Modeling Prep',
    ''
  ].filter((line) => line !== null);
  return `${header.join('\n')}\n${String(record.content).trim()}\n`;
}

export async function fmpItems(company, settings, ctx) {
  const apiKey = process.env.FMP_API_KEY;
  if (!apiKey) {
    ctx.warnOnce('fmp-key', 'FMP_API_KEY is not set, so licensed transcripts are skipped');
    return [];
  }
  const symbol = encodeURIComponent(company.fmpSymbol);
  const raw = await getJson(`${BASE}/earning-call-transcript-dates?symbol=${symbol}&apikey=${apiKey}`);
  const error = apiError(raw);
  if (error) throw new Error(`${company.ticker}: Financial Modeling Prep refused the request: ${error}`);

  const periods = normalizeTranscriptDates(raw)
    .filter((p) => p.fiscalYear >= settings.sinceYear)
    .slice(0, settings.fmp.maxTranscriptsPerCompany);

  return periods.map((p) => {
    const period = { fiscalYear: p.fiscalYear, quarter: p.quarter };
    const publicUrl = `${BASE}/earning-call-transcript?symbol=${symbol}&year=${p.fiscalYear}&quarter=${p.quarter}`;
    return {
      source: 'fmp',
      sourceId: `${company.fmpSymbol}:${p.fiscalYear}:Q${p.quarter}`,
      sourceUrl: publicUrl,
      period,
      docType: 'transcript',
      hint: 'fmp',
      async fetch() {
        const data = await getJson(`${publicUrl}&apikey=${apiKey}`);
        const err = apiError(data);
        if (err) throw new Error(`Financial Modeling Prep refused the transcript request: ${err}`);
        const record = Array.isArray(data) ? data.find((r) => r && r.content) : null;
        if (!record) throw new Error(`No transcript text returned for ${company.ticker} FY${p.fiscalYear} Q${p.quarter}`);
        return {
          buffer: Buffer.from(formatTranscript(company, period, record), 'utf8'),
          contentType: 'text/plain',
          dispositionName: 'transcript.txt',
          url: publicUrl
        };
      }
    };
  });
}
