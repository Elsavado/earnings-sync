import { readFile } from 'node:fs/promises';
import { CATEGORIES } from './files.js';

const SOURCE_SECTIONS = ['europepmc', 'ctgov', 'tcia', 'isic', 'gdc', 'physionet', 'github', 'files', 'leads', 'websites'];

function checkCategory(category, where) {
  if (!CATEGORIES[category]) {
    throw new Error(`${where}: category "${category}" is not one of ${Object.keys(CATEGORIES).join(', ')}`);
  }
}

export function normalizeConfig(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('Config must be a JSON object');
  const s = raw.settings || {};
  const settings = {
    driveRootFolderName: s.driveRootFolderName || 'Medical Data',
    drivePrivateFolderName: s.drivePrivateFolderName || 'Medical Sync - private',
    driveReserveMB: Number(s.driveReserveMB ?? 2048),
    maxFileSizeMB: Number(s.maxFileSizeMB ?? 2048),
    runBudgetMinutes: Number(process.env.RUN_BUDGET_MINUTES || s.runBudgetMinutes || 0),
    rescanDays: Number(s.rescanDays ?? 30)
  };
  for (const name of SOURCE_SECTIONS) {
    const section = raw[name];
    if (!section) throw new Error(`Config is missing the "${name}" section`);
    settings[name] = { ...section, enabled: section.enabled !== false };
  }
  settings.tcia.collections ||= [];
  settings.websites.sites ||= [];
  settings.gdc.groups.forEach((g, i) => checkCategory(g.category, `gdc.groups[${i}]`));
  settings.physionet.projects.forEach((p, i) => checkCategory(p.category, `physionet.projects[${i}]`));
  settings.github.datasets.forEach((d, i) => checkCategory(d.category, `github.datasets[${i}]`));
  settings.files.items.forEach((f, i) => checkCategory(f.category, `files.items[${i}]`));
  for (const category of Object.keys(settings.leads.phrases || {})) checkCategory(category, 'leads.phrases');
  return settings;
}

export async function loadConfig(path) {
  let text;
  try {
    text = await readFile(path, 'utf8');
  } catch (err) {
    throw new Error(`Could not read config file ${path}: ${err.message}`);
  }
  try {
    return normalizeConfig(JSON.parse(text));
  } catch (err) {
    throw new Error(`Config file ${path}: ${err.message}`);
  }
}
