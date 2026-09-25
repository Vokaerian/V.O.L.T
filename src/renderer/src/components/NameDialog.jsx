// Name popup for a new load order (SCOPE.md §2a). The folder name (slug) is
// derived from this name in the main process. askName=false turns it into a
// plain confirm popup (e.g. "save before Push"). toggleLabel adds a checkbox
// (default checked) whose state is passed to onConfirm as the second argument.
// placeholder lets the same popup ask for other text (e.g. a rentry.co URL).
// confirmClass styles the confirm button (e.g. 'warn-outline' for Run without saving).
import { useEffect, useRef, useState } from 'react';

export default function NameDialog({ title, message, busy, error, onConfirm, onCancel, confirmLabel = 'Create', askName = true, toggleLabel, placeholder = 'e.g. My first load order', confirmClass = 'primary' }) {
  const [name, setName] = useState('');
  const [checked, setChecked] = useState(true);
  const inputRef = useRef(null);

  useEffect(() => {
    if (inputRef.current) inputRef.current.focus();
  }, []);

  const submit = (e) => {
    e.preventDefault();
    if ((!askName || name.trim()) && !busy) onConfirm(name.trim(), checked);
  };

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
        <h2>{title}</h2>
        {message && <p>{message}</p>}
        {askName && (
          <input
            ref={inputRef}
            value={name}
            maxLength={120}
            placeholder={placeholder}
            onChange={(e) => setName(e.target.value)}
          />
        )}
        {toggleLabel && (
          <label>
            <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} /> {toggleLabel}
          </label>
        )}
        {error && <p className="error">{error}</p>}
        <div className="button-row end">
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className={confirmClass} disabled={(askName && !name.trim()) || busy} autoFocus={!askName}>
            {confirmLabel}
          </button>
        </div>
      </form>
    </div>
  );
}
