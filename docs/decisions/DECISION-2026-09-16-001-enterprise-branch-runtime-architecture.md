# DECISION-2026-09-16-001 — Enterprise Branch Runtime Architecture Rebuild

**Date:** 2026-09-16  
**Decision Level:** D2 (Major) — per GOVERNANCE.md §4: changes platform architecture direction, versioning domain model, persistence strategy, and roadmap scope.  
**Lane:** Release Improvement / Core Platform Architecture  
**Status:** Approved (Ratified by Mohamed 2026-09-16)  

---

## Context

On 2026-09-16, the architecture report *"MCS Manager — Enterprise Branch Runtime Platform"* was reviewed. The report proposed rebuilding ONX Manager's testing and versioning foundation around the decoupling principle: **"Branch != Server != Container != Test."**

Under ROADMAP v1.1, Phase 4 (Community Features) and Phase 5 (Containers System) were completed and closed. The next scheduled phase was Phase 6 (Final Installs / Wrap-up) followed by Phase 7 (previously narrowed to visual/brand polish). Mohamed directed that the enterprise-grade testing and versioning refactor be executed as the core architectural foundation ahead of final release wrap-up.

## Decision

Authorize the Enterprise Branch Runtime Architecture Program, structured into progressive stages (A through G) with dedicated RECON, Design Specs, and verification gates:

1. **Stage A (Domain Reconstruction):** Formalize domain entities (`Project`, `Repository`, `Commit`, `Branch`, `Revision`, `Materialization`, `Runtime`, `PersistentDataset`, `Run`) and ADRs 0013–0016.
2. **Stage B (Real Version Control):** Commit DAG ancestry (`server_commit_parents`), branch lifecycle with status column (`server_branches`), immutable tags (`server_tags`), deterministic diffing, and merge commit support.
3. **Stage C (Filesystem Model & Materialization Engine):** Isolated worktrees (`.onx/worktrees/`), atomic filesystem staging, and live-change import reviews (`server_materializations`, `server_import_reviews`).
4. **Stage D (Runtime Control & Scheduling):** Database-level concurrency admission gate (`server_admission_leases`), earmarked resource capacity accounting, and multi-worker safety.
5. **Stage E (Console & Observability):** Demand-driven WebSocket console log streaming follower, interactive bidirectional WS exec/input, and unified multi-core container metrics.
6. **Stage F (Test Platform & Crash Correlation):** Reusable `TestDefinition` profiles, 1:1 `Runtime` attachment to Docker containers, automated `PatternCrashAnalyzer` mod blame, structured `EvidenceBundle` persistence, and lazy 24h artifact retention.
7. **Stage G (Enterprise Capabilities — Narrowed Scope):** Configurable `BranchProtectionPolicy` on `ServerBranch`, direct-commit rejection with administrative emergency force bypass, and deletion safeguards.
8. **Frontend UI Batch:** Production-grade interfaces for all new versioning capabilities in `frontend/src/server_manager/`.

## Impact

- **Architecture:** Replaces ad-hoc versioning with a formalized Git-inspired DAG, worktrees, and isolated container execution.
- **Persistence:** Additive migrations `b1e2100000015` through `b1e2100000019`.
- **Contracts:** Advances route contract from 122 to 150 live API routes, verified against `contracts/permissions.yaml`.
- **Roadmap:** Positioned as the architectural culmination of the platform prior to Phase 6 final installer wrap-up.
