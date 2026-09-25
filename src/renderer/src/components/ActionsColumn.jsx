// Main screen's 4th column, right edge (SCOPE.md §3): Import/Export, Rescan,
// Sort/Save/Sync (Save goes warn-outline while dirty), then pinned to the bottom:
// scan issues, merged warnings+errors, Push, Run.

export default function ActionsColumn({
  busy,
  noGame,
  dirty,
  paths,
  activeCount,
  canRescan,
  canSort,
  problemCount,
  warningCount,
  errorCount,
  onImport,
  onExport,
  onRescan,
  onSort,
  onSave,
  syncing,
  onSync,
  onShowScanIssues,
  onShowIssues,
  onPush,
  onRun,
}) {
  const disabled = busy || !!noGame;
  return (
    <div className="actions-column">
      <div className="actions-group">
        <button
          onClick={onImport}
          disabled={busy}
          title="Replace the active list with one from the clipboard, a RimPy .xml file, a rentry.co page or a save. Undoable; not saved until you Save."
        >
          Import...
        </button>
        <button
          onClick={onExport}
          disabled={busy || activeCount === 0}
          title="Share the active list: copy it in RimSort/rentry.co format, or save it as a RimPy .xml file."
        >
          Export...
        </button>
      </div>
      <div className="actions-group">
        <button onClick={onRescan} disabled={disabled || !canRescan} title="Rescan the game's Data and Mods folders (and the Steam Workshop folder).">
          Rescan
        </button>
      </div>
      <div className="actions-group">
        <button
          onClick={onSort}
          disabled={disabled || !canSort}
          title="Reorder the active list by each mod's own loadAfter/loadBefore rules. Core and DLC keep their release order; mods without rules go alphabetically. Doesn't check dependencies or incompatibilities yet."
        >
          Sort
        </button>
        <button
          className={dirty ? 'warn-outline' : undefined}
          onClick={onSave}
          disabled={disabled}
          title="Write this list to the current load order. Doesn't touch the game."
        >
          Save
        </button>
        <button
          onClick={onSync}
          disabled={disabled || syncing}
          title="Subscribe on Steam to every mod downloaded with SteamCMD, then remove VOLT's own copy"
        >
          {syncing ? 'Syncing...' : 'Sync'}
        </button>
      </div>
      <div className="spacer" />
      {(problemCount > 0 || warningCount > 0 || errorCount > 0) && (
        <div className="actions-group">
          {problemCount > 0 && (
            <button className="issue-count scan" onClick={onShowScanIssues} title="Show scan issues">
              {problemCount} scan issue{problemCount === 1 ? '' : 's'}
            </button>
          )}
          {(warningCount > 0 || errorCount > 0) && (
            <button className="issue-count" onClick={onShowIssues} title="Show warnings and errors">
              <span className="issue-icon warning">{'⚠︎'}</span> {warningCount}{' '}
              <span className="muted">{'·'}</span>{' '}
              <span className="issue-icon error">{'✕'}</span> {errorCount}
            </button>
          )}
        </div>
      )}
      <div className="actions-group">
        <button
          className="accent-outline"
          onClick={onPush}
          disabled={disabled || !paths || !paths.configDir}
          title={
            paths && paths.configDir
              ? "Write the active list to the game's ModsConfig.xml"
              : "RimWorld's Config folder isn't set"
          }
        >
          Push
        </button>
        <button className="primary" onClick={onRun} disabled={disabled} title="Launch RimWorld">
          Run
        </button>
      </div>
    </div>
  );
}
