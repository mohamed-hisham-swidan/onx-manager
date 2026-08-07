import { useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { useWSStore } from "@/stores/wsStore";
import { Sparkline } from "./Sparkline";

function useApi() {
  return createAuthenticatedApi();
}

const MAX_POINTS = 120;

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

  const tpsData = (metrics ?? []).map((m) => m.tps);
  const playersData = (metrics ?? []).map((m) => m.players);
  const ramData = (metrics ?? []).map((m) => m.ram_used_mb);
  const cpuData = (metrics ?? []).map((m) => m.cpu_percent);

  const current = metrics?.length
    ? metrics.reduce((latest, m) => (m.timestamp > latest.timestamp ? m : latest))
    : undefined;

  const connectionState = useWSStore((s) => s.connectionState);
  const staleNote =
    connectionState === "reconnecting"
      ? { text: "Metrics not live — reconnecting...", color: "text-amber-700 dark:text-amber-400" }
      : connectionState === "connecting"
        ? { text: "Connecting to live metrics…", color: "text-gray-500 dark:text-gray-400" }
        : connectionState === "disconnected"
          ? { text: "Metrics not live — showing last known", color: "text-red-600 dark:text-red-400" }
          : null;

  const metricCards = [
    { label: "TPS", value: current?.tps?.toFixed(1) ?? "—", data: tpsData, color: "#22c55e", fillColor: "rgba(34, 197, 94, 0.1)" },
    { label: "Players", value: current?.players ?? "—", data: playersData, color: "#3b82f6", fillColor: "rgba(59, 130, 246, 0.1)" },
    { label: "RAM", value: current ? `${(current.ram_used_mb / 1024).toFixed(1)} GB` : "—", data: ramData, color: "#eab308", fillColor: "rgba(234, 179, 8, 0.1)" },
    { label: "CPU", value: current ? `${current.cpu_percent.toFixed(1)}%` : "—", data: cpuData, color: "#ef4444", fillColor: "rgba(239, 68, 68, 0.1)" },
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
          <div key={card.label} className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-3">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{card.label}</p>
            <p className="text-lg font-bold text-gray-900 dark:text-gray-100 mb-2">{card.value}</p>
            <Sparkline data={card.data} color={card.color} fillColor={card.fillColor} />
          </div>
        ))}
      </div>
    </>
  );
}
