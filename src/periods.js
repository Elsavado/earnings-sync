const WORD_QUARTERS = { first: 1, second: 2, third: 3, fourth: 4, '1st': 1, '2nd': 2, '3rd': 3, '4th': 4 };

export function quarterEndMonths(fyEndMonth) {
  return [0, 3, 6, 9].map((offset) => ((fyEndMonth - 1 + offset) % 12) + 1);
}

export function fiscalPeriodForQuarterEnd(year, month, fyEndMonth) {
  const quarter = Math.floor(((month - fyEndMonth - 1 + 12) % 12) / 3) + 1;
  const fiscalYear = month > fyEndMonth ? year + 1 : year;
  return { fiscalYear, quarter };
}

// Companies on 52/53-week years end periods a few days into the next month
// (J&J's year ends around 3 January, Deere's around 1 November). A period that
// ends in the first week of a month really belongs to the previous month.
export function effectiveMonth(dateStr) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(dateStr || ''));
  if (!match) return null;
  let year = Number(match[1]);
  let month = Number(match[2]);
  if (Number(match[3]) <= 7) {
    month -= 1;
    if (month === 0) {
      month = 12;
      year -= 1;
    }
  }
  return { year, month };
}

// Fiscal year-end month from the SEC's "MMDD" fiscalYearEnd ("0103" -> 12).
export function fiscalMonthFromSec(mmdd) {
  if (!/^\d{4}$/.test(String(mmdd || ''))) return 12;
  return effectiveMonth(`2000-${mmdd.slice(0, 2)}-${mmdd.slice(2)}`).month;
}

// Fiscal period covered by a 10-Q, 10-K, 20-F or 40-F, from its period-of-report date.
export function periodFromReportDate(dateStr, fyEndMonth, form) {
  const eff = effectiveMonth(dateStr);
  if (!eff) return null;
  const period = fiscalPeriodForQuarterEnd(eff.year, eff.month, fyEndMonth);
  return /^(10-K|20-F|40-F)/.test(form) ? { fiscalYear: period.fiscalYear, quarter: 4 } : period;
}

// Earnings releases follow the quarter they report on, so the reported quarter is
// the most recent fiscal quarter end strictly before the release month.
export function reportedPeriodFromReleaseDate(dateStr, fyEndMonth) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(dateStr || ''));
  if (!match) return null;
  let year = Number(match[1]);
  let month = Number(match[2]);
  const ends = new Set(quarterEndMonths(fyEndMonth));
  for (let i = 0; i < 4; i++) {
    month -= 1;
    if (month === 0) {
      month = 12;
      year -= 1;
    }
    if (ends.has(month)) return fiscalPeriodForQuarterEnd(year, month, fyEndMonth);
  }
  return null;
}

function toYear(raw) {
  const n = Number(raw);
  if (!Number.isFinite(n)) return null;
  const year = raw.length <= 2 ? 2000 + n : n;
  const max = new Date().getUTCFullYear() + 2;
  return year >= 2000 && year <= max ? year : null;
}

const PATTERNS = [
  { re: /\bF?Q([1-4])[\s_\/'’-]*(?:FY|F)?['’]?(20\d{2})(?!\d)/i, q: 1, y: 2 },
  { re: /\bF?Q([1-4])[\s_-]*(?:FY|F|['’])(\d{2})(?!\d)/i, q: 1, y: 2 },
  { re: /\b(?:FY|F)['’]?(20\d{2}|\d{2})[\s_\/-]*Q([1-4])\b/i, q: 2, y: 1 },
  { re: /\b(20\d{2})[\s_\/-]*Q([1-4])\b/i, q: 2, y: 1 },
  {
    re: /\b(first|second|third|fourth|1st|2nd|3rd|4th)[\s-]+quarter[\s,]+(?:of\s+)?(?:fiscal\s+(?:year\s+)?)?(?:FY\s*)?['’]?(20\d{2}|\d{2})(?!\d)/i,
    q: 1,
    y: 2,
    word: true
  },
  {
    re: /\b(?:fiscal\s+(?:year\s+)?|FY\s*)(20\d{2}|\d{2})[\s,]+(first|second|third|fourth|1st|2nd|3rd|4th)[\s-]+quarter\b/i,
    q: 2,
    y: 1,
    word: true
  }
];

export function parsePeriod(text) {
  if (!text) return null;
  const s = String(text);
  for (const p of PATTERNS) {
    const m = p.re.exec(s);
    if (!m) continue;
    const quarter = p.word ? WORD_QUARTERS[m[p.q].toLowerCase()] : Number(m[p.q]);
    const fiscalYear = toYear(m[p.y]);
    if (quarter && fiscalYear) return { fiscalYear, quarter };
  }
  return null;
}

export function periodLabel(period) {
  return period ? `FY${period.fiscalYear}-Q${period.quarter}` : 'Unsorted';
}
