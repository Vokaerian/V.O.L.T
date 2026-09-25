// Plain log at <appRoot>/volt.log, so a crash (and dev-mode auto-restart)
// leaves something to read. One level of rotation: each initLog() moves the
// previous run's volt.log to volt.log.prev (replacing any older one), then
// starts a fresh file. A previous run that logged nothing but its own startup
// header (e.g. a dev-mode auto-restart moments after the last one) is just
// deleted instead, so .prev keeps the last run that actually did something.
// Never throws: a failed rotation just keeps appending.
const fs = require('node:fs');
const path = require('node:path');

let file = null; // unset until initLog: log() is then a no-op (e.g. check harnesses)

function log(message) {
  if (!file) return;
  try {
    fs.appendFileSync(file, `[${new Date().toISOString()}] ${message}\n`);
  } catch {
    // logging must never crash or block the app
  }
}

function initLog(appRoot) {
  file = path.join(appRoot, 'volt.log');
  let rotateError = null;
  try {
    if (fs.existsSync(file)) {
      const lines = fs.readFileSync(file, 'utf8').split('\n').filter((l) => l.trim());
      if (lines.length > 1) {
        // rm first: renameSync onto an existing file isn't a silent overwrite everywhere.
        fs.rmSync(`${file}.prev`, { force: true });
        fs.renameSync(file, `${file}.prev`);
      } else {
        fs.rmSync(file, { force: true }); // header-only (or empty): leave .prev alone
      }
    }
  } catch (err) {
    rotateError = err && err.message ? err.message : String(err);
  }
  try {
    const { version } = require('../../package.json');
    fs.appendFileSync(file, `=== VOLT started, v${version}, ${new Date().toISOString()} ===\n`);
  } catch {
    // see log()
  }
  if (rotateError) log(`log rotation failed, appending to the existing log instead: ${rotateError}`);
  return file;
}

// JSON of any value, capped at `max` chars so one huge argument (a pasted mod
// list, a data URL) can't make a single log line enormous.
function clip(value, max = 4000) {
  let s;
  try {
    s = typeof value === 'string' ? value : JSON.stringify(value);
  } catch {
    s = String(value);
  }
  if (s === undefined) s = 'undefined';
  return s.length > max ? `${s.slice(0, max)}…[truncated, ${s.length} chars total]` : s;
}

// What main.js's IPC wrapper logs for a call's arguments / its result.
// Clipboard contents and pasted mod-list text are user data, not app detail:
// only their length is logged. A few big results get a summary instead.
const chars = (v) => (typeof v === 'string' ? `<${v.length} chars>` : clip(v));
const ARG_SUMMARY = {
  'clipboard:writeText': (args) => `[${args.map(chars).join(',')}]`,
  'modList:importText': (args) => `[${args.map(chars).join(',')}]`,
};
const RESULT_SUMMARY = {
  'clipboard:readText': chars,
  'mods:scan': (v) => `${v.mods.length} mods, ${v.problems.length} problems`,
  'mods:preview': (v) => (v ? `image data URL, ${v.length} chars` : 'no preview'),
  'communityRules:get': (v) => `${Object.keys(v.rules).length} rules (${v.source})`,
};
function ipcArgsText(channel, args) {
  return ARG_SUMMARY[channel] ? ARG_SUMMARY[channel](args) : clip(args);
}
function ipcResultText(channel, value) {
  try {
    return RESULT_SUMMARY[channel] ? RESULT_SUMMARY[channel](value) : clip(value);
  } catch {
    return clip(value);
  }
}

module.exports = { initLog, log, clip, ipcArgsText, ipcResultText, logPath: () => file };
