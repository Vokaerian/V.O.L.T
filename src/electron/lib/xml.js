'use strict';
// Shared fast-xml-parser instance + helpers for RimWorld's XML files
// (About.xml, ModsConfig.xml). Values stay strings (parseTagValue: false) so a
// packageId or version like "1.0" is never coerced to a number, and <li> is
// always an array so single-item lists behave like multi-item ones.

const { XMLParser } = require('fast-xml-parser');
const { stripBom } = require('./fsutil');

const parser = new XMLParser({
  ignoreAttributes: true,
  parseTagValue: false,
  trimValues: true,
  isArray: (name) => name === 'li',
});

function parseXml(text) {
  return parser.parse(stripBom(String(text)));
}

// Case-insensitive property lookup (RimWorld's own loader is lenient about tag casing).
function getCI(obj, key) {
  if (!obj || typeof obj !== 'object') return undefined;
  if (Object.prototype.hasOwnProperty.call(obj, key)) return obj[key];
  const lower = key.toLowerCase();
  for (const k of Object.keys(obj)) if (k.toLowerCase() === lower) return obj[k];
  return undefined;
}

function text(v) {
  if (v == null) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (Array.isArray(v)) return v.map(text).join(', ');
  if (typeof v === 'object' && '#text' in v) return text(v['#text']);
  return '';
}

// <foo><li>a</li><li>b</li></foo> -> ['a', 'b']
function list(v) {
  const li = getCI(v, 'li');
  if (!Array.isArray(li)) return [];
  return li.map((x) => text(x).trim()).filter(Boolean);
}

// <foo><li><packageId>a</packageId>...</li><li>...</li></foo>, field 'packageId'
// -> ['a', ...]. Case-insensitive field lookup; entries without it (or plain-text
// <li>s) are skipped.
function listField(v, field) {
  const li = getCI(v, 'li');
  if (!Array.isArray(li)) return [];
  return li.map((x) => text(getCI(x, field)).trim()).filter(Boolean);
}

function escapeXml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

module.exports = { parseXml, getCI, text, list, listField, escapeXml };
