// Header row 1 (SCOPE.md §3), one row: Settings (opens SettingsWindow),
// Game/Mods/Config as plain links that open the folder, storefront tag,
// VOLT version. Mods folder is always <game>/Mods.

const SOURCE_LABEL = { steam: 'Steam', gog: 'GOG', manual: 'Manual' };

export default function PathsBar({ paths, appVersion, onOpenPath, onSettings }) {
  const p = paths || {};
  const link = (label, value, cls = '') => (
    <button
      className={'path-link ' + cls}
      disabled={!value}
      title={value || `${label} folder not set`}
      onClick={() => onOpenPath(value)}
    >
      {label}
    </button>
  );
  return (
    <div className="paths-bar">
      <div className="header-row">
        <button className="settings-btn" onClick={onSettings}>
          Settings
        </button>
        <span className="muted">Paths:</span>
        {link('Game', p.gameDir)}
        <span className="muted">/</span>
        {link('Mods', p.modsDir)}
        <span className="muted">/</span>
        {link('Config', p.configDir, 'path-link-last')}
        {SOURCE_LABEL[p.gameSource] && <span className="tag">{SOURCE_LABEL[p.gameSource]}</span>}
        {appVersion && <span className="muted">V. O. L. T. v{appVersion}</span>}
      </div>
    </div>
  );
}
