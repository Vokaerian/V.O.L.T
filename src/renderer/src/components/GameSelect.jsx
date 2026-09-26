const GAMES_ROW_1 = [
  { key: 'rimworld', name: 'RimWorld', initials: 'RW', enabled: true },
  { key: 'zomboid', name: 'Project Zomboid', initials: 'PZ', enabled: false },
  { key: 'lethal', name: 'Lethal Company', initials: 'LC', enabled: false },
  { key: 'valheim', name: 'Valheim', initials: 'VH', enabled: false },
];
const GAMES_ROW_2 = [
  { key: 'sts2', name: 'Slay the Spire 2', initials: 'S2', enabled: false },
  { key: 'repo', name: 'R.E.P.O.', initials: 'RP', enabled: false },
  { key: 'palworld', name: 'Palworld', initials: 'PW', enabled: false },
];

export default function GameSelect({ onSelect }) {
  return (
    <div className="game-select">
      <div className="game-select-header">
        <h1>V. O. L. T.</h1>
        <div className="game-select-accent-bar" />
        <div className="game-select-subtitle">Vokaerian's Omni-game Load-order Tool</div>
      </div>
      <div className="game-select-caption">Select a game</div>
      <div className="game-select-grid">
        <div className="game-select-row">
          {GAMES_ROW_1.map((g) => (
            <GameTile key={g.key} game={g} onSelect={onSelect} />
          ))}
        </div>
        <div className="game-select-row">
          {GAMES_ROW_2.map((g) => (
            <GameTile key={g.key} game={g} onSelect={onSelect} />
          ))}
        </div>
      </div>
    </div>
  );
}

function GameTile({ game, onSelect }) {
  return (
    <button
      type="button"
      className={`game-tile ${game.enabled ? 'enabled' : 'disabled'}`}
      disabled={!game.enabled}
      onClick={game.enabled ? () => onSelect(game.key) : undefined}
    >
      <div className="game-tile-cover">
        <span className="game-tile-initials">{game.initials}</span>
        <span className="game-tile-cover-tag">Cover art — placeholder</span>
      </div>
      <div className="game-tile-label">{game.name}</div>
      {!game.enabled && (
        <div className="game-tile-scrim">
          <span className="game-tile-badge">Coming soon</span>
        </div>
      )}
    </button>
  );
}
