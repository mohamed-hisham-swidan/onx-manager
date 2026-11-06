import { useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { useEffectiveConnectionState, useIsChannelDegraded } from "@/stores/wsStore";
import { Sparkline } from "./Sparkline";

function useApi() {
  return createAuthenticatedApi();
}

export const MAX_POINTS = 120;

interface ServerMetricsChartsProps {
  serverId: string;
}

export function ServerMetricsCharts({ serverId }: ServerMetricsChartsProps) {
  const api = useApi();

  const { data: metrics } = useQuery({
    queryKey: queryKeys.monitoring.metrics(serverId),
    queryFn: () => api.getMetrics(serverId, MAX_POINTS),
    refetchInterval: 5000,
  });

  const tpsData = (metrics ?? []).map((m) => m.tps).filter((t): t is number => t != null);
  const playersData = (metrics ?? []).map((m) => m.players);
  const ramData = (metrics ?? []).map((m) => m.ram_used_mb);
  const cpuData = (metrics ?? []).map((m) => m.cpu_percent);

  const current = metrics?.length
    ? metrics.reduce((latest, m) => (m.timestamp > latest.timestamp ? m : latest))
    : undefined;

  const connectionState = useEffectiveConnectionState();
  const metricsChannelDegraded = useIsChannelDegraded(`metrics:${serverId}`);
  const staleNote =
    connectionState === "reconnecting"
      ? { text: "Metrics not live — reconnecting...", color: "text-status-warning" }
      : connectionState === "connecting"
        ? { text: "Connecting to live metrics…", color: "text-text-muted" }
        : connectionState === "disconnected"
          ? { text: "Metrics not live — showing last known", color: "text-status-danger" }
          : metricsChannelDegraded
            ? { text: "Metrics not live — subscription rejected", color: "text-status-warning" }
            : null;

  const metricCards = [
    { label: "TPS", value: current?.tps != null ? current.tps.toFixed(1) : "—", data: tpsData, color: "var(--status-success)", fillColor: "var(--status-success-bg)" },
    { label: "Players", value: current?.players ?? "—", data: playersData, color: "var(--accent-primary)", fillColor: "var(--status-info-bg)" },
    { label: "RAM", value: current ? `${(current.ram_used_mb / 1024).toFixed(1)} GB` : "—", data: ramData, color: "var(--status-warning)", fillColor: "var(--status-warning-bg)" },
    { label: "CPU", value: current ? `${current.cpu_percent.toFixed(1)}%` : "—", data: cpuData, color: "var(--status-danger)", fillColor: "var(--status-danger-bg)" },
  ];

  return (
    <>
      {staleNote && (
        <p role="status" className={`mb-2 text-xs font-medium ${staleNote.color}`}>
          {staleNote.text}
        </p>
      )}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {metricCards.map((card) => (
          <div key={card.label} className="bg-surface-card rounded-xl border border-border-default p-3">
            <p className="text-xs text-text-muted mb-1">{card.label}</p>
            <p className="text-lg font-bold text-text-primary mb-2">{card.value}</p>
            <Sparkline data={card.data} color={card.color} fillColor={card.fillColor} />
          </div>
        ))}
      </div>
    </>
  );
}
