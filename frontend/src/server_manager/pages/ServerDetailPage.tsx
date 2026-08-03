import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useServerDetail, useStartServer, useStopServer, useRestartServer, useDeleteServer } from "@/server_manager/hooks/useServers";
import { Skeleton } from "@/components/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Icon } from "@/components/ui/Icon";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { stripMinecraftFormatting } from "@/server_manager/utils/motd";
import { ServerConfigEditor } from "@/server_manager/components/ServerConfigEditor";
import { ServerConsole } from "@/server_manager/components/ServerConsole";
import { ServerMetricsCharts } from "@/server_manager/components/ServerMetricsCharts";
import { toast } from "@/stores/toastStore";
import type { ServerDetailResponse } from "@/server_manager/types";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <dt className="shrink-0 text-sm text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className="text-right text-sm font-medium text-gray-900 dark:text-gray-100">{children}</dd>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="p-5 sm:p-6">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
        {title}
      </h3>
      <dl className="divide-y divide-gray-100 dark:divide-gray-700/50">{children}</dl>
    </section>
  );
}

function renderMotd(motd: string | undefined): string {
  const cleaned = stripMinecraftFormatting(motd ?? "");
  return cleaned || "—";
}

export function ServerDetailPage() {
  const { serverId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const { data: server, isLoading, error } = useServerDetail(serverId ?? "");
  const startServer = useStartServer();
  const stopServer = useStopServer();
  const restartServer = useRestartServer();
  const deleteServer = useDeleteServer();
  const [activeTab, setActiveTab] = useState<"info" | "config" | "console" | "metrics">("info");
  const [showDelete, setShowDelete] = useState(false);

  if (!serverId) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-400">
        No server ID specified.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-96" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <Skeleton className="h-4 w-16 mb-2" />
              <Skeleton className="h-6 w-24" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-400">
        {error instanceof Error ? error.message : "Failed to load server details"}
      </div>
    );
  }

  if (!server) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-6 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400">
        Server not found.
      </div>
    );
  }

  const actions = (s: ServerDetailResponse) => (
    <>
      {["stopped", "created", "crashed"].includes(s.status) && (
        <button
          onClick={() =>
            startServer.mutate(serverId, {
              onSuccess: () => toast("success", "Server started", `"${s.name}" is starting.`),
              onError: (err) => toast("error", "Start failed", errorMessage(err)),
            })
          }
          disabled={startServer.isPending}
          className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-green-700 disabled:opacity-50"
        >
          <Icon name="play" size={14} />
          {startServer.isPending ? "Starting..." : "Start"}
        </button>
      )}
      {s.status === "running" && (
        <>
          <button
            onClick={() =>
              stopServer.mutate(serverId, {
                onSuccess: () => toast("success", "Server stopped", `"${s.name}" is stopping.`),
                onError: (err) => toast("error", "Stop failed", errorMessage(err)),
              })
            }
            disabled={stopServer.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-orange-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-orange-700 disabled:opacity-50"
          >
            <Icon name="stop" size={14} />
            {stopServer.isPending ? "Stopping..." : "Stop"}
          </button>
          <button
            onClick={() =>
              restartServer.mutate(serverId, {
                onSuccess: () => toast("success", "Server restarting", `"${s.name}" is restarting.`),
                onError: (err) => toast("error", "Restart failed", errorMessage(err)),
              })
            }
            disabled={restartServer.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-yellow-700 disabled:opacity-50"
          >
            <Icon name="restart" size={14} />
            {restartServer.isPending ? "Restarting..." : "Restart"}
          </button>
        </>
      )}
      <button
        onClick={() => setShowDelete(true)}
        disabled={deleteServer.isPending}
        className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50 dark:border-red-900/40 dark:text-red-400 dark:hover:bg-red-900/20"
      >
        <Icon name="trash" size={14} />
        Delete
      </button>
    </>
  );

  const tabs = [
    { key: "info" as const, label: "Information" },
    { key: "config" as const, label: "Configuration" },
    { key: "console" as const, label: "Console" },
    { key: "metrics" as const, label: "Metrics" },
  ];

  return (
    <div>
      <Link
        to="/servers"
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 transition-colors hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
      >
        <Icon name="chevron-left" size={16} />
        Servers
      </Link>

      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">
            <Icon name="server" size={24} />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-xl font-semibold text-gray-900 dark:text-gray-100">
                {server.name}
              </h2>
              <StatusBadge status={server.status} />
            </div>
            <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">
              {server.server_type} · {server.minecraft_version} · port {server.port}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">{actions(server)}</div>
      </div>

      <div className="mb-6 flex gap-1 border-b border-gray-200 dark:border-gray-700">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === t.key
                ? "border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400"
                : "border-transparent text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === "info" && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
            <DetailSection title="General">
              <DetailRow label="Minecraft Version">{server.minecraft_version}</DetailRow>
              <DetailRow label="Server Type">{server.server_type}</DetailRow>
              <DetailRow label="Gamemode">
                <span className="capitalize">{server.gamemode}</span>
              </DetailRow>
              <DetailRow label="Difficulty">
                <span className="capitalize">{server.difficulty}</span>
              </DetailRow>
            </DetailSection>
            <div className="border-t border-gray-100 dark:border-gray-700/50" />
            <DetailSection title="Network">
              <DetailRow label="Port">{server.port}</DetailRow>
              <DetailRow label="Max Players">{server.max_players}</DetailRow>
              <DetailRow label="MOTD">
                <span className="block max-w-xs text-right">{renderMotd(server.motd)}</span>
              </DetailRow>
            </DetailSection>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
            <DetailSection title="Gameplay">
              <DetailRow label="PVP">{server.pvp ? "Enabled" : "Disabled"}</DetailRow>
              <DetailRow label="Whitelist">{server.whitelist ? "Enabled" : "Disabled"}</DetailRow>
              <DetailRow label="Online Mode">{server.online_mode ? "Yes" : "No"}</DetailRow>
              <DetailRow label="Command Blocks">{server.enable_command_block ? "Enabled" : "Disabled"}</DetailRow>
              <DetailRow label="Spawn Protection">{server.spawn_protection} blocks</DetailRow>
            </DetailSection>
            <div className="border-t border-gray-100 dark:border-gray-700/50" />
            <DetailSection title="Performance">
              <DetailRow label="View Distance">{server.view_distance} chunks</DetailRow>
              <DetailRow label="Simulation Distance">{server.simulation_distance} chunks</DetailRow>
              <DetailRow label="Memory">
                {server.min_memory_mb} MB / {server.max_memory_mb} MB
              </DetailRow>
              <DetailRow label="Java Args">
                <span className="block max-w-xs truncate font-mono text-xs" title={server.java_args}>
                  {server.java_args}
                </span>
              </DetailRow>
            </DetailSection>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800 lg:col-span-2">
            <DetailSection title="Deployment">
              <DetailRow label="Provider">{server.provider ?? "—"}</DetailRow>
              <DetailRow label="Host">
                {server.deployment_host ? `${server.deployment_host}:${server.deployment_port ?? "—"}` : "—"}
              </DetailRow>
              <DetailRow label="PID">{server.deployment_pid ?? "—"}</DetailRow>
              <DetailRow label="Root Path">
                <span className="block max-w-xs truncate font-mono text-xs" title={server.root_path ?? undefined}>
                  {server.root_path ?? "—"}
                </span>
              </DetailRow>
              <DetailRow label="Startup Jar">
                <span className="block max-w-xs truncate font-mono text-xs" title={server.startup_jar ?? undefined}>
                  {server.startup_jar ?? "—"}
                </span>
              </DetailRow>
            </DetailSection>
          </div>
        </div>
      )}

      {activeTab === "config" && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
          <h3 className="mb-4 font-semibold text-gray-900 dark:text-gray-100">Server Configuration</h3>
          <ServerConfigEditor serverId={serverId} server={server} />
        </div>
      )}

      {activeTab === "console" && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
          <h3 className="mb-4 font-semibold text-gray-900 dark:text-gray-100">Server Console</h3>
          <ServerConsole serverId={serverId} />
        </div>
      )}

      {activeTab === "metrics" && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
          <h3 className="mb-4 font-semibold text-gray-900 dark:text-gray-100">Server Metrics</h3>
          <ServerMetricsCharts serverId={serverId} />
        </div>
      )}

      <ConfirmDialog
        open={showDelete}
        title="Delete server?"
        description={`This permanently deletes "${server.name}" and its data. This action cannot be undone.`}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={() =>
          deleteServer.mutate(serverId, {
            onSuccess: () => navigate("/servers"),
            onError: (err) => toast("error", "Delete failed", errorMessage(err)),
            onSettled: () => setShowDelete(false),
          })
        }
        onCancel={() => setShowDelete(false)}
      />
    </div>
  );
}
