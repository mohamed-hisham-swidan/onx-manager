# ONX Manager Desktop App

Lightweight Electron wrapper around ONX Manager (`v0.1.0`) designed with strict resource hygiene:

- **Single window + system tray** (`Open`, `Switch Connection`, `Restart Local Backend`, `Quit`)
- **Zero duplicated frontend code** — serves the standard ONX React SPA directly
- **Dual connection modes**:
  1. **Local Mode (Default)**: Silently starts and supervises your local Python 3.12 ONX backend in the background (no console popups), waits for `/health`, and loads the GUI directly (`ONX_DEPLOYMENT_PROFILE=local`).
  2. **Remote Mode**: Connect to any VPS or friend's shared ONX Manager URL (including Cloudflare Tunnels). Stops any unused local backend automatically to free RAM/CPU.

## Prerequisites

For **Local Mode**, install the local backend environment first using the repository root installer (`./install.sh --mode=local` on Linux/macOS or `.\install.ps1` on Windows). For **Remote Mode** only, no local Python runtime is needed.

## Running & Testing

```bash
cd desktop
npm install
npm run lint     # Syntax checks across all main/preload/helper/setup scripts
npm test         # Unit tests via Node's built-in test runner
npm start        # Self-heals Electron binary if needed and launches the desktop shell
```

Or launch directly from the repository root (auto-installs `desktop/` packages if missing):

```bash
npm run desktop
```

### Automatic Electron Self-Healing & npm `allowScripts`

Modern npm versions block package `postinstall` scripts (including `electron`'s binary installer) unless approved via `allowScripts`. Even if `node_modules/electron/dist` or `path.txt` is missing after `npm install`, `npm start` / `npm run dev` runs `scripts/ensure-electron.js` via `prestart`/`predev` to automatically restore the binary via `install.js` or cached archive extraction and verify POSIX execute permissions.

If `desktop/node_modules` lives on a filesystem mounted with `noexec` (`EACCES`), `ensure-electron.js` prints instructions to copy `dist/` to an executable folder and set `ELECTRON_OVERRIDE_DIST_PATH`.

Press `Ctrl+Shift+K` (`Cmd+Shift+K` on macOS) or select **Switch Connection** from the system tray menu at any time to switch between Local Mode and saved Remote servers.

## Packaging Installers

```bash
cd desktop
npm run build:win     # Windows NSIS installer (.exe) in desktop/dist/
npm run build:linux   # Linux AppImage in desktop/dist/
```
