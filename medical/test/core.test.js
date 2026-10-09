import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { imagingModality, imagingSpecialty, pathologySite, genomicsFolder, diseaseArea } from '../src/taxonomy.js';
import { categorize, extensionFromName, fileName, resolveExtension } from '../src/files.js';
import { largeDocUrl } from '../src/sources/ctgov.js';
import { parseProjectPage } from '../src/sources/physionet.js';
import { licenseAllowed } from '../src/sources/europepmc.js';
import { downloadUrlFor } from '../src/sources/github.js';
import { extractLinks } from '../src/sources/websites.js';
import { parseDisplayName, filingUrl, leadsCsv } from '../src/leads.js';
import { stripCommonRoot } from '../src/unzip.js';
import { normalizeConfig } from '../src/config.js';
import { tally, counterCsv, formatSize } from '../src/progress.js';
import { parseRobots, robotsAllows } from '../src/robots.js';

test('imaging: modality and specialty folders', () => {
  assert.equal(imagingModality('CT'), 'CT');
  assert.equal(imagingModality('MR'), 'MRI');
  assert.equal(imagingModality('DX'), 'X-ray');
  assert.equal(imagingModality('MG'), 'X-ray');
  assert.equal(imagingModality('US'), 'Ultrasound');
  assert.equal(imagingModality('PT'), 'PET');
  assert.equal(imagingModality('NM'), 'Nuclear medicine');
  assert.equal(imagingModality('SEG'), null);
  assert.equal(imagingSpecialty('LIDC-IDRI', 'CHEST'), 'Pulmonology');
  assert.equal(imagingSpecialty('AREN0534', 'ABDOMEN'), 'Pediatrics');
  assert.equal(imagingSpecialty('COVID-19-AR', 'CHEST'), 'Emergency Medicine');
  assert.equal(imagingSpecialty('UPENN-GBM', 'BRAIN'), 'Neurology');
  assert.equal(imagingSpecialty('KiTS', 'KIDNEY'), 'Nephrology');
  assert.equal(imagingSpecialty('Pancreas-CT', 'PANCREAS'), 'Gastroenterology');
  assert.equal(imagingSpecialty('Breast-MRI', 'BREAST'), 'Oncology');
});

test('pathology and genomics folders', () => {
  assert.equal(pathologySite('Skin'), 'Dermatology (skin)');
  assert.equal(pathologySite('Colon'), 'GI (colon, rectum, gastric, esophageal)');
  assert.equal(pathologySite('Cervix uteri'), 'Cervical & endometrial');
  assert.equal(pathologySite('Corpus uteri'), 'Cervical & endometrial');
  assert.equal(pathologySite('Prostate gland'), 'Prostate');
  assert.equal(pathologySite('Breast'), 'Breast');
  assert.equal(pathologySite('Hematopoietic and reticuloendothelial systems'), 'Hematopathology (blood, bone marrow, lymph node)');
  assert.equal(pathologySite('Kidney'), 'Other surgical resection specimens');
  assert.equal(genomicsFolder('Masked Somatic Mutation', 'WXS'), 'WES - somatic mutations');
  assert.equal(genomicsFolder('Masked Somatic Mutation', 'Targeted Sequencing'), 'Gene panels - somatic mutations');
  assert.equal(genomicsFolder('Protein Expression Quantification', 'Reverse Phase Protein Array'), 'Signaling & pathway data (protein expression, RPPA)');
  assert.equal(genomicsFolder('Gene Expression Quantification', 'RNA-Seq'), 'Lab molecular data - gene expression (RNA-seq)');
  assert.equal(genomicsFolder('Copy Number Segment', 'WGS'), 'WGS - copy number');
  assert.equal(diseaseArea('Brain'), 'Neuro');
  assert.equal(diseaseArea('Lung'), 'Onco - Lung');
});

test('company documents are kept only when they match one of the eight types', () => {
  assert.equal(categorize('Digital pathology whole-slide imaging white paper'), 'pathology');
  assert.equal(categorize('Exome sequencing validation'), 'genomics');
  assert.equal(categorize('MRI protocol guide'), 'imaging');
  assert.equal(categorize('Dexcom CGM clinical evidence'), 'wearables');
  assert.equal(categorize('Ambient clinical documentation brochure'), 'audio');
  assert.equal(categorize('FHIR integration for EHR'), 'ehr');
  assert.equal(categorize('Billing and coding guide'), 'claims');
  assert.equal(categorize('Case study: hospital rollout'), 'other');
  assert.equal(categorize('Annual sustainability report'), null);
  assert.equal(categorize('Careers brochure'), null);
});

test('file names and extensions', () => {
  assert.equal(extensionFromName('abc.maf.gz'), 'maf.gz');
  assert.equal(extensionFromName('slide.svs'), 'svs');
  assert.equal(resolveExtension({ url: 'https://x.org/a/b.pdf' }), 'pdf');
  assert.equal(resolveExtension({ contentType: 'application/zip' }), 'zip');
  assert.equal(fileName({ prefix: 'PMC1', title: 'A Case of X: Rare!', uid: 'abc123', ext: 'pdf' }), 'PMC1_a-case-of-x-rare_abc123.pdf');
});

test('source URL builders and parsers', () => {
  assert.equal(largeDocUrl('NCT06846736', 'Prot_000.pdf'), 'https://cdn.clinicaltrials.gov/large-docs/36/NCT06846736/Prot_000.pdf');
  assert.equal(licenseAllowed('CC BY', ['cc by']), true);
  assert.equal(licenseAllowed('cc by-nc', ['cc by']), false);
  assert.equal(licenseAllowed('', ['cc by']), false);
  assert.equal(
    downloadUrlFor('o/r', 'main', { name: 'a.wav', size: 133, path: 'audio/a.wav', download_url: 'https://raw/x' }),
    'https://media.githubusercontent.com/media/o/r/main/audio/a.wav'
  );
  assert.equal(downloadUrlFor('o/r', 'main', { name: 'a.txt', size: 5000, path: 'notes/a.txt', download_url: 'https://raw/x' }), 'https://raw/x');
  assert.deepEqual(parseDisplayName('Akoya Biosciences, Inc.  (AKYA)  (CIK 0001711933)'), { name: 'Akoya Biosciences, Inc.', ticker: 'AKYA', cik: '1711933' });
  assert.deepEqual(parseDisplayName('Some Private Co  (CIK 0000000042)'), { name: 'Some Private Co', ticker: '', cik: '42' });
  assert.equal(filingUrl('1711933', '0001558370-25-003124:akya-10k.htm'), 'https://www.sec.gov/Archives/edgar/data/1711933/000155837025003124/akya-10k.htm');
});

test('PhysioNet project page parsing', () => {
  const html = `<h1>MMASH: Multilevel Monitoring</h1><dt>Access Policy:</dt><dd>Anyone can access the files, as long as they conform to the terms of the specified license.</dd>
    <dt>License (for files):</dt><dd><a>Open Data Commons Open Database License v1.0</a></dd> Discovery
    <li><a href="/content/mmash/get-zip/1.0.0/">Download the ZIP file</a> (22.7 MB)</li>`;
  const p = parseProjectPage(html, 'https://physionet.org/content/mmash/1.0.0/');
  assert.equal(p.version, '1.0.0');
  assert.equal(p.openAccess, true);
  assert.equal(p.license, 'Open Data Commons Open Database License v1.0');
  assert.equal(p.zip, 'https://physionet.org/content/mmash/get-zip/1.0.0/');
  assert.equal(p.size, Math.round(22.7 * 1048576));
  const closed = parseProjectPage('<dt>Access Policy:</dt><dd>Only credentialed users who sign the DUA can access the files.</dd>', 'https://physionet.org/content/x/2.2/');
  assert.equal(closed.openAccess, false);
});

test('website link extraction', () => {
  const links = extractLinks('<a href="/docs/wp.pdf">Pathology white paper</a><a href="mailto:a@b">mail</a><a href="#top">top</a>', 'https://www.example.com/resources/');
  assert.deepEqual(links, [{ url: 'https://www.example.com/docs/wp.pdf', text: 'Pathology white paper' }]);
});

test('robots.txt rules', () => {
  const rules = parseRobots('User-agent: *\nDisallow: /private/\nAllow: /private/ok\n');
  assert.equal(robotsAllows(rules, '/docs/a.pdf'), true);
  assert.equal(robotsAllows(rules, '/private/a.pdf'), false);
  assert.equal(robotsAllows(rules, '/private/ok/a.pdf'), true);
});

test('zip common root is stripped only when every entry shares it', () => {
  assert.equal(stripCommonRoot(['proj-1.0/a.csv', 'proj-1.0/sub/b.csv']), 'proj-1.0/');
  assert.equal(stripCommonRoot(['a.csv', 'proj/b.csv']), '');
  assert.equal(stripCommonRoot([]), '');
});

test('counter: files and storage per data type and sub-type', () => {
  const f = (cat, sub, size, name = 'x') => ({ name, size: String(size), appProperties: { mdCategory: cat, mdSubtype: sub } });
  const counts = tally([
    f('pathology', 'Whole-slide images', 3 * 1073741824),
    f('pathology', 'Whole-slide images', 1073741824),
    f('pathology', 'Pathology reports', 1048576),
    f('wearables', 'Apple Watch', 2048),
    f('wearables', 'Apple Watch', 10, '_SOURCE.txt'),
    { name: 'stray', size: '5', appProperties: {} }
  ]);
  assert.equal(counts.total.files, 4);
  assert.equal(counts.types.pathology.files, 3);
  assert.equal(counts.types.pathology.subtypes.get('Whole-slide images').files, 2);
  assert.equal(counts.types.wearables.files, 1);
  assert.equal(counts.types.imaging.files, 0);
  assert.equal(formatSize(4 * 1073741824), '4.00 GB');
  const csv = counterCsv(counts, '2026-10-09 12:00');
  assert.match(csv, /^data_type,sub_type,files,storage,storage_gb,share_of_storage,counted_at_utc\n/);
  assert.match(csv, /Pathology,Whole-slide images,2,4\.00 GB,4\.000,/);
  assert.match(csv, /Pathology,TOTAL,3,/);
  assert.match(csv, /DICOM - Imaging,TOTAL,0,0 KB,0\.000,0\.0%/);
  assert.match(csv, /ALL DATA TYPES,TOTAL,4,/);
});

test('leads CSV', () => {
  const csv = leadsCsv([{ ticker: 'AKYA', name: 'Akoya, Inc.', cik: '1', sic: '3826', categories: ['pathology'], phrases: ['whole-slide images'], conferences: ['J.P. Morgan Healthcare Conference'], filings: 2, latest: { date: '2025-03-17', form: '10-K', url: 'u' }, nextCall: '2026-11-05', callTime: 'post-market', website: '' }]);
  assert.match(csv, /AKYA,"Akoya, Inc\.",1,3826,pathology,whole-slide images,J.P. Morgan Healthcare Conference,2,2025-03-17,10-K,u,2026-11-05,post-market,/);
});

test('shipped config is valid and covers exactly the eight types', async () => {
  const settings = normalizeConfig(JSON.parse(await readFile(new URL('../medical.json', import.meta.url), 'utf8')));
  assert.equal(settings.driveRootFolderName, 'Medical Data');
  assert.deepEqual(Object.keys(settings.leads.phrases).sort(), ['audio', 'claims', 'ehr', 'genomics', 'imaging', 'pathology', 'wearables']);
  assert.throws(() => normalizeConfig({ ...JSON.parse(JSON.stringify({ settings: {} })) }), /missing/);
});

test('only data is kept: archive clutter, licences and bookkeeping files are dropped', async () => {
  const { isArchiveClutter } = await import('../src/files.js');
  const { isNotData } = await import('../src/cleanup.js');
  for (const n of ['p/LICENSE.txt', 'p/License-CC-BY.pdf', 'COPYING', 'p/SHA256SUMS.txt', '__MACOSX/p/._a.dcm', 'p/.DS_Store', 'p/sub/']) assert.ok(isArchiveClutter(n), n);
  for (const n of ['p/hosp/admissions.csv.gz', 'p/RECORDS', 'p/licensed_data.csv', 'p/s01.dat']) assert.ok(!isArchiveClutter(n), n);
  for (const n of ['_SOURCE.txt', 'NCT01234567_study-record-a-trial_ab12cd.json', '._a.dcm']) assert.ok(isNotData(n), n);
  for (const n of ['NCT01234567_protocol-2020_ab12cd.pdf', 'PMC1_case_ab12cd.pdf']) assert.ok(!isNotData(n), n);
});

test('lead websites are read back from the company-leads sheet', async () => {
  const { leadSitesFromCsv } = await import('../src/leads.js');
  const csv = 'ticker,company,website\r\nDGX,"Quest Diagnostics, Inc.",https://www.questdiagnostics.com\r\n,"Acme ""Labs""",https://acme.example\r\nX,No Site,\r\n';
  assert.deepEqual(leadSitesFromCsv(csv), [
    { name: 'DGX', startUrls: ['https://www.questdiagnostics.com'] },
    { name: 'Acme "Labs"', startUrls: ['https://acme.example'] }
  ]);
});

test('data sits with its notes: per consultation, per case, per patient', async () => {
  const { groupFolder } = await import('../src/sources/github.js');
  const { gdcPath } = await import('../src/sources/gdc.js');
  const { relocation } = await import('../src/cleanup.js');
  const set = { groupBy: String.raw`day\d+_consultation\d+` };
  for (const n of ['day1_consultation03_doctor.wav', 'day1_consultation03_patient.TextGrid', 'day1_consultation03.json']) assert.equal(groupFolder(set, n), 'day1_consultation03');

  const slide = { data_type: 'Slide Image', cases: [{ submitter_id: 'TCGA-A1-A0SB', primary_site: 'Breast' }] };
  assert.equal(gdcPath({ category: 'pathology', folder: ['Whole-slide images'] }, slide).at(-1), 'TCGA-A1-A0SB');
  const report = { ...slide, data_type: 'Pathology Report' };
  assert.equal(gdcPath({ category: 'pathology', folder: ['Pathology reports'] }, report, { reportWithSlides: true })[0], 'Whole-slide images');
  assert.equal(gdcPath({ category: 'pathology', folder: ['Pathology reports'] }, report)[0], 'Pathology reports');

  assert.deepEqual(relocation({ name: 'primock57_day1_consultation03_doctor_ab12cd.wav' }, 'audio', 'PriMock57 mock consultations'), { move: 'file', under: 'grandparent', into: 'day1_consultation03' });
  const gdc = 'Attribution: NCI Genomic Data Commons, project TCGA-BRCA, case TCGA-A1-A0SB, file abc';
  assert.deepEqual(relocation({ name: 'a.svs', description: gdc }, 'Breast', 'Whole-slide images'), { move: 'file', under: 'parent', into: 'TCGA-A1-A0SB' });
  assert.equal(relocation({ name: 'a.svs', description: gdc }, 'TCGA-A1-A0SB', 'Breast'), null);
  const tcia = 'Attribution: The Cancer Imaging Archive, collection 4D-Lung (https://doi.org/x)';
  assert.deepEqual(relocation({ name: '1-01.dcm', description: tcia }, '100_HM10395_ct-lung-series-507_ab12cd', '4D-Lung'), { move: 'tcia', collection: '4D-Lung', uid6: 'ab12cd' });
  assert.deepEqual(relocation({ name: '1-01.dcm', description: tcia }, 'Series 507 - P4 P100 S113 I0, Gated, 70.0% (CT, 50 images)', '1997-10-03 - p4'), { move: 'tcia', collection: '4D-Lung', uid6: null });
  assert.equal(relocation({ name: 'x_Clinical_Data.tsv', description: tcia }, 'Clinical data', '4D-Lung'), null);
});

test('every image series gets its own well-named folder under patient and scan session', async () => {
  const { seriesLayout } = await import('../src/sources/tcia.js');
  const s = (uid, study, num, desc, date = '1997-10-03 00:00:00.0') => ({ SeriesInstanceUID: uid, StudyInstanceUID: study, PatientID: '100_HM10395', StudyDate: date, StudyDesc: 'p4', SeriesNumber: num, SeriesDescription: desc, Modality: 'CT', ImageCount: 50 });
  const layout = seriesLayout([s('1', 'A', 507, 'P4^P100^S113^I0, Gated, 70.0%'), s('2', 'B', 507, 'P4^P100^S114^I0, Gated, 70.0%'), s('3', 'A', 1, 'Scout'), s('4', 'A', 1, 'Scout'), s('5', 'C', 2, 'Axial', '1997-10-10')]);
  assert.deepEqual(layout.get('1'), { patient: '100_HM10395', study: '1997-10-03 - p4 (scan 1 of 2)', name: 'Series 507 - P4 P100 S113 I0, Gated, 70.0% (CT, 50 images)' });
  assert.equal(layout.get('2').study, '1997-10-03 - p4 (scan 2 of 2)');
  assert.equal(layout.get('3').name, 'Series 1 - Scout (CT, 50 images) (copy 1 of 2)');
  assert.equal(layout.get('4').name, 'Series 1 - Scout (CT, 50 images) (copy 2 of 2)');
  assert.equal(layout.get('5').study, '1997-10-10 - p4');
});

test('a TCIA collection is one folder with its clinical data and annotations, no licence files', async () => {
  const { collectionNoteFiles, collectionPlace } = await import('../src/sources/tcia.js');
  const d = (title, file, type, extra = {}) => ({ id: title.length, title: { rendered: title }, download_title: title, download_type: type, data_license: 'CC BY 4.0', download_access: 'Public', file_type: [file.split('.').pop().toUpperCase()], download_file: { guid: `https://www.cancerimagingarchive.net/wp-content/uploads/${file}` }, ...extra });
  const notes = collectionNoteFiles([
    d('UCSD-BMETS-DA-CLINICAL', 'UCSD_Clinical_Data.tsv', 'Clinical Data'),
    d('UCSD-BMETS-DA-OTHER1', 'UCSD_MRImetadata_Dictionary.tsv', 'Other'),
    d('UCSD-BMETS-DA-OTHER2', 'UCSD_License.pdf', 'Other'),
    d('UCSD-BMETS-DA-SEG', 'UCSD_Seg.tcia', 'Image Annotations'),
    d('UCSD-BMETS-DA-RESTRICTED', 'UCSD_extra.csv', 'Clinical Data', { data_license: 'TCIA Restricted', download_access: 'Limited' }),
    d('UCSD-BMETS-DA-PATH', 'slides.svs', 'Pathology Images', { download_file: null, download_url: 'https://faspex.cancerimagingarchive.net/aspera/x' })
  ]);
  assert.deepEqual(notes.get('UCSD-BMETS').map((f) => `${f.folder}/${f.fileName}`), ['Clinical data/UCSD_Clinical_Data.tsv', 'Annotations/UCSD_MRImetadata_Dictionary.tsv']);

  const s = (Modality, BodyPartExamined) => ({ Modality, BodyPartExamined });
  assert.deepEqual(collectionPlace('LUNG-PET-CT', [s('CT', 'CHEST'), s('PT', 'CHEST'), s('CT', 'CHEST'), s('SEG', 'CHEST')]), { specialty: 'Pulmonology', modality: 'CT' });
  assert.deepEqual(collectionPlace('ONLY-SEG', [s('SEG', 'CHEST')]).modality, null);
});

test('ISIC skin images: notes in the name, grouped by patient and lesion when known', async () => {
  const { isicPlacement } = await import('../src/sources/isic.js');
  const image = (clinical) => ({ isic_id: 'ISIC_0000004', metadata: { acquisition: { image_type: 'dermoscopic' }, clinical } });
  const plain = isicPlacement(image({ diagnosis_1: 'Malignant', diagnosis_3: 'Melanoma, NOS', anatom_site_2: 'Posterior trunk', sex: 'male', age_approx: 80 }));
  assert.equal(plain.name, 'ISIC_0000004 - Melanoma, NOS - Posterior trunk - male, 80y');
  assert.deepEqual(plain.path, ['Dermatology', 'Dermoscopy', 'ISIC', 'By diagnosis', 'Melanoma, NOS']);
  const linked = isicPlacement(image({ diagnosis_1: 'Benign', diagnosis_3: 'Nevus', patient_id: 'IP_123', lesion_id: 'IL_456' }));
  assert.deepEqual(linked.path, ['Dermatology', 'Dermoscopy', 'ISIC', 'Patient IP_123', 'Lesion IL_456 - Nevus']);
});

test('discovered PhysioNet projects are sorted into the eight types', async () => {
  const { placeProject } = await import('../src/sources/physionet.js');
  const place = (title, topics = []) => placeProject({ title, topics: topics.map((description) => ({ description })) });
  assert.deepEqual(place('PTB Diagnostic ECG Database'), { category: 'wearables', folder: ['ECG & Holter monitors', 'PhysioNet'] });
  assert.equal(place('CirCor DigiScope Phonocardiogram Dataset').category, 'audio');
  assert.equal(place('eICU Collaborative Research Database Demo', ['critical care']).category, 'ehr');
  assert.equal(place('Siena Scalp EEG Database').folder[0], 'EEG & brain signals');
  assert.equal(place('A Multi-Modal Satellite Imagery Dataset for Public Health Analysis in Colombia'), null);
});

test('cloud buckets: listings, slide grouping and OpenNeuro data types', async () => {
  const { parseListing, mirrorPath, openneuroKind } = await import('../src/sources/buckets.js');
  const page = parseListing('<ListBucketResult><Contents><Key>CAMELYON16/images/tumor_001.tif</Key><Size>42</Size></Contents><CommonPrefixes><Prefix>ds000001/</Prefix></CommonPrefixes><NextContinuationToken>abc&amp;1</NextContinuationToken></ListBucketResult>');
  assert.deepEqual(page, { files: [{ key: 'CAMELYON16/images/tumor_001.tif', size: 42 }], folders: ['ds000001/'], next: 'abc&1' });
  const set = { prefix: 'CAMELYON16/', groupBy: String.raw`(normal|tumor|test)_\d+`, folder: ['Whole-slide images', 'CAMELYON16'] };
  for (const key of ['CAMELYON16/images/tumor_001.tif', 'CAMELYON16/annotations/tumor_001.xml', 'CAMELYON16/masks/tumor_001_mask.tif']) {
    assert.deepEqual(mirrorPath(set, key).path, ['Whole-slide images', 'CAMELYON16', 'tumor_001']);
  }
  assert.equal(openneuroKind(['ds1/sub-01/anat/T1w.nii.gz', 'ds1/sub-01/func/bold.nii.gz']), 'imaging');
  assert.equal(openneuroKind(['ds2/sub-01/eeg/x.edf']), 'signals');
  assert.equal(openneuroKind(['ds3/README']), null);
});
