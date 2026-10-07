import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parsePeriod, reportedPeriodFromReleaseDate, fiscalPeriodForQuarterEnd } from '../src/periods.js';
import { parseRobots, robotsAllows } from '../src/robots.js';
import { extractCandidateLinks } from '../src/sources/ir.js';
import { parseFilingIndex } from '../src/sources/edgar.js';
import { normalizeTranscriptDates } from '../src/sources/fmp.js';
import { normalizeConfig } from '../src/config.js';
import { buildFileName, classifyDocType, resolveExtension } from '../src/files.js';
import { fileNameFromDisposition, redactUrl } from '../src/http.js';

test('fiscal quarter mapping', () => {
  assert.deepEqual(fiscalPeriodForQuarterEnd(2025, 12, 9), { fiscalYear: 2026, quarter: 1 });
  assert.deepEqual(fiscalPeriodForQuarterEnd(2026, 9, 9), { fiscalYear: 2026, quarter: 4 });
  assert.deepEqual(fiscalPeriodForQuarterEnd(2026, 3, 12), { fiscalYear: 2026, quarter: 1 });
  assert.deepEqual(fiscalPeriodForQuarterEnd(2025, 9, 6), { fiscalYear: 2026, quarter: 1 });
  assert.deepEqual(fiscalPeriodForQuarterEnd(2026, 1, 1), { fiscalYear: 2026, quarter: 4 });
});

test('release date to reported quarter', () => {
  assert.deepEqual(reportedPeriodFromReleaseDate('2026-01-29', 9), { fiscalYear: 2026, quarter: 1 });
  assert.deepEqual(reportedPeriodFromReleaseDate('2026-10-30', 9), { fiscalYear: 2026, quarter: 4 });
  assert.deepEqual(reportedPeriodFromReleaseDate('2026-07-14', 12), { fiscalYear: 2026, quarter: 2 });
  assert.deepEqual(reportedPeriodFromReleaseDate('2026-02-20', 1), { fiscalYear: 2026, quarter: 4 });
  assert.deepEqual(reportedPeriodFromReleaseDate('2026-01-28', 6), { fiscalYear: 2026, quarter: 2 });
  assert.equal(reportedPeriodFromReleaseDate('not a date', 12), null);
});

test('period parsing from link text and URLs', () => {
  const cases = [
    ['Q3 2026 Earnings Call Transcript', 2026, 3],
    ['Q4FY26 slides', 2026, 4],
    ["Q2'26 presentation", 2026, 2],
    ['FY2026 Q1 Results', 2026, 1],
    ['/files/doc_financials/2026/q3/report.pdf', 2026, 3],
    ['Third Quarter Fiscal 2026 Results', 2026, 3],
    ['first quarter 2025 press release', 2025, 1],
    ['Fiscal Year 2026 Fourth Quarter', 2026, 4],
    ['FQ2-2026-Supplement.pdf', 2026, 2]
  ];
  for (const [text, fy, q] of cases) {
    assert.deepEqual(parsePeriod(text), { fiscalYear: fy, quarter: q }, text);
  }
  assert.equal(parsePeriod('Annual report'), null);
  assert.equal(parsePeriod('Q1 10 items'), null);
});

test('robots.txt rules', () => {
  const rules = parseRobots('User-agent: badbot\nDisallow: /\n\nUser-agent: *\nDisallow: /private/\nAllow: /private/ok\nDisallow: /*.zip$\n');
  assert.equal(robotsAllows(rules, '/files/q3.pdf'), true);
  assert.equal(robotsAllows(rules, '/private/x.pdf'), false);
  assert.equal(robotsAllows(rules, '/private/ok/x.pdf'), true);
  assert.equal(robotsAllows(rules, '/a/b.zip'), false);
});

test('IR link extraction', () => {
  const { companies } = normalizeConfig({
    companies: [{ ticker: 'abc', irPages: [{ url: 'https://ir.example.com/results/' }] }]
  });
  const page = companies[0].irPages[0];
  const html = `
    <ul>
      <li><span>Q3 2026</span> <a href="/files/abc-transcript.pdf">Earnings Call Transcript</a></li>
      <li><a href="https://cdn.example.com/doc_financials/2026/q2/Slides.pdf">Presentation</a></li>
      <li><a href="/files/proxy-statement.pdf">Proxy Statement</a></li>
      <li><a href="/about">About us</a></li>
      <li><a href="/static-files/abc123">Q1 2026 Earnings Release</a></li>
      <li><a href="/files/abc-transcript.pdf#page=2">Earnings Call Transcript</a></li>
    </ul>`;
  const links = extractCandidateLinks(html, page.url, page);
  assert.equal(links.length, 3);
  assert.equal(links[0].url, 'https://ir.example.com/files/abc-transcript.pdf');
  assert.deepEqual(links[0].period, { fiscalYear: 2026, quarter: 3 });
  assert.deepEqual(links[1].period, { fiscalYear: 2026, quarter: 2 });
  assert.equal(links[2].url, 'https://ir.example.com/static-files/abc123');
});

test('EDGAR filing index parsing', () => {
  const html = `<table class="tableFile" summary="Document Format Files">
    <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
    <tr><td>1</td><td>8-K</td><td><a href="/ix?doc=/Archives/edgar/data/1/000/a8k.htm">a8k.htm</a></td><td>8-K</td><td>1</td></tr>
    <tr><td>2</td><td>PRESS RELEASE</td><td><a href="/Archives/edgar/data/1/000/ex991.htm">ex991.htm</a></td><td>EX-99.1</td><td>1</td></tr>
  </table>`;
  const docs = parseFilingIndex(html, 'https://www.sec.gov');
  assert.equal(docs.length, 2);
  assert.equal(docs[0].url, 'https://www.sec.gov/Archives/edgar/data/1/000/a8k.htm');
  assert.equal(docs[1].type, 'EX-99.1');
  assert.equal(classifyDocType(`${docs[1].description} ${docs[1].name}`), 'press-release');
});

test('FMP transcript date normalization', () => {
  const dates = normalizeTranscriptDates([
    { quarter: 1, fiscalYear: 2026, date: '2026-01-29' },
    { quarter: 4, fiscalYear: 2025 },
    { quarter: 2, year: 2026 },
    { quarter: 9, fiscalYear: 2026 }
  ]);
  assert.deepEqual(
    dates.map((d) => `${d.fiscalYear}Q${d.quarter}`),
    ['2026Q2', '2026Q1', '2025Q4']
  );
});

test('config validation', () => {
  assert.throws(() => normalizeConfig({ companies: [] }), /non-empty/);
  assert.throws(() => normalizeConfig({ companies: [{ ticker: 'A', fiscalYearEndMonth: 13 }] }), /fiscalYearEndMonth/);
  assert.throws(() => normalizeConfig({ companies: [{ ticker: 'A' }, { ticker: 'a' }] }), /more than once/);
  const { companies } = normalizeConfig({ companies: [{ ticker: ' msft ', fiscalYearEndMonth: 6, sources: { ir: false } }] });
  assert.equal(companies[0].ticker, 'MSFT');
  assert.equal(companies[0].sources.ir, false);
});

test('file naming and helpers', () => {
  assert.equal(
    buildFileName({ ticker: 'AAPL', periodLabel: 'FY2026-Q1', docType: 'presentation', hint: 'Q1 FY26 Slides!', ext: 'pdf' }),
    'AAPL_FY2026-Q1_presentation_q1-fy26-slides.pdf'
  );
  assert.equal(resolveExtension({ url: 'https://x.com/static-files/abc', contentType: 'application/pdf' }), 'pdf');
  assert.equal(resolveExtension({ url: 'https://x.com/a', dispositionName: 'deck.pptx', contentType: 'application/pdf' }), 'pptx');
  assert.equal(fileNameFromDisposition('attachment; filename="Q3 Release.pdf"'), 'Q3 Release.pdf');
  assert.equal(fileNameFromDisposition("attachment; filename*=UTF-8''Q3%20Deck.pdf"), 'Q3 Deck.pdf');
  assert.equal(redactUrl('https://a.com/x?symbol=A&apikey=secret'), 'https://a.com/x?symbol=A&apikey=REDACTED');
});
