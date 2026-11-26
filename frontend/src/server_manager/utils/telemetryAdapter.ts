import type { ServerResponse } from "@/server_manager/types";
import type { BackupResponse, HostResourceBudget, ScheduleResponse } from "@/types";
import type { MetricsSnapshot } from "@/services/api";
import type { ServerLiveTelemetry } from "@/server_manager/components/servers/serversUtils";
import { formatRelativeTime, parseServerDate } from "@/server_manager/utils/format";

export interface ServerStatusCounts {
  onlineCount: number;
  offlineCount: number;
  crashedCount: number;
  startingCount: number;
  stoppingCount: number;
  attentionCount: number;
}

export interface HostTelemetryMetrics {
  onlinePlayers: number;
  maxPlayers: number;
  tpsAvg: number | null;
  cpuPercent: number;
  cpuHistory: number[];
  liveRssMb: number;
  liveRssGb: number;
  activeAllocatedMb: number;
  activeAllocatedGb: number;
  allocatableRamMb: number | null;
  allocatableRamGb: number | null;
  availableRamMb: number | null;
  availableRamGb: number | null;
  liveRssOfAllocatedPct: number;
  backupTotalBytes: number;
  backupCompletedCount: number;
  backupFailedCount: number;
  backupTotalCount: number;
  lastBackupRelative: string;
  activeSchedulesCount: number | null;
}

export interface GetHostTelemetryInput {
  servers: ServerResponse[];
  snapshotsByServerId: Record<string, MetricsSnapshot[]>;
  metricsByServerId?: Record<string, ServerLiveTelemetry>;
  hostBudget?: HostResourceBudget | null;
  backups?: BackupResponse[] | null;
  schedules?: ScheduleResponse[] | null;
}

function roundTo1(value: number): number {
  return Math.round(value * 10) / 10;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function formatRamGb(mb: number): string {
  return `${roundTo1(Math.max(0, mb) / 1024).toFixed(1)} GB`;
}

export function computeServerCounts(servers: ServerResponse[]): ServerStatusCounts {
  let onlineCount = 0;
  let offlineCount = 0;
  let crashedCount = 0;
  let startingCount = 0;
  let stoppingCount = 0;

  for (const s of servers) {
    if (s.status === "running") {
      onlineCount += 1;
    } else if (s.status === "starting" || s.status === "provisioning") {
      startingCount += 1;
    } else if (s.status === "stopping") {
      stoppingCount += 1;
    } else if (
      s.status === "crashed" ||
      s.status === "broken" ||
      s.status === "provisioning_failed"
    ) {
      crashedCount += 1;
    } else {
      offlineCount += 1;
    }
  }

  return {
    onlineCount,
    offlineCount,
    crashedCount,
    startingCount,
    stoppingCount,
    attentionCount: crashedCount,
  };
}

/**
 * Aggregate per-server CPU snapshots into timestamp-aligned 5-second buckets
 * across all running servers so multi-server history never drops earlier nodes.
 * Returns only real samples (no fabricated flat baseline when fewer than 2 samples exist).
 */
export function computeCpuHistory(
  runningServerIds: string[],
  snapshotsByServerId: Record<string, MetricsSnapshot[]>,
  bucketSeconds = 5,
  maxPoints = 20,
): number[] {
  if (runningServerIds.length === 0) return [];

  const bucketMs = bucketSeconds * 1000;
  const buckets = new Map<number, Map<string, number>>();

  for (const serverId of runningServerIds) {
    const raw = snapshotsByServerId[serverId];
    if (!Array.isArray(raw) || raw.length === 0) continue;

    const ordered = raw
      .map((snap, idx) => ({
        snap,
        idx,
        parsedMs: parseServerDate(snap.timestamp)?.getTime() ?? null,
      }))
      .sort((a, b) => {
        if (a.parsedMs !== null && b.parsedMs !== null) {
          return a.parsedMs - b.parsedMs;
        }
        return a.idx - b.idx;
      });

    for (const entry of ordered) {
      const cpu = Number(entry.snap.cpu_percent);
      if (!Number.isFinite(cpu)) continue;
      const bucketKey =
        entry.parsedMs !== null
          ? Math.floor(entry.parsedMs / bucketMs) * bucketMs
          : entry.idx;

      let bucket = buckets.get(bucketKey);
      if (!bucket) {
        bucket = new Map<string, number>();
        buckets.set(bucketKey, bucket);
      }
      bucket.set(serverId, Math.max(0, cpu));
    }
  }

  const sortedKeys = Array.from(buckets.keys()).sort((a, b) => a - b);
  const recentKeys = sortedKeys.slice(-maxPoints);

  return recentKeys.map((key) => {
    const bucket = buckets.get(key);
    if (!bucket) return 0;
    let sum = 0;
    for (const val of bucket.values()) {
      sum += val;
    }
    return roundTo1(clamp(sum, 0, 100));
  });
}

function pickLatestSnapshot(snapshots: MetricsSnapshot[] | undefined): MetricsSnapshot | undefined {
  if (!Array.isArray(snapshots) || snapshots.length === 0) return undefined;
  let latest = snapshots[0];
  let latestMs = parseServerDate(latest.timestamp)?.getTime() ?? 0;

  for (let i = 1; i < snapshots.length; i += 1) {
    const cur = snapshots[i];
    const curMs = parseServerDate(cur.timestamp)?.getTime() ?? 0;
    if (curMs > latestMs || (curMs === latestMs && cur.timestamp > latest.timestamp)) {
      latest = cur;
      latestMs = curMs;
    }
  }
  return latest;
}

export function getHostTelemetry({
  servers,
  snapshotsByServerId,
  metricsByServerId,
  hostBudget,
  backups,
  schedules,
}: GetHostTelemetryInput): HostTelemetryMetrics {
  const runningServers = servers.filter((s) => s.status === "running");
  const runningServerIds = runningServers.map((s) => s.server_id);

  let onlinePlayers = 0;
  let maxPlayers = 0;
  let cpuPercentRaw = 0;
  let liveRssMbRaw = 0;
  let tpsSum = 0;
  let tpsCount = 0;

  for (const s of runningServers) {
    maxPlayers += s.max_players || 20;
    const latest = pickLatestSnapshot(snapshotsByServerId[s.server_id]);
    const fallback = metricsByServerId?.[s.server_id];

    const players = latest?.players ?? fallback?.players ?? 0;
    if (players !== null) {
      onlinePlayers += players;
    }

    const cpu = latest?.cpu_percent ?? fallback?.cpuPercent ?? 0;
    if (cpu !== null && Number.isFinite(cpu)) {
      cpuPercentRaw += Math.max(0, cpu);
    }

    const ramUsed = latest?.ram_used_mb ?? fallback?.ramUsedMb ?? 0;
    if (ramUsed !== null && Number.isFinite(ramUsed)) {
      liveRssMbRaw += Math.max(0, ramUsed);
    }

    const tps = latest?.tps ?? fallback?.tps ?? null;
    if (tps !== null && Number.isFinite(tps) && tps > 0) {
      tpsSum += tps;
      tpsCount += 1;
    }
  }

  const liveRssMb = Math.round(liveRssMbRaw * 10) / 10;
  const activeAllocatedMb =
    typeof hostBudget?.allocated_ram_mb === "number"
      ? hostBudget.allocated_ram_mb
      : servers.reduce((sum, s) => {
          const isActive =
            s.status === "running" ||
            s.status === "starting" ||
            s.status === "provisioning";
          return sum + (isActive ? Math.max(0, s.max_memory_mb ?? 0) : 0);
        }, 0);

  const allocatableRamMb =
    typeof hostBudget?.allocatable_ram_mb === "number"
      ? hostBudget.allocatable_ram_mb
      : null;
  const availableRamMb =
    typeof hostBudget?.available_ram_mb === "number"
      ? hostBudget.available_ram_mb
      : null;

  const liveRssOfAllocatedPct =
    activeAllocatedMb > 0
      ? roundTo1(clamp((liveRssMb / activeAllocatedMb) * 100, 0, 100))
      : 0;

  const backupList = Array.isArray(backups) ? backups : [];
  let backupTotalBytes = 0;
  let backupCompletedCount = 0;
  let backupFailedCount = 0;
  let latestCompletedTs = 0;
  let latestCompletedAt: string | null = null;

  for (const b of backupList) {
    backupTotalBytes += Math.max(0, Number(b.size_bytes) || 0);
    if (b.status === "completed") {
      backupCompletedCount += 1;
      const dateCandidate = b.completed_at || b.created_at;
      const ms = parseServerDate(dateCandidate)?.getTime() ?? 0;
      if (ms > latestCompletedTs) {
        latestCompletedTs = ms;
        latestCompletedAt = dateCandidate;
      }
    } else if (b.status === "failed" || b.status === "failed_timeout") {
      backupFailedCount += 1;
    }
  }

  const activeSchedulesCount = Array.isArray(schedules)
    ? schedules.filter((sch) => sch.enabled !== false).length
    : null;

  return {
    onlinePlayers,
    maxPlayers,
    tpsAvg: tpsCount > 0 ? roundTo1(tpsSum / tpsCount) : null,
    cpuPercent: roundTo1(cpuPercentRaw),
    cpuHistory: computeCpuHistory(runningServerIds, snapshotsByServerId),
    liveRssMb,
    liveRssGb: roundTo1(liveRssMb / 1024),
    activeAllocatedMb,
    activeAllocatedGb: roundTo1(activeAllocatedMb / 1024),
    allocatableRamMb,
    allocatableRamGb: allocatableRamMb !== null ? roundTo1(allocatableRamMb / 1024) : null,
    availableRamMb,
    availableRamGb: availableRamMb !== null ? roundTo1(availableRamMb / 1024) : null,
    liveRssOfAllocatedPct,
    backupTotalBytes,
    backupCompletedCount,
    backupFailedCount,
    backupTotalCount: backupList.length,
    lastBackupRelative: latestCompletedAt
      ? formatRelativeTime(latestCompletedAt) || "Just now"
      : "None",
    activeSchedulesCount,
  };
}
