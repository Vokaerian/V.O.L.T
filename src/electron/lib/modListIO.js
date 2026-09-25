'use strict';
// Mod list import/export formats (PLAN.md Phase 3). Every importer returns an
// ordered, cleaned list of packageIds; the renderer applies it like loading a
// load order. Export to RimPy .xml reuses modsConfig.freshModsConfig; the
// RimSort text / rentry markdown exports are built in the renderer (lists.js).

const fs = require('node:fs/promises');
const { parseXml, getCI, list } = require('./xml');
const { cleanIds } = require('./ids');

const RENTRY_TIMEOUT_MS = 10_000;
const SAVE_HEAD_BYTES = 512 * 1024;
const NOT_A_LIST = "Doesn't look like a RimPy export or a RimSort mod list.";
const NO_SAVE_LIST = 'This save has no recorded mod list.';

// RimPy export = a ModsConfig.xml. Anything around the <ModsConfigData> block
// (e.g. markdown fences on a rentry.co page) is ignored.
function parseRimPyXmlText(text) {
  const s = String(text);
  const start = s.search(/<ModsConfigData\b/i);
  const close = /<\/ModsConfigData\s*>/gi;
  let end = -1;
  for (let m; (m = close.exec(s)); ) end = m.index + m[0].length; // last closing tag
  const root = start >= 0 && end > start ? getCI(parseXml(s.slice(start, end)), 'ModsConfigData') : undefined;
  const activeMods = root && getCI(root, 'activeMods');
  if (activeMods === undefined) throw new Error("This isn't a RimPy mod list (no <ModsConfigData>/<activeMods> found).");
  return cleanIds(list(activeMods));
}

// RimSort clipboard export: "Name [packageId][url]" per line; header/blank lines skipped.
function parseRimSortText(text) {
  const ids = [];
  for (const line of String(text).split(/\r?\n/)) {
    const m = /\[([^\[\]]+)\]\[[^\[\]]*\]\s*$/.exec(line);
    if (m) ids.push(m[1]);
  }
  return cleanIds(ids);
}

// rentry.co markdown (RimSort's page export, and ours: lists.js buildRentryMarkdown).
// Every id follows "packageid:" whether in (...) or {...}; no markdown parsing needed.
function parseRentryMarkdownText(text) {
  return cleanIds([...String(text).matchAll(/packageid:\s*([^\s(){}\[\]]+)/gi)].map((m) => m[1]));
}

// Clipboard / rentry.co text: any of the three formats. Sniffs the first ~500 chars
// anywhere (not just a strict prefix), so XML inside a markdown code block works.
function detectAndParse(text) {
  const head = String(text).slice(0, 500);
  const ids = /<\?xml|<ModsConfigData/i.test(head)
    ? parseRimPyXmlText(text)
    : /packageid:/i.test(text)
      ? parseRentryMarkdownText(text)
      : parseRimSortText(text);
  if (!ids.length) throw new Error(NOT_A_LIST);
  return ids;
}

async function readHead(filePath, bytes) {
  const fh = await fs.open(filePath, 'r');
  try {
    const buf = Buffer.alloc(bytes);
    const { bytesRead } = await fh.read(buf, 0, bytes, 0);
    return buf.toString('utf8', 0, bytesRead);
  } finally {
    await fh.close();
  }
}

// Mod ids from a RimWorld .rws save's <meta><modIds>. Only the meta block is
// parsed, never the (tens of MB) <game> tree.
// ponytail: assumes </meta> lies in the first 512KB (~53KB for a 600-mod save);
// past that it falls back to reading the whole file. Stream-scan for </meta> if
// that fallback ever matters.
async function readSaveModList(filePath) {
  let text = await readHead(filePath, SAVE_HEAD_BYTES);
  let end = text.indexOf('</meta>');
  if (end < 0) {
    text = await fs.readFile(filePath, 'utf8');
    end = text.indexOf('</meta>');
  }
  if (end < 0) throw new Error(NO_SAVE_LIST);
  const root = getCI(parseXml(text.slice(0, end + '</meta>'.length) + '</savegame>'), 'savegame');
  const modIds = getCI(getCI(root, 'meta'), 'modIds');
  const ids = cleanIds(list(modIds));
  if (!ids.length) throw new Error(NO_SAVE_LIST);
  return ids;
}

// A rentry.co/rentry.org page URL (share link, /edit or old /raw link) -> the plain page URL.
function rentryPageUrl(input) {
  let s = String(input || '').trim();
  if (!/^https?:\/\//i.test(s)) s = 'https://' + s;
  let u;
  try {
    u = new URL(s);
  } catch {
    throw new Error(`Not a valid URL: ${input}`);
  }
  if (!/^(www\.)?rentry\.(co|org)$/i.test(u.hostname)) throw new Error(`Not a rentry.co URL: ${input}`);
  const p = u.pathname.replace(/\/+$/, '').replace(/\/(edit|raw)$/i, '').replace(/\/+$/, '');
  if (!p) throw new Error(`That URL has no rentry.co page in it: ${input}`);
  return `https://${u.hostname}${p}`;
}

const ENTITIES = { lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', '#39': "'", '#x27': "'" };

// Rendered HTML, stage 1: drop script/style blocks and comments (never visible text).
function sanitizeHtml(html) {
  return String(html)
    .replace(/<(script|style)\b[\s\S]*?<\/\1\s*>/gi, ' ')
    .replace(/<!--[\s\S]*?-->/g, ' ');
}

// Stage 2: tags -> text. Block-ending tags become newlines (the RimSort text
// parser is line-based), other tags a space; &amp; decoded last.
// ponytail: regex tag strip, not an HTML parser; enough to find "packageid:" text.
function stripTags(html) {
  return String(html)
    .replace(/<br\b[^>]*>|<\/(p|li|div|h[1-6]|tr|pre|ol|ul)\s*>/gi, '\n')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&(lt|gt|quot|apos|nbsp|#39|#x27);/gi, (_, e) => ENTITIES[e.toLowerCase()])
    .replace(/&amp;/gi, '&')
    .replace(/[ \t]+/g, ' ')
    .replace(/ *\n[\s]*/g, '\n')
    .trim();
}

// Rendered HTML -> visible text.
function htmlToText(html) {
  return stripTags(sanitizeHtml(html));
}

// A fetched rentry.co page -> ordered ids. A line with visible "packageid: x"
// (our exports, RimSort's warning boxes) gives x. A line whose only id is a
// Steam Workshop link's href (RimSort's Workshop entries: the packageid never
// renders) gives the sentinel "workshop:<id>", resolved against scanned mods by
// lists.js resolveWorkshopPlaceholders. Each link's id is swapped in as a
// marker *on its own line* before tags are stripped, so a line pairs only with
// its own link (a global href queue would desync on lines that carry both a
// link and a visible packageid). Nothing found -> generic detectAndParse.
const WS_MARK = '\u0001';
function parseRentryPageHtml(html) {
  const text = stripTags(
    sanitizeHtml(html)
      .replace(/<li\b/gi, '\n$&')
      .replace(/<a\b[^>]*filedetails\/\?id=(\d+)[^>]*>/gi, ` ${WS_MARK}$1${WS_MARK} `),
  );
  const ids = [];
  for (const line of text.split('\n')) {
    const pid = /packageid:\s*([^\s(){}\[\]]+)/i.exec(line);
    const rs = /\[([^\[\]]+)\]\[[^\[\]]*\]\s*$/.exec(line); // a RimSort text line, url autolinked
    const wid = /\u0001(\d+)\u0001/.exec(line);
    if (pid) ids.push(pid[1]);
    else if (rs) ids.push(rs[1]);
    else if (wid) ids.push(`workshop:${wid[1]}`);
  }
  const out = cleanIds(ids);
  return out.length ? out : detectAndParse(text.split(WS_MARK).join(''));
}

// There is no unauthenticated raw-markdown route (/api/raw needs a rentry-auth
// header), so read the public rendered page; returns its raw HTML for parseRentryPageHtml.
async function fetchRentryPage(url, appVersion) {
  const page = rentryPageUrl(url);
  const res = await fetch(page, {
    signal: AbortSignal.timeout(RENTRY_TIMEOUT_MS),
    headers: { 'User-Agent': `VOLT/${appVersion || '?'} mod-list importer` },
  });
  if (!res.ok) throw new Error(`rentry.co returned HTTP ${res.status} for ${page}.`);
  return res.text();
}

// Anonymous, CSRF-exempt create endpoint (per github.com/radude/rentry; unconfirmed against the live site).
// Form-encoded POST; JSON reply { status: '200', url } or { status, errors }. No edit_code/url sent.
async function publishRentry(text, appVersion) {
  const res = await fetch('https://rentry.co/api/new', {
    method: 'POST',
    signal: AbortSignal.timeout(RENTRY_TIMEOUT_MS),
    headers: { 'User-Agent': `VOLT/${appVersion || '?'} mod-list exporter` },
    body: new URLSearchParams({ text }),
  });
  if (res.status === 429) throw new Error('rentry.co is rate-limiting requests (HTTP 429). Try again in a minute.');
  if (!res.ok) throw new Error(`rentry.co returned HTTP ${res.status} when publishing.`);
  const j = await res.json();
  if (String(j.status) !== '200' || !j.url) {
    const detail = j.errors ? (typeof j.errors === 'string' ? j.errors : JSON.stringify(j.errors)) : j.content || '';
    throw new Error(`rentry.co refused the upload (status ${j.status})${detail ? `: ${detail}` : '.'}`);
  }
  const u = String(j.url);
  return /^https?:\/\//i.test(u) ? u : `https://rentry.co/${u.replace(/^\/+/, '')}`;
}

module.exports = { parseRimPyXmlText, parseRimSortText, parseRentryMarkdownText, detectAndParse, readSaveModList, rentryPageUrl, sanitizeHtml, stripTags, htmlToText, parseRentryPageHtml, fetchRentryPage, publishRentry };
