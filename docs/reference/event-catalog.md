# Event Catalog

> Cross-references: [Contract Registry](contract-registry.md), [Dependency Graph](dependency-graph.md), [Module Map](module-map.md)

Sources: `events/README.md`, `contracts/events.yaml`

---

## Event Envelope

Every event published on the `EventBus` follows this structure:

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Unique event identifier |
| `type` | string | Dot-notation name (e.g. `server.crashed`) |
| `version` | integer | Schema version, starts at 1 |
| `timestamp` | datetime | When the event occurred |
| `source` | string | Batch name that published |
| `correlation_id` | UUID | Links related events |
| `payload` | object | Event-specific data |

## Domain Events

| Event | Version | Publisher | Subscribers | Payload |
|---|---|---|---|---|
| `system.startup` | 1 | Batch 01 | All | `{ version, hostname }` |
| `system.shutdown` | 1 | Batch 01 | All | `{ uptime }` |
| `circuit.opened` | 1 | Batch 01 | Batch 09 | `{ provider_name, failure_count, window_seconds }` |
| `circuit.closed` | — | Batch 01 | Batch 09 | `{ provider, downtime }` |
| `server.created` | 1 | Batch 04 | Batch 06, 09 | `{ server_id, name, version }` |
| `server.starting` | — | Batch 04 | Batch 06, 09, 10 | `{ server_id }` |
| `server.running` | — | Batch 04 | Batch 06, 09, 10 | `{ server_id, pid, port }` |
| `server.stopping` | — | Batch 04 | Batch 06, 09, 10 | `{ server_id, reason }` |
| `server.stopped` | — | Batch 04 | Batch 06, 09, 10 | `{ server_id }` |
| `server.crashed` | 1 | Batch 04 | Batch 06, 09, 10 | `{ server_id, exit_code?, last_log_lines[] }` |
| `server.config_changed` | — | Batch 04 | Batch 06, 10 | `{ server_id, keys }` |
| `backup.started` | — | Batch 04 | Batch 06, 09 | `{ backup_id, server_id }` |
| `backup.completed` | 1 | Batch 04 | Batch 06, 07, 09 | `{ backup_id, server_id, size_bytes, checksum_sha256 }` |
| `backup.completed` | 2 | Batch 04 | Batch 06, 07, 09 | `{ backup_id, server_id, size_bytes, size_human, checksum_sha256, checksum_algorithm }` |
| `backup.failed` | — | Batch 04 | Batch 06, 09 | `{ backup_id, server_id, reason }` |
| `plugin.installed` | 1 | Batch 04 | Batch 06, 07, 10 | `{ plugin_id, server_id, version }` |
| `plugin.enabled` | — | Batch 04 | Batch 06, 10 | `{ plugin_id, server_id }` |
| `plugin.disabled` | — | Batch 04 | Batch 06, 10 | `{ plugin_id, server_id }` |
| `user.login` | 1 | Batch 08 | Batch 06, 09 | `{ user_id, ip_address, timestamp }` |
| `user.logout` | — | Batch 08 | Batch 06 | `{ user_id }` |

Events without a version number are catalogued in the README but have no formal schema in `events.yaml` yet.

## Event Rules

1. **Single publisher:** Each event has exactly one publisher batch
2. **Additive payloads:** Fields are never removed from event payloads
3. **Versioned schemas:** Schema changes increment the `version` field in the envelope; new payload fields are added, old ones are never removed
4. **Registry-first:** New events are added to the catalog before any batch implements them
5. **Event Store persistence:** All events are persisted via the `EventStore` (C-012) maintained by Batch 09

## Schema Versions

The only event with multiple schema versions is `backup.completed`:
- **v1:** `backup_id`, `server_id`, `size_bytes`, `checksum_sha256`
- **v2:** Added `size_human`, `checksum_algorithm`; both versions are published to allow backward-compatible consumption

---

See [Contract Registry](contract-registry.md) for the `EventBus` contract (C-002) and `EventStore` contract (C-012).
