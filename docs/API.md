# REST API Reference

**Version:** 1.0
**Base URL:** `https://<host>/api/v1`
**Content-Type:** `application/json`

> Cross-references: [Architecture](ARCHITECTURE.md)

---

## Table of Contents

1. [Authentication](#authentication)
2. [Standard Headers](#standard-headers)
3. [Response Envelope](#response-envelope)
4. [Pagination](#pagination)
5. [Error Format](#error-format)
6. [Rate Limiting](#rate-limiting)
7. [Endpoints](#endpoints)
   - [Auth](#auth)
   - [Servers](#servers)
   - [Backups](#backups)
   - [Plugins](#plugins)
   - [Users](#users)
    - [Health](#health)
    - [Monitoring](#monitoring)
    - [Tasks](#tasks)
8. [WebSocket Protocol](#websocket-protocol)

---

## Authentication

All requests **except** `POST /auth/login` require a Bearer JWT in the `Authorization` header.

```
Authorization: Bearer <jwt>
```

Tokens are issued as a **pair**: an access token (short-lived, 15 minutes) and a refresh token (long-lived, 7 days). Use `POST /auth/refresh` to obtain a new pair before the access token expires.

### API Keys

Long-lived API keys are supported for automation clients. Include the key as the Bearer token:

```
Authorization: Bearer <api_key>
```

API keys are managed via `GET/POST/DELETE /users/{id}/keys`.

---

## Standard Headers

| Header | Required | Description |
|---|---|---|
| `Authorization` | Yes (except `/auth/login`) | `Bearer <jwt>` or `Bearer <api_key>` |
| `Content-Type` | Yes | `application/json` |
| `Idempotency-Key` | No | UUID v4 — ensures idempotent command execution |
| `X-Request-ID` | No | Client-generated request ID for tracing |

### Idempotency

Every mutating command (`POST`, `PUT`, `DELETE`) accepts an optional `Idempotency-Key` header. When provided:

- Duplicate requests within 24 hours return the cached result (same HTTP status + body).
- The key is a client-generated UUID v4.
- Responses include `X-Idempotent: true` when a cached result is returned.

---

## Response Envelope

All successful responses follow a uniform envelope:

```json
{
  "data": { ... },
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 142,
    "total_pages": 8
  }
}
```

| Field | Type | Present |
|---|---|---|
| `data` | `any` | Always |
| `pagination` | `object\|null` | Only on list endpoints |

The `pagination` field is omitted entirely for single-resource responses.

---

## Pagination

All list endpoints are paginated with the following query parameters:

| Parameter | Type | Default | Max | Description |
|---|---|---|---|---|
| `page` | integer | `1` | — | 1-indexed page number |
| `per_page` | integer | `20` | `100` | Items per page |

The `Link` header is included for navigation:

```
Link: </api/v1/servers?page=1&per_page=20>; rel="first",
      </api/v1/servers?page=3&per_page=20>; rel="next",
      </api/v1/servers?page=8&per_page=20>; rel="last"
```

---

## Error Format

All errors return a consistent JSON body:

```json
{
  "code": "SERVER_NOT_FOUND",
  "message": "Server with ID 'abc' not found.",
  "details": null,
  "request_id": "req_abc123",
  "retryable": false,
  "documentation_url": "/docs/errors#SERVER_NOT_FOUND"
}
```

| Field | Type | Description |
|---|---|---|
| `code` | `string` | Machine-readable error code (SCREAMING_SNAKE_CASE) |
| `message` | `string` | Human-readable description |
| `details` | `object\|null` | Additional context (e.g. validation errors) |
| `request_id` | `string` | Correlates to the server-side trace |
| `retryable` | `boolean` | Whether the client may safely retry |
| `documentation_url` | `string\|null` | Link to detailed error documentation |

### Common Error Codes

| Code | HTTP Status | Description |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Request body or parameters failed validation |
| `UNAUTHORIZED` | 401 | Missing or expired JWT |
| `FORBIDDEN` | 403 | Authenticated but lacks permission |
| `NOT_FOUND` | 404 | Resource does not exist |
| `CONFLICT` | 409 | Resource state conflict (e.g. duplicate name) |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Unexpected server error |
| `SERVICE_UNAVAILABLE` | 503 | Temporary outage (retryable) |
| `SERVER_NOT_FOUND` | 404 | Server ID not found |
| `BACKUP_IN_PROGRESS` | 409 | A backup is already running |
| `PLUGIN_DEPENDENCY_MISSING` | 422 | Plugin dependency not satisfied |
| `INVALID_CREDENTIALS` | 401 | Email/password mismatch |
| `TOKEN_EXPIRED` | 401 | Access token expired, refresh required |

---

## Rate Limiting

Every response includes rate-limit headers:

| Header | Description |
|---|---|
| `X-RateLimit-Limit` | Maximum requests per window |
| `X-RateLimit-Remaining` | Remaining requests in current window |
| `X-RateLimit-Reset` | Unix timestamp when the window resets |

**Default limits** (per-IP for unauthenticated, per-user for authenticated):

| Scope | Limit | Window |
|---|---|---|
| Unauthenticated | 60 | 1 minute |
| Authenticated | 300 | 1 minute |
| `/auth/login` | 10 | 1 minute |
| WebSocket messages | 60 | 1 minute |

Exceeding the limit returns `429 Too Many Requests` with a `Retry-After` header.

---

## Endpoints

### Auth

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/login` | Email + password → JWT pair |
| `POST` | `/auth/refresh` | Refresh token → new JWT pair |
| `POST` | `/auth/logout` | Revoke refresh token |

#### `POST /auth/login`

```json
// Request
{
  "email": "user@example.com",
  "password": "••••••••"
}

// Response 200
{
  "data": {
    "access_token": "eyJ...",
    "refresh_token": "eyJ...",
    "token_type": "Bearer",
    "expires_in": 900
  }
}
```

#### `POST /auth/refresh`

```json
// Request
{
  "refresh_token": "eyJ..."
}

// Response 200
{
  "data": {
    "access_token": "eyJ...",
    "refresh_token": "eyJ...",
    "token_type": "Bearer",
    "expires_in": 900
  }
}
```

---

### Servers

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/servers` | List servers |
| `POST` | `/servers` | Create a server |
| `GET` | `/servers/{id}` | Server details |
| `PUT` | `/servers/{id}` | Update server configuration |
| `DELETE` | `/servers/{id}` | Delete a server |
| `POST` | `/servers/{id}/start` | Start the server process |
| `POST` | `/servers/{id}/stop` | Stop the server process |
| `POST` | `/servers/{id}/restart` | Restart the server process |
| `POST` | `/servers/{id}/kill` | Force-kill the server process |
| `POST` | `/servers/{id}/console` | Send a console command |
| `GET` | `/servers/{id}/log` | Fetch log lines |

#### `GET /servers`

```json
// Response 200
{
  "data": [
    {
      "id": "srv_abc123",
      "name": "Survival World",
      "type": "vanilla",
      "version": "1.21",
      "status": "running",
      "players_online": 3,
      "max_players": 20,
      "created_at": "2025-01-15T10:00:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 5,
    "total_pages": 1
  }
}
```

**Query parameters:** `name` (filter), `type` (filter), `status` (filter), `page`, `per_page`.

#### `POST /servers`

```json
// Request
{
  "name": "Survival World",
  "type": "vanilla",
  "version": "1.21",
  "port": 25565,
  "max_players": 20,
  "memory_mb": 2048,
  "motd": "Welcome!"
}

// Response 201
{
  "data": {
    "id": "srv_abc123",
    "name": "Survival World",
    "status": "stopped",
    "created_at": "2025-01-15T10:00:00Z"
  }
}
```

#### `GET /servers/{id}`

```json
// Response 200
{
  "data": {
    "id": "srv_abc123",
    "name": "Survival World",
    "type": "vanilla",
    "version": "1.21",
    "status": "running",
    "port": 25565,
    "max_players": 20,
    "memory_mb": 2048,
    "motd": "Welcome!",
    "players_online": 3,
    "uptime_seconds": 86400,
    "created_at": "2025-01-15T10:00:00Z",
    "started_at": "2025-01-20T08:00:00Z"
  }
}
```

#### `PUT /servers/{id}`

```json
// Request (partial update — only included fields are changed)
{
  "max_players": 30,
  "motd": "Updated MOTD"
}

// Response 200
{
  "data": {
    "id": "srv_abc123",
    "name": "Survival World",
    "max_players": 30,
    "motd": "Updated MOTD"
  }
}
```

#### `DELETE /servers/{id}`

Returns `204 No Content` on success. Returns `404 NOT_FOUND` if the server does not exist.

#### `POST /servers/{id}/start`

```json
// Response 200
{
  "data": {
    "id": "srv_abc123",
    "status": "starting"
  }
}
```

#### `POST /servers/{id}/stop`

Returns `202 Accepted` — the server will stop asynchronously. Track progress via the returned task ID or WebSocket events.

```json
{
  "data": {
    "task_id": "task_xyz",
    "status": "stopping"
  }
}
```

#### `POST /servers/{id}/console`

```json
// Request
{
  "command": "say Hello, world!"
}

// Response 200
{
  "data": {
    "sent": true
  }
}
```

#### `GET /servers/{id}/log`

| Query Parameter | Type | Default | Description |
|---|---|---|---|
| `tail` | integer | `100` | Number of most recent lines |
| `follow` | boolean | `false` | If `true`, upgrades to a streaming response |

```json
// Response 200
{
  "data": {
    "lines": [
      {"timestamp": "2025-01-20T08:00:01Z", "level": "INFO", "message": "Server started"},
      {"timestamp": "2025-01-20T08:00:02Z", "level": "INFO", "message": "Done!"}
    ]
  }
}
```

---

### Backups

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/servers/{id}/backups` | List backups for a server |
| `POST` | `/servers/{id}/backups` | Create a new backup |
| `GET` | `/servers/{id}/backups/{bid}` | Backup details |
| `POST` | `/servers/{id}/backups/{bid}/restore` | Restore a backup |
| `DELETE` | `/servers/{id}/backups/{bid}` | Delete a backup |

#### `GET /servers/{id}/backups`

```json
// Response 200
{
  "data": [
    {
      "id": "bak_xyz",
      "server_id": "srv_abc123",
      "size_bytes": 524288000,
      "status": "completed",
      "created_at": "2025-01-19T00:00:00Z"
    }
  ],
  "pagination": { "page": 1, "per_page": 20, "total": 3, "total_pages": 1 }
}
```

#### `POST /servers/{id}/backups`

```json
// Request
{
  "description": "Pre-update snapshot"
}

// Response 201
{
  "data": {
    "id": "bak_xyz",
    "status": "running",
    "progress_pct": 0
  }
}
```

The backup progresses asynchronously. Subscribe to `backup.progress` WebSocket events.

#### `POST /servers/{id}/backups/{bid}/restore`

Returns `202 Accepted`. The server will be stopped, restored, and restarted asynchronously.

```json
{
  "data": {
    "task_id": "task_abc",
    "status": "restoring"
  }
}
```

---

### Plugins

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/servers/{id}/plugins` | List installed plugins |
| `POST` | `/servers/{id}/plugins` | Install a plugin |
| `GET` | `/servers/{id}/plugins/{pid}` | Plugin details |
| `POST` | `/servers/{id}/plugins/{pid}/enable` | Enable a plugin |
| `POST` | `/servers/{id}/plugins/{pid}/disable` | Disable a plugin |
| `DELETE` | `/servers/{id}/plugins/{pid}` | Uninstall a plugin |

#### `POST /servers/{id}/plugins`

```json
// Request (multipart/form-data or URL)
{
  "source": "https://example.com/plugin.jar",
  "version": "1.0.0"
}

// Response 201
{
  "data": {
    "id": "plg_xyz",
    "name": "EssentialsX",
    "version": "1.0.0",
    "enabled": true,
    "server_id": "srv_abc123"
  }
}
```

---

### Users

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/users` | List users (admin only) |
| `POST` | `/users` | Create a user (admin only) |
| `GET` | `/users/{id}` | User details |
| `PUT` | `/users/{id}` | Update user |
| `DELETE` | `/users/{id}` | Delete user (admin only) |

#### `GET /users/{id}`

```json
// Response 200
{
  "data": {
    "id": "usr_abc",
    "email": "user@example.com",
    "display_name": "Alex",
    "role": "admin",
    "created_at": "2025-01-01T00:00:00Z"
  }
}
```

### API Keys (nested under users)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/users/{id}/keys` | List API keys |
| `POST` | `/users/{id}/keys` | Create a new API key |
| `DELETE` | `/users/{id}/keys/{kid}` | Revoke an API key |

#### `POST /users/{id}/keys`

```json
// Request
{
  "label": "CI/CD Pipeline"
}

// Response 201
{
  "data": {
    "id": "key_abc",
    "label": "CI/CD Pipeline",
    "key": "mcs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "created_at": "2025-01-20T12:00:00Z"
  }
}
```

> **Note:** The full key value is returned **only at creation**. Store it immediately.

---

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health/status/{id}` | Get server health status |
| `POST` | `/health/evaluate/{id}` | Trigger health evaluation |
| `GET` | `/health/timeline/{id}` | Get health timeline entries |
| `GET` | `/health/dashboard` | Aggregated health dashboard |

#### `GET /health/status/{server_id}`

```json
// Response 200
{
  "data": {
    "server_id": "srv_abc123",
    "status": "healthy",
    "previous_status": "warning",
    "contributing_factors": ["All checks passed"],
    "trend": "improving",
    "confidence": 0.95,
    "last_updated": "2025-01-20T12:00:00Z"
  }
}
```

Status values: `healthy`, `warning`, `critical`, `broken`, `unknown`, `pending`.

#### `POST /health/evaluate/{server_id}`

Triggers a health evaluation for the server. Returns the computed status.

```json
// Response 200
{
  "data": {
    "server_id": "srv_abc123",
    "status": "healthy"
  }
}
```

#### `GET /health/timeline/{server_id}`

Returns the health state change history for a server.

| Query Parameter | Type | Default | Description |
|-----------------|------|---------|-------------|
| `limit` | integer | `100` | Number of entries |

```json
// Response 200
{
  "data": {
    "entries": [
      {
        "server_id": "srv_abc123",
        "previous_status": "pending",
        "new_status": "healthy",
        "contributing_factors": ["All checks passed"],
        "timestamp": "2025-01-20T12:00:00Z"
      }
    ]
  }
}
```

#### `GET /health/dashboard`

```json
// Response 200
{
  "data": {
    "total_servers": 5,
    "healthy": 3,
    "warning": 1,
    "critical": 1,
    "broken": 0,
    "unknown": 0,
    "pending": 0,
    "servers": [
      {
        "server_id": "srv_abc123",
        "status": "healthy",
        "trend": "stable",
        "contributing_factors": [],
        "last_updated": "2025-01-20T12:00:00Z"
      }
    ]
  }
}
```

---

### Monitoring

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/monitor/health` | System health summary |
| `GET` | `/monitor/metrics` | Prometheus-formatted metrics |
| `GET` | `/monitor/servers/{id}/stats` | Per-server resource stats |

#### `GET /monitor/health`

```json
// Response 200
{
  "data": {
    "status": "healthy",
    "database": "connected",
    "redis": "connected",
    "uptime_seconds": 3600,
    "version": "1.0.0"
  }
}
```

#### `GET /monitor/servers/{id}/stats`

```json
// Response 200
{
  "data": {
    "server_id": "srv_abc123",
    "cpu_pct": 12.5,
    "memory_mb": 1024,
    "disk_mb": 4096,
    "players_online": 3,
    "tps": 19.8,
    "updated_at": "2025-01-20T12:00:00Z"
  }
}
```

---

### Tasks

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/tasks` | List scheduled and running tasks |
| `GET` | `/tasks/{id}` | Task details and status |
| `POST` | `/tasks/{id}/cancel` | Cancel a running task |

#### `GET /tasks/{id}`

```json
// Response 200
{
  "data": {
    "id": "task_abc",
    "type": "backup",
    "status": "running",
    "progress_pct": 45,
    "created_at": "2025-01-20T11:00:00Z",
    "started_at": "2025-01-20T11:00:05Z",
    "completed_at": null,
    "error": null
  }
}
```

---

## WebSocket Protocol

**Endpoint:** `wss://<host>/ws/v1?token=<jwt>`

The JWT or API key is passed as a query parameter. The connection is authenticated on upgrade; invalid tokens receive a 401 close frame.

### Event Format

All WebSocket messages are JSON-encoded:

```json
{
  "event": "server.status",
  "data": { ... },
  "timestamp": "2025-01-20T12:00:00Z"
}
```

### Server-to-Client Events

| Event | Payload | Description |
|---|---|---|
| `server.status` | `{ id, status, players_online, tps }` | Server state change |
| `server.log` | `{ id, lines: [{timestamp, level, message}] }` | New log lines |
| `server.console` | `{ id, line }` | Console output line |
| `backup.progress` | `{ id, server_id, progress_pct, status }` | Backup job progress |
| `backup.completed` | `{ id, server_id, size_bytes }` | Backup finished |
| `plugin.status` | `{ id, server_id, name, enabled }` | Plugin enabled/disabled |
| `plugin.installed` | `{ id, server_id, name, version }` | Plugin installed |
| `metrics` | `{ server_id, cpu_pct, memory_mb, tps }` | Periodic metrics tick |
| `task.status` | `{ id, type, status, progress_pct }` | Task state change |
| `health.status` | `{ server_id, status, previous_status, contributing_factors, trend }` | Health state change |
| `health.crash_classified` | `{ server_id, failure_code, confidence, summary }` | Crash classified |
| `health.alarm` | `{ server_id, alert_type, current_value, threshold }` | Health alert triggered |

### Client-to-Server Commands

| Command | Payload | Description |
|---|---|---|
| `subscribe` | `{ events: ["server.status", "metrics"] }` | Subscribe to event types |
| `unsubscribe` | `{ events: ["metrics"] }` | Unsubscribe from event types |
| `ping` | `{}` | Keepalive ping |

### Rate Limiting

Clients may send up to **60 messages per minute**. Excessive messages trigger a 4409 close frame with a 30-second reconnection ban.

### Reconnection

After an unexpected disconnect, clients should reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s). Include the last received event timestamp to resume from:

```
wss://<host>/ws/v1?token=<jwt>&since=2025-01-20T11:59:00Z
```

The server will replay events from that timestamp, subject to a 5-minute replay buffer.
