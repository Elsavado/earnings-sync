function stamp() {
  return new Date().toISOString().slice(11, 19);
}

export const log = {
  info: (msg) => console.log(`[${stamp()}] ${msg}`),
  warn: (msg) => console.warn(`[${stamp()}] WARN ${msg}`),
  error: (msg) => console.error(`[${stamp()}] ERROR ${msg}`)
};

export function createContext() {
  const contact = process.env.SEC_USER_AGENT || '';
  const scraperUserAgent =
    process.env.SCRAPER_USER_AGENT ||
    `Mozilla/5.0 (compatible; MedicalSync/1.0${contact ? `; contact: ${contact}` : ''})`;

  let browserPromise = null;
  const warned = new Set();

  return {
    log,
    scraperUserAgent,
    secUserAgent: contact,
    warnOnce(key, message) {
      if (warned.has(key)) return;
      warned.add(key);
      log.warn(message);
    },
    browser() {
      if (!browserPromise) {
        browserPromise = (async () => {
          let playwright;
          try {
            playwright = await import('playwright');
          } catch {
            throw new Error('Playwright is not installed. Run: npx playwright install --with-deps chromium');
          }
          return playwright.chromium.launch({ headless: true });
        })();
      }
      return browserPromise;
    },
    async renderPage(url) {
      const browser = await this.browser();
      const page = await browser.newPage({ userAgent: scraperUserAgent });
      try {
        const response = await page.goto(url, { waitUntil: 'load', timeout: 60000 });
        const status = response ? response.status() : 0;
        if (status >= 400) throw new Error(`HTTP ${status} for ${url}`);
        await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
        return await page.content();
      } finally {
        await page.close().catch(() => {});
      }
    },
    // Prints already-anonymised HTML to PDF. Nothing is fetched from the network, so
    // remote images (logos) and scripts never load.
    async htmlToPdf(html) {
      const browser = await this.browser();
      const page = await browser.newPage({ javaScriptEnabled: false });
      try {
        await page.route('**/*', (route) => route.abort());
        await page.setContent(html.toString('utf8'), { waitUntil: 'domcontentloaded', timeout: 180000 });
        return await page.pdf({ format: 'Letter', printBackground: true, margin: { top: '0.5in', bottom: '0.5in', left: '0.5in', right: '0.5in' } });
      } finally {
        await page.close().catch(() => {});
      }
    },
    async close() {
      if (!browserPromise) return;
      try {
        const browser = await browserPromise;
        await browser.close();
      } catch {
        // Browser never launched successfully; nothing to close.
      }
    }
  };
}
