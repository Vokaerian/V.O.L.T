// Details for the selected mod (SCOPE.md §4a): preview image (About/Preview.png,
// when present), name, authors, path, package ID, description. pendingTitle:
// a "not found" Workshop-id entry's collection-import title (App.jsx
// workshopTitles), shown as its name; without one the id is shown.
import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { cleanDescription } from '../lists.js';

export default function DetailsPanel({ id, mod, pendingTitle }) {
  const modPath = mod ? mod.path : null;
  const [preview, setPreview] = useState(null); // { path, url }

  // Fetched per selection only; `path` guards against a slower earlier reply.
  useEffect(() => {
    if (!modPath) return;
    let live = true;
    api.getModPreview(modPath).then(
      (url) => live && setPreview({ path: modPath, url }),
      () => live && setPreview({ path: modPath, url: null }),
    );
    return () => {
      live = false;
    };
  }, [modPath]);

  const previewUrl = preview && preview.path === modPath ? preview.url : null;

  if (!id) {
    return (
      <aside className="details">
        <p className="details-empty">Select a mod to see its details.</p>
      </aside>
    );
  }
  return (
    <aside className="details">
      {previewUrl && <img className="details-preview" src={previewUrl} alt="" />}
      <dl className="details-grid">
        <dt>Name:</dt>
        <dd>{mod ? mod.name : pendingTitle || id}</dd>
        <dt>Authors:</dt>
        <dd>{mod && mod.authors.length ? mod.authors.join(', ') : '-'}</dd>
        <dt>Path:</dt>
        <dd className="mono">{mod ? mod.path : 'Not found in any scanned folder'}</dd>
        <dt>Package ID:</dt>
        <dd className="mono">{mod ? mod.packageId || '(none)' : id}</dd>
      </dl>
      {mod && mod.warnings.length > 0 && (
        <ul className="details-warnings">
          {mod.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {mod && mod.ddsLeftover && (
        <p className="details-note">
          This folder contains only .dds texture files - likely a leftover from texture compression, not a real mod.
        </p>
      )}
      <div className="details-description">
        {mod
          ? cleanDescription(mod.description) || 'No description.'
          : "This mod is in the load order but wasn't found in the game's Data or Mods folder (or, for Steam, the Workshop folder) - it may be uninstalled or unsubscribed. It is kept in the list and written as-is on Save and Push."}
      </div>
    </aside>
  );
}
