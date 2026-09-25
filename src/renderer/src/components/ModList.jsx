// One mod-list pane (SCOPE.md §4a): title with count, per-pane search, and a
// virtualized list (600+ active mods is normal). With `sortable` (the active
// pane only) rows can be drag-reordered via dnd-kit; dragging is disabled while
// a search filter hides rows, since reordering a filtered view is ambiguous.
// The eye toggle in the search box (SCOPE.md §3) switches that pane from
// hiding non-matches to dimming them (matches get an accent bar); nothing is
// hidden then, so drag stays enabled.
// Right-click opens the mod context menu (open folder/URL, filter, copy, color,
// then Steam Workshop Subscribe/Unsubscribe below a divider - PLAN.md item 4).
// A "not found" row being subscribed to shows dimmed with "downloading...".
// Otherwise a "not found" row whose id is a Workshop id (notFoundWorkshopId:
// collection import's "workshop:<id>" placeholders, bare numeric ids) is
// "pending": dashed outline, normal-colored name (its collection title when
// known, else the id), "(pending)", and an inline Subscribe button. Other
// "not found" rows keep the red name + "(not found)".
// Rows mark official content (Core/DLC) with an "L" badge, .dds-only leftover
// folders (mods.js ddsLeftover) with a muted ".dds" badge after the name, show outdated mods'
// names in red, and highlight the selected mod's dependencies and dependents.
// Active hard conflicts (incompatibleWith, lists.js validateActive) get the
// outdated red name plus a --warn outline, on top of any other marking.
// Active pane only: per-row validation icons after the name (yellow warning
// triangle, then red cross), each opening the issues window on that mod's issue.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { defaultRangeExtractor, useVirtualizer } from '@tanstack/react-virtual';
import { DndContext, DragOverlay, PointerSensor, closestCenter, useSensor, useSensors } from '@dnd-kit/core';
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { isOutdated, modMatches, modName, notFoundWorkshopId, subscribeReady, unsubscribeKind, usesSteamCmd, workshopUrls } from '../lists.js';
import { api, errMsg } from '../api.js';
import ContextMenu from './ContextMenu.jsx';
import { issueSummary } from './ValidationWindow.jsx';

const ROW_HEIGHT = 24;
const ROW_GAP = 2; // space between row cards, taken from the bottom of each row's slot
const NO_IDS = new Set();
const NO_CONFLICTS = new Map();
const NO_ISSUES = new Map();
const NO_TITLES = new Map();

export default function ModList({
  title,
  ids,
  mods,
  selectedId,
  onSelect,
  onActivate,
  sortable = false,
  onReorder,
  emptyText,
  modColors,
  onSetColor,
  say,
  gameVersion,
  dependencyIds = NO_IDS, // mods the selected mod depends on
  dependentIds = NO_IDS, // mods depending on the selected mod
  conflicts = NO_CONFLICTS, // Map id -> Set of active ids it conflicts with
  issuesByMod = NO_ISSUES, // Map id -> its validateActive issues (active pane only)
  onShowIssue, // (issue.key) => open the issues window on that issue
  steamAvailable = false, // Steam Workshop actions possible (main.js steam:available)
  acquireVia = 'steamcmd', // the acquisition mode in effect (App.jsx; lists.js ACQUIRE_MODES)
  downloading = NO_IDS, // not-found ids with a Subscribe in progress
  onSubscribe, // (id) => subscribe to a not-found Workshop-id entry
  onUnsubscribe, // (id) => confirm, then unsubscribe from (or, SteamCMD-only, just delete) an installed Workshop mod
  workshopTitles = NO_TITLES, // Map Workshop id -> title, from collection import (in-memory only)
}) {
  const [query, setQuery] = useState('');
  const [colorFilter, setColorFilter] = useState(null); // '#rrggbb' or null
  const [dim, setDim] = useState(false); // eye open: dim non-matches instead of hiding them
  const [dragId, setDragId] = useState(null);
  const [menu, setMenu] = useState(null); // { x, y, id }
  const scrollRef = useRef(null);
  const colorInput = useRef(null);
  const colorTarget = useRef(null);
  const pickerAt = useRef(undefined); // last menu position, where the color picker opens

  const q = query.trim().toLowerCase();
  const filtered = !!q || !!colorFilter;
  const matches = useMemo(
    () =>
      filtered
        ? new Set(ids.filter((id) => (!q || modMatches(mods, id, q)) && (!colorFilter || modColors[id] === colorFilter)))
        : null,
    [ids, mods, q, colorFilter, modColors, filtered],
  );
  const hiding = filtered && !dim;
  const rows = useMemo(() => (hiding ? ids.filter((id) => matches.has(id)) : ids), [ids, matches, hiding]);
  const dragEnabled = sortable && !hiding;
  const dragIndex = dragId == null ? -1 : rows.indexOf(dragId);

  // Keep the dragged row mounted even when it scrolls out of the rendered window.
  const rangeExtractor = useCallback(
    (range) => {
      const indexes = defaultRangeExtractor(range);
      if (dragIndex >= 0 && !indexes.includes(dragIndex)) {
        indexes.push(dragIndex);
        indexes.sort((a, b) => a - b);
      }
      return indexes;
    },
    [dragIndex],
  );

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 15,
    rangeExtractor,
    getItemKey: (index) => rows[index],
  });

  // Native 'change' fires once when the picker closes; React's onChange would
  // fire (and write settings.json) on every step of dragging through colors.
  useEffect(() => {
    const el = colorInput.current;
    const onChange = () => colorTarget.current && onSetColor(colorTarget.current, el.value);
    el.addEventListener('change', onChange);
    return () => el.removeEventListener('change', onChange);
  }, [onSetColor]);

  const closeMenu = useCallback(() => setMenu(null), []);
  // SteamCMD mode needs no Steam at all (GOG included); the Steam-client mode does.
  const canSubscribe = subscribeReady(acquireVia, steamAvailable);

  const openMenu = (e, id) => {
    e.preventDefault();
    onSelect(id);
    pickerAt.current = { left: e.clientX, top: e.clientY };
    setMenu({ x: e.clientX, y: e.clientY, id });
  };

  const act = (fn, done) => async () => {
    try {
      await fn();
      if (done) say(done);
    } catch (err) {
      say(errMsg(err), 'error');
    }
  };

  const menuItems = (id) => {
    const mod = mods.get(id);
    const urls = workshopUrls(mod);
    const color = modColors[id];
    const pkg = mod ? mod.packageId : id; // a not-found mod's id is its lowercased packageId
    return [
      { label: 'Open folder', disabled: !mod, onClick: act(() => api.openPath(mod.path)) },
      { label: 'Open URL in browser', disabled: !urls, onClick: act(() => api.openExternal(urls.web)) },
      { label: 'Open URL in Steam', disabled: !urls, onClick: act(() => api.openExternal(urls.steam)) },
      {
        label: 'Filter by',
        items: [
          { label: 'This mod author', disabled: !mod || !mod.authors.length, onClick: () => setQuery(mod.authors[0]) },
          { label: 'This mod color', disabled: !color, onClick: () => setColorFilter(color) },
        ],
      },
      {
        label: 'Copy to clipboard',
        items: [
          { label: 'Copy URL', disabled: !urls, onClick: act(() => api.copyText(urls.web), 'Copied the Workshop URL.') },
          { label: 'Copy PackageId', disabled: !pkg, onClick: act(() => api.copyText(pkg), `Copied "${pkg}".`) },
        ],
      },
      {
        label: 'Mod color',
        items: [
          {
            label: 'Change mod color',
            onClick: () => {
              colorTarget.current = id;
              colorInput.current.value = color || '#ffffff';
              colorInput.current.click();
            },
          },
          { label: 'Discolor mod', disabled: !color, onClick: () => onSetColor(id, null) },
        ],
      },
      { divider: true },
      {
        label: 'Subscribe',
        disabled: !canSubscribe || !notFoundWorkshopId(id, mods) || downloading.has(id),
        onClick: () => onSubscribe(id),
      },
      // A real Steam subscription (source 'workshop') needs Steam; a SteamCMD
      // download (source 'steamcmd' or 'gog') was never subscribed, so Unsubscribe only
      // deletes its files and needs no Steam (lists.js unsubscribeKind).
      {
        label: 'Unsubscribe',
        disabled: !(unsubscribeKind(mod) === 'delete' || (unsubscribeKind(mod) === 'steam' && steamAvailable)),
        onClick: () => onUnsubscribe(id),
      },
    ];
  };

  // Small drag threshold so click (select) and double-click (move) still work.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  const onDragEnd = ({ active, over }) => {
    setDragId(null);
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(active.id);
    const to = ids.indexOf(over.id);
    if (from < 0 || to < 0) return;
    onReorder(arrayMove(ids, from, to));
  };

  const conflictNames = (id) => {
    const set = conflicts.get(id);
    return set ? [...set].map((c) => modName(mods, c)) : null;
  };

  const RowComponent = dragEnabled ? SortableRow : Row;
  const list = (
    <div className="list-scroll" ref={scrollRef}>
      <div className="list-inner" style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((vi) => {
          const id = rows[vi.index];
          const wid = notFoundWorkshopId(id, mods);
          return (
            <RowComponent
              key={id}
              id={id}
              top={vi.start}
              mod={mods.get(id)}
              color={modColors[id]}
              outdated={isOutdated(mods.get(id), gameVersion)}
              selected={id === selectedId}
              dependency={dependencyIds.has(id)}
              dependent={dependentIds.has(id)}
              conflictNames={conflictNames(id)}
              dimmed={!!matches && dim && !matches.has(id)}
              matched={!!matches && dim && matches.has(id)}
              issues={issuesByMod.get(id)}
              downloading={downloading.has(id)}
              pendingWid={wid}
              pendingTitle={wid ? workshopTitles.get(wid) : undefined}
              canSubscribe={canSubscribe}
              acquireVia={acquireVia}
              onSubscribe={onSubscribe}
              mods={mods}
              onShowIssue={onShowIssue}
              onSelect={onSelect}
              onActivate={onActivate}
              onMenu={openMenu}
            />
          );
        })}
      </div>
      {rows.length === 0 && <div className="list-empty">{hiding ? 'No matches' : emptyText}</div>}
    </div>
  );

  return (
    <section className="pane">
      <header className="pane-title">
        {title} [{filtered ? `${matches.size}/${ids.length}` : ids.length}]
      </header>
      <div className="pane-search-wrap">
        <input
          className="pane-search"
          type="search"
          placeholder="Search name, author or package ID"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button
          className={'search-eye' + (dim ? ' on' : '')}
          aria-pressed={dim}
          title={dim ? 'Showing all mods, non-matches dimmed. Click to hide non-matches.' : 'Hiding non-matches. Click to show all mods with non-matches dimmed.'}
          onClick={() => setDim(!dim)}
        >
          <EyeIcon open={dim} />
        </button>
      </div>
      {colorFilter && (
        <div className="pane-hint pane-color-filter">
          Only mods colored <span className="row-color" style={{ background: colorFilter }} />
          <button onClick={() => setColorFilter(null)}>Clear</button>
        </div>
      )}
      {sortable ? (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={(e) => setDragId(e.active.id)}
          onDragCancel={() => setDragId(null)}
          onDragEnd={onDragEnd}
        >
          <SortableContext items={rows} strategy={verticalListSortingStrategy}>
            {list}
          </SortableContext>
          <DragOverlay>
            {dragId ? (
              <div className="row row-overlay">
                <RowLabel
                  id={dragId}
                  mod={mods.get(dragId)}
                  color={modColors[dragId]}
                  outdated={isOutdated(mods.get(dragId), gameVersion)}
                  conflict={conflicts.has(dragId)}
                  downloading={downloading.has(dragId)}
                  pending={!!notFoundWorkshopId(dragId, mods)}
                  title={workshopTitles.get(notFoundWorkshopId(dragId, mods))}
                />
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      ) : (
        list
      )}
      {sortable && hiding && <div className="pane-hint">Clear the filter to drag-reorder.</div>}
      {/* Native color picker, opened from the menu; positioned at the menu so the popup appears there. */}
      <input
        ref={colorInput}
        type="color"
        className="color-input"
        tabIndex={-1}
        style={pickerAt.current}
      />
      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuItems(menu.id)} onClose={closeMenu} />}
    </section>
  );
}

function EyeIcon({ open }) {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
      <path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z" />
      <circle cx="8" cy="8" r="2" />
      {!open && <path d="M2 14L14 2" />}
    </svg>
  );
}

// pending: the not-found id is a Workshop id (notFoundWorkshopId); title: its
// collection-import title, if known (else the id is shown).
function RowLabel({ id, mod, color, outdated, conflict, downloading, pending, title }) {
  const swatch = color && <span className="row-color" style={{ background: color }} />;
  if (!mod) {
    if (pending && !downloading) {
      return (
        <>
          {swatch}
          <span className="row-name pending">
            {title || id} <em>(pending)</em>
          </span>
        </>
      );
    }
    return (
      <>
        {swatch}
        <span className="row-name missing">
          {title || id} <em>{downloading ? '\u27F3 downloading\u2026' : '(not found)'}</em>
        </span>
      </>
    );
  }
  return (
    <>
      {swatch}
      {mod.source === 'official' && (
        <span className="row-badge" title="Official content (Core/DLC), not a mod.">
          L
        </span>
      )}
      <span className={'row-name' + (outdated || conflict ? ' outdated' : '')}>{mod.name}</span>
      {mod.ddsLeftover && (
        <span className="row-badge dds-leftover" title="Only .dds texture files - likely a texture-compression leftover, not a real mod.">
          .dds
        </span>
      )}
      {mod.warnings.length > 0 && (
        <span className="row-warn" title={mod.warnings.join('\n')}>
          !
        </span>
      )}
    </>
  );
}

function RowView({
  id,
  mod,
  color,
  outdated,
  selected,
  dependency,
  dependent,
  conflictNames,
  dimmed,
  matched,
  issues,
  downloading,
  pendingWid,
  pendingTitle,
  canSubscribe,
  acquireVia,
  onSubscribe,
  mods,
  onShowIssue,
  dragging,
  style,
  nodeRef,
  dragProps,
  onSelect,
  onActivate,
  onMenu,
}) {
  const pending = !mod && !!pendingWid && !downloading;
  const cls =
    'row' +
    (selected ? ' selected' : '') +
    (dependency ? ' dependency' : '') +
    (dependent ? ' dependent' : '') +
    (conflictNames ? ' conflict' : '') +
    (dimmed ? ' dimmed' : '') +
    (matched ? ' match' : '') +
    (downloading ? ' downloading' : '') +
    (pending ? ' pending' : '') +
    (dragging ? ' dragging' : '');
  const notes = [
    outdated && `Outdated: supports ${mod.supportedVersions.join(', ')} only`,
    dependency && 'Required by the selected mod',
    dependent && 'Requires the selected mod',
    conflictNames && `Incompatible with: ${conflictNames.join(', ')}`,
  ].filter(Boolean);
  return (
    <div
      ref={nodeRef}
      className={cls}
      style={style}
      title={(mod ? `${mod.name}\n${mod.packageId}` : pendingTitle ? `${pendingTitle}\n${id}` : id) + notes.map((t) => `\n${t}`).join('')}
      // toggle only on a single click: a double-click's second click (detail 2)
      // must not undo the first, so the activated row stays selected.
      onClick={(e) => onSelect(id, e.detail === 1)}
      onDoubleClick={() => onActivate(id)}
      onContextMenu={(e) => onMenu(e, id)}
      {...dragProps}
    >
      <RowLabel
        id={id}
        mod={mod}
        color={color}
        outdated={outdated}
        conflict={!!conflictNames}
        downloading={downloading}
        pending={!!pendingWid}
        title={pendingTitle}
      />
      {issues && <RowIssues issues={issues} mods={mods} onShowIssue={onShowIssue} />}
      {pending && (
        // Same handler and eligibility as the context menu's Subscribe (only
        // rendered while not downloading). Its events stay off the row: no
        // select/activate, and no drag start.
        <button
          className="accent-outline row-subscribe"
          disabled={!canSubscribe}
          title={
            usesSteamCmd(acquireVia)
              ? 'Download this mod with SteamCMD'
              : canSubscribe
                ? 'Subscribe on Steam and download this mod'
                : "Steam isn't available (not a Steam install, or the Steamworks library didn't load)"
          }
          onClick={(e) => {
            e.stopPropagation();
            onSubscribe(id);
          }}
          onDoubleClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
        >
          Subscribe
        </button>
      )}
    </div>
  );
}

// Warning triangle, then red cross (rightmost), each shown only when the mod
// has an issue of that severity. Tooltip: one line per issue of that severity;
// click opens the issues window on the first of them.
function RowIssues({ issues, mods, onShowIssue }) {
  const icon = (severity, glyph) => {
    const list = issues.filter((i) => i.severity === severity);
    if (!list.length) return null;
    const open = (e) => {
      e.stopPropagation();
      onShowIssue(list[0].key);
    };
    return (
      <span
        className={`row-issue ${severity}`}
        title={list.map((i) => issueSummary(i, mods)).join('\n')}
        onClick={open}
        onDoubleClick={(e) => e.stopPropagation()}
      >
        {glyph}
      </span>
    );
  };
  return (
    <span className="row-issues">
      {icon('warning', '\u26A0\uFE0E')}
      {icon('error', '\u2715')}
    </span>
  );
}

function Row({ top, ...rest }) {
  return <RowView {...rest} style={{ top, height: ROW_HEIGHT - ROW_GAP }} />;
}

function SortableRow({ id, top, ...rest }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  return (
    <RowView
      {...rest}
      id={id}
      nodeRef={setNodeRef}
      dragProps={{ ...attributes, ...listeners }}
      dragging={isDragging}
      style={{ top, height: ROW_HEIGHT - ROW_GAP, transform: CSS.Translate.toString(transform), transition }}
    />
  );
}
