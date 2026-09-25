'use strict';
// Load-order folder naming (SCOPE.md §2a): lowercase, punctuation stripped,
// spaces -> "-". "My first load order!" -> "my-first-load-order".

const WINDOWS_RESERVED = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/;
const MAX_LEN = 64;

function slugify(name) {
  let s = String(name ?? '').normalize('NFC').toLowerCase();
  s = s.replace(/[^\p{L}\p{M}\p{N}\s-]+/gu, ''); // strip punctuation/symbols; keep letters (any script), digits, spaces, hyphens
  s = s.trim().replace(/\s+/g, '-').replace(/-+/g, '-').replace(/^-+|-+$/g, '');
  if (s.length > MAX_LEN) s = s.slice(0, MAX_LEN).replace(/-+$/g, '');
  if (!s) s = 'load-order';
  if (WINDOWS_RESERVED.test(s)) s += '-load-order';
  return s;
}

// A slug as it may appear in IPC calls: no dots or separators, so it can never
// escape the load-orders folder.
function isValidSlug(s) {
  return typeof s === 'string' && s.length > 0 && s.length <= MAX_LEN + 8 && /^[\p{L}\p{M}\p{N}-]+$/u.test(s);
}

module.exports = { slugify, isValidSlug };
