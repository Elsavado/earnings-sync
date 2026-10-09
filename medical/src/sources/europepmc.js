// "Other": published patient case reports and medical education cases, open access only,
// from Europe PMC (which mirrors PubMed Central). Only licences in settings.europepmc.licenses
// are kept, so every file may be stored and reused with attribution.
import { getJson, getText } from '../http.js';

const API = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search';

export function licenseAllowed(license, allowed) {
  const l = String(license || '').toLowerCase().trim();
  return Boolean(l) && allowed.includes(l);
}

const PMC_BUCKET = 'https://pmc-oa-opendata.s3.amazonaws.com';

// PDFs come from PubMed Central's open-access bucket (its route for bulk downloads); the
// europepmc.org PDF links refuse automated downloads. The newest version of the article wins.
export function latestPdfKey(listXml, pmcid) {
  const keys = [...String(listXml).matchAll(/<Key>([^<]+)<\/Key>/g)].map((m) => m[1]);
  const pdfs = keys
    .map((k) => {
      const [folder, file] = k.split('/');
      const version = Number(folder.slice(pmcid.length + 1));
      return { k, v: folder.startsWith(`${pmcid}.`) && file === `${folder}.pdf` ? version : 0 };
    })
    .filter((x) => x.v > 0);
  return pdfs.sort((a, b) => b.v - a.v)[0]?.k || null;
}

async function pdfUrl(pmcid, cfg) {
  if (!pmcid) return null;
  const { text: xml } = await getText(`${PMC_BUCKET}/?list-type=2&prefix=${encodeURIComponent(`${pmcid}.`)}&max-keys=50`, { minIntervalMs: cfg.minIntervalMs });
  const key = latestPdfKey(xml, pmcid);
  return key ? `${PMC_BUCKET}/${key}` : null;
}

export async function* europepmcItems(settings, ctx) {
  const cfg = settings.europepmc;
  // Version 2: the first listing ran past thousands of PDFs that could not be downloaded.
  const state = (ctx.state.europepmc2 ||= {});
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
        let link;
        try {
          link = await pdfUrl(r.pmcid, cfg);
        } catch (err) {
          ctx.report.errors.push(`europepmc ${r.pmcid}: ${err.message}`);
          continue;
        }
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
