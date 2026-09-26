import rimworldCover from '../assets/covers/rimworld.jpg';
import zomboidCover from '../assets/covers/zomboid.jpg';
import lethalCover from '../assets/covers/lethal.jpg';
import valheimCover from '../assets/covers/valheim.jpg';
import sts2Cover from '../assets/covers/sts2.jpg';
import repoCover from '../assets/covers/repo.jpg';
import palworldCover from '../assets/covers/palworld.jpg';

const GAMES = [
  { key: 'rimworld', name: 'RimWorld', cover: rimworldCover, enabled: true },
  { key: 'zomboid', name: 'Project Zomboid', cover: zomboidCover, enabled: false },
  { key: 'lethal', name: 'Lethal Company', cover: lethalCover, enabled: false },
  { key: 'valheim', name: 'Valheim', cover: valheimCover, enabled: false },
  { key: 'sts2', name: 'Slay the Spire 2', cover: sts2Cover, enabled: false },
  { key: 'repo', name: 'R.E.P.O.', cover: repoCover, enabled: false },
  { key: 'palworld', name: 'Palworld', cover: palworldCover, enabled: false },
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
        {GAMES.map((g) => (
          <GameTile key={g.key} game={g} onSelect={onSelect} />
        ))}
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
        <img src={game.cover} alt="" className="game-tile-cover-image" />
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
