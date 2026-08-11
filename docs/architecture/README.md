# Architecture & Design Index

Deep design and subsystem documents describing how MCS Manager is built and
why. Reference manuals (API, testing, development, deployment) live at `docs/`
root; this directory holds design/architecture references.

| Document | Status | Purpose |
|----------|--------|---------|
| [Architecture](ARCHITECTURE.md) | ✅ **IMPLEMENTED** | System context, module structure, CQRS/hexagonal patterns, task wiring, reconciliation. |
| [Database](DATABASE.md) | ✅ **IMPLEMENTED** | Schema design, migration chain, query patterns, migration guide. |
| [Security](SECURITY.md) | ✅ **IMPLEMENTED** | Authentication, authorization (Phase 4 enforced: global + server-scoped RBAC), audit chain, data protection, rate limiting, sessions. |
| [Frontend](FRONTEND.md) | ✅ **IMPLEMENTED** | React 19 app structure, state management, WebSocket integration, API client, testing. |
| [Plugins & Marketplace](plugins-and-marketplace.md) | ✅ **IMPLEMENTED** | Plugin registry (filesystem source of truth) + Modrinth marketplace implementation. |
| [Network Access Design](network-access-design.md) | 🟡 **PLANNED** | Phases 7–8 design reference: TunnelProvider vs DnsProvider, dynamic endpoints, tunnel ≠ auth. |
| [Provisioning](PROVISIONING.md) | ✅ **IMPLEMENTED** | Server creation flow, JAR validation, supported server types. |
| [Marketplace Design Review](K5-marketplace-design-review.md) | ✅ **IMPLEMENTED** | K5 marketplace first-class-section design review and implementation record. |

Part of the [documentation index](../README.md).