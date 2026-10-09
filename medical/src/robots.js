import { request } from './http.js';

const cache = new Map();

function escapeRegex(s) {
  return s.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
}

function compile(pattern) {
  const anchored = pattern.endsWith('$');
  const body = (anchored ? pattern.slice(0, -1) : pattern).split('*').map(escapeRegex).join('.*');
  return new RegExp(`^${body}${anchored ? '$' : ''}`);
}

export function parseRobots(text) {
  const rules = [];
  let applies = false;
  let inHeader = false;
  for (const rawLine of String(text).split(/\r?\n/)) {
    const line = rawLine.replace(/#.*$/, '').trim();
    if (!line) continue;
    const idx = line.indexOf(':');
    if (idx < 0) continue;
    const field = line.slice(0, idx).trim().toLowerCase();
    const value = line.slice(idx + 1).trim();
    if (field === 'user-agent') {
      if (!inHeader) applies = false;
      inHeader = true;
      if (value === '*') applies = true;
      continue;
    }
    inHeader = false;
    if (!applies || !value) continue;
    if (field === 'disallow') rules.push({ allow: false, pattern: value, regex: compile(value) });
    else if (field === 'allow') rules.push({ allow: true, pattern: value, regex: compile(value) });
  }
  return rules;
}

export function robotsAllows(rules, pathAndQuery) {
  let best = null;
  for (const rule of rules) {
    if (!rule.regex.test(pathAndQuery)) continue;
    if (!best || rule.pattern.length > best.pattern.length || (rule.pattern.length === best.pattern.length && rule.allow)) {
      best = rule;
    }
  }
  return best ? best.allow : true;
}

async function loadRules(origin, userAgent) {
  try {
    const res = await request(`${origin}/robots.txt`, { headers: { 'User-Agent': userAgent }, retries: 1, timeoutMs: 15000 });
    if (!res.ok) {
      await res.body?.cancel().catch(() => {});
      return [];
    }
    return parseRobots(await res.text());
  } catch {
    return [];
  }
}

export async function isAllowedByRobots(url, userAgent) {
  const u = new URL(url);
  if (!cache.has(u.origin)) cache.set(u.origin, loadRules(u.origin, userAgent));
  const rules = await cache.get(u.origin);
  return robotsAllows(rules, `${u.pathname}${u.search}`);
}
