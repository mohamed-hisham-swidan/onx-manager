# Testing Guide

## Test Suites Overview

| Layer | Framework | Test Count | Location |
|---|---|---|---|
| Backend (unit + integration) | pytest + pytest-asyncio | 1070 collected / 1068 passing (2 pre-existing env failures) | `backend/tests/` |
| Frontend (component + unit) | Vitest + jsdom | 236 | `frontend/src/**/*.test.*` |

> Measured 2026-08-04. The 2 backend failures are environment issues, not regressions: `test_api_endpoints.py::TestServers::test_start_server` (closed-DB rollback) and `tests/tasks/test_metrics_collector.py::test_metrics_task_requires_collector` (stale expectation vs the graceful warning handler). See `docs/current-state.md` §4.

---

## Backend Testing

### Framework & Configuration

- **pytest** with `pytest-asyncio` for async test support
- `asyncio_mode = "auto"` — all test functions are automatically treated as async
- Test paths: `backend/tests/`
- Coverage: `pytest-cov`

```bash
# Run all backend tests
cd backend && pytest

# Run with coverage report
cd backend && pytest --cov=app

# Run a single module's tests (e.g. API endpoints)
cd backend && pytest tests/api/

# Run integration tests
cd backend && pytest tests/test_integration.py

# Run a specific test file
cd backend && pytest tests/auth/test_jwt.py

# Run tests matching a keyword
cd backend && pytest -k "websocket"

# Run with verbose output
cd backend && pytest -v

# Watch mode (re-run on changes)
cd backend && pytest-watch
```

### Test Structure

Tests mirror the module structure of the application:

```
backend/tests/
├── conftest.py                    # Shared fixtures: event_loop, buses, mock handler
├── test_command_bus.py
├── test_query_bus.py
├── test_event_bus.py
├── test_unit_of_work.py
├── test_websocket.py
├── test_integration.py
├── domain/                        # Aggregate and value object tests
│   ├── test_server_aggregate.py
│   ├── test_backup_aggregate.py
│   ├── test_plugin_aggregate.py
│   ├── test_plugin_registry.py
│   ├── test_user_aggregate.py
│   ├── test_monitoring_aggregate.py
│   ├── test_value_objects.py
│   ├── test_diagnostics.py
│   └── test_runtime_exceptions.py
├── application/                   # Command/query handler tests
│   ├── conftest.py
│   ├── test_server_commands.py
│   ├── test_server_queries.py
│   ├── test_backup_commands.py
│   ├── test_backup_queries.py
│   ├── test_plugin_commands.py
│   ├── test_plugin_queries.py
│   ├── test_monitoring_handlers.py
│   ├── test_sagas.py
│   ├── test_provisioning_integration.py
│   └── test_jar_service.py
├── infrastructure/                # Provider and repository tests
│   ├── test_providers.py
│   ├── test_repositories.py
│   ├── test_storage.py
│   ├── test_fs.py
│   ├── test_location.py
│   └── test_patterns.py
├── api/                           # API endpoint tests
│   └── test_api_endpoints.py
├── auth/                          # Authentication and authorization tests
│   ├── test_jwt.py
│   ├── test_password.py
│   ├── test_login_flow.py
│   ├── test_api_keys.py
│   ├── test_permissions.py
│   └── test_audit.py
├── plugin/                        # Plugin system tests
│   ├── test_manifest.py
│   ├── test_lifecycle.py
│   ├── test_sandbox.py
│   ├── test_subprocess_runner.py
│   ├── test_dependency_resolver.py
│   └── test_sdk.py
├── monitoring/                    # Monitoring tests
│   └── test_health.py
├── tasks/                         # Task queue and scheduler tests
│   ├── test_task_queue.py
│   ├── test_scheduler.py
│   ├── test_backup_task.py
│   ├── test_metrics_collector.py
│   └── test_cleanup.py
├── event_store/                   # Event store tests
│   ├── test_chain.py
│   ├── test_repository.py
│   └── test_dead_letter.py
├── test_idempotency.py
├── test_feature_flags.py
├── test_circuit_breaker.py
├── test_saga.py
├── test_config.py
├── test_exceptions.py
├── test_logging.py
├── test_security.py
└── test_database.py
```

### How to Write Tests

Tests follow the Arrange-Act-Assert pattern. Shared fixtures live in `conftest.py`:

```python
# tests/conftest.py — provides buses and mock handlers
@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture
async def command_bus() -> CommandBus:
    return CommandBus()

@pytest_asyncio.fixture
async def event_bus() -> EventBus:
    return EventBus()
```

Example test:

```python
@pytest.mark.asyncio
async def test_command_bus_dispatches_to_handler(command_bus: CommandBus):
    handler = MockHandler()
    command_bus.register("test.command", handler)
    result = await command_bus.dispatch("test.command", {"key": "value"})
    assert result == {"handled": True}
    assert len(handler.calls) == 1
```

### Mocking Strategy

- **MockHandler** (`backend/tests/conftest.py:42`) — records calls and optionally raises errors; used across all bus tests
- **InMemoryIdempotencyStore** — replaces the DB-backed store in tests
- **httpx.AsyncClient** — used for API endpoint tests via FastAPI's `TestClient` with async transport
- Infrastructure providers are mocked at their interface boundaries — tests never call real Docker or filesystem APIs in unit tests
- Integration tests (`test_integration.py`) exercise real component interaction with SQLite in-memory databases

---

## Frontend Testing

### Framework & Configuration

- **Vitest** with **jsdom** environment
- **@testing-library/react** for component rendering and interaction
- Vitest config: `frontend/vitest.config.ts`

```typescript
// vitest.config.ts
export default defineConfig({
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  test: {
    globals: true,
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    setupFiles: ["src/test-setup.ts"],
  },
});
```

```bash
# Run all frontend tests
cd frontend && npm test

# Run with watch mode
cd frontend && npm run test:watch

# Run with coverage
cd frontend && npx vitest run --coverage

# Run a specific test file
cd frontend && npx vitest run src/stores/authStore.test.ts
```

### Test Structure

```
frontend/src/
├── stores/
│   ├── authStore.test.ts           # Token management, login/logout
│   ├── uiStore.test.ts             # Theme, sidebar state
│   └── wsStore.test.ts             # WebSocket connection state
├── services/
│   └── api.test.ts                 # API client, auth injection, refresh
├── websocket/
│   ├── client.test.ts              # Connection, reconnect, ping
│   ├── handler.test.ts             # Message routing, cache callbacks
│   └── channels.test.ts            # Channel subscription, validation
├── components/
│   ├── guards/
│   │   └── AuthGuard.test.tsx
│   ├── layout/
│   │   ├── Sidebar.test.tsx
│   │   └── TopNav.test.tsx
│   ├── WebSocketManager.test.tsx
│   ├── EmptyState.test.tsx
│   ├── Skeleton.test.tsx
│   └── ErrorBoundary.test.tsx
├── server_manager/
│   ├── pages/
│   │   ├── DashboardPage.test.tsx
│   │   ├── ServersPage.test.tsx
│   │   ├── ServerDetailPage.test.tsx
│   │   ├── BackupListPage.test.tsx
│   │   ├── PluginListPage.test.tsx
│   │   ├── SettingsPage.test.tsx
│   │   └── ApiKeysPage.test.tsx
│   └── components/
│       ├── ServerConfigEditor.test.tsx
│       ├── InstallPluginDialog.test.tsx
│       ├── CreateBackupDialog.test.tsx
│       └── Sparkline.test.tsx
├── pages/
│   └── LoginPage.test.tsx
└── layouts/
    └── AppLayout.test.tsx
```

### How to Write Tests

Tests use `@testing-library/react` for rendering and `@testing-library/user-event` for interactions:

```typescript
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect } from "vitest";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders title and description", () => {
    render(<EmptyState title="No servers" description="Create your first server." />);
    expect(screen.getByText("No servers")).toBeInTheDocument();
    expect(screen.getByText("Create your first server.")).toBeInTheDocument();
  });

  it("fires action callback on button click", async () => {
    const onAction = vi.fn();
    render(<EmptyState title="Empty" actionLabel="Go" onAction={onAction} />);
    await userEvent.click(screen.getByText("Go"));
    expect(onAction).toHaveBeenCalledOnce();
  });
});
```

Key testing utilities:
- `vi.fn()` — Vitest's mock function (replaces Jest's `jest.fn()`)
- `render()` — from `@testing-library/react`
- `userEvent` — simulates user interactions (preferred over `fireEvent`)
- `screen.getByText()`, `screen.getByRole()`, etc. — query helpers

### Mocking Strategy

- **localStorage mock** — configured in `test-setup.ts` for auth store tests
- **matchMedia mock** — configured in `test-setup.ts` for dark mode detection
- **fetch/WebSocket** — mocked in service and websocket tests; actual connections never made
- **TanStack Query** — wrapped in `QueryClientProvider` with a fresh `QueryClient` for each test
- **Zustand stores** — tested directly; stores are reset between tests via `beforeEach`

### Coverage

```bash
cd frontend && npx vitest run --coverage
```

---

## Integration Testing (Planned)

End-to-end tests that exercise the full stack are planned. These will:

- Spin up the backend, PostgreSQL, and Redis via Docker Compose
- Run a headless frontend (Playwright) for browser-level tests
- Verify WebSocket reconnection, state sync, and auth token refresh
- Test real plugin installation and subprocess execution
- Benchmark metrics collection and retention pipeline

The integration suite will live in `backend/tests/e2e/` and use the existing Docker Compose profile.

---

## Test Commands Reference

| Command | Scope |
|---|---|
| `./scripts/test` | All backend tests |
| `cd backend && pytest` | All backend tests |
| `cd backend && pytest --cov=app` | Backend with coverage |
| `cd backend && pytest -k "pattern"` | Filtered backend tests |
| `cd frontend && npm test` | All frontend tests |
| `cd frontend && npm run test:watch` | Frontend watch mode |
| `cd frontend && npx vitest run --coverage` | Frontend with coverage |

## Quality Gates

Every PR must pass:

1. **Lint** — `ruff check .` (backend) / `npm run lint` (frontend)
2. **Type check** — `pyright` (backend) / `npm run typecheck` (frontend)
3. **All tests passing** — `pytest` (backend) / `npm test` (frontend)
4. **Coverage ≥ 90%** for new code

Run the full gate locally:

```bash
./scripts/check                           # Backend gate
cd frontend && npm run typecheck && npm run lint && npm test  # Frontend gate
```

See [Development Guide](DEVELOPMENT.md) for the complete development workflow.
