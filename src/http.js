export class SkipError extends Error {
  constructor(message) {
    super(message);
    this.name = 'SkipError';
  }
}

const hostLastHit = new Map();

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function redactUrl(url) {
  return String(url).replace(/([?&](?:apikey|api_key|token|key)=)[^&]+/gi, '$1REDACTED');
}

async function throttle(url, minIntervalMs) {
  if (!minIntervalMs) return;
  const host = new URL(url).host;
  const last = hostLastHit.get(host) || 0;
  const wait = last + minIntervalMs - Date.now();
  if (wait > 0) await sleep(wait);
  hostLastHit.set(host, Date.now());
}

function backoff(attempt) {
  return Math.min(30000, 1000 * 2 ** attempt) + Math.floor(Math.random() * 500);
}

export async function request(url, { headers = {}, minIntervalMs = 0, retries = 3, timeoutMs = 60000 } = {}) {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt++) {
    await throttle(url, minIntervalMs);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(url, { headers, signal: controller.signal, redirect: 'follow' });
      if (res.status === 429 || res.status >= 500) {
        lastError = new Error(`HTTP ${res.status} for ${redactUrl(url)}`);
        await res.body?.cancel().catch(() => {});
        if (attempt < retries) {
          const retryAfter = Number(res.headers.get('retry-after'));
          await sleep(Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : backoff(attempt));
        }
        continue;
      }
      return res;
    } catch (err) {
      lastError = new Error(`Request failed for ${redactUrl(url)}: ${err.name === 'AbortError' ? 'timed out' : err.message}`);
      if (attempt < retries) await sleep(backoff(attempt));
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastError;
}

export async function getJson(url, options = {}) {
  const res = await request(url, { ...options, headers: { Accept: 'application/json', ...(options.headers || {}) } });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status} for ${redactUrl(url)}${body ? `: ${body.slice(0, 200)}` : ''}`);
  }
  return res.json();
}

export async function getText(url, options = {}) {
  const res = await request(url, options);
  if (!res.ok) {
    await res.body?.cancel().catch(() => {});
    throw new Error(`HTTP ${res.status} for ${redactUrl(url)}`);
  }
  return res.text();
}

export function fileNameFromDisposition(header) {
  if (!header) return null;
  const star = header.match(/filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''));
    } catch {
      return star[1].trim().replace(/^"|"$/g, '');
    }
  }
  const plain = header.match(/filename\s*=\s*("?)([^";]+)\1/i);
  return plain ? plain[2].trim() : null;
}

export async function downloadBuffer(url, { headers = {}, maxBytes = 0, minIntervalMs = 0, timeoutMs = 300000 } = {}) {
  const res = await request(url, { headers, minIntervalMs, timeoutMs });
  if (!res.ok) {
    await res.body?.cancel().catch(() => {});
    throw new Error(`HTTP ${res.status} downloading ${redactUrl(url)}`);
  }
  const declared = Number(res.headers.get('content-length'));
  if (maxBytes && Number.isFinite(declared) && declared > maxBytes) {
    await res.body?.cancel().catch(() => {});
    throw new SkipError(`${redactUrl(url)} is ${(declared / 1048576).toFixed(1)} MB, above the size limit`);
  }
  const buffer = Buffer.from(await res.arrayBuffer());
  if (maxBytes && buffer.length > maxBytes) {
    throw new SkipError(`${redactUrl(url)} is ${(buffer.length / 1048576).toFixed(1)} MB, above the size limit`);
  }
  return {
    buffer,
    contentType: (res.headers.get('content-type') || '').split(';')[0].trim().toLowerCase(),
    dispositionName: fileNameFromDisposition(res.headers.get('content-disposition')),
    finalUrl: res.url || url
  };
}
