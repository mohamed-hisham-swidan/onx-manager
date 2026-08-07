# Network Access / Port Forwarding — Design

**Status:** 🟡 **PLANNED** — this is a design reference for Phases 7–8 of
`docs/roadmap/MCS-Manager-Engineering-Blueprint-V5.md`. Nothing here is implemented yet, and no
provider is selected. It exists so Phases 7–8 start from a shared architecture
instead of a blank brief.

**Last updated:** 2026-08-04
**Blocked on:** Phases 1–6 of `MCS-Manager-Engineering-Blueprint-V5.md`

---

## 1. Purpose

The goal of the Network Access phase is to let a user reach **their own single
running MCS Manager instance** from outside their local network (phone, a
friend's house, on the road) — without requiring them to configure port
forwarding, UPnP, a static IP, or dynamic DNS by hand.

This design separates the concerns that the naive mental model conflates:

- **Tunnel** — raw inbound transport from the internet to the app.
- **DNS** — human-readable naming of an endpoint.
- **Exposure** — *what* is being exposed (game port vs management UI).
- **Authentication** — proving who the caller is *after* transport arrives.

A common failure in tools like this is to treat these as one feature
("remote access"). They are four independent axes and are designed as such.

---

## 2. Non-negotiable principles

### 2.1 Tunnel ≠ Authentication

A tunnel is transport only. It may get traffic to the app from anywhere, but it
does **not** vouch for the caller. Every tunneled request must pass through the
**exact same** authentication and authorization stack as a local request.

Concretely:

- Terminate the tunnel **in front of** the existing FastAPI middleware
  (`AuthMiddleware` → `AuditMiddleware` → `RateLimitMiddleware`), never around
  it.
- **No tunneled route is unauthenticated by virtue of arriving over the
  tunnel.** A tunnel does not add "trusted" status to a request.
- Recommended hardening: a shared secret or mTLS between the tunnel client and
  the app itself, so even a compromised tunnel provider cannot inject traffic
  that looks locally-sourced.

This principle makes the WS/Push path and the REST path follow the same rule:
anything the tunnel delivers still needs a valid token.

### 2.2 Game exposure and Management exposure are independent

Exposing the Minecraft game port and exposing the MCS Manager web UI solve
different problems and carry different security postures:

| Axis | What's exposed | Auth model |
|------|----------------|------------|
| **Game exposure** | The Minecraft server's own port (`25565`), so friends can join | Minecraft has no auth at the transport level (the game handles identity internally). Exposing it opens the game to the public. |
| **Management exposure** | The MCS Manager web UI/API, so *you* can administer the server remotely | Always requires the full auth stack (login, permissions, audit, rate limits). |

These must be **two independent toggles** with separate tunnels, separate
endpoints, and separate security defaults. They must never be gated together,
and the UI must never present them as one decision.

### 2.3 DNS is optional and separate

Not every tunnel needs DNS:

- An ephemeral tunnel may assign a random `*.trycloudflare.com`-style URL that
  *is* the endpoint — no DNS configuration exists or is needed.
- A named tunnel or a custom domain needs a DNS provider entry to point at the
  tunnel's current endpoint.

Therefore DNS is a **separate provider interface** (`DnsProvider`), and only
some deployments will have one configured.

### 2.4 Dynamic endpoints

Tunnel endpoints are frequently **not known until runtime**:

- Ephemeral URLs are assigned per connection/process start.
- Named tunnels may resolve to a fixed hostname, but the underlying transport
  address can change.

The system must treat endpoint URLs as **data discovered at runtime**, not
static configuration:

- The backend exposes the current endpoint(s) to the UI (e.g. a status field on
  a tunnel: `endpoint_url`, `status`, `error`).
- The UI renders live endpoints so the user can copy the current URL to share
  it.
- Configuration may hold a *desired* name (e.g. a subdomain), but the *actual*
  endpoint is whatever the provider reports.

### 2.5 No provider preselection

This document identifies **candidate** providers and the requirements they must
meet. It does **not** choose a default tunnel or DNS provider. When Phase 7
implementation starts, providers will be evaluated against the requirements
here, and the evaluation result (with selection rationale) will be recorded
before any provider is wired in.

The provider abstractions are designed so that switching providers does not
change application code.

---

## 3. Architecture

### 3.1 Two provider interfaces

```
┌───────────────┐     ┌──────────────────┐
│ TunnelProvider│     │  DnsProvider     │
├───────────────┤     ├──────────────────┤
│ start()       │     │ ensure_record()  │
│ stop()        │     │ delete_record()  │
│ status()      │     │ list_records()   │
│ endpoint_url()│     └──────────────────┘
└───────────────┘
```

**`TunnelProvider`** — owns raw inbound transport.

| Method | Purpose |
|--------|---------|
| `start()` | Establish the tunnel; return/record the runtime endpoint |
| `stop()` | Tear the tunnel down |
| `status()` | Health/state of the tunnel |
| `endpoint_url()` | The **live** endpoint URL (may be ephemeral) |

**`DnsProvider`** — owns name resolution only.

| Method | Purpose |
|--------|---------|
| `ensure_record(name, target)` | Point a name at the tunnel's current endpoint |
| `delete_record(name)` | Remove a name |
| `list_records()` | Current records |

Both are abstract interfaces behind a factory, matching the existing
`StorageBackend` and `PluginCatalogProvider` patterns. Neither interface
"knows about" the other.

### 3.2 Why the interfaces are separate

The two concerns have independent lifecycles and failure modes:

- A tunnel can be up with no DNS (ephemeral URL).
- DNS can exist while a tunnel is down (record points at nothing / is stale).
- They may come from different vendors entirely.

Coupling them (e.g. a single "Tunnel" object that also manages DNS) would force
every tunnel provider to implement DNS and every deployment to configure both.
This separation is the core architectural decision of the phase.

### 3.3 Game vs Management as two exposures

Each exposure is an **independent tunnel**:

```
Game tunnel ──► Minecraft server port (25565)  — no MCS Manager auth involved
                                                    (game handles identity)
Management tunnel ──► FastAPI middleware stack   — full auth stack mandatory

                ┌─────────────────────────────┐
                │  AuthMiddleware             │
Internet ─────► │  AuditMiddleware            │ ──► REST/WS/UI
 (tunnel)       │  RateLimitMiddleware        │
                └─────────────────────────────┘
```

- The **game tunnel** forwards TCP to the server's game port. It is *not* an
  HTTP path and does not touch the FastAPI middleware stack.
- The **management tunnel** terminates in front of the middleware stack. It
  proxies HTTP/WS traffic to the app exactly as local traffic would.

This means "the tunnel" is never a single object either — there can be zero,
one, or two tunnels active, each with its own provider instance.

---

## 4. Installer flow (Phase 7 scope)

Explicit choice, **no silent default**:

1. Ask: *"Local only (this network)"* vs *"Publish (accessible from the
   internet)."*
2. **Local only** → bind to localhost/LAN only, no tunnel, no public exposure.
   (This is today's behavior; requires no new work beyond the wizard step.)
3. **Publish** → ask which exposure(s) to publish:
   - Management UI (requires auth stack + publish-mode hardening)
   - Game port (optional, independent)
4. If DNS is available/desired, ask for a name; otherwise use the ephemeral
   endpoint.

---

## 5. Provider evaluation requirements (no preselection)

When Phase 7 begins, candidate tunnel and DNS providers will be evaluated
against these requirements. The evaluation (with rationale) must be recorded
before any provider is wired.

### 5.1 Tunnel providers

Candidates to consider (not a selection): Cloudflare Tunnel-style client,
self-hosted reverse relay, UPnP mapping, SSH reverse tunnel.

| Requirement | Why |
|-------------|-----|
| Works behind CGNAT/NAT with **zero router config** | The actual UX goal of the phase |
| No inbound port opened on the user's router | Prevents forgotten/exposed forwarded ports |
| Supports runtime endpoints (dynamic URL) | §2.4 |
| Isolatable per exposure (game vs management) | §2.2 |
| Can be authenticated/locked to the app (shared secret or mTLS) | §2.1 |
| No account/trust requirements that leak into the app's threat model without documentation | §2.1 |
| Viable on the supported host platforms (Linux primary) | Baseline constraint |

### 5.2 DNS providers

Candidates to consider (not a selection): cloud DNS APIs, DDNS-style update,
static DNS (manual).

| Requirement | Why |
|-------------|-----|
| Separate from the tunnel provider (pluggable) | §3.1–3.2 |
| Supports creating/updating/removing records via API | `DnsProvider` contract |
| Works with the tunnel's runtime endpoint (dynamic) | §2.4 |
| Optional — deployments without DNS must work | §2.3 |

---

## 6. Publish-mode hardening (couples to Phase 1/2)

The following are **preconditions** carried from earlier phases and re-asserted
here because network exposure is what makes them mandatory:

1. **Per-client rate limiting** (Phase 1) — a global bucket facing the public
   internet is a trivial DoS vector.
2. **Complete authorization** (Phase 1) — unauthenticated access to anything
   must be the explicitly allow-listed exception, not the default.
3. **RBAC/ABAC enforced everywhere** (Phase 2).
4. **Mandatory HTTPS** — refuse to publish the management UI over plain HTTP.
5. **Shorter access-token lifetimes** in publish mode; **optional but strongly
   prompted 2FA** at first publish.
6. **`GET /metrics` (K10)** — revisit whether the Prometheus scrape endpoint
   stays public once the app is reachable from the internet.

---

## 7. Open questions

| # | Question | Notes |
|---|----------|-------|
| 1 | Tunnel provider evaluation | §5.1 — resolve when Phase 7 starts |
| 2 | DNS provider evaluation | §5.2 — resolve when Phase 7 starts |
| 3 | 2FA mandatory or optional in publish mode | Recommendation: optional + prompted |
| 4 | Who terminates the management tunnel (app process vs external daemon)? | Affects startup order and lifecycle |
| 5 | Game-port exposure default (on/off) | Recommendation: off by default; explicit opt-in |

---

## 8. Out of scope for this design

- **Multi-tenant hosting** — isolation, billing, per-tenant limits, abuse
  handling. Requires its own dedicated design conversation.
- **Remote agents / multi-node** (controlling multiple separate physical
  machines from one dashboard). Different trust model — Phase 6 / out of v1.0
  scope.
- **Provider implementation code** — this document intentionally ships before
  any provider is selected or written.

---

## 9. Cross-references

- `docs/roadmap/MCS-Manager-Engineering-Blueprint-V5.md` §9 — Phase 7 roadmap summary
- `docs/current-state.md` §4.2 — current auth state the tunnel must preserve
- `docs/architecture/SECURITY.md` — the stack every management-tunneled request must pass
- `docs/PERMISSIONS_FUTURE_IDEAS.md` §3 — `GET /metrics` exposure decision
