// Settings window (SCOPE.md §3): same modal family as ValidationWindow, with
// horizontal tabs. General holds the path fields + Browse + Autodetect that
// used to live in PathsBar; Steam holds the "Download mods via" choice - the
// three exclusive mod-acquisition modes (SCOPE.md §2a, settings.json
// steamAcquireVia; 'gog' is auto-picked for a GOG install until the user
// chooses, acquireAuto), then Check for missing Workshop mods
// (re-downloads the active list's not-found Workshop rows); Troubleshooting has Open log file
// (<appRoot>/volt.log, electron/lib/log.js) and Open previous log file (the
// previous run's volt.log.prev; disabled when there isn't one).
// Mods folder is always <game folder>/Mods, so it has no Browse.
import { useEffect, useState } from 'react';

const TABS = ['General', 'Steam', 'Troubleshooting'];
const SOURCE_LABEL = { steam: 'Steam', gog: 'GOG', manual: 'Manual' };
// [mode, label, tooltip]
const ACQUIRE_OPTIONS = [
  [
    'steamcmd',
    'SteamCMD, then sync to Steam (recommended)',
    'Downloads with SteamCMD into the Mods folder, so a mod works right away; Sync to Steam later subscribes it on Steam and removes the copy.',
  ],
  ['steamworks', 'Steam client directly', "Subscribes through the Steam client; Steam downloads the mod into its own Workshop folder. Nothing goes into the Mods folder."],
  [
    'gog',
    'SteamCMD, keep in Mods (GOG)',
    'Downloads with SteamCMD into the Mods folder and keeps it there for good: never synced to Steam. Chosen automatically for a GOG install.',
  ],
];

export default function SettingsWindow({
  paths,
  busy,
  acquireVia,
  acquireAuto,
  onSetAcquireVia,
  checkingMissing,
  onCheckMissing,
  onAutodetect,
  onBrowse,
  logPath,
  prevLogPath,
  onOpenPath,
  onClose,
}) {
  const [tab, setTab] = useState('General');
  const p = paths || {};

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
      <div className="modal settings-window" role="dialog" aria-label="Settings">
        <header className="validation-head">
          <h2>Settings</h2>
          <button onClick={onClose}>Close</button>
        </header>
        <nav className="settings-tabs" role="tablist">
          {TABS.map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={t === tab}
              className={'settings-tab' + (t === tab ? ' selected' : '')}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </nav>
        <section className="settings-panel" role="tabpanel">
          {tab === 'General' ? (
            <>
              <PathRow
                label="Game folder"
                value={p.gameDir}
                tag={SOURCE_LABEL[p.gameSource]}
                busy={busy}
                onBrowse={() => onBrowse('game')}
              />
              <PathRow label="Local mods" value={p.modsDir} />
              <PathRow label="Config folder" value={p.configDir} busy={busy} onBrowse={() => onBrowse('config')} />
              <div className="button-row">
                <button onClick={onAutodetect} disabled={busy}>
                  Autodetect paths
                </button>
              </div>
            </>
          ) : tab === 'Steam' ? (
            <>
              {/* wraps: three options (plus the GOG note) can outgrow the window's width */}
              <div className="path-row" role="radiogroup" aria-label="Download mods via" style={{ flexWrap: 'wrap' }}>
                <span className="muted">Download mods via:</span>
                {ACQUIRE_OPTIONS.map(([value, label, hint]) => (
                  <label key={value} title={hint}>
                    <input
                      type="radio"
                      name="steam-acquire-via"
                      checked={acquireVia === value}
                      onChange={() => onSetAcquireVia(value)}
                    />{' '}
                    {label}
                  </label>
                ))}
                {acquireAuto && acquireVia === 'gog' && <span className="muted">(chosen automatically: GOG install)</span>}
              </div>
              <div className="button-row">
                <button
                  onClick={onCheckMissing}
                  disabled={checkingMissing}
                  title="Download every mod in the active list that isn't found on disk but has a Workshop id, via the method chosen above"
                >
                  {checkingMissing ? 'Checking...' : 'Check for missing Workshop mods'}
                </button>
              </div>
            </>
          ) : (
            <div className="button-row">
              <button onClick={() => onOpenPath(logPath)} disabled={!logPath} title={logPath || undefined}>
                Open log file
              </button>
              <button
                onClick={() => onOpenPath(prevLogPath)}
                disabled={!prevLogPath}
                title={prevLogPath || 'No previous log yet (created on the next launch)'}
              >
                Open previous log file
              </button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function PathRow({ label, value, tag, busy, onBrowse }) {
  return (
    <div className="path-row">
      <span className="path-label">{label}</span>
      <span className={value ? 'path-value' : 'path-value unset'} title={value || ''}>
        {value || 'Not found'}
      </span>
      {tag && <span className="tag">{tag}</span>}
      {onBrowse && (
        <button onClick={onBrowse} disabled={busy}>
          Browse...
        </button>
      )}
    </div>
  );
}
