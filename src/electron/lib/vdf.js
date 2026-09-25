'use strict';
// Minimal parser for Valve's KeyValues text format (libraryfolders.vdf,
// appmanifest_*.acf). Returns nested plain objects; all values are strings.

function parseVdf(input) {
  const src = String(input);
  const n = src.length;
  let i = 0;

  const skip = () => {
    for (;;) {
      while (i < n && /\s/.test(src[i])) i++;
      if (src[i] === '/' && src[i + 1] === '/') {
        while (i < n && src[i] !== '\n') i++;
        continue;
      }
      // Conditional suffixes like [$WIN32] - ignored.
      if (src[i] === '[') {
        while (i < n && src[i] !== ']') i++;
        i++;
        continue;
      }
      return;
    }
  };

  const readString = () => {
    if (src[i] === '"') {
      i++;
      let out = '';
      while (i < n && src[i] !== '"') {
        if (src[i] === '\\' && i + 1 < n) {
          const c = src[i + 1];
          out += c === 'n' ? '\n' : c === 't' ? '\t' : c;
          i += 2;
        } else {
          out += src[i++];
        }
      }
      if (i >= n) throw new Error('VDF: unterminated string');
      i++;
      return out;
    }
    const start = i;
    while (i < n && !/[\s{}"]/.test(src[i])) i++;
    if (i === start) throw new Error(`VDF: unexpected character "${src[i]}" at offset ${i}`);
    return src.slice(start, i);
  };

  const readObject = (top) => {
    const obj = {};
    for (;;) {
      skip();
      if (i >= n) {
        if (top) return obj;
        throw new Error('VDF: unexpected end of input');
      }
      if (src[i] === '}') {
        if (top) throw new Error('VDF: unmatched "}"');
        i++;
        return obj;
      }
      const key = readString();
      skip();
      if (src[i] === '{') {
        i++;
        obj[key] = readObject(false);
      } else {
        obj[key] = readString();
      }
    }
  };

  return readObject(true);
}

// VDF keys are case-insensitive in practice ("AppState" vs "appstate").
function getCI(obj, key) {
  if (!obj || typeof obj !== 'object') return undefined;
  if (Object.prototype.hasOwnProperty.call(obj, key)) return obj[key];
  const lower = key.toLowerCase();
  for (const k of Object.keys(obj)) if (k.toLowerCase() === lower) return obj[k];
  return undefined;
}

module.exports = { parseVdf, getCI };
