// Open-access PhysioNet projects: "Wearables" (CGM, Apple Watch, wrist sensors, heart-rate
// monitors) and "EHR" (the de-identified MIMIC-IV and eICU demo databases). Each project's
// published ZIP is unpacked into a folder, after checking on the project page that access is
// open (no credentialing) and the licence is in the allowed list.
import { getText } from '../http.js';

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

export async function* physionetItems(settings, ctx) {
  const cfg = settings.physionet;
  const licenseRe = new RegExp(cfg.licensePattern, 'i');
  const denyRe = new RegExp(cfg.licenseDenyPattern, 'i');
  for (const project of cfg.projects) {
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
