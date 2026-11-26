import { describe, it, expect } from "vitest";
import * as telemetryAdapter from "./telemetryAdapter";
import { computeCpuHistory, computeServerCounts, getHostTelemetry } from "./telemetryAdapter";
import type { ServerResponse } from "@/server_manager/types";
import type { BackupResponse, HostResourceBudget, ScheduleResponse } from "@/types";
import type { MetricsSnapshot } from "@/services/api";

function makeServer(overrides: Partial<ServerResponse> = {}): ServerResponse {
  return {
    server_id: "srv-1",
    name: "Survival",
    server_type: "paper",
    minecraft_version: "1.21.4",
    status: "running",
    group_id: "default",
    port: 25565,
    motd: "",
    max_players: 20,
    gamemode: "survival",
    difficulty: "normal",
    max_memory_mb: 4096,
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

const sampleBudget: HostResourceBudget = {
  total_ram_mb: 16384,
  os_reserve_ram_mb: 4096,
  allocatable_ram_mb: 12288,
  allocated_ram_mb: 4096,
  available_ram_mb: 8192,
  total_cpus: 8,
  reserved_cpus: 2,
  allocatable_cpus: 6,
  allocated_cpus: 0,
  available_cpus: 6,
  profile: "local",
  ram_reserve_override_mb: 0,
  cpu_reserve_override: 0,
  allocations: [
    {
      id: "srv-1",
      name: "Survival",
      kind: "server",
      status: "running",
      ram_mb: 4096,
      cpu_cores: 0,
    },
  ],
};

describe("telemetryAdapter (honest telemetry math)", () => {
  it("does not expose fabricated getInitialDaemonLogs helper", () => {
    expect("getInitialDaemonLogs" in telemetryAdapter).toBe(false);
  });

  it("computes real backup bytes, counts, and schedules without fake 0.5 GB per-server fallback", () => {
    const servers = [makeServer({ server_id: "s1" }), makeServer({ server_id: "s2", status: "stopped" })];
    const backups: BackupResponse[] = [
      {
        backup_id: "b1",
        server_id: "s1",
        backup_type: "full",
        status: "completed",
        size_bytes: 512 * 1024 * 1024,
        checksum: "abc",
        error_message: "",
        created_at: "2026-11-23T10:00:00Z",
        completed_at: "2026-11-23T10:02:00Z",
        tier: "tier_1",
        pinned: false,
      },
      {
        backup_id: "b2",
        server_id: "s1",
        backup_type: "full",
        status: "failed_timeout",
        size_bytes: 100 * 1024 * 1024,
        checksum: "",
        error_message: "Timeout",
        created_at: "2026-11-23T11:00:00Z",
        completed_at: null,
        tier: "tier_1",
        pinned: false,
      },
    ];
    const schedules: ScheduleResponse[] = [
      {
        id: "sch-1",
        name: "Nightly",
        cron_expression: "0 3 * * *",
        task_name: "backup",
        params: { server_id: "s1" },
        enabled: true,
        last_run_at: null,
        created_at: null,
      },
      {
        id: "sch-2",
        name: "Paused",
        cron_expression: "0 6 * * *",
        task_name: "restart",
        params: { server_id: "s1" },
        enabled: false,
        last_run_at: null,
        created_at: null,
      },
    ];

    const emptyRes = getHostTelemetry({
      servers,
      snapshotsByServerId: {},
      backups: [],
      schedules: [],
    });
    expect(emptyRes.backupTotalBytes).toBe(0);
    expect(emptyRes.backupCompletedCount).toBe(0);
    expect(emptyRes.lastBackupRelative).toBe("None");
    expect(emptyRes.activeSchedulesCount).toBe(0);

    const populated = getHostTelemetry({
      servers,
      snapshotsByServerId: {},
      backups,
      schedules,
    });
    expect(populated.backupTotalBytes).toBe((512 + 100) * 1024 * 1024);
    expect(populated.backupCompletedCount).toBe(1);
    expect(populated.backupFailedCount).toBe(1);
    expect(populated.backupTotalCount).toBe(2);
    expect(populated.activeSchedulesCount).toBe(1);
    expect(populated.lastBackupRelative).not.toBe("None");
  });

  it("sums multi-server CPU samples per 5s timestamp bucket without dropping earlier servers or fabricating 20 flat points", () => {
    const snapshots: Record<string, MetricsSnapshot[]> = {
      "srv-1": [
        { timestamp: "2026-11-23T12:00:00Z", cpu_percent: 12.5, ram_used_mb: 1024, tps: 20, players: 2 },
        { timestamp: "2026-11-23T12:00:05Z", cpu_percent: 25.0, ram_used_mb: 1024, tps: 20, players: 2 },
      ],
      "srv-2": [
        { timestamp: "2026-11-23T12:00:01Z", cpu_percent: 20.0, ram_used_mb: 1024, tps: 19.5, players: 1 },
        { timestamp: "2026-11-23T12:00:07Z", cpu_percent: 40.0, ram_used_mb: 1024, tps: 19.5, players: 1 },
      ],
    };

    const history = computeCpuHistory(["srv-1", "srv-2"], snapshots);
    expect(history).toEqual([32.5, 65]);

    const singleSample = computeCpuHistory(["srv-1"], {
      "srv-1": [{ timestamp: "2026-11-23T12:00:00Z", cpu_percent: 18.2, ram_used_mb: 1024, tps: 20, players: 1 }],
    });
    expect(singleSample).toEqual([18.2]);
  });

  it("keeps live RSS, active allocated RAM, and host available RAM mathematically consistent and excludes stopped servers", () => {
    const servers = [
      makeServer({ server_id: "srv-1", status: "running", max_memory_mb: 4096 }),
      makeServer({ server_id: "srv-2", status: "stopped", max_memory_mb: 8192 }),
      makeServer({ server_id: "srv-3", status: "provisioning_failed", max_memory_mb: 2048 }),
    ];

    const counts = computeServerCounts(servers);
    expect(counts.onlineCount).toBe(1);
    expect(counts.offlineCount).toBe(1);
    expect(counts.crashedCount).toBe(1);
    expect(counts.attentionCount).toBe(1);

    // Without hostBudget: stopped/failed servers must not inflate activeAllocatedMb
    const withoutBudget = getHostTelemetry({
      servers,
      snapshotsByServerId: {
        "srv-1": [
          { timestamp: "2026-11-23T12:00:00Z", cpu_percent: 34.5, ram_used_mb: 2457.6, tps: 19.8, players: 3 },
        ],
      },
    });
    expect(withoutBudget.liveRssMb).toBe(2457.6);
    expect(withoutBudget.activeAllocatedMb).toBe(4096);
    expect(withoutBudget.availableRamMb).toBeNull();
    expect(withoutBudget.allocatableRamMb).toBeNull();

    // With hostBudget: matches hostBudget.available_ram_mb to the exact decimal
    const withBudget = getHostTelemetry({
      servers,
      hostBudget: sampleBudget,
      snapshotsByServerId: {
        "srv-1": [
          { timestamp: "2026-11-23T12:00:00Z", cpu_percent: 34.5, ram_used_mb: 2457.6, tps: 19.8, players: 3 },
        ],
      },
    });
    expect(withBudget.activeAllocatedMb).toBe(4096);
    expect(withBudget.availableRamMb).toBe(8192);
    expect(withBudget.allocatableRamMb).toBe(12288);
    expect(withBudget.liveRssOfAllocatedPct).toBe(60);
  });
});
