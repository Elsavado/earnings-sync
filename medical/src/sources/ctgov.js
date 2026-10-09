// "Other": new and ongoing clinical studies from ClinicalTrials.gov. For each study the full
// record (JSON) is stored next to the documents the sponsor posted: protocol, statistical
// analysis plan and informed-consent form.
import { getJson } from '../http.js';

const API = 'https://clinicaltrials.gov/api/v2/studies';

export function largeDocUrl(nctId, filename) {
  return `https://cdn.clinicaltrials.gov/large-docs/${nctId.slice(-2)}/${nctId}/${filename}`;
}

export async function* ctgovItems(settings, ctx) {
  const cfg = settings.ctgov;
  const state = (ctx.state.ctgov ||= {});
  for (const q of cfg.queries) {
    const qs = (state[q.name] ||= { pageToken: null, done: false });
    if (qs.done) continue;
    let taken = 0;
    while (!qs.done && (!cfg.maxStudiesPerQueryPerRun || taken < cfg.maxStudiesPerQueryPerRun)) {
      const params = new URLSearchParams({ pageSize: '100', 'filter.overallStatus': q.statuses.join(',') });
      if (cfg.requireDocuments) params.set('filter.advanced', 'AREA[LargeDocHasProtocol]true OR AREA[LargeDocHasICF]true OR AREA[LargeDocHasSAP]true');
      if (q.condition) params.set('query.cond', q.condition);
      if (qs.pageToken) params.set('pageToken', qs.pageToken);
      let data;
      try {
        data = await getJson(`${API}?${params}`, { minIntervalMs: cfg.minIntervalMs });
      } catch (err) {
        // Page tokens expire between runs; start the query again (stored studies are skipped).
        if (qs.pageToken && /HTTP 400/.test(err.message)) {
          qs.pageToken = null;
          continue;
        }
        throw err;
      }
      for (const study of data.studies || []) {
        const ps = study.protocolSection || {};
        const nctId = ps.identificationModule?.nctId;
        if (!nctId) continue;
        taken++;
        const title = ps.identificationModule?.briefTitle || '';
        const path = [...q.folder, nctId];
        const common = {
          source: 'ctgov',
          category: 'other',
          path,
          prefix: nctId,
          license: 'ClinicalTrials.gov public record (cite the NCT number)',
          attribution: `ClinicalTrials.gov ${nctId}: ${title}`,
          landing: `https://clinicaltrials.gov/study/${nctId}`
        };
        // Only the study's own documents (protocol, statistical analysis plan, consent form) are kept.
        for (const doc of study.documentSection?.largeDocumentModule?.largeDocs || []) {
          if (!doc.filename) continue;
          yield {
            ...common,
            id: `${nctId}/${doc.filename}`,
            title: `${doc.label || doc.typeAbbrev} ${doc.date || ''}`,
            ext: 'pdf',
            size: doc.size || null,
            url: largeDocUrl(nctId, doc.filename),
            expectType: 'application/pdf'
          };
        }
      }
      if (data.nextPageToken) qs.pageToken = data.nextPageToken;
      else qs.done = true;
    }
  }
}
