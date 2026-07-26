# Shared Contracts

## Contract Registry

| ID | Interface | Provider | Consumer(s) | Since |
|---|---|---|---|---|
| C-001 | `CommandBus` | Batch-01 | All batches | v4.0 |
| C-002 | `EventBus` | Batch-01 | All batches | v4.0 |
| C-003 | `QueryBus` | Batch-01 | All batches | v4.0 |
| C-004 | `UnitOfWork` | Batch-01 | All batches | v4.0 |
| C-005 | `MCSError` | Batch-01 | All batches | v4.0 |
| C-006 | `ServerProvider` | Batch-03 | Batch-04, 05, 06 | v4.0 |
| C-007 | `Server` aggregate | Batch-02 | Batches 03, 04, 05, 09 | v4.0 |
| C-008 | `JWTProvider` | Batch-08 | Batches 05, 06 | v4.0 |
| C-009 | `PermissionEvaluator` | Batch-08 | Batches 05, 06 | v4.0 |
| C-010 | `AuditLogger` | Batch-08 | Batch-05 | v4.0 |
| C-011 | `TaskQueue` | Batch-09 | Batches 04, 05 | v4.0 |
| C-012 | `EventStore` | Batch-09 | All batches | v4.0 |

## Breaking Changes

- Change C-001 (CommandBus interface): requires all handler registrations to update
- Change C-006 (ServerProvider): requires all provider implementations to update
