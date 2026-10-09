// "Pathology" (whole-slide images, pathology reports) and "Genomics" (open-tier processed
// genomic files) from the NCI Genomic Data Commons. Only files with access = "open" are
// requested; controlled-access data (raw reads, germline variants) is never touched.
// Files are kept per patient case: <type folder>/<site or disease area>/<case>/. A case's
// pathology report is fetched together with its slides and stored in the same folder.
import { postJson } from '../http.js';
import { diseaseArea, genomicsFolder, pathologySite } from '../taxonomy.js';

const API = 'https://api.gdc.cancer.gov';
const PAGE = 100;
const FIELDS = 'file_id,file_name,file_size,data_type,data_format,experimental_strategy,cases.case_id,cases.project.project_id,cases.primary_site,cases.submitter_id';
const SLIDE = 'Slide Image';
const REPORT = 'Pathology Report';

function openFiles(dataTypes, extra = []) {
  return {
    op: 'and',
    content: [
      { op: 'in', content: { field: 'access', value: ['open'] } },
      { op: 'in', content: { field: 'data_type', value: dataTypes } },
      ...extra
    ]
  };
}

async function searchFiles(filters, from, size, cfg) {
  const data = await postJson(`${API}/files`, { filters, fields: FIELDS, sort: 'file_id:asc', from, size, format: 'json' }, { minIntervalMs: cfg.minIntervalMs });
  return { hits: data.data?.hits || [], total: data.data?.pagination?.total ?? 0 };
}

function caseFilter(caseId) {
  return { op: 'in', content: { field: 'cases.case_id', value: [caseId] } };
}

// The case folder, e.g. ['Whole-slide images', 'Breast', 'TCGA-A1-A0SB'].
export function gdcPath(group, f, { reportWithSlides = false } = {}) {
  const kase = f.cases?.[0] || {};
  const caseFolder = kase.submitter_id || kase.case_id || 'Unknown case';
  if (group.category !== 'pathology') return [genomicsFolder(f.data_type, f.experimental_strategy), diseaseArea(kase.primary_site), caseFolder];
  const folder = reportWithSlides ? ['Whole-slide images'] : group.folder;
  return [...folder, pathologySite(kase.primary_site), caseFolder];
}

function toItem(group, f, settings, path) {
  const kase = f.cases?.[0] || {};
  const maxBytes = (group.maxFileSizeMB || settings.maxFileSizeMB) * 1048576;
  return {
    source: 'gdc',
    id: f.file_id,
    category: group.category,
    path,
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

export async function* gdcItems(settings, ctx) {
  const cfg = settings.gdc;
  const state = (ctx.state.gdc ||= {});
  const reportsFetched = new Set();
  const slideCases = new Map();
  const hasSlides = async (caseId) => {
    if (!slideCases.has(caseId)) slideCases.set(caseId, (await searchFiles(openFiles([SLIDE], [caseFilter(caseId)]), 0, 1, cfg)).total > 0);
    return slideCases.get(caseId);
  };

  for (const group of cfg.groups) {
    const gs = (state[group.name] ||= { from: 0, done: false });
    if (gs.done) continue;
    const extra = [];
    if (group.projects?.length) extra.push({ op: 'in', content: { field: 'cases.project.project_id', value: group.projects } });
    if (group.primarySites?.length) extra.push({ op: 'in', content: { field: 'cases.primary_site', value: group.primarySites } });
    const isSlides = group.dataTypes.includes(SLIDE);
    const isReports = group.dataTypes.includes(REPORT) && !isSlides;
    let taken = 0;
    while (!gs.done && (!cfg.maxPerGroupPerRun || taken < cfg.maxPerGroupPerRun)) {
      const { hits, total } = await searchFiles(openFiles(group.dataTypes, extra), gs.from, PAGE, cfg);
      for (const f of hits) {
        const maxBytes = (group.maxFileSizeMB || settings.maxFileSizeMB) * 1048576;
        if (f.file_size > maxBytes) {
          ctx.stats.sizeSkipped++;
          continue;
        }
        const caseId = f.cases?.[0]?.case_id;
        // A report whose case has slides belongs in that case's slide folder.
        const reportWithSlides = isReports && caseId ? await hasSlides(caseId) : false;
        const path = gdcPath(group, f, { reportWithSlides });
        taken++;
        yield toItem(group, f, settings, path);
        // Each slide's case brings its pathology report into the same folder.
        if (isSlides && caseId && !reportsFetched.has(caseId)) {
          reportsFetched.add(caseId);
          const { hits: reports } = await searchFiles(openFiles([REPORT], [caseFilter(caseId)]), 0, 20, cfg);
          for (const r of reports) yield toItem({ ...group, maxFileSizeMB: null }, r, settings, path);
        }
      }
      gs.from += hits.length;
      if (hits.length === 0 || gs.from >= total) gs.done = true;
    }
  }
}
