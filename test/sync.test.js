import { test } from 'node:test';
import assert from 'node:assert/strict';
import { effectiveMonth, periodFromReportDate } from '../src/periods.js';
import { relevantRows } from '../src/sources/edgar.js';
import { findResultsLink } from '../src/sources/ir.js';
import { smartFileName } from '../src/files.js';
import { assignCodes, companyCode, scrubHint } from '../src/anonymize.js';
import { normalizeConfig } from '../src/config.js';

test('52/53-week period ends map to the previous month', () => {
  assert.deepEqual(effectiveMonth('2026-01-03'), { year: 2025, month: 12 });
  assert.deepEqual(effectiveMonth('2026-09-26'), { year: 2026, month: 9 });
  // J&J (year ends ~3 Jan, so December) quarter ending 29 Mar 2026
  assert.deepEqual(periodFromReportDate('2026-03-29', 12, '10-Q'), { fiscalYear: 2026, quarter: 1 });
  // Apple 10-K for the year ending 26 Sep 2026
  assert.deepEqual(periodFromReportDate('2026-09-26', 9, '10-K'), { fiscalYear: 2026, quarter: 4 });
  // Micron quarter ending 4 Jun 2026 with a year ending early September (August)
  assert.deepEqual(periodFromReportDate('2026-06-04', 8, '10-Q'), { fiscalYear: 2026, quarter: 3 });
});

test('EDGAR rows keep earnings 8-Ks, 10-Qs and 10-Ks only', () => {
  const block = {
    accessionNumber: ['a1', 'a2', 'a3', 'a4', 'a5', 'a6'],
    form: ['8-K', '8-K', '10-Q', '10-K/A', '424B2', '10-K'],
    items: ['2.02,9.01', '5.07', '', '', '', ''],
    filingDate: ['2026-07-14', '2026-06-01', '2026-08-01', '2026-03-01', '2026-02-01', '2026-02-13'],
    reportDate: ['2026-07-14', '', '2026-06-30', '', '', '2025-12-31'],
    primaryDocument: ['x.htm', 'y.htm', 'q.htm', 'ka.htm', 'n.htm', 'k.htm']
  };
  assert.deepEqual(
    relevantRows(block, ['8-K', '10-Q', '10-K']).map((r) => `${r.accession}:${r.kind}`),
    ['a1:8-K', 'a3:10-Q', 'a6:10-K']
  );
  assert.deepEqual(relevantRows(block, ['8-K']).map((r) => r.accession), ['a1']);
});

test('finds the quarterly results page on an IR home page', () => {
  const html = `<a href="/news">News</a><a href="https://other.com/q">Quarterly Results</a>
    <a href="/financial-information/financial-results">Financial Results</a>
    <a href="/financial-information/quarterly-results">Quarterly Results</a>`;
  assert.equal(findResultsLink(html, 'https://ir.example.com/'), 'https://ir.example.com/financial-information/quarterly-results');
  assert.equal(findResultsLink('<a href="/x">About</a>', 'https://ir.example.com/'), null);
});

test('company codes are stable, secret-dependent and unique', () => {
  assert.equal(companyCode('JPM', 'k1'), companyCode('JPM', 'k1'));
  assert.notEqual(companyCode('JPM', 'k1'), companyCode('JPM', 'k2'));
  assert.match(companyCode('JPM', 'k1'), /^CO-[0-9A-F]{6}$/);
  const { companies } = normalizeConfig({ companies: [{ ticker: 'A' }, { ticker: 'B' }, { ticker: 'C' }] });
  assignCodes(companies, 'k1');
  assert.equal(new Set(companies.map((c) => c.code)).size, 3);
});

test('file names carry the code, never the company', () => {
  const { companies } = normalizeConfig({
    companies: [{ ticker: 'NVDA', name: 'NVIDIA Corporation', aliases: ['NVIDIA'], domains: ['nvidia.com'] }]
  });
  const [c] = companies;
  c.code = 'CO-ABC123';
  const name = smartFileName({
    code: c.code,
    periodLabel: 'FY2027-Q2',
    docType: 'presentation',
    date: '',
    hint: scrubHint('NVIDIA Q2 FY27 CFO Commentary slides (PDF 1.2 MB)', c),
    uid: 'a3f9c2',
    ext: 'pdf'
  });
  assert.equal(name, 'CO-ABC123_FY2027-Q2_investor-presentation_cfo-commentary-slides_a3f9c2.pdf');
  assert.doesNotMatch(name, /nvidia|nvda/i);
});
