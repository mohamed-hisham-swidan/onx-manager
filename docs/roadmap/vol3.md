<a name="volume-3"></a>
## Volume 3 — Phase 2: Product Foundation & UI Stabilization 🔶

### 3.1 Objective

Make the frontend a first-class, stable surface — consistent loading/error/empty states and
navigation — on top of Phase 1's nav baseline. This phase is about honesty and consistency in the
UI layer, not new features.

### 3.2 Current reality (frontend)

- React 19 + Vite + TypeScript 5, TanStack Query, Zustand, TailwindCSS 4.
- Routes (`frontend/src/App.tsx`): `/login`, `/register`, then guarded: `/` (Dashboard),
  `/servers`, `/servers/create`, `/servers/import`, `/servers/:serverId`, `/backups`, `/plugins`,
  `/plugins/marketplace`, `/settings`, `/settings/api-keys`, `*`. **Per Phase 1 (K5), `/marketplace`
  as a top-level route should now also appear here — this route list is carried from v3 §4 and has
  not been re-confirmed against the current `App.tsx` since K5 landed. First task of this phase:
  refresh this list against the actual router config.**
- Sidebar: Dashboard, Servers, Backups, Plugins, Settings — **plus Marketplace, per K5**. Same
  caveat as above.
- Zustand stores: `authStore` (localStorage `mcs_auth`), `uiStore`, `wsStore`.
- WebSocket client is fully implemented (connect/reconnect/ping/message queue), but the backend
  rejects every subscription (K1) and never dispatches events (K2) — a complete client that is
  behaviorally non-functional. **This is a Phase 3 fix, not Phase 2** — Phase 2's job here is to
  make that brokenness honest in the UI (not silently "connected"), not to fix the underlying bug.

### 3.3 Desired state

- Navigation clearly separates plugin-management from marketplace, and server-scoped from global
  pages.
- Loading/error/empty states are uniform across all pages.
- API state and cache behavior are deterministic (TanStack Query configured once, applied
  consistently).
- WebSocket behavior is documented and either works or is explicitly disabled per surface — no
  "connected but silent" dead end.
- Settings UX reflects what actually persists. Persistence itself lands in Phase 3; Phase 2
  disables/annotates non-persistent controls rather than faking success.
- Permissions UX shows only actions the user may take. Authorization enforcement lands in Phase 4;
  Phase 2 lays the presentation groundwork against `contracts/permissions.yaml` — which itself has
  an open versioning question (D2). Phase 2 should build against whichever version is committed at
  the time, and flag if D2 resolves mid-phase in a way that changes the permission set it built
  against.
- No new design system — apply what already exists, consistently.

### 3.4 Workstreams

1. **Navigation & IA**, building on Phase 1's restructure, including the post-K5 refresh in §3.2.
2. **Shared loading/error/empty primitives**, applied repo-wide — one set of components, not
   per-page reinvention.
3. **API client + TanStack Query configuration audit** — one query-client config, consistent
   staleTime/cacheTime/retry policy across all queries rather than ad hoc per-hook settings.
4. **Settings page accuracy** relative to actual persistence — every control either persists or is
   visibly disabled/labeled as non-functional. No control silently no-ops.
5. **WebSocket surface honesty** — live vs. explicitly disabled, surfaced in the UI, not hidden
   behind a client that "looks" connected while the backend fail-closes every subscription (K1).
6. **Frontend test coverage** for all of the above.

### 3.5 Dependencies

Phase 1 (nav restructure baseline). Given §2.6, this phase's first workstream item should confirm
Phase 1's actual current state (route list, sidebar) rather than assume the v3 snapshot is still
accurate — it's already one batch (K5) out of date at the time of writing.

### 3.6 Acceptance criteria

- Every route has defined loading/error/empty behavior.
- Navigation distinguishes server-scoped from global surfaces.
- Frontend tests cover the restructured navigation and state primitives.
- Settings page has zero controls that silently no-op.
- WebSocket surface has zero "shows connected, does nothing" states.

### 3.7 Verification

Frontend suite green; manual walkthrough; route-by-route state review recorded in
`docs/FRONTEND.md` (this is a v3-carried commitment — the review needs to actually get written
into that file, not just performed and left undocumented).

### 3.8 Explicit non-goals

- Fixing K1/K2 (WebSocket backend bug) — Phase 3.
- Implementing settings persistence — Phase 3.
- Enforcing permissions server-side — Phase 4.
- New visual design system — out of scope entirely; this phase applies what exists.

### 3.9 Risks

- **Building permission-aware UI against an unstable contract.** `contracts/permissions.yaml` has
  an open version question (D2: v1.3 committed vs. v1.4 uncommitted, with a phantom deleted-route
  entry). Workstream 5's presentation groundwork should be built defensively — read permission
  strings from the contract at build/runtime rather than hardcoding a list that D2's resolution
  could invalidate.
- **Scope bleed into Phase 3.** The WebSocket and Settings workstreams sit right at the boundary
  with Phase 3's must-fix items. Discipline required to keep Phase 2 to "make the current state
  honest in the UI" without quietly starting to fix the backend causes — that's real, valuable
  work, but it's Phase 3's, and starting it here blurs both phases' acceptance criteria.
