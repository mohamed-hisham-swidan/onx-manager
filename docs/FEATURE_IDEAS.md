# Feature Ideas — Deferred / Parking-Lot Document

**Status:** Not started — backlog / parking-lot document.
**Purpose:** Captures feature ideas Mohamed has raised and decisions explicitly
deferred to a later roadmap phase. This is **not** a spec and nothing here is
committed work.
**Last updated:** 2026-08-03

---

## 1. Reveal server / backup directory in the OS file manager

**Requested:** 2026-08-03

A direct link/button in the server and backup UI sections to open that server's
or backup's directory in the OS file manager — e.g. from the server detail page
or the backups list. Mohamed confirmed this is useful for his own testing
workflow (quick access to world files, logs, backups on disk).

**Why deferred (not implemented now):**

- This is **new feature work**, and the project is currently in **Phase 1
  (Security & Stability Hardening)** per `docs/mcs-manager-roadmap-v1.md`, which
  explicitly blocks new capability until Phase 1's exit criteria close.
- It also carries real security surface: opening a filesystem path from a web UI
  typically means the backend either shells out to something like
  `xdg-open` / `explorer`, or returns a path for a client-side file-manager
  integration. Either way, if the path isn't strictly validated against the real
  server/backup `root_path`, it becomes a path-traversal or command-injection
  vector (user-controllable path segments, traversal, or unsanitized input
  reaching a shell command).

**Security constraints any future implementation MUST satisfy:**

1. **Strict server-side path resolution** against the DB's `root_path` field
   only — no client-supplied path fragments may be accepted or resolved.
2. **No shell string interpolation.** If a command must be spawned (e.g.
   `xdg-open` / `explorer`), invoke it with a fixed argv and pass the resolved
   absolute path as a single, non-interpolated argument.
3. **Read-only "reveal in file manager" action**, scoped to a single
   already-authorized `resource_id` (server id / backup id) rather than an
   arbitrary path parameter.

**Suggested target phase:** **Phase 4 (Frontend Redesign & Parity)** — the
roadmap phase for UI/UX feature work.
