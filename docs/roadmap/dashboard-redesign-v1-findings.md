# Dashboard & Server Management Redesign — Findings + Vision (2026-08-09)

Status: DRAFT — RECON NOT YET STARTED. This document captures a voice-note
brain-dump from live user testing, organized for handoff into the usual
RECON → design decision → build → review → commit cycle. Nothing below has
been verified against actual code yet.

## Reference design

"Blade Hosting"-style panel (reference: uploaded `play.hosting` demo
screenshot). Key layout elements to match:
- Left sidebar, grouped: **YOUR SERVER** (Console, Files, Marketplace) →
  **TOOLS** (Software, Modpacks, Subusers) → **CONFIG** (Network, Startup,
  Settings).
- Main area: live console output + Start / Restart / Stop buttons top-right.
- Right column: Address card (click-to-copy), Uptime card, CPU Usage card,
  RAM Usage card, Storage Usage bar (used / total).
- Below the fold: CPU / RAM / Network usage graphs, three side-by-side.
- Dark theme throughout, matching our existing dark mode.

## Part A — Quick, isolated frontend fixes

Independent of Part B; low risk; good candidate for an early standalone batch.

1. **Plugin/mod images not rendering** — marketplace list & detail views
   show no icon/thumbnail for plugins or mods; needs fixing so the image
   actually displays.
2. **~90% of installed plugins/mods show "version: unknown"** — anything
   added from outside the normal marketplace-install flow lacks version
   info. Needs a detection/fallback strategy (RECON should establish where
   version data could realistically come from for externally-added items).
3. **Servers list filter UX** — currently two separate controls sit next to
   each other: a status filter dropdown, and a second unlabeled rectangle
   control whose current behavior is not confirmed (possibly name sort,
   unconfirmed even by the user). Replace both with a single filter icon
   that opens a menu offering "Sort by status" / "Sort by name".
4. **Deferred, not in scope right now:** a login-page bug was flagged but
   the user wants to raise it separately later.

## Part B — Server management redesign ("Blade Hosting"-style)

Large, multi-area effort touching navigation architecture, a new file
manager surface, and a full page redesign.

1. **New "inside-server" navigation context.** Opening a specific server
   switches to a dedicated sidebar, distinct from the app's main sidebar,
   with a small back-arrow at the top to return to normal navigation.
   Top-level items: **Files** (a real file manager, positioned like a
   first-class top item — same visual weight as Console today) and, if the
   server supports mods, a **Mods** item placed next to Files.
2. **Server detail/console page redesign** to mirror the reference
   screenshot: server name + Start/Restart/Stop at top, live console,
   right-side cards (Address/Uptime/CPU/RAM/Storage Usage), plus a
   warnings/alerts panel — same visual language as the current dark theme.
3. **"Coming soon" convention.** Anything the reference design shows that
   we don't have working yet gets a "Coming soon" label instead of being
   silently missing or broken.
4. **Forward-compat placeholder for containerization roadmap item.** A
   future phase will give each server an isolated disk (containerization).
   Not building that now — but the storage UI should stay flexible, and an
   open-ended "Zone" number field should be added as a placeholder so this
   area doesn't need rework later.

## Open questions — need answers before RECON can start

1. **Backend items "already discussed"** — referenced without detail in
   this conversation. Needs clarification on what these are before they
   can be scoped.
2. **The unlabeled second filter control** next to the status filter on the
   servers list — its current behavior isn't confirmed even by the user.
   RECON on the actual code is required before designing its replacement.

## Suggested sequencing

Part B touches navigation architecture, a new file-manager surface, and a
full page redesign — real complexity. Recommendation: keep it as one
continuous work session (per stated preference for "one big batch"), but
still land it as several separately-reviewed, separately-committed pieces
internally — the same discipline that worked well for Marketplace Redesign
v2 (Batches A–F). Draft ordering, to be adjusted once RECON reveals actual
complexity per area:

- **Batch 1** — Part A (3 independent, low-risk fixes)
- **Batch 2** — In-server sidebar shell (navigation only: Files + Mods as
  nav items, back-arrow)
- **Batch 3** — File manager surface
- **Batch 4** — Mods-in-server surface (may fold into Batch 3 depending on
  RECON findings)
- **Batch 5** — Server detail/console page redesign (stat cards, warnings
  panel, Coming Soon labels)

This ordering is a draft, not a commitment — confirm/adjust after RECON.
