# Changelog

All notable changes to ONX Manager are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-07

### Added

- **Multi-Runtime Server Management**: Create, import (directory scan or `.zip` upload), start, stop, restart, and delete Minecraft servers across **Vanilla, Paper, Spigot, Purpur, Fabric, Forge, and NeoForge** with automatic JAR/installer provisioning and retry support.
- **Execution Providers**: Cross-platform process execution via `LocalLinuxProvider` (tmux), `LocalWindowsProvider` (native Win32 detached process groups), and `DockerProvider` (isolated containers with bridge networking, dynamic IP inspection, loopback RCON, and opt-in Docker-outside-of-Docker support).
- **Git-Inspired Versioning & Branch Runtime**:
  - Immutable commits, multi-parent merge DAG (`server_commit_parents`), branches (`created` / `active` / `archived`), symbolic tags (`server_tags`), and deterministic tree/commit diffing.
  - Configurable branch protection policies (`require_test_pass`, `allow_direct_commit`, `allow_force_bypass`, `prevent_deletion`) with emergency bypass auditing.
  - Atomic filesystem worktree materializations (`readonly` and `edit` modes) and uncommitted live-change import reviews.
  - Database-backed concurrent admission control (`RuntimeAdmissionScheduler`) with host RAM/CPU headroom verification.
  - Reusable test definitions (`TestDefinition`), isolated test runs with `SmokeTestVerifier`, `FakePlayerVerifier`, and `MineflayerVerifier`, automated crash pattern correlation with mod blame, and structured evidence bundles.
- **Multi-Step Operations Engine**: Asynchronous `Operation` aggregate with step progress tracking, cooperative cancellation, retry, dual-layer idempotency, and WebSocket projection (`/api/v1/operations`).
- **Live Console, Telemetry & Activity Auditing**:
  - Demand-driven WebSocket console streaming (`ConsoleStreamManager`) with interactive command execution (`exec_input` / `exec_resize`).
  - Real-time CPU, RAM, TPS, and player count collection with Prometheus `/metrics` export and configurable threshold alerts.
  - Persistent per-server activity and cryptographic hash-chained event store (`event_store`).
- **In-Browser File Manager**: Directory browsing, syntax-highlighted text editor, file upload/download, and path-traversal/sensitive-file sandboxing.
- **Plugin & Mod Marketplace**: Modrinth catalog search, version compatibility matching, SHA-1/SHA-512 verified installation, custom `.jar` upload, and on-disk plugin/mod reconciliation.
- **Encrypted Backups & Schedules**: Full and world-scoped `tar.gz` backups with AES-256-GCM encryption, SHA-256 checksum verification, point-in-time restoration, local/S3 storage backends, and cron-scheduled automation.
- **Network Exposure**: Built-in Playit.gg tunnel management, Cloudflare Named Tunnels, and UPnP port forwarding for both the web panel and individual game servers.
- **Authentication & Zero-Trust RBAC**:
  - First-run Owner bootstrap wizard (`/setup`) with `LOCAL` and `GLOBAL` access modes and SHA-256 hashed invitation tokens.
  - RS256 JWT authentication (15-minute access tokens, 7-day rotating refresh tokens), Argon2id password hashing, and scoped API keys (`onx_` prefix).
  - Global and server-scoped RBAC enforced across all 155 live routes and verified by CI against `contracts/permissions.yaml`.
- **Frontend Dashboard & Design System**:
  - React 19 + TypeScript 5 + Tailwind CSS v4 SPA with route-level code splitting, semantic design tokens, and multi-skin theming (Graphite & Azure) with WCAG AA contrast validation.
  - Unified `AppShell` and `ServerShell` with quick server switcher, connectable IP/port copy widgets, and live console stream attachment.
- **Zero-Config Unified Launcher**: Cross-platform `launcher.py`, `start.sh`, and `start.bat` with automatic Python 3.12 and Node.js 22 LTS prerequisite checks, preflight process reconciliation, and pre-backend database schema verification (`b1e2100000022`).
