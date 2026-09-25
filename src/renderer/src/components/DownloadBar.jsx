// SteamCMD download row, right of the status text in the status bar (PLAN.md
// item 4, "Download progress & control"). Shown while a SteamCMD download is
// in flight or paused (App.jsx dl state). Left to right: pause/resume button,
// label, progress pill (overall: finished items + the current item's
// fraction), done/total counter, speed, and a warning icon when an item failed
// (native title = which and why; not reliably keyboard-reachable, accepted).

function formatSpeed(bps) {
  if (bps == null || !Number.isFinite(bps)) return '-';
  if (bps >= 1024 * 1024) return `${(bps / (1024 * 1024)).toFixed(1)} MB/s`;
  return `${Math.round(bps / 1024)} KB/s`;
}

export default function DownloadBar({ dl, titles, onToggle }) {
  const total = dl.wids.length;
  const completed = dl.done.length;
  const curFrac = dl.cur && !dl.done.includes(dl.cur.id) ? dl.cur.percent / 100 : 0;
  const percent = total ? Math.min(100, ((completed + curFrac) / total) * 100) : 0;
  const failures = Object.entries(dl.failed);
  const label = dl.paused ? 'Resume download' : 'Pause download';
  return (
    <div className="dl-bar">
      <button className="dl-btn" onClick={onToggle} disabled={dl.pausing} aria-label={label} title={label}>
        <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          {dl.paused ? (
            <path d="M4 2.5v11l10-5.5z" />
          ) : (
            <>
              <rect x="3" y="2" width="3.5" height="12" rx="1.25" />
              <rect x="9.5" y="2" width="3.5" height="12" rx="1.25" />
            </>
          )}
        </svg>
      </button>
      <span>{dl.paused ? 'Paused' : 'Downloading...'}</span>
      <div className="dl-track" role="progressbar" aria-label="SteamCMD download progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(percent)}>
        <div className="dl-fill" style={{ width: `${percent}%` }} />
      </div>
      <span className="mono dl-num">
        {completed} / {total}
      </span>
      <span className="mono dl-num dl-speed">{dl.paused ? '-' : formatSpeed(dl.cur?.speed)}</span>
      {failures.length > 0 && (
        <span
          className="dl-warn"
          role="img"
          aria-label={`${failures.length} download${failures.length === 1 ? '' : 's'} failed`}
          title={failures.map(([wid, why]) => `${titles.get(wid) || `Workshop item ${wid}`}: ${why}`).join('\n')}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M8 1.75L15 14H1z" />
            <path d="M8 6.25v3.5" />
            <path d="M8 11.9v.1" />
          </svg>
        </span>
      )}
    </div>
  );
}
