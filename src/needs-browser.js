// Exits 0 when any IR page in the config needs a headless browser, 1 otherwise.
// The workflow uses this to install Chromium only when it is required.
import { loadConfig } from './config.js';

const { companies } = await loadConfig(process.env.CONFIG_PATH || 'companies.json');
const needed = companies.some((c) => c.sources.ir && c.irPages.some((p) => p.render));
console.log(needed ? 'Browser rendering needed' : 'Browser rendering not needed');
process.exit(needed ? 0 : 1);
