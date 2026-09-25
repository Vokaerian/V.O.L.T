// Scan issues window: folders the mod scan (electron/lib/mods.js scanModRoots)
// couldn't turn into a mod. Same look as ValidationWindow - short label on the
// rail, full message + path on the right - but a separate data source: these
// problems mostly have no mod object, so there's no DetailsPanel here.
import { useEffect, useState } from 'react';
import { api, errMsg } from '../api.js';

const RAIL_LABEL = {
  'missing-folder': 'Folder not found',
  'no-about': 'Not a mod folder',
  'parse-error': 'Unreadable About.xml',
  'duplicate-id': 'Duplicate package ID',
};

// Static "why this happens" note per kind, under the specific message.
// Scan order (paths.js modRoots): official, then Mods, then Workshop; first wins.
const WHY = {
  'missing-folder':
    "This is one of the folders VOLT scans for mods (for example the game's Mods folder), but it doesn't exist. It may have been deleted, moved, or renamed since the last scan, or the game folder in Settings may be wrong.",
  'no-about':
    "This folder doesn't contain an About/About.xml file, so VOLT can't tell it's a mod. It may not be a mod folder at all, or its About.xml was deleted, moved, or renamed.",
  'parse-error':
    "This mod's About.xml exists but couldn't be read as valid XML. It may be corrupted, an incomplete download, or hand-edited incorrectly.",
  'duplicate-id':
    "Two different mod folders declare the same internal package ID, and RimWorld can only load one. VOLT keeps the first one it finds (official content, then your local Mods folder, then the Steam Workshop folder, in that order) and ignores the rest. This doesn't necessarily mean either mod is broken: it commonly happens when two different Workshop uploads are built from the same original mod and the fork never changed the internal ID.",
};

const baseName = (p) => p.split(/[\\/]/).filter(Boolean).pop() || p;

// A duplicate-id pair whose About.xml names are identical can only be told
// apart by their Steam Workshop listing titles - looked up only then, and only
// when both sides are Workshop items (mods.js dupSide).
const needsWorkshopTitles = (p) =>
  p && p.kind === 'duplicate-id' && p.kept && p.ignored && p.kept.name === p.ignored.name && p.kept.workshopId && p.ignored.workshopId;

// Session cache: Workshop id -> Promise<{ title, found, result }> (main.js
// steam:workshopTitles; result = Steam's EResult). A failed lookup is cached
// too (no retry this session); the About.xml names still show.
// With steam (Steam Workshop actions available), a not-found Web API answer
// falls back to the logged-in Steam client (steam:workshopItem): a live item
// the keyless API reports as not found can still be visible there. Cached
// under its own key, so a later steam=true lookup still tries the fallback.
// Fallback failure of any kind keeps the Web API answer (neutral note).
const titleCache = new Map();
function workshopTitle(id, steam) {
  const key = steam ? `${id}+steam` : id;
  if (!titleCache.has(key)) {
    const web = steam
      ? workshopTitle(id, false)
      : api.steamWorkshopTitles([id]).then(
          (r) => (r && r[id]) || { title: null, found: false, result: null },
          (err) => ({ title: null, found: false, result: null, error: errMsg(err) }),
        );
    titleCache.set(
      key,
      !steam
        ? web
        : web.then((t) =>
            t.found
              ? t
              : api.steamWorkshopItem(id).then(
                  (s) => (s && s.found && s.title ? { title: s.title, found: true, result: null } : t),
                  () => t,
                ),
          ),
    );
  }
  return titleCache.get(key);
}

// One side's line: the listing title, or a neutral note. Deliberately no guess
// at why (removed/private/banned): a live public item has come back not-found,
// so the raw EResult is shown instead of an interpretation.
function titleText(t) {
  if (t.title) return t.title;
  if (t.error) return `(Steam title lookup failed: ${t.error})`;
  if (t.found) return '(Steam returned this item without a title)';
  return `(Steam didn't return a title for this item${t.result != null ? `, result code ${t.result}` : ''})`;
}

// Duplicate-id message with each side's lookup folded into its own Kept/Ignored
// block (one of each, no second section): a resolved title replaces the
// About.xml name (identical -> no visible change); an unresolved side keeps its
// name with the neutral note on the line under it. Same layout as mods.js's
// duplicate-id message, whose first paragraph (the package ID line) is reused.
function dupMessage(p, ws) {
  const side = (label, mod, t) =>
    `${label}: ${t.title || mod.name}${t.title ? '' : `\n${titleText(t)}`}\n${mod.path}`;
  return `${p.message.split('\n\n')[0]}\n\n${side('Kept', p.kept, ws.kept)}\n\n${side('Ignored', p.ignored, ws.ignored)}`;
}

export default function ScanIssuesWindow({ problems, steamAvailable = false, onClose, onIgnore }) {
  const [selIdx, setSelIdx] = useState(0);
  const [error, setError] = useState(null);
  // Out of range (e.g. after Ignore removed the last entry) falls back to the first.
  const sel = problems[selIdx] || problems[0] || null;
  // Workshop lookups for the selected duplicate: null, 'loading' or { p, kept, ignored }
  // (each { title, found, result, error? }; each side shown independently; p =
  // the problem they belong to, so a stale result never renders under another).
  const [wsTitles, setWsTitles] = useState(null);
  useEffect(() => {
    setWsTitles(null);
    if (!api || !needsWorkshopTitles(sel)) return;
    let live = true;
    setWsTitles('loading');
    Promise.all([
      workshopTitle(sel.kept.workshopId, steamAvailable),
      workshopTitle(sel.ignored.workshopId, steamAvailable),
    ]).then(([kept, ignored]) => {
      if (live) setWsTitles({ p: sel, kept, ignored });
    });
    return () => {
      live = false;
    };
  }, [sel, steamAvailable]);
  const openFolder = () => {
    setError(null);
    api.openPath(sel.path).catch((err) => setError(errMsg(err)));
  };

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal validation-window scan-issues" role="dialog" aria-label="Scan issues">
        <header className="validation-head">
          <h2>Scan issues</h2>
          <button disabled={!sel} onClick={() => onIgnore(sel.path)}>Ignore</button>
          <button disabled={!sel || sel.kind === 'missing-folder'} onClick={openFolder}>Folder</button>
          <button onClick={onClose}>Close</button>
        </header>
        {sel ? (
          <div className="validation-body">
            <nav className="validation-rail">
              {problems.map((p, i) => (
                <button
                  key={i}
                  className={'validation-entry scan' + (p === sel ? ' selected' : '')}
                  onClick={() => {
                    setSelIdx(i);
                    setError(null);
                  }}
                >
                  {RAIL_LABEL[p.kind] || 'Scan issue'}
                  <span className="validation-target">{baseName(p.path)}</span>
                </button>
              ))}
            </nav>
            <div className="validation-right">
              <section className="validation-detail">
                <h3>{RAIL_LABEL[sel.kind] || 'Scan issue'}</h3>
                <p>{wsTitles && wsTitles.p === sel ? dupMessage(sel, wsTitles) : sel.message}</p>
                {wsTitles === 'loading' && <p className="muted">Looking up Steam Workshop titles...</p>}
                <p className="mono">{sel.path}</p>
                {error && <p className="error">{error}</p>}
                {WHY[sel.kind] && <p className="muted scan-why">{WHY[sel.kind]}</p>}
              </section>
            </div>
          </div>
        ) : (
          <p>No scan issues.</p>
        )}
      </div>
    </div>
  );
}
