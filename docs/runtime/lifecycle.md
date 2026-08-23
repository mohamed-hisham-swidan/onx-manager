# Server Lifecycle State Machine

**Status:** Living Reference (Synchronized with live codebase)  
**Aggregate Root:** `Server` (`backend/app/modules/server/domain/aggregate.py`)  
**Total States:** 8 `ServerStatus` states

---

## 1. State Definitions

| State | Enum Value | Description |
|---|---|---|
| `CREATED` | `"created"` | Server record created in database; files provisioned on disk, ready to start. |
| `PROVISIONING` | `"provisioning"` | Asynchronous Forge/NeoForge auto-installer running in background. |
| `PROVISIONING_FAILED` | `"provisioning_failed"` | Auto-installation encountered error (transient network failure, corrupt download, or bad installer). |
| `STARTING` | `"starting"` | Launch command executed; supervisor waiting for port bind and "Done (" console confirmation. |
| `RUNNING` | `"running"` | Process active, port bound, heartbeat verified by `RuntimeSupervisor`. |
| `STOPPING` | `"stopping"` | Graceful `/stop` command issued; waiting for process exit within timeout. |
| `STOPPED` | `"stopped"` | Process terminated cleanly; all OS resources released. |
| `CRASHED` | `"crashed"` | Process died unexpectedly, PID lost, or heartbeat verification failed. |

---

## 2. State Transition Diagram

```
                 ┌───────────────┐
                 │    CREATED    │
                 └───────┬───────┘
                         │ Start
                         v
  ┌──────────────┐ Start ┌───────────────┐ Auto-Install ┌─────────────────────┐
  │ PROVISIONING ├──────►│   STARTING    │◄─────────────┤ PROVISIONING_FAILED │
  └──────┬───────┘       └───────┬───────┘ (Retry)      └──────────▲──────────┘
         │                       │                                 │
         │ Fail                  │ Ready ("Done")                  │ Fail
         └───────────────────────┼─────────────────────────────────┘
                                 │
                                 v
                         ┌───────────────┐
            ┌───────────►│    RUNNING    │◄───────────┐
            │            └───────┬───────┘            │
            │                    │                    │
            │ Auto-Recovery      │ Stop               │ Restart
            │                    v                    │
    ┌───────┴───────┐    ┌───────────────┐            │
    │    CRASHED    │    │   STOPPING    │────────────┘
    └───────▲───────┘    └───────┬───────┘
            │                    │ Exit
            │ Unexpected Death   v
            └────────────┌───────────────┐
                         │    STOPPED    │
                         └───────────────┘
```

---

## 3. Valid Transitions Matrix (`_SERVER_TRANSITIONS`)

```python
_SERVER_TRANSITIONS = {
    ServerStatus.CREATED: {ServerStatus.STARTING, ServerStatus.PROVISIONING},
    ServerStatus.PROVISIONING: {ServerStatus.CREATED, ServerStatus.STARTING, ServerStatus.PROVISIONING_FAILED},
    ServerStatus.PROVISIONING_FAILED: {ServerStatus.PROVISIONING, ServerStatus.STARTING},
    ServerStatus.STARTING: {ServerStatus.RUNNING, ServerStatus.STOPPING, ServerStatus.CRASHED, ServerStatus.STOPPED},
    ServerStatus.RUNNING: {ServerStatus.STOPPING, ServerStatus.CRASHED, ServerStatus.STARTING},
    ServerStatus.STOPPING: {ServerStatus.STOPPED, ServerStatus.CRASHED},
    ServerStatus.STOPPED: {ServerStatus.STARTING},
    ServerStatus.CRASHED: {ServerStatus.STARTING, ServerStatus.STOPPED},
}
```
