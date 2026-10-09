// "Pathology" (whole-slide images, pathology reports) and "Genomics" (open-tier processed
// genomic files) from the NCI Genomic Data Commons. Only files with access = "open" are
// requested; controlled-access data (raw reads, germline variants) is never touched.
import { postJson } from '../http.js';
import { diseaseArea, genomicsFolder, pathologySite } from '../taxonomy.js';

const API = 'https://api.gdc.cancer.gov';
const PAGE = 100;

export async function* gdcItems(settings, ctx) {
  const cfg = settings.gdc;
  const state = (ctx.state.gdc ||= {});
  for (const group of cfg.groups) {
    const gs = (state[group.name] ||= { from: 0, done: false });
    if (gs.done) continue;
    const content = [
      { op: 'in', content: { field: 'access', value: ['open'] } },
      { op: 'in', content: { field: 'data_type', value: group.dataTypes } }
    ];
    if (group.projects?.length) content.push({ op: 'in', content: { field: 'cases.project.project_id', value: group.projects } });
    if (group.primarySites?.length) content.push({ op: 'in', content: { field: 'cases.primary_site', value: group.primarySites } });
    let taken = 0;
    while (!gs.done && (!cfg.maxPerGroupPerRun || taken < cfg.maxPerGroupPerRun)) {
      const data = await postJson(
        `${API}/files`,
        {
          filters: { op: 'and', content },
          fields: 'file_id,file_name,file_size,data_type,data_format,experimental_strategy,cases.project.project_id,cases.primary_site,cases.submitter_id',
          sort: 'file_id:asc',
          from: gs.from,
          size: PAGE,
          format: 'json'
        },
        { minIntervalMs: cfg.minIntervalMs }
      );
      const hits = data.data?.hits || [];
      for (const f of hits) {
        const maxBytes = (group.maxFileSizeMB || settings.maxFileSizeMB) * 1048576;
        if (f.file_size > maxBytes) {
          ctx.stats.sizeSkipped++;
          continue;
        }
        const kase = f.cases?.[0] || {};
        taken++;
        yield {
          source: 'gdc',
          id: f.file_id,
          category: group.category,
          path:
            group.category === 'pathology'
              ? [...group.folder, pathologySite(kase.primary_site)]
              : [genomicsFolder(f.data_type, f.experimental_strategy), diseaseArea(kase.primary_site)],
          prefix: kase.project?.project_id,
          title: f.file_name.replace(/\.[^.]+(\.gz)?$/, ''),
          fileName: f.file_name,
          size: f.file_size,
          url: `${API}/data/${f.file_id}`,
          maxBytes,
          license: 'NIH GDC open access (cite the GDC and the source project)',
          attribution: `NCI Genomic Data Commons, project ${kase.project?.project_id || 'n/a'}, case ${kase.submitter_id || 'n/a'}, file ${f.file_id}`,
          landing: `https://portal.gdc.cancer.gov/files/${f.file_id}`
        };
      }
      const total = data.data?.pagination?.total ?? 0;
      gs.from += hits.length;
      if (hits.length === 0 || gs.from >= total) gs.done = true;
    }
  }
}
