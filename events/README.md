# Domain Event Catalog

## Event Registry

| Event | Publisher | Subscribers | Payload |
|---|---|---|---|
| `server.created` | Batch-04 | Batch-06, 09 | `{ server_id, name, version }` |
| `server.starting` | Batch-04 | Batch-06, 09, 10 | `{ server_id }` |
| `server.running` | Batch-04 | Batch-06, 09, 10 | `{ server_id, pid, port }` |
| `server.stopping` | Batch-04 | Batch-06, 09, 10 | `{ server_id, reason }` |
| `server.stopped` | Batch-04 | Batch-06, 09, 10 | `{ server_id }` |
| `server.crashed` | Batch-04 | Batch-06, 09, 10 | `{ server_id, exit_code, logs }` |
| `server.config_changed` | Batch-04 | Batch-06, 10 | `{ server_id, keys }` |
| `backup.started` | Batch-04 | Batch-06, 09 | `{ backup_id, server_id }` |
| `backup.completed` | Batch-04 | Batch-06, 07, 09 | `{ backup_id, server_id, size, checksum }` |
| `backup.failed` | Batch-04 | Batch-06, 09 | `{ backup_id, server_id, reason }` |
| `plugin.installed` | Batch-04 | Batch-06, 07, 10 | `{ plugin_id, server_id, version }` |
| `plugin.enabled` | Batch-04 | Batch-06, 10 | `{ plugin_id, server_id }` |
| `plugin.disabled` | Batch-04 | Batch-06, 10 | `{ plugin_id, server_id }` |
| `user.login` | Batch-08 | Batch-06, 09 | `{ user_id, ip }` |
| `user.logout` | Batch-08 | Batch-06 | `{ user_id }` |
| `system.startup` | Batch-01 | All | `{ version, hostname }` |
| `system.shutdown` | Batch-01 | All | `{ uptime }` |
| `circuit.opened` | Batch-01 | Batch-09 | `{ provider, count }` |
| `circuit.closed` | Batch-01 | Batch-09 | `{ provider, downtime }` |

## Rules

1. New events are added here first, before any batch implements them
2. Each event has exactly one publisher batch
3. Event payloads are additive only (never remove fields)
4. Schema changes require a new schema_version field in the payload
