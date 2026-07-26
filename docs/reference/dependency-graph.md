# Dependency Graph

> Cross-references: [Module Map](module-map.md), [Contract Registry](contract-registry.md), [Architecture](../ARCHITECTURE.md), [API](../API.md)

## Batch Dependencies

```
Batch 01 (Core) ──► Batch 02 (Domain) ──► Batch 03 (Providers) ──► Batch 04 (Application)
                                                                          │
    Batch 08 (Auth) ◄──────────────────────────────────────────────────────┤
         │                                                                 │
         └──► Batch 05 (API) ◄─────────────────────────────────────────────┘
                  │
                  ├──► Batch 06 (WebSocket)
                  ├──► Batch 10 (Frontend)
                  └──► Batch 09 (Monitoring)

    Batch 07 (Plugins) ◄── Batch 04 (uses application layer)
```

## Execution Order & Dependency Rules

| Batch | Depends On | Can Start After | Notes |
|---|---|---|---|
| 01 | Nothing | Immediately | Foundation — everything builds on this |
| 02 | 01 | Batch 01 done | Domain model layer |
| 03 | 01, 02 | Batch 02 done | Infrastructure providers |
| 04 | 01, 02, 03 | Batch 03 done | Application layer |
| 05 | 01, 04, 08 | Batch 04 + 08 done | API layer (waits for Auth) |
| 06 | 01, 04, 05 | Batch 05 done | WebSocket (depends on API) |
| 07 | 01, 02, 03, 04 | Batch 04 done | Plugin system (can parallel with 05/06) |
| 08 | 01, 02 | Batch 02 done | Auth — can parallel with Batch 03/04 |
| 09 | 01, 04, 05 | Batch 04 done | Monitoring — can parallel with 06/07 |
| 10 | 05, 06 | Batch 06 done | Frontend (depends on API + WS) |

## Shared Interfaces (Contracts)

These interfaces cross batch boundaries and must not change without coordination:

| Interface | Provided By | Consumed By | Contract ID |
|---|---|---|---|
| `CommandBus` | Batch 01 | All batches | C-001 |
| `EventBus` | Batch 01 | All batches | C-002 |
| `QueryBus` | Batch 01 | All batches | C-003 |
| `UnitOfWork` | Batch 01 | All batches | C-004 |
| `MCSError` hierarchy | Batch 01 | All batches | C-005 |
| `ServerProvider` | Batch 03 | Batch 04, 05, 06 | C-006 |
| `Server` aggregate | Batch 02 | Batch 03, 04, 05, 09 | C-007 |
| `JWTProvider` | Batch 08 | Batch 05, 06 | C-008 |
| `PermissionEvaluator` | Batch 08 | Batch 05, 06 | C-009 |
| `AuditLogger` | Batch 08 | Batch 05 | C-010 |
| `TaskQueue` | Batch 09 | Batch 04, 05 | C-011 |
| `EventStore` | Batch 09 | All batches | C-012 |

Full details in the [Contract Registry](contract-registry.md).

## Cross-Batch Request Protocol

When Batch A needs something from Batch B:

1. Batch A writes a `REQUEST` entry in `MASTER_PLAN.md`
2. Format:
   ```
   REQUEST
   From: Batch-A
   To: Batch-B
   Needed: Short description
   Reason: Why it's needed
   Required Interface: Function signature / class
   Priority: High/Medium/Low
   ```
3. Batch B implements the requirement in its next session
4. Batch B updates the request status to COMPLETED in `MASTER_PLAN.md`
5. Batch A can proceed

## Prohibited Dependencies

| Violation | Reason |
|---|---|
| Batch 05 → Batch 03 (direct) | API must go through Batch 04 application layer |
| Batch 10 → backend internals | Frontend consumes only API contracts |
| Batch 07 → Batch 08 | Plugins are auth-agnostic |

---

See [Module Map](module-map.md) for full module listing per batch.
