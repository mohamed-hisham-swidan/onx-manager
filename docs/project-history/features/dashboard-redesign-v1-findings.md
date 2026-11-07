# Dashboard & Server Management Redesign — Findings + Vision (2026-08-09)

Status: COMPLETE (2026-08-10). All planned batches across Part A and Part B have been implemented, independently reviewed, and committed.

## Reference design

"Blade Hosting"-style panel (reference: uploaded `play.hosting` demo
screenshot). Key layout elements matched:
- Left sidebar, grouped: **YOUR SERVER** (Console, Files, Marketplace/Mods) →
  **CONFIG** (Settings).
- Main area: live console output + Start / Restart / Stop controls top-right.
- Right column: Address card (click-to-copy), Uptime card, CPU Usage card,
  RAM Usage card, Storage Usage card ("Coming Soon").
- Below the fold: CPU / RAM / Network usage graphs, three side-by-side.
- Dark theme throughout.

## Part A — Quick, isolated frontend fixes (COMPLETE)

1. **Plugin/mod images not rendering [CLOSED]** — commit `b6a47fc` (Batch 2). Marketplace & installed list icon rendering fixed.
2. **~90% of installed plugins/mods show "version: unknown" [CLOSED]** — commit `54428ad` (Batch 3). Parses real version metadata from plugin `.jar` files.
3. **Servers list filter UX [CLOSED]** — commit `bdbb877` (Batch 1). Consolidated status filter + name sort into a single popover.

## Part B — Server management redesign ("Blade Hosting"-style) (COMPLETE)

1. **In-server navigation shell [CLOSED]** — commit `adbf556` (Batch 1). Dedicated sidebar context with back-navigation.
2. **Blade Hosting-style detail/console page [CLOSED]** — commit `72e8c1c` (Batch 2). Stat cards, trend graphs, warnings panel.
3. **Files REST API [CLOSED]** — commit `ae6848d` (Batch 3). Secure backend filesystem REST API with path sandboxing.
4. **File Manager UI [CLOSED]** — commit `e96f902` (Batch 4). First-class `/servers/:serverId/files` view with inline editor & upload.
5. **Server detail polish & Zone ID placeholder [CLOSED]** — commit `79d18d7` (Batch 5). Zone ID row in deployment section, honest "Coming Soon" states for Storage & Network I/O.
6. **Server-Type-Aware Mods/Plugins UI [CLOSED]** — commit `7226e6c`. Contextual navigation and Install Modal showing "Mods" or "Plugins" based on server type.

## Execution Summary

All Part A (3 batches) and Part B (5 batches) deliverables have landed on master:
- **Part A Batch 1:** `bdbb877` (consolidated filter/sort popover)
- **Part A Batch 2:** `b6a47fc` (plugin/mod icon fix)
- **Part A Batch 3:** `54428ad` (real version parsing from JARs)
- **Part B Batch 1:** `adbf556` (in-server navigation shell)
- **Part B Batch 2:** `72e8c1c` (Blade Hosting-style server detail layout)
- **Part B Batch 3:** `ae6848d` (Files REST API)
- **Part B Batch 4:** `e96f902` (File Manager UI)
- **Mods/Plugins UI:** `7226e6c` (server-type-aware navigation & modal)
- **Part B Batch 5:** `79d18d7` (Server detail polish & Zone ID placeholder)
