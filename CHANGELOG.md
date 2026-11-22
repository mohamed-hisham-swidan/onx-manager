# Changelog

All notable changes to ONX Manager are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- TODO(HUMAN): Finalize the 0.1.0 release date before tagging the first public release -->

## [0.1.0] - Unreleased

### Added

- **Multi-Runtime Server Management**: Create, import (directory scan or `.zip` upload), start, stop, restart, and delete Minecraft servers across **Vanilla, Paper (Fill v3), Spigot, Purpur, Fabric, Forge (`1.17.1`–`1.20.1`+ & legacy), NeoForge, and Quilt** with automatic JAR/installer provisioning, deterministic Java floor resolution, and retry support.
- **Docker-Only Runtime & Container Hardening (P6)**: Standardized on hardened Docker container execution (`DockerProvider` with `--cap-drop=ALL`, `--security-opt=no-new-privileges:true`, `--pids-limit=2048`, non-root `--user`, `/data`-only bind mounts, bridge networking, dynamic IP inspection, loopback RCON, and opt-in DooD support), removing legacy local host tmux/Win32 providers with local-to-Docker migration tooling.
- **Multi-Worker Lifecycle Leases**: DB-backed `server_lifecycle_leases` serialization and fail-closed `stop_confirmed` gating across server start/stop/restart/delete/restore paths.
- **Simple & Advanced Server Modes + Live Conversion (P1–P7)**:
  - `ServerMode.SIMPLE` for zero-friction server hosting with host-side baseline lockfiles (`onx-jars.lock.json`).
  - `ServerMode.ADVANCED` (POSIX hosts) for Git-native declarative server engineering backed by Allow-list v2.3 (`open_safe_path_fd`), Lockfile Format 2.1, SHA-256 Artifact CAS, and an authoritative `0700` host-state layout, plus live Simple ↔ Advanced conversion endpoints (`/convert/to-advanced`, `/convert/to-simple`).
- **Git-Native Versioning, Protected `main` & Vaults**:
  - Native Git repositories (`repo.git` + worktrees), immutable commits, multi-parent merge DAG (`server_commit_parents`), symbolic tags (`server_tags`), system-level `main` branch protection, and deterministic 3-way structured config merging (YAML, TOML, JSON, `.properties`, `diff3`).
  - AES-256-GCM encrypted Class-C state snapshots (`class_c_snapshots`, `format_version=2`) and `${ONX_SECRET_*}` secret vault (`server_secrets`) with Structured & Pattern Secret Scanner (`secret_scanner.py`).
  - Clean Export + crash-safe Journaled Directory Swap (`renameat2` / journaled `.prev`) with startup recovery.
- **Isolated Branch Runtimes & Bot Testing**:
  - Parallel branch runtime containers (`BranchRuntimeService`) with atomic host port sets, ephemeral Class-C overlays, quiescent `DataTemplates`, and live RCON branch console.
  - Database-backed concurrent admission control (`RuntimeAdmissionScheduler`), reusable `TestDefinition` profiles, `SmokeTestVerifier`, `FakePlayerVerifier`, and `MineflayerVerifier`, automated crash pattern correlation with mod blame, and structured evidence bundles.
- **GitHub Sync & Webhooks**: Fetch-first remote sync, non-fast-forward `main` guards, encrypted deploy-key vault, credential scrubber, HMAC-verified webhook ingress (`/api/v1/webhooks/github/{server_id}`), and durable delivery queue.
- **Modpacks, Loader Environment Cache (LEC) & 1-Click Safe Upgrades**:
  - `.mrpack` and CurseForge modpack archive parsing and installation via a strict 19-host HTTPS download allow-list and encrypted `PanelSecretStore`.
  - Pre-warmed host Loader Environment Cache (LEC) with reflink/copy attach for Paper, Forge, NeoForge, Fabric, and Quilt.
  - Hash-only Modrinth compatibility matrix with transitive dependency BFS, pure-Python NBT `level.dat` `DataVersion` verification, 4-step race-free Upgrade Health Gate, and automatic Triad Rollback (Class A+B, Class-C snapshot, pinned Class-E backup).
- **Multi-Step Operations Engine**: Asynchronous `Operation` aggregate with step progress tracking, cooperative cancellation, retry, dual-layer idempotency, and WebSocket projection (`/api/v1/operations`).
- **Live Console, Telemetry & Activity Auditing**: Demand-driven WebSocket console streaming (`ConsoleStreamManager`) with interactive command execution, real-time CPU/RAM/TPS/player graphs, Prometheus `/metrics` export, configurable alerts, and hash-chained `event_store`.
- **In-Browser File Manager**: Directory browsing, live-state inspection, syntax-highlighted editor, upload/download, and path-traversal sandboxing.
- **Plugin & Mod Marketplace**: Modrinth catalog search, version compatibility matching, SHA-1/SHA-512 verified installation, custom `.jar` upload, and on-disk plugin/mod reconciliation.
- **Two-Tier Encrypted Backups & Schedules (P7)**: Tier-1 snapshots and Tier-2 archives with chunked AES-256-GCM envelope encryption (`ONX_MASTER_KEK`-wrapped DEKs), SHA-256 checksums, pinned rollback protection, local/S3 storage backends, and cron-scheduled automation.
- **Network Exposure**: Built-in Playit.gg tunnel management, Cloudflare Named Tunnels, and UPnP port forwarding for panel and game servers.
- **Authentication & Zero-Trust RBAC**: RS256 JWT authentication, Argon2id password hashing, scoped `onx_` API keys, `/setup` Owner bootstrap (`LOCAL`/`GLOBAL`), invitations, and RBAC/ABAC enforced across **213 live routes** (`contracts/permissions.yaml`).
- **Frontend Dashboard & Design System**: React 19 + TypeScript 5.5 + Tailwind CSS v4 SPA with route-level code splitting, semantic design tokens, multi-skin theming with WCAG AA contrast verification, corner-style & brand tokens, and unified `AppShell`/`ServerShell`.
- **Zero-Config Unified Launcher**: Cross-platform `launcher.py`, `start.sh`, and `start.bat` with exact Python 3.12 and Node.js checks, preflight reconciliation, and fail-closed Alembic DB compatibility verification (`b1e2100000032`).
