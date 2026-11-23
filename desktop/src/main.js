"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { app, BrowserWindow, Menu, Tray, ipcMain, nativeImage, shell } = require("electron");

const { LocalBackendManager, probePanelEndpoint } = require("./backendManager");
const {
  loadStore,
  removeRemote,
  setActiveTarget,
  upsertRemote,
} = require("./connectionsStore");

// Disable unused heavy background features to keep memory footprint lean.
app.commandLine.appendSwitch("disable-background-timer-throttling");
app.commandLine.appendSwitch("disable-features", "HardwareMediaKeyHandling");

let mainWindow = null;
let tray = null;
let backendManager = null;
let isQuitting = false;
let activeTarget = { mode: "launcher", url: null, label: "Connection Launcher" };

function getStorePath() {
  return path.join(app.getPath("userData"), "connections.json");
}

function getBrandIconPath(relativePath = null) {
  const target = relativePath || (process.platform === "win32" ? "icon.ico" : "icon.png");
  const candidateDirs = [];
  if (app.isPackaged && process.resourcesPath) {
    candidateDirs.push(path.join(process.resourcesPath, "app.asar.unpacked", "assets"));
  }
  candidateDirs.push(path.resolve(__dirname, "..", "assets"));

  for (const assetsDir of candidateDirs) {
    const preferred = path.join(assetsDir, target);
    if (fs.existsSync(preferred)) {
      return preferred;
    }
  }
  return path.join(candidateDirs[candidateDirs.length - 1], "icon.svg");
}

function createWindow() {
  const iconPath = getBrandIconPath();
  const windowIcon = nativeImage.createFromPath(iconPath);
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    title: "ONX Manager",
    icon: windowIcon.isEmpty() ? iconPath : windowIcon,
    autoHideMenuBar: true,
    backgroundColor: "#0b0e14",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
      backgroundThrottling: true,
    },
  });

  mainWindow.setMenuBarVisibility(false);
  if (typeof mainWindow.removeMenu === "function") {
    mainWindow.removeMenu();
  }

  mainWindow.once("ready-to-show", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show();
    }
  });

  mainWindow.webContents.on("before-input-event", (event, input) => {
    if (input.type !== "keyDown") return;
    const mod = input.control || input.meta;
    const key = String(input.key || "").toLowerCase();
    if (mod && input.shift && key === "k") {
      event.preventDefault();
      loadLauncherScreen();
    } else if (mod && !input.shift && key === "r") {
      event.preventDefault();
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.reload();
      }
    } else if (key === "f12" || (mod && input.shift && key === "i")) {
      event.preventDefault();
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.toggleDevTools();
      }
    } else if (mod && key === "q") {
      event.preventDefault();
      isQuitting = true;
      app.quit();
    }
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http://") || url.startsWith("https://")) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });

  mainWindow.on("close", (event) => {
    if (!isQuitting && tray) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  return mainWindow;
}

function buildTray() {
  const trayPath =
    process.platform === "linux"
      ? getBrandIconPath(path.join("icons", "32x32.png"))
      : getBrandIconPath();
  let icon = nativeImage.createFromPath(trayPath);
  if (icon.isEmpty()) {
    icon = nativeImage.createEmpty();
  } else {
    icon = icon.resize({ width: 32, height: 32, quality: "best" });
  }
  tray = new Tray(icon);
  tray.setToolTip("ONX Manager");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      {
        label: "Open ONX Manager",
        click: () => {
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.show();
            mainWindow.focus();
          }
        },
      },
      {
        label: "Switch Connection (Local / Remote)...",
        click: () => {
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.show();
            mainWindow.focus();
          }
          loadLauncherScreen();
        },
      },
      {
        label: "Restart Local Backend",
        click: () => restartLocalBackend(),
      },
      { type: "separator" },
      {
        label: "Quit ONX Manager",
        click: () => {
          isQuitting = true;
          app.quit();
        },
      },
    ]),
  );
  tray.on("click", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

function broadcastStatus() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("desktop:status-change", {
      backend: backendManager ? backendManager.getSnapshot() : null,
      target: activeTarget,
    });
  }
}

async function loadLauncherScreen() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  activeTarget = { mode: "launcher", url: null, label: "Connection Launcher" };
  await mainWindow.loadFile(path.join(__dirname, "launcher.html"));
  broadcastStatus();
}

async function connectLocal() {
  const snap = await backendManager.start();
  setActiveTarget(getStorePath(), "local", null);
  activeTarget = { mode: "local", url: snap.url, label: "Local Panel" };
  if (mainWindow && !mainWindow.isDestroyed() && snap.url) {
    await mainWindow.loadURL(snap.url);
  }
  broadcastStatus();
  return snap;
}

async function connectRemote({ id, name, url }) {
  const probe = await probePanelEndpoint(url);
  if (!probe.ok) {
    throw new Error(probe.error || "Unable to reach remote ONX Manager panel.");
  }
  const { store, entry } = upsertRemote(getStorePath(), { id, name, url: probe.url });
  setActiveTarget(getStorePath(), "remote", entry.id);
  // Stop local backend when connecting remotely to minimize RAM/CPU footprint.
  await backendManager.stop();
  activeTarget = { mode: "remote", url: entry.url, label: entry.name };
  if (mainWindow && !mainWindow.isDestroyed()) {
    await mainWindow.loadURL(entry.url);
  }
  broadcastStatus();
  return { entry, store, probe };
}

async function restartLocalBackend() {
  const snap = await backendManager.restart();
  if (activeTarget.mode === "local" && mainWindow && !mainWindow.isDestroyed() && snap.url) {
    await mainWindow.loadURL(snap.url);
  }
  broadcastStatus();
  return snap;
}

function registerIpc() {
  ipcMain.handle("desktop:get-state", () => ({
    store: loadStore(getStorePath()),
    backend: backendManager.getSnapshot(),
    target: activeTarget,
    version: app.getVersion(),
  }));

  ipcMain.handle("desktop:connect-local", () => connectLocal());
  ipcMain.handle("desktop:connect-remote", (_evt, payload) => connectRemote(payload));
  ipcMain.handle("desktop:probe-remote", (_evt, url) => probePanelEndpoint(url));
  ipcMain.handle("desktop:delete-remote", (_evt, id) => removeRemote(getStorePath(), id));
  ipcMain.handle("desktop:restart-backend", () => restartLocalBackend());
  ipcMain.handle("desktop:open-launcher", () => loadLauncherScreen());
  ipcMain.handle("desktop:get-backend-logs", () => backendManager.getLogs());
}

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    if (process.platform === "linux" && typeof app.setDesktopName === "function") {
      app.setDesktopName("onx-manager.desktop");
    }
    backendManager = new LocalBackendManager({
      onStatusChange: () => broadcastStatus(),
    });
    registerIpc();
    Menu.setApplicationMenu(null);
    buildTray();
    createWindow();

    await loadLauncherScreen();

    // Auto-start default Local mode unless user explicitly opens switcher
    const store = loadStore(getStorePath());
    if (store.lastMode === "local" && !process.argv.includes("--chooser")) {
      connectLocal().catch(() => {
        // Error state + logs remain visible in launcher.html
        broadcastStatus();
      });
    }
  });

  app.on("before-quit", async (event) => {
    if (backendManager && backendManager.child) {
      event.preventDefault();
      isQuitting = true;
      try {
        await backendManager.stop();
      } finally {
        app.exit(0);
      }
    }
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
      isQuitting = true;
      app.quit();
    }
  });
}
