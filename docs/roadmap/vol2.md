<a name="volume-2"></a>
## Volume 2 — Phase 1: Plugins / Marketplace Separation 🔄 NEARING CLOSE

### 2.1 Objective

Split "what plugins does this server have" (server-scoped, lifecycle-oriented) from "what plugins
can I discover and install" (global catalog, discovery-oriented) as genuinely distinct product
surfaces, not one page with a sub-tab.

### 2.2 Current reality

| Area | Answers | Scope |
|------|---------|-------|
| **Plugins** | "What plugins does this server have?" | Server-scoped: installed list, state, lifecycle, enable/disable, removal, configuration |
| **Marketplace** | "What plugins can I discover and install?" | Global catalog/discovery/store; server selection happens at install time |

- Backend: one router, `/api/v1/servers/{server_id}/plugins/*`, handles both plugin management and
  marketplace (search / versions / install). Provider selection is configuration-driven via
  `MCS_PLUGIN_PROVIDERS` (default `modrinth`), validated fail-fast at startup.
- Live route table (v3, verified 2026-08-05): `GET /plugins`, `GET /plugins/{plugin_id}`,
  `DELETE /plugins/{plugin_id}`, `POST /plugins/{plugin_id}/enable`,
  `POST /plugins/{plugin_id}/disable`, `GET /plugins/marketplace/search`,
  `GET /plugins/marketplace/projects/{id}/versions`, `POST /plugins/marketplace/install`. No
  standalone install route outside marketplace — the old `POST /plugins` manual-install route was
  removed in `b1b6dd8` (2026-08-04).
- Frontend: `PluginListPage` (server-scoped) and `PluginMarketplacePage` historically shared the
  `/plugins` namespace. **Per STATUS.md K5 (2026-08-06): Marketplace now has its own top-level
  route (`/marketplace`), sidebar entry, and a global search endpoint
  (`GET /api/v1/marketplace/search`) distinct from the server-scoped one.** The install flow was
  reworked with a server picker (server selection happens at install time), pre-selecting by deep
  link → last-used server → first compatible → any server.

### 2.3 Workstreams

1. **Frontend nav restructure (K5).** ✅ Done per STATUS.md 2026-08-06 — own sidebar entry, own
   route, own search, install flow with server picker. **Not yet independently re-verified by live
   route/component introspection** the way v3 verified Phase 0 — recommend a short verification
   pass at the start of Phase 2 rather than trusting the batch note alone (see §2.6).
2. **Route/namespace clarity.** Decide whether marketplace API routes stay under
   `/servers/{server_id}/plugins/marketplace/*` or move to a marketplace-owned namespace. **Open —
   D4, Volume 10.**
3. **Provider abstraction (K16).** ✅ K16A done (2026-08-05): provider selection is
   configuration-driven, validated at startup, fail-fast on unknown/empty/multiple providers.
   **K16A accepts exactly one active provider** — the comma-separated list syntax in
   `MCS_PLUGIN_PROVIDERS` is intentionally preserved for the remaining K16 scope (inspecting the
   configured list via API, adding a second provider), but multi-provider configuration currently
   fails fast at startup. Remaining K16 work is **not** part of Phase 1 exit — it's deferred to
   Phase 1's backlog for whenever a second provider is actually needed, not blocking.
4. **Foundation for future catalog features.** Checksums, version metadata, and dependency info
   already exist in the version-selection model — reuse rather than rebuild when marketplace grows.

### 2.4 Dependencies

None — backend marketplace already shipped before this phase started.

### 2.5 Acceptance criteria

| Criterion | Status |
|---|---|
| Marketplace is independently navigable (own nav entry + route) | ✅ Met per K5 (2026-08-06) |
| Installing from Marketplace places a verified `.jar` in the selected server's `plugins/` directory; reconciled list reflects it | 🔶 Not explicitly confirmed in STATUS.md — verify in §2.6 |
| Plugin management reads as server-scoped; Marketplace reads as global | ✅ Met per K5 — separate search endpoints |
| Provider list is configuration-driven, Modrinth default | ✅ Met per K16A (2026-08-05) |
| D4 (route namespace) resolved | 🔶 Open |

### 2.6 What's actually left before this phase can close

Phase 1 is close to done but not formally closed. Three concrete items:

1. **Independent verification of K5/K16A.** Both are logged as done in `STATUS.md`'s batch
   narrative, which per that document's own header is "not the source of truth for current
   numbers." A short pass — hit the routes, confirm the sidebar entry renders, confirm install
   actually writes the `.jar` to the right server directory — closes the gap between "logged as
   done" and "verified done" the way v3 closed it for Phase 0.
2. **D4.** Route namespace decision blocks a clean Phase 1 → Phase 2 handoff for anyone building
   new marketplace-adjacent frontend work, since they'd be building against a namespace that might
   move.
3. **D3.** The two files with pending working-tree diffs (§1.2) should be committed as their own
   commit before Phase 1 is called closed — an open working-tree diff against a "done" phase is a
   documentation-vs-code mismatch waiting to happen, which is precisely the class of error this
   whole document rewrite exists to avoid repeating.

### 2.7 Testing

Backend + frontend suites green (1,084 backend per §1.1, 236+ frontend); manual UX walk of both
nav surfaces; frontend tests for both the server-scoped and global marketplace search paths.

### 2.8 Risks

- **Route namespace churn (D4).** If marketplace routes move after other code starts depending on
  `/servers/{id}/plugins/marketplace/*`, that's a breaking change needing a compatibility shim.
  Resolving D4 now, before Phase 2 frontend work builds more surface against the current path, is
  cheaper than resolving it later.
- **Silent scope creep into K16 remainder.** Multi-provider support is real work with its own
  testing surface (provider conflict resolution, per-provider config validation). It must not
  quietly become a Phase 1 blocker just because it's adjacent — it's explicitly backlog, not exit
  criteria.
