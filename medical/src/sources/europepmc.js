// "Other": published patient case reports and medical education cases, open access only,
// from Europe PMC (which mirrors PubMed Central). Only licences in settings.europepmc.licenses
// are kept, so every file may be stored and reused with attribution.
import { getJson } from '../http.js';

const API = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search';

export function licenseAllowed(license, allowed) {
  const l = String(license || '').toLowerCase().trim();
  return Boolean(l) && allowed.includes(l);
}

function pdfUrl(result) {
  const urls = result.fullTextUrlList?.fullTextUrl || [];
  const epmc = urls.find((u) => u.documentStyle === 'pdf' && u.site === 'Europe_PMC');
  return epmc?.url || (result.pmcid ? `https://europepmc.org/articles/${result.pmcid}?pdf=render` : null);
}

export async function* europepmcItems(settings, ctx) {
  const cfg = settings.europepmc;
  const state = (ctx.state.europepmc ||= {});
  for (const q of cfg.queries) {
    const qs = (state[q.name] ||= { cursor: '*', done: false });
    if (qs.done) continue;
    let taken = 0;
    while (!qs.done && (!cfg.maxPerQueryPerRun || taken < cfg.maxPerQueryPerRun)) {
      const query = `(${q.query}) AND OPEN_ACCESS:y AND HAS_PDF:y`;
      const url = `${API}?query=${encodeURIComponent(query)}&resultType=core&format=json&pageSize=100&cursorMark=${encodeURIComponent(qs.cursor)}`;
      const data = await getJson(url, { minIntervalMs: cfg.minIntervalMs });
      const results = data.resultList?.result || [];
      for (const r of results) {
        if (!licenseAllowed(r.license, cfg.licenses)) {
          ctx.stats.licenseSkipped++;
          continue;
        }
        const link = pdfUrl(r);
        if (!link) continue;
        taken++;
        yield {
          source: 'europepmc',
          id: r.pmcid || r.id,
          category: 'other',
          path: q.folder,
          prefix: r.pmcid,
          title: r.title,
          ext: 'pdf',
          url: link,
          expectType: 'application/pdf',
          license: r.license.toUpperCase(),
          attribution: `${r.authorString || ''} ${r.journalInfo?.journal?.title || ''} ${r.pubYear || ''}. doi:${r.doi || 'n/a'} (${r.pmcid})`.trim(),
          landing: `https://europepmc.org/article/PMC/${r.pmcid}`
        };
      }
      // Advance only after the page is handed over, so a stopped run repeats at most one page.
      if (!data.nextCursorMark || data.nextCursorMark === qs.cursor || results.length === 0) qs.done = true;
      else qs.cursor = data.nextCursorMark;
    }
  }
}
