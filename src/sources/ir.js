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

const RESULTS_LINK = /quarterly (results|earnings|reports?)|financial results|earnings (releases?|materials|reports?)|results (&|and) (presentations?|reports?)|financial (information|reports?)/i;

// When a configured page is gone (404), look for the results page from the IR home page.
export function findResultsLink(html, pageUrl) {
  const $ = cheerio.load(html);
  const host = new URL(pageUrl).host;
  let best = null;
  $('a[href]').each((_, el) => {
    const text = normalizeSpace($(el).text());
    if (!text || text.length > 60 || !RESULTS_LINK.test(text)) return;
    let abs;
    try {
      abs = new URL($(el).attr('href'), pageUrl);
    } catch {
      return;
    }
    if (abs.host !== host || !/^https?:$/.test(abs.protocol)) return;
    const score = /quarterly/i.test(text) ? 2 : 1;
    if (!best || score > best.score) best = { url: abs.toString(), score };
  });
  return best?.url || null;
}

const SECTION_LINK = /annual\s+reports?|financial\s+reports?|quarterly\s+(results|earnings|reports?)|financial\s+results|presentations?|events?\s*(&|and)\s*presentations|investor\s+day|analyst\s+day|capital\s+markets\s+day|webcasts?|transcripts?|interim\s+reports?|financial\s+information|reports?\s*(&|and)\s*(filings|presentations)|fact\s*(sheet|book)/i;

// Same-host links to IR sections worth visiting from the results page.
export function findSectionLinks(html, pageUrl) {
  const $ = cheerio.load(html);
  const host = new URL(pageUrl).host;
  const out = [];
  $('a[href]').each((_, el) => {
    const text = normalizeSpace($(el).text());
    if (!text || text.length > 50 || !SECTION_LINK.test(text)) return;
    let abs;
    try {
      abs = new URL($(el).attr('href'), pageUrl);
    } catch {
      return;
    }
    abs.hash = '';
    const url = abs.toString();
    if (abs.host !== host || !/^https?:$/.test(abs.protocol) || url === pageUrl || out.includes(url)) return;
    if (/\.(pdf|xlsx?|pptx?|docx?|csv|zip|mp[34])$/i.test(abs.pathname)) return;
    out.push(url);
  });
  return out;
}

async function loadPage(url, page, settings, ctx) {
  return page.render
    ? ctx.renderPage(url)
    : getText(url, {
        headers: { 'User-Agent': ctx.scraperUserAgent, Accept: 'text/html,application/xhtml+xml' },
        minIntervalMs: settings.ir.minIntervalMs
      });
}

async function loadWithFallback(company, page, settings, ctx) {
  try {
    return { html: await loadPage(page.url, page, settings, ctx), url: page.url };
  } catch (err) {
    if (!/HTTP 404/.test(err.message)) throw err;
    const home = `${new URL(page.url).origin}/`;
    ctx.log.warn(`${company.ticker}: ${page.url} is gone (404); looking for the results page from ${home}`);
    const homeHtml = await loadPage(home, page, settings, ctx);
    const found = findResultsLink(homeHtml, home);
    if (found && found !== page.url) {
      try {
        return { html: await loadPage(found, page, settings, ctx), url: found };
      } catch {
        // Fall through to the home page itself.
      }
    }
    return { html: homeHtml, url: home };
  }
}

export async function irItems(company, settings, ctx) {
  const items = [];
  for (const page of company.irPages) {
    if (settings.respectRobotsTxt && !(await isAllowedByRobots(page.url, ctx.scraperUserAgent))) {
      ctx.log.warn(`${company.ticker}: robots.txt disallows ${page.url}; skipping this page`);
      continue;
    }
    let loaded;
    try {
      loaded = await loadWithFallback(company, page, settings, ctx);
    } catch (err) {
      throw new Error(`${company.ticker}: could not load IR page ${page.url}: ${err.message}`);
    }
    const { html, url: pageUrl } = loaded;

    // The results page rarely holds everything: also visit the IR site's sections for
    // annual reports, presentations, events and investor days (same host only).
    const pages = [{ html, url: pageUrl }];
    for (const sub of findSectionLinks(html, pageUrl).slice(0, settings.ir.maxSubpages)) {
      if (settings.respectRobotsTxt && !(await isAllowedByRobots(sub, ctx.scraperUserAgent))) continue;
      try {
        pages.push({ html: await loadPage(sub, page, settings, ctx), url: sub });
      } catch (err) {
        ctx.log.warn(`${company.ticker}: could not load IR section ${sub}: ${err.message}`);
      }
    }
    const seenLinks = new Set();
    let links = [];
    for (const p of pages) {
      for (const link of extractCandidateLinks(p.html, p.url, page)) {
        if (seenLinks.has(link.url) || (link.period && link.period.fiscalYear < settings.sinceYear)) continue;
        seenLinks.add(link.url);
        links.push({ ...link, pageUrl: p.url });
      }
    }
    if (settings.ir.maxFilesPerPage) links = links.slice(0, settings.ir.maxFilesPerPage);

    ctx.log.info(`${company.ticker}: ${links.length} candidate file(s) on ${pages.length} IR page(s) from ${pageUrl}`);

    for (const link of links) {
      items.push({
        source: 'ir',
        sourceId: link.url,
        sourceUrl: link.url,
        period: link.period,
        date: '',
        docType: classifyDocType(`${link.text} ${link.url}`, link.ext === 'xlsx' || link.ext === 'xls' || link.ext === 'csv' ? 'data-workbook' : 'document'),
        hint: link.text || decodeSafe(new URL(link.url).pathname.split('/').pop() || '').replace(/\.[a-z0-9]{1,5}$/i, ''),
        async fetch() {
          if (settings.respectRobotsTxt && !(await isAllowedByRobots(link.url, ctx.scraperUserAgent))) {
            throw new SkipError(`robots.txt disallows ${link.url}`);
          }
          const file = await downloadBuffer(link.url, {
            headers: { 'User-Agent': ctx.scraperUserAgent, Referer: link.pageUrl || pageUrl },
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
