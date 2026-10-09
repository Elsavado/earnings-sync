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
  assert.equal(imagingModality('PT'), null);
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
