// Warnings/errors detail window (SCOPE.md §4a, Phase 2b): a scrollable rail of
// every validation issue (lists.js validateActive), grouped under one header
// per affected mod, RimPy-style; the right side shows the selected issue's
// mod (the regular DetailsPanel) over that issue's detail text. Warn-only:
// closing it is the only action. Updates live as the load order changes.
// issueSummary is also the tooltip of the Active pane's per-row issue icons.
import { useEffect, useState } from 'react';
import { modName } from '../lists.js';
import DetailsPanel from './DetailsPanel.jsx';

const LABEL = {
  'order-before': 'Should be loaded before:',
  'order-after': 'Should be loaded after:',
  'order-dependency': 'Should be loaded after (dependencies):',
  'order-dependency-conflict': 'Should be loaded after (dependencies, blocked by a load order rule):',
  inactive: 'Missing dependencies (inactive):',
  'not-found': 'Missing dependencies (not installed):',
  conflict: 'Incompatible with:',
};

// Rail buttons only: the right-side detail repeats the qualifier and the full target list.
const RAIL_LABEL = {
  'order-before': 'Load order',
  'order-after': 'Load order',
  'order-dependency': 'Load order',
  'order-dependency-conflict': 'Load order',
  inactive: 'Missing dependencies',
  'not-found': 'Missing dependencies',
  conflict: 'Conflict',
};

// One line per issue: its header label plus the target mods' names.
export function issueSummary(issue, mods) {
  return `${LABEL[issue.kind]} ${issue.targets.map((t) => modName(mods, t)).join(', ')}`;
}

// Which rules block an 'order-dependency-conflict' (issue.ruleSources).
function blockingRules(sources) {
  const community = sources.includes('community');
  const about = sources.includes('about');
  if (community && about) return 'the RimSort community rules and About.xml loadBefore/loadAfter rules';
  if (community) return 'the RimSort community rules';
  return 'About.xml loadBefore/loadAfter rules';
}

function detailText(issue, mods) {
  const name = modName(mods, issue.modId);
  if (issue.kind === 'order-before') {
    return `${name}'s own load order rules (its About.xml loadBefore, or the RimSort community rules) say it must load before these mods, but it is currently below them. Move it above them, or use Sort.`;
  }
  if (issue.kind === 'order-after') {
    return `${name}'s own load order rules (its About.xml loadAfter, or the RimSort community rules) say it must load after these mods, but it is currently above them. Move it below them, or use Sort.`;
  }
  if (issue.kind === 'order-dependency') {
    return `${name} requires these mods (modDependencies in About.xml), and they are active but currently load after it. A dependency should load before the mods that need it - move ${name} below them, or use Sort.`;
  }
  if (issue.kind === 'order-dependency-conflict') {
    return `${name} requires these mods (modDependencies in About.xml), and they are active but currently load after it. Normally Sort would fix this, but ${blockingRules(issue.ruleSources || [])} require the opposite order, so Sort leaves it as is. Resolve the conflicting rule, or reorder manually if you're sure it's safe.`;
  }
  if (issue.kind === 'inactive') {
    return `${name} requires these mods. They are installed but not active - activate them (double-click in the Inactive list) to fix this.`;
  }
  if (issue.kind === 'not-found') {
    return `${name} requires these mods, but none of the scanned folders (game Data, Mods, Steam Workshop) has them. Install or subscribe to them, then Rescan.`;
  }
  return `${name} and these active mods are declared incompatible (incompatibleWith in About.xml). RimWorld shouldn't run them together - deactivate one side.`;
}

// initialKey (a specific issue.key, from a row icon) wins over initialSeverity
// (the first issue of that severity, from the count buttons).
export default function ValidationWindow({ issues, mods, initialSeverity, initialKey, onClose }) {
  const [selKey, setSelKey] = useState(() => {
    const first =
      issues.find((i) => i.key === initialKey) || issues.find((i) => i.severity === initialSeverity) || issues[0];
    return first ? first.key : null;
  });
  // Live list: if the selected issue went away (fixed), fall back to the first one.
  const sel = issues.find((i) => i.key === selKey) || issues[0] || null;

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const groups = [];
  for (const i of issues) {
    const last = groups[groups.length - 1];
    if (last && last.modId === i.modId) last.items.push(i);
    else groups.push({ modId: i.modId, items: [i] });
  }

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal validation-window" role="dialog" aria-label="Load order warnings and errors">
        <header className="validation-head">
          <h2>Warnings and errors</h2>
          <button onClick={onClose}>Close</button>
        </header>
        {sel ? (
          <div className="validation-body">
            <nav className="validation-rail">
              {groups.map((g) => (
                <div key={g.modId} className="validation-group">
                  <div className="validation-mod">{modName(mods, g.modId)}</div>
                  {g.items.map((i) => (
                    <button
                      key={i.key}
                      className={`validation-entry ${i.severity}` + (i === sel ? ' selected' : '')}
                      onClick={() => setSelKey(i.key)}
                    >
                      {RAIL_LABEL[i.kind]}
                    </button>
                  ))}
                </div>
              ))}
            </nav>
            <div className="validation-right">
              <DetailsPanel id={sel.modId} mod={mods.get(sel.modId)} />
              <section className={`validation-detail ${sel.severity}`}>
                <h3>{LABEL[sel.kind]}</h3>
                <p>{detailText(sel, mods)}</p>
                <ul>
                  {sel.targets.map((t) => (
                    <li key={t}>
                      {mods.has(t) ? `${modName(mods, t)} ` : ''}
                      <span className="mono">{mods.has(t) ? `(${mods.get(t).packageId})` : t}</span>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          </div>
        ) : (
          <p>No warnings or errors in the current load order.</p>
        )}
      </div>
    </div>
  );
}
