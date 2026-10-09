// Public documents posted on healthcare companies' own websites (white papers, clinical
// evidence, case studies, validation studies). A document is collected only when its link
// text or URL places it in one of the eight data types; everything else is ignored.
// robots.txt is respected and each site gets one request per settings.websites.minIntervalMs.
import * as cheerio from 'cheerio';
import { getText } from '../http.js';
import { isAllowedByRobots } from '../robots.js';
import { categorize, extensionFromUrl } from '../files.js';

const DOC_EXTS = new Set(['pdf', 'docx', 'pptx', 'xlsx']);
const SKIP_PAGE = /\.(jpg|jpeg|png|gif|svg|webp|mp4|zip|css|js|ico|xml)$/i;

function sameSite(a, b) {
  const strip = (h) => h.replace(/^www\./, '');
  return strip(new URL(a).hostname) === strip(new URL(b).hostname);
}

export function extractLinks(html, baseUrl) {
  const $ = cheerio.load(html);
  const links = [];
  $('a[href]').each((_, el) => {
    const href = $(el).attr('href');
    if (!href || href.startsWith('#') || /^(mailto|tel|javascript):/i.test(href)) return;
    let url;
    try {
      url = new URL(href, baseUrl);
    } catch {
      return;
    }
    if (!/^https?:$/.test(url.protocol)) return;
    url.hash = '';
    const text = $(el).text().replace(/\s+/g, ' ').trim() || $(el).attr('title') || $(el).attr('aria-label') || '';
    links.push({ url: url.href, text });
  });
  return links;
}

export async function* websiteItems(settings, ctx) {
  const cfg = settings.websites;
  for (const site of cfg.sites) {
    const queue = site.startUrls.map((u) => ({ url: u, depth: 0 }));
    const seenPages = new Set();
    const seenDocs = new Set();
    let pages = 0;
    while (queue.length && pages < cfg.maxPagesPerSite) {
      const { url, depth } = queue.shift();
      if (seenPages.has(url)) continue;
      seenPages.add(url);
      if (cfg.respectRobotsTxt && !(await isAllowedByRobots(url, ctx.scraperUserAgent))) continue;
      let html;
      try {
        ({ text: html } = await getText(url, { headers: { 'User-Agent': ctx.scraperUserAgent }, minIntervalMs: cfg.minIntervalMs, retries: 1 }));
      } catch (err) {
        ctx.report.skipped.push(`website ${site.name}: ${err.message}`);
        continue;
      }
      pages++;
      for (const link of extractLinks(html, url)) {
        if (!sameSite(link.url, site.startUrls[0]) && !(site.extraHosts || []).some((h) => new URL(link.url).hostname.endsWith(h))) continue;
        const ext = extensionFromUrl(link.url);
        if (DOC_EXTS.has(ext)) {
          if (seenDocs.has(link.url)) continue;
          seenDocs.add(link.url);
          const category = categorize(`${link.text} ${decodeURIComponent(new URL(link.url).pathname)}`);
          if (!category) continue;
          if (cfg.respectRobotsTxt && !(await isAllowedByRobots(link.url, ctx.scraperUserAgent))) continue;
          yield {
            source: 'website',
            id: link.url,
            category,
            path: ['Company documents', site.name],
            prefix: site.name,
            title: link.text || new URL(link.url).pathname.split('/').pop(),
            ext,
            url: link.url,
            headers: { 'User-Agent': ctx.scraperUserAgent },
            minIntervalMs: cfg.minIntervalMs,
            license: 'Publicly posted by the company (copyright the company; not openly licensed)',
            attribution: `${site.name}, ${link.url}`,
            landing: url
          };
        } else if (depth < cfg.maxDepth && !SKIP_PAGE.test(link.url) && sameSite(link.url, site.startUrls[0])) {
          queue.push({ url: link.url, depth: depth + 1 });
        }
      }
    }
  }
}
