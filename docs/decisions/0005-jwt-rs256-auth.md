# ADR-0005: JWT RS256 Authentication — Refresh Tokens, Audit Chain, Permissions, Timestamps

**Status**: Accepted
**Date**: 2026-07-22
**Author**: Architecture Review Board

## Context

Batch 08 introduced user authentication, authorization, and audit logging. Five design decisions were made to balance security, simplicity, and integration with existing batches.

---

### Decision 1: JWT Algorithm — RS256 (Asymmetric)

Asymmetric signing allows services (Batch 05 API, Batch 06 WebSocket) to verify tokens without holding the private key. Symmetric HS256 would require sharing a secret across all services.

**Chosen Approach**: RS256 with a 2048-bit RSA keypair. The keypair is auto-generated in-process by default; `set_private_key()` and `set_public_key()` are available for loading external PEM files in production.

**Consequences**: Slightly slower signing and verification compared to HS256. Auto-generated keys are ephemeral — production must load persistent keys via `set_private_key()`. Batch 05 and Batch 06 can verify tokens with `set_public_key()` only, without signing capability.

---

### Decision 2: Refresh Token Storage — Opaque Tokens in DB

Refresh tokens must be revocable and single-use. Stateless JWT refresh tokens cannot be revoked without a blocklist.

**Chosen Approach**: Opaque 48-byte random tokens stored as SHA-256 hash in the database. Each refresh operation rotates the token: the old token is revoked and a new one is issued.

**Consequences**: DB lookup per refresh adds slight latency. Opaque tokens cannot carry embedded claims. The logout endpoint revokes the refresh token by hash lookup. Refresh without a valid token returns 401.

---

### Decision 3: Audit Log — SHA-256 Hash Chain

The audit log must be tamper-evident without the overhead of per-row digital signatures.

**Chosen Approach**: SHA-256 hash chain where each row's hash is computed over JSON-serialized content plus the previous row's hash. This is simpler than per-row signatures and sufficient for tamper detection.

**Consequences**: `verify_chain()` recomputes all hashes and reports mismatches. Hash collisions are infeasible with SHA-256. The chain detects tampering but does not prevent it — no public-key infrastructure is needed.

---

### Decision 4: Permission Model — RBAC + ABAC Hybrid

The system needs both role-based access (broad roles like viewer, operator, admin) and resource-specific control (e.g., a user can only modify servers they own).

**Chosen Approach**: RBAC as the primary model with an ABAC extension for resource-owner checks. `PermissionEvaluator` checks role permissions first, then applies context rules such as resource ownership.

**Consequences**: ABAC is limited to simple context checks (`resource_owner_id`). Complex policy rules would require additional infrastructure. Batch 05 and Batch 06 can call `PermissionEvaluator` for authorization decisions. Inactive users are rejected at evaluation time.

---

### Decision 5: Timestamp Format in Audit Chain — ISO 8601

Hash chain verification must produce identical hashes on write and on verification reads. SQLite stores timestamps as strings, which can introduce format inconsistencies.

**Chosen Approach**: ISO 8601 with Z suffix for UTC. The `_fmt_ts()` function normalizes both `datetime` objects and SQLite string timestamps to the same format: `YYYY-MM-DDTHH:MM:SS.ffffffZ`.

**Consequences**: Slightly more parsing overhead than storing epoch integers. Timestamps are human-readable in the database without conversion. Chain verification produces matching hashes across write and read cycles regardless of SQLite's string-based datetime storage.
