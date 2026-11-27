# Changelog

All notable changes to ONX Manager are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-26

Initial public release of **ONX Manager**.

### Added

- **Server Creation & Lifecycle Management**: Create, import (directory scan or `.zip` upload), start, stop, restart, and delete Minecraft servers across **Vanilla, Paper (Fill v3), Spigot, Purpur, Fabric, Forge, NeoForge, and Quilt** with live step/ETA provisioning telemetry, deterministic Java runtime selection, `spawn-protection=0` default, companion port publishing, and non-destructive provisioning retry.
- **Hardened Docker Runtime**: Containerized Minecraft execution with `--cap-drop=ALL`, `--security-opt=no-new-privileges:true`, `--pids-limit`, non-root UID/GID mapping, `/data`-only bind mounts, loopback-only RCON, memory/CPU caps, host resource budget admission control (`GET /api/v1/monitoring/host-resources`), multi-worker lifecycle leases, and opt-in Docker-outside-of-Docker (DooD) support.
- **Simple & Advanced Git-Backed Server Modes**:
  - **Simple Mode** for zero-friction server hosting with fast configuration management.
  - **Advanced Mode** (Linux/macOS) with per-server Git repositories, working branches, protected `main`, structured 3-way config merges (`YAML`, `TOML`, `JSON`, `.properties`), encrypted live-data snapshots, `${ONX_SECRET_*}` secret vault with automatic secret scanning, isolated branch test containers, GitHub sync/webhooks, and live **Simple ↔ Advanced** conversion.
- **1-Click Safe Upgrades & 5-Check Health Gate**: Modrinth compatibility verification across installed plugins/mods with transitive dependency checking, pre-upgrade pinned rollback backups, a 5-check verification gate (startup log readiness, live Minecraft SLP status & version check, RCON world flush, `level.dat` integrity check, and optional public reachability check), and automatic rollback on failure.
- **Plugins, Mods & Modpacks**:
  - In-shell Modrinth marketplace and project detail pages with strict **Plugins** vs **Mods** separation and dual `Plugin · Mod` project support.
  - Modrinth-style Game Version + Loader pickers, deterministic version matching, 2-option dependency installation, universal `.jar` upload validation, and `.mrpack` / CurseForge modpack archive import for modded servers.
- **Live Console, Telemetry & Change History**: WebSocket live console streaming (`stdout` + `stderr` deduplicated) with interactive RCON execution, real-time CPU/RAM/MSPT→TPS/player metrics, Prometheus `/metrics`, configurable alert rules, and branch-aware server Change History.
- **Sandboxed File & Log Manager**: Directory browsing, live-state inspection, syntax-highlighted editor, upload/download, and strict symlink/path-traversal protection.
- **Encrypted Backups & Scheduling**: Local snapshots and chunked AES-256-GCM envelope-encrypted archives with SHA-256 verification, upgrade-pinned delete protection, local or S3-compatible storage, and cron-scheduled automation.
- **Network Exposure**: Built-in **Playit.gg** tunnel management, **Cloudflare Named & Quick Tunnels**, **UPnP** port forwarding with CGNAT detection, per-branch exposure isolation, and SSRF-safe live Minecraft SLP reachability probing.
- **Security & Zero-Trust Access Control**: Username-based GUI `/setup` (`LOCAL` or invite-only `GLOBAL`), passwordless loopback `local` desktop mode with fail-closed password gating before external tunnels or `0.0.0.0` binding, RS256 JWT, Argon2id passwords, scoped `onx_` API keys, and RBAC/ABAC verified across **217 live routes** (`contracts/permissions.yaml`).
- **Frontend Web Panel & Electron Desktop App**:
  - React 19 + TypeScript 5.5 + Tailwind CSS v4 SPA with semantic design tokens, multi-skin theming with WCAG AA contrast checks, and unified `AppShell` / `ServerShell` navigation.
  - Lightweight Electron desktop shell (`desktop/`) with launcher-scoped IPC security, Local backend auto-supervision, and Remote VPS switcher (`Ctrl+Shift+K`).
- **Native Installers & CLI**: Cross-platform `install.sh` (VPS `systemd` or Local Desktop), `install.ps1` (Windows), `onx` CLI, and `launcher.py` with Python 3.12 environment handling and Alembic schema compatibility verification (`b1e2100000034`).
