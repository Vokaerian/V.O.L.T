// Right-click menu (SCOPE.md §4a). items: [{ label, onClick?, disabled?, items? }];
// an entry with `items` is a submenu, opened on hover; { divider: true } is a
// separator line. Closes on any outside mouse-down, Escape, window
// blur/resize or scroll.
import { useEffect, useLayoutEffect, useRef, useState } from 'react';

export default function ContextMenu({ x, y, items, onClose }) {
  const ref = useRef(null);
  const [pos, setPos] = useState({ left: x, top: y });

  // Keep the menu inside the window. ponytail: submenus aren't clamped; they can
  // spill off the right edge for a pane at the far right of a narrow window.
  useLayoutEffect(() => {
    const r = ref.current.getBoundingClientRect();
    setPos({
      left: Math.max(0, Math.min(x, window.innerWidth - r.width)),
      top: Math.max(0, Math.min(y, window.innerHeight - r.height)),
    });
  }, [x, y]);

  useEffect(() => {
    const onDown = (e) => {
      if (!ref.current.contains(e.target)) onClose();
    };
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    window.addEventListener('blur', onClose);
    window.addEventListener('resize', onClose);
    window.addEventListener('scroll', onClose, true);
    return () => {
      window.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('blur', onClose);
      window.removeEventListener('resize', onClose);
      window.removeEventListener('scroll', onClose, true);
    };
  }, [onClose]);

  return (
    <div ref={ref} className="ctx-menu" style={pos} onContextMenu={(e) => e.preventDefault()}>
      <MenuItems items={items} onClose={onClose} />
    </div>
  );
}

function MenuItems({ items, onClose }) {
  return items.map((it, i) =>
    it.divider ? (
      <div key={`divider-${i}`} className="ctx-divider" />
    ) : it.items ? (
      <div key={it.label} className="ctx-item ctx-sub">
        {it.label}
        <span className="ctx-arrow">▸</span>
        <div className="ctx-menu ctx-submenu">
          <MenuItems items={it.items} onClose={onClose} />
        </div>
      </div>
    ) : (
      <div
        key={it.label}
        className={'ctx-item' + (it.disabled ? ' disabled' : '')}
        onClick={() => {
          if (it.disabled) return;
          onClose();
          it.onClick();
        }}
      >
        {it.label}
      </div>
    ),
  );
}
