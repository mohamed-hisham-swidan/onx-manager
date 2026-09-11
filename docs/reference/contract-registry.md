# System Contract Registry & Permissions Schema

**Status:** Living Reference (Synchronized with live codebase)  
**Schema Files Location:** `contracts/`

---

## 1. System Contract Inventory

| Contract ID | Name | File Path | Scope & Purpose |
|---|---|---|---|
| **C-001** | `permissions.yaml` | `contracts/permissions.yaml` | Comprehensive RBAC/ABAC route contract mapping 106 live routes to roles & scopes. |
| **C-002** | `api.yaml` | `contracts/api.yaml` | OpenAPI contract specification outline for API v1. |
| **C-003** | `events.yaml` | `contracts/events.yaml` | Domain event schema definitions and payload versioning. |
| **C-004** | `plugin.yaml` | `contracts/plugin.yaml` | Plugin manifest contract and JSON-RPC subprocess bridge interface. |
| **C-005** | `config.schema.json` | `contracts/config.schema.json` | JSON Schema for application configuration and settings store. |

---

## 2. Route Permission Contracts (`contracts/permissions.yaml`)

The permissions registry enforces zero-trust route security across all **106 live API routes**:
- **Owner-only routes:** System bootstrap, global settings, user role elevation, panel exposure configuration.
- **Admin routes:** User management, global server creation, backup deletion.
- **Server-scoped routes:** Server start/stop/restart, console access, file editing, plugin installation (governed by user server access lists).
- **Public routes:** Login, register (with invite), setup status check, health probes.

Verified by CI gate: `./scripts/check-route-contract` (106/106 PASS).
