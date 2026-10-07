import * as cheerio from 'cheerio';
import { downloadBuffer, getText, SkipError } from '../http.js';
import { isAllowedByRobots } from '../robots.js';
import { parsePeriod } from '../periods.js';
import { classifyDocType, extensionFromUrl } from '../files.js';

function normalizeSpace(text) {
  return String(text || '').replace(/\s+/g, ' ').trim();
}

function decodeSafe(s) {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

function linkContext($, el, linkText) {
  let node = $(el).parent();
  for (let depth = 0; depth < 4 && node.length; depth++) {
    const t = normalizeSpace(node.text());
    if (t.length > 400) break;
    if (t.length > linkText.length + 3) return t;
    node = node.parent();
  }
  return '';
}

export function extractCandidateLinks(html, pageUrl, page) {
  const $ = cheerio.load(html);
  const seen = new Set();
  const out = [];
  $('a[href]').each((_, el) => {
    const a = $(el);
    const rawHref = (a.attr('href') || '').trim();
    if (!rawHref || rawHref.startsWith('#') || /^(mailto|javascript|tel|data):/i.test(rawHref)) return;
    let abs;
    try {
      abs = new URL(rawHref, pageUrl);
    } catch {
      return;
    }
    if (!/^https?:$/.test(abs.protocol)) return;
    abs.hash = '';
    const url = abs.toString();
    if (seen.has(url)) return;

    const text = normalizeSpace([a.text(), a.attr('title'), a.attr('aria-label')].filter(Boolean).join(' '));
    const path = decodeSafe(abs.pathname);
    const context = linkContext($, el, text);
    const ext = extensionFromUrl(url);
    const lowerUrl = url.toLowerCase();

    const allowedExt = Boolean(ext) && page.fileTypes.includes(ext);
    const hinted = !ext && page.downloadHints.some((h) => lowerUrl.includes(h));
    if (!allowedExt && !hinted) return;

    const primary = `${text} ${path}`.toLowerCase();
    if (page.exclude.some((k) => primary.includes(k))) return;
    if (!page.include.some((k) => primary.includes(k) || context.toLowerCase().includes(k))) return;

    seen.add(url);
    out.push({
      url,
      text,
      context,
      ext,
      period: parsePeriod(text) || parsePeriod(path) || parsePeriod(context)
    });
  });
  return out;
}

export async function irItems(company, settings, ctx) {
  const items = [];
  for (const page of company.irPages) {
    if (settings.respectRobotsTxt && !(await isAllowedByRobots(page.url, ctx.scraperUserAgent))) {
      ctx.log.warn(`${company.ticker}: robots.txt disallows ${page.url}; skipping this page`);
      continue;
    }
    let html;
    try {
      html = page.render
        ? await ctx.renderPage(page.url)
        : await getText(page.url, {
            headers: { 'User-Agent': ctx.scraperUserAgent, Accept: 'text/html,application/xhtml+xml' },
            minIntervalMs: settings.ir.minIntervalMs
          });
    } catch (err) {
      throw new Error(`${company.ticker}: could not load IR page ${page.url}: ${err.message}`);
    }

    const links = extractCandidateLinks(html, page.url, page)
      .filter((link) => !link.period || link.period.fiscalYear >= settings.sinceYear)
      .slice(0, settings.ir.maxFilesPerPage);

    ctx.log.info(`${company.ticker}: ${links.length} candidate file(s) on ${page.url}`);

    for (const link of links) {
      const fileNameHint = decodeSafe(new URL(link.url).pathname.split('/').pop() || '').replace(/\.[a-z0-9]{1,5}$/i, '');
      items.push({
        source: 'ir',
        sourceId: link.url,
        sourceUrl: link.url,
        period: link.period,
        docType: classifyDocType(`${link.text} ${link.url}`),
        hint: fileNameHint.length >= 4 ? fileNameHint : link.text,
        async fetch() {
          if (settings.respectRobotsTxt && !(await isAllowedByRobots(link.url, ctx.scraperUserAgent))) {
            throw new SkipError(`robots.txt disallows ${link.url}`);
          }
          const file = await downloadBuffer(link.url, {
            headers: { 'User-Agent': ctx.scraperUserAgent, Referer: page.url },
            maxBytes: settings.maxFileBytes,
            minIntervalMs: settings.ir.minIntervalMs
          });
          const wantsHtml = page.fileTypes.includes('htm') || page.fileTypes.includes('html');
          if (file.contentType === 'text/html' && !wantsHtml) {
            throw new SkipError(`${link.url} returned a web page rather than a file`);
          }
          return { ...file, url: link.url };
        }
      });
    }
  }
  return items;
}
