"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("onxDesktop", {
  getState: () => ipcRenderer.invoke("desktop:get-state"),
  connectLocal: () => ipcRenderer.invoke("desktop:connect-local"),
  connectRemote: (payload) => ipcRenderer.invoke("desktop:connect-remote", payload),
  probeRemote: (url) => ipcRenderer.invoke("desktop:probe-remote", url),
  deleteRemote: (id) => ipcRenderer.invoke("desktop:delete-remote", id),
  restartBackend: () => ipcRenderer.invoke("desktop:restart-backend"),
  openLauncher: () => ipcRenderer.invoke("desktop:open-launcher"),
  getBackendLogs: () => ipcRenderer.invoke("desktop:get-backend-logs"),
  onStatusChange: (cb) => {
    if (typeof cb !== "function") return () => {};
    const listener = (_event, payload) => cb(payload);
    ipcRenderer.on("desktop:status-change", listener);
    return () => ipcRenderer.removeListener("desktop:status-change", listener);
  },
});
