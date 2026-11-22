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
npm run lint     # Syntax checks across all main/preload/helper scripts
npm test         # Unit tests via Node's built-in test runner
npm start        # Launch the Electron desktop shell
```

Press `Ctrl+Shift+K` (`Cmd+Shift+K` on macOS) or use **Connection → Switch Connection** at any time to switch between Local Mode and saved Remote servers.

## Packaging Installers

```bash
cd desktop
npm run build:win     # Windows NSIS installer (.exe) in desktop/dist/
npm run build:linux   # Linux AppImage in desktop/dist/
```
