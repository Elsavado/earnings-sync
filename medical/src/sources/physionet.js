// Open-access PhysioNet projects: "Wearables" (CGM, Apple Watch, wrist sensors, heart-rate
// monitors) and "EHR" (the de-identified MIMIC-IV and eICU demo databases). Each project's
// published ZIP is unpacked into a folder, after checking on the project page that access is
// open (no credentialing) and the licence is in the allowed list.
import { getJson, getText } from '../http.js';

const BASE = 'https://physionet.org';

function pageText(html) {
  return html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ');
}

export function parseProjectPage(html, finalUrl) {
  const version = (finalUrl.match(/\/content\/[^/]+\/([^/]+)\/?$/) || [])[1] || null;
  const text = pageText(html);
  const openAccess = /Access Policy:? Anyone can access the files/i.test(text);
  const license = (text.match(/License(?: \(for files\))?:? (.+?) (?:Discovery|DOI|Topics|Project Website|Corresponding Author)/) || [])[1] || null;
  const zip = (html.match(/href="(\/content\/[^"]+\/get-zip\/[^"]+)"/) || [])[1] || null;
  const sizeMatch = text.match(/Download the ZIP file \(([\d.]+) (KB|MB|GB)\)/i);
  const mult = { KB: 1024, MB: 1048576, GB: 1073741824 };
  const size = sizeMatch ? Math.round(Number(sizeMatch[1]) * mult[sizeMatch[2].toUpperCase()]) : null;
  const title = (html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/) || [])[1];
  return { version, openAccess, license, zip: zip ? `${BASE}${zip}` : null, size, title: title ? pageText(title).trim() : null };
}

// Where a discovered project belongs among the eight types, from its title and topics.
const PLACES = [
  [/heart sound|lung sound|phonocardiogra|stethoscop|\bsounds?\b|voice|speech|cough|audio|auditory|acoustic/, 'audio', 'Body sounds & voice recordings'],
  [/\behr\b|electronic health|mimic|eicu|critical care|intensive care|\bicu\b|clinical database|clinical data\b|sepsis|medication|vitaldb|emergency department|hospital/, 'ehr', 'Clinical databases (ICU & hospital)'],
  [/x-ray|radiograph|\bct\b|\bmri?\b|ultrasound|echocardiogra|imaging|\bimages?\b|retina|fundus/, 'imaging', null],
  [/glucose|\bcgm\b/, 'wearables', 'Continuous glucose monitors (Dexcom, Libre)'],
  [/fetal|maternal|pregnan|uterine|electrohysterogra|labou?r\b/, 'wearables', 'Fetal & maternal monitoring'],
  [/sleep|polysomno|apnea/, 'wearables', 'Sleep & polysomnography'],
  [/\beeg\b|electroencephalogra|neuroelectric|brain|seizure|\bemg\b|electromyogra/, 'wearables', 'EEG & brain signals'],
  [/gait|accelerom|actigraph|movement|posture|parkinson|fall|walking/, 'wearables', 'Gait, movement & accelerometry'],
  [/\becgs?\b|ekg|electrocardio|holter|arrhythmi|atrial|interbeat|rr interval|qt\b|ischemi|myocard|mit-bih|\bst (change|database)|long[- ]term st|sinus rhythm|ventricular|ectopy|heart failure|\bpaf\b|cardiac|ec13|waveforms?/, 'wearables', 'ECG & Holter monitors'],
  [/\bppg\b|photopleth|heart rate|blood pressure|pulse|wearable|oxygen|spo2/, 'wearables', 'Heart rate, blood pressure & PPG'],
  [/respirat|breath|ventilat|multiparameter|physiolog|vital signs?/, 'wearables', 'Other physiological signals']
];

export function placeProject(project) {
  const text = `${project.title} ${(project.topics || []).map((t) => t.description || t).join(' ')}`.toLowerCase();
  for (const [re, category, subtype] of PLACES) {
    if (!re.test(text)) continue;
    if (category === 'imaging') return { category, folder: ['Physiology & other imaging', 'PhysioNet'] };
    return { category, folder: [subtype, 'PhysioNet'] };
  }
  return null;
}

// Every open-access PhysioNet database and challenge (latest version) under a data licence,
// besides the projects listed in the config.
async function discoverProjects(cfg, known) {
  const all = await getJson(`${BASE}/api/v1/project/published/`, { minIntervalMs: cfg.minIntervalMs, timeoutMs: 180000 });
  const licenseRe = new RegExp(cfg.licensePattern, 'i');
  const denyRe = new RegExp(cfg.licenseDenyPattern, 'i');
  const found = [];
  for (const p of all) {
    if (p.access_policy !== 'Open' || !p.is_latest_version || known.has(p.slug)) continue;
    if (!['Database', 'Challenge'].includes(p.resource_type)) continue;
    const license = p.license?.name || '';
    if (!licenseRe.test(license) || denyRe.test(license)) continue;
    const place = placeProject(p);
    if (!place) continue;
    found.push({ slug: p.slug, ...place, discovered: true });
  }
  return found.sort((a, b) => a.slug.localeCompare(b.slug));
}

export async function* physionetItems(settings, ctx) {
  const cfg = settings.physionet;
  const licenseRe = new RegExp(cfg.licensePattern, 'i');
  const denyRe = new RegExp(cfg.licenseDenyPattern, 'i');
  const projects = [...cfg.projects];
  if (cfg.discover) projects.push(...(await discoverProjects(cfg, new Set(projects.map((x) => x.slug)))));
  for (const project of projects) {
    const { text, finalUrl } = await getText(`${BASE}/content/${project.slug}/`, {
      minIntervalMs: cfg.minIntervalMs,
      headers: { 'User-Agent': ctx.scraperUserAgent }
    });
    const p = parseProjectPage(text, finalUrl);
    if (!p.openAccess) {
      ctx.report.skipped.push(`physionet ${project.slug}: not open access (credentialed or restricted); not collected`);
      continue;
    }
    if (!p.license || !licenseRe.test(p.license) || denyRe.test(p.license)) {
      ctx.report.skipped.push(`physionet ${project.slug}: licence "${p.license || 'unknown'}" is not in the allowed list`);
      continue;
    }
    if (!p.zip) {
      ctx.report.skipped.push(`physionet ${project.slug}: no ZIP download on the project page`);
      continue;
    }
    const maxBytes = cfg.maxZipSizeMB * 1048576;
    if (p.size && p.size > maxBytes) {
      ctx.report.skipped.push(`physionet ${project.slug}: ZIP is ${(p.size / 1073741824).toFixed(1)} GB, above maxZipSizeMB`);
      continue;
    }
    yield {
      source: 'physionet',
      id: `${project.slug}/${p.version}`,
      category: project.category,
      path: project.folder,
      prefix: `${project.slug}-v${p.version}`,
      title: p.title || project.slug,
      folderName: project.discovered ? `${(p.title || project.slug).replace(/[\/\:*?"<>|]+/g, '-').slice(0, 110)} (v${p.version})` : undefined,
      ext: 'zip',
      unzip: true,
      size: p.size,
      url: p.zip,
      maxBytes,
      headers: { 'User-Agent': ctx.scraperUserAgent },
      license: p.license,
      attribution: `PhysioNet: ${p.title || project.slug}, version ${p.version}`,
      landing: finalUrl
    };
  }
}
