'use strict';
// Preload (sandboxed): exposes the IPC API to the renderer as window.volt.
// Each method resolves to the handler's value or rejects with its message
// (onSteamCmdProgress is the one push subscription: main -> renderer events).

const { contextBridge, ipcRenderer } = require('electron');

async function call(channel, ...args) {
  const res = await ipcRenderer.invoke(channel, ...args);
  if (!res || !res.ok) throw new Error(res && res.error ? res.error : `IPC call ${channel} failed`);
  return res.value;
}

contextBridge.exposeInMainWorld('volt', {
  getAppInfo: () => call('app:info'),
  log: (message) => call('log:write', message),
  getSettings: () => call('settings:get'),
  getPaths: () => call('paths:get'),
  autodetectPaths: () => call('paths:autodetect'),
  browsePath: (kind) => call('paths:browse', kind),
  scanMods: () => call('mods:scan'),
  getModPreview: (modDir) => call('mods:preview', modDir),
  setModColor: (id, color) => call('settings:setModColor', id, color),
  setScanIssueIgnored: (p, ignored) => call('settings:setScanIssueIgnored', p, ignored),
  setSteamAcquireVia: (via) => call('settings:setSteamAcquireVia', via),
  copyText: (text) => call('clipboard:writeText', text),
  readClipboard: () => call('clipboard:readText'),
  importModListText: (text) => call('modList:importText', text),
  importModListFile: (kind) => call('modList:importFile', kind),
  importModListFromRentry: (url) => call('modList:importRentry', url),
  exportModListFile: (activeIds) => call('modList:exportFile', activeIds),
  publishRentryList: (text) => call('modList:publishRentry', text),
  openPath: (p) => call('shell:openPath', p),
  openExternal: (url) => call('shell:openExternal', url),
  launchGame: () => call('game:launch'),
  steamAvailable: () => call('steam:available'),
  steamSubscribe: (id) => call('steam:subscribe', id),
  steamUnsubscribe: (id) => call('steam:unsubscribe', id),
  steamInstallInfo: (id) => call('steam:installInfo', id),
  steamIsSubscribed: (id) => call('steam:isSubscribed', id),
  steamWorkshopItem: (id) => call('steam:workshopItem', id),
  steamRelease: (id) => call('steam:release', id),
  steamDeleteItemFolder: (id) => call('steam:deleteItemFolder', id),
  steamResolveCollection: (input) => call('steam:resolveCollection', input),
  steamWorkshopTitles: (ids) => call('steam:workshopTitles', ids),
  steamCmdDownload: (ids, mode) => call('steamcmd:download', ids, mode),
  steamCmdCancel: () => call('steamcmd:cancel'),
  // Live SteamCMD download events (main.js sendProgress); returns an unsubscribe.
  onSteamCmdProgress: (cb) => {
    const fn = (_e, payload) => cb(payload);
    ipcRenderer.on('steamcmd:progress', fn);
    return () => ipcRenderer.removeListener('steamcmd:progress', fn);
  },
  steamCmdDeleteItem: (modPath) => call('steamcmd:deleteItem', modPath),
  readModsConfig: () => call('modsConfig:read'),
  pushModsConfig: (activeIds) => call('modsConfig:push', activeIds),
  listLoadOrders: () => call('loadOrders:list'),
  createLoadOrder: (name, lists) => call('loadOrders:create', name, lists),
  loadLoadOrder: (slug) => call('loadOrders:load', slug),
  saveLoadOrder: (slug, lists) => call('loadOrders:save', slug, lists),
  getCommunityRules: () => call('communityRules:get'),
});
