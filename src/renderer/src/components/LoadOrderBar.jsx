// Load-order picker + "New load order" (SCOPE.md §2a), then the game version
// right-aligned (SCOPE.md §3). Rescan/Sort/Save live in ActionsColumn.

export default function LoadOrderBar({
  loadOrders,
  currentSlug,
  dirty,
  disabled,
  onSelect,
  onNew,
  onCopy,
  onUndo,
  gameVersion,
}) {
  return (
    <div className="loadorder-bar">
      <label htmlFor="load-order-select">Load order</label>
      <select
        id="load-order-select"
        value={currentSlug || ''}
        disabled={disabled}
        onChange={(e) => e.target.value && onSelect(e.target.value)}
      >
        {!currentSlug && <option value="">(no load order selected)</option>}
        {loadOrders.map((lo) => (
          <option key={lo.slug} value={lo.slug} disabled={!!lo.error}>
            {lo.name}
            {lo.error ? ' (unreadable)' : ''}
          </option>
        ))}
      </select>
      <button onClick={onNew} disabled={disabled}>
        New load order...
      </button>
      <button onClick={onCopy} disabled={disabled}>
        Copy to new...
      </button>
      {dirty && (
        <>
          <span className="dirty">Unsaved changes</span>
          <button className="undo-btn" onClick={onUndo} disabled={disabled} title="Undo the most recent change to the active list">
            {'↺'}
          </button>
        </>
      )}
      <div className="spacer" />
      {gameVersion && <span className="muted">Game version: {gameVersion}</span>}
    </div>
  );
}
