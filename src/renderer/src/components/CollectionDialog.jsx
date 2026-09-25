// "From Steam Workshop..." import popup (PLAN.md item 4), same .modal family
// as NameDialog: a URL/id input, a preview line once it resolves, then Cancel
// plus Add to list / Replace list / New load order... for a collection (the
// chosen button's value goes to onImport as `mode`), or a single Import for a
// single mod. The input resolves by itself shortly after typing/pasting stops
// (Enter resolves at once), through main.js steam:resolveCollection. The
// import buttons are only enabled while the preview matches the current input;
// Enter then submits the first one, the non-destructive Add to list. Each item is matched
// against the scan with the same lookup rentry import uses
// (lists.js resolveWorkshopPlaceholders): installed -> its packageId, anything
// else -> a "workshop:<id>" pending placeholder. A single mod's URL/id works
// too: main resolves it as a one-item collection (steamWebApi.js
// resolveSingleItem), shown and imported exactly the same way.
import { useEffect, useMemo, useRef, useState } from 'react';
import { api, errMsg } from '../api.js';
import { resolveWorkshopPlaceholders } from '../lists.js';

const RESOLVE_DELAY_MS = 500;
const plural = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;

export default function CollectionDialog({ mods, busy, onImport, onCancel }) {
  const [input, setInput] = useState('');
  // { status: 'idle' } | { status: 'resolving' } | { status: 'ok', value } | { status: 'error', message }
  const [res, setRes] = useState({ status: 'idle' });
  const inputRef = useRef(null);
  const seq = useRef(0); // bumps on every edit/resolve; a stale reply is ignored
  const timer = useRef(null);

  useEffect(() => {
    inputRef.current.focus();
    return () => clearTimeout(timer.current);
  }, []);

  const resolveNow = (text) => {
    clearTimeout(timer.current);
    const q = text.trim();
    const my = ++seq.current;
    if (!q) {
      setRes({ status: 'idle' });
      return;
    }
    setRes({ status: 'resolving' });
    api.steamResolveCollection(q).then(
      (value) => my === seq.current && setRes({ status: 'ok', value }),
      (err) => my === seq.current && setRes({ status: 'error', message: errMsg(err) }),
    );
  };

  const onChange = (e) => {
    const text = e.target.value;
    setInput(text);
    seq.current++; // drop any reply for the previous text
    setRes({ status: 'idle' });
    clearTimeout(timer.current);
    if (text.trim()) timer.current = setTimeout(() => resolveNow(text), RESOLVE_DELAY_MS);
  };

  const preview = useMemo(() => {
    if (res.status !== 'ok') return null;
    const { items } = res.value;
    const r = resolveWorkshopPlaceholders(items.map((it) => `workshop:${it.id}`), mods, { keepUnmatched: true });
    const pendingIds = new Set(r.ids);
    return {
      ids: r.ids,
      total: items.length,
      pending: r.pending,
      installed: items.length - r.pending,
      // pending items Steam no longer returns (removed/private/banned): Subscribe can't fetch these
      unavailable: items.filter((it) => it.details && !it.details.found && pendingIds.has(`workshop:${it.id}`)).length,
    };
  }, [res, mods]);

  const submit = (e) => {
    e.preventDefault();
    if (busy) return;
    const mode = e.nativeEvent.submitter?.value || 'add'; // implicit (Enter) submit = the first submit button
    if (preview) onImport({ ...res.value, ids: preview.ids, pending: preview.pending, mode });
  };

  const v = res.status === 'ok' ? res.value : null;
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <form
        className="modal"
        onSubmit={submit}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onCancel();
        }}
      >
        <h2>Import from Steam Workshop</h2>
        <p>
          Paste a Steam Workshop collection's URL, or just its id (a single mod's link or id works too). Installed mods
          are added as they are; the rest are added as pending, ready to Subscribe.
        </p>
        <input
          ref={inputRef}
          value={input}
          placeholder="https://steamcommunity.com/sharedfiles/filedetails/?id=..."
          onChange={onChange}
          onKeyDown={(e) => {
            // Enter before a preview exists resolves now (the disabled Import
            // button would otherwise swallow the implicit submit).
            if (e.key === 'Enter' && !preview) {
              e.preventDefault();
              if (res.status !== 'resolving') resolveNow(input);
            }
          }}
        />
        {res.status === 'resolving' && <p>Looking it up on Steam...</p>}
        {res.status === 'error' && <p className="error">{res.message}</p>}
        {preview && (
          <>
            {v.title && <p className="collection-title">{v.title}</p>}
            <p className="collection-preview">
              {plural(preview.total, 'item')} {'—'} {preview.installed} installed, {preview.pending} pending
            </p>
            {(preview.unavailable > 0 || v.detailsError || v.skippedCollections > 0) && (
              <p>
                {[
                  preview.unavailable > 0 &&
                    `${plural(preview.unavailable, 'item')} Steam no longer lists (removed, private or banned) can't be subscribed to.`,
                  v.skippedCollections > 0 && `${plural(v.skippedCollections, 'nested collection')} couldn't be read and ${v.skippedCollections === 1 ? 'was' : 'were'} left out.`,
                  v.detailsError && `Couldn't load the item names (${v.detailsError}); pending items will show their Workshop id.`,
                ]
                  .filter(Boolean)
                  .join(' ')}
              </p>
            )}
          </>
        )}
        <div className="button-row end">
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          {v?.single ? (
            <button type="submit" className="primary" disabled={!preview || busy}>
              Import
            </button>
          ) : (
            <>
              <button type="submit" value="add" className="primary" disabled={!preview || busy}>
                Add to list
              </button>
              <button type="submit" value="replace" disabled={!preview || busy}>
                Replace list
              </button>
              <button type="submit" value="new" disabled={!preview || busy}>
                New load order...
              </button>
            </>
          )}
        </div>
      </form>
    </div>
  );
}
