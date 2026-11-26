import { Link } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { formatUptime } from "@/server_manager/components/servers/serversUtils";
import type { ServerResponse } from "@/server_manager/types";
import type { HealthDashboardResponse, HealthResponse } from "@/types";

export interface DashboardHeaderProps {
  isLocal: boolean;
  showFullControls: boolean;
  health?: HealthResponse | null;
  setupVersion?: string | null;
  healthDashboard?: HealthDashboardResponse | null;
  servers: ServerResponse[];
  permissions: {
    canCreate: boolean;
    canImport: boolean;
  };
}

function isDatabaseReady(dbStatus: string | undefined): boolean {
  if (!dbStatus) return false;
  const normalized = dbStatus.trim().toLowerCase();
  return (
    normalized === "ok" ||
    normalized === "connected" ||
    normalized === "healthy" ||
    normalized === "ready"
  );
}

export function DashboardHeader({
  isLocal,
  showFullControls,
  health,
  setupVersion,
  healthDashboard,
  servers,
  permissions,
}: DashboardHeaderProps) {
  const versionRaw = health?.version || setupVersion || null;
  const versionLabel = versionRaw
    ? versionRaw.startsWith("v")
      ? versionRaw
      : `v${versionRaw}`
    : null;
  const panelUptime = formatUptime(health?.uptime_seconds);
  const dockerKnown = typeof health?.docker === "boolean";
  const dockerConnected = health?.docker === true;
  const dbKnown = typeof health?.database === "string" && health.database.trim().length > 0;
  const dbReady = isDatabaseReady(health?.database);

  const attentionServers = servers.filter(
    (s) =>
      s.status === "crashed" ||
      s.status === "broken" ||
      s.status === "provisioning_failed",
  );
  const activeServerIds = new Set(servers.map((s) => s.server_id));
  const criticalCount =
    healthDashboard?.servers && healthDashboard.servers.length > 0
      ? healthDashboard.servers.filter(
          (entry) => activeServerIds.has(entry.server_id) && entry.status === "critical",
        ).length
      : (healthDashboard?.critical ?? 0);
  const showAttentionBanner =
    health?.docker === false || attentionServers.length > 0 || criticalCount > 0;

  const targetHref =
    attentionServers.length === 1
      ? `/servers/${attentionServers[0].server_id}/console`
      : "/servers?status=attention";

  return (
    <header className="space-y-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-border-subtle bg-surface-muted text-text-accent">
              <Icon name="dashboard" size={18} />
            </div>
            <div className="min-w-0">
              <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-text-primary">
                Dashboard
              </h1>
              <p className="text-xs sm:text-sm text-text-muted">
                {isLocal && !showFullControls
                  ? "Local fleet health, resources, and quick sharing."
                  : "Live fleet health, resources, and recent activity."}
              </p>
            </div>
          </div>

          {/* Real Daemon Status Strip */}
          {(dockerKnown || dbKnown || versionLabel || panelUptime) && (
            <div
              role="status"
              aria-label="Daemon status"
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5 pl-0.5 text-xs text-text-secondary"
            >
              {dockerKnown && (
                <span className="inline-flex items-center gap-1.5 font-medium whitespace-nowrap">
                  <span
                    className={`h-2 w-2 rounded-full ${
                      dockerConnected ? "bg-status-success" : "bg-status-danger"
                    }`}
                    aria-hidden="true"
                  />
                  <span className={dockerConnected ? "text-status-success" : "text-status-danger"}>
                    {dockerConnected ? "Docker Connected" : "Docker Offline"}
                  </span>
                </span>
              )}

              {dockerKnown && dbKnown && (
                <span className="text-text-muted" aria-hidden="true">
                  ·
                </span>
              )}

              {dbKnown && (
                <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      dbReady ? "bg-status-success" : "bg-status-warning"
                    }`}
                    aria-hidden="true"
                  />
                  <span className={dbReady ? "text-text-secondary" : "text-status-warning"}>
                    {dbReady ? "Database Ready" : "Database Degraded"}
                  </span>
                </span>
              )}

              {versionLabel && (
                <>
                  {(dockerKnown || dbKnown) && (
                    <span className="text-text-muted" aria-hidden="true">
                      ·
                    </span>
                  )}
                  <span className="font-mono text-text-muted whitespace-nowrap">
                    {versionLabel}
                  </span>
                </>
              )}

              {panelUptime && (
                <>
                  <span className="text-text-muted" aria-hidden="true">
                    ·
                  </span>
                  <span className="font-mono text-text-muted whitespace-nowrap tabular-nums">
                    Panel {panelUptime.replace(/^Up\s+/i, "up ")}
                  </span>
                </>
              )}
            </div>
          )}
        </div>

        {(permissions.canImport || permissions.canCreate) && (
          <div className="flex flex-wrap items-center gap-2 shrink-0">
            {permissions.canImport && (
              <Link
                to="/servers/import"
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3.5 text-xs font-semibold text-text-primary transition-colors hover:border-border-strong hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
              >
                <Icon name="upload" size={14} />
                <span>Import</span>
              </Link>
            )}
            {permissions.canCreate && (
              <Link
                to="/servers/create"
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg bg-accent-primary px-4 text-xs font-semibold text-accent-contrast-text shadow-xs transition-colors hover:bg-accent-hover active:bg-accent-active focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
              >
                <Icon name="plus" size={14} />
                <span>New Server</span>
              </Link>
            )}
          </div>
        )}
      </div>

      {/* Actionable Attention Banner */}
      {showAttentionBanner && (
        <div
          role="alert"
          className="flex flex-col gap-3 rounded-xl border border-status-danger/40 bg-status-danger-bg px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex items-start sm:items-center gap-2.5 min-w-0">
            <Icon name="alert" size={16} className="mt-0.5 sm:mt-0 shrink-0 text-status-danger" />
            <p className="text-xs sm:text-sm font-medium text-text-primary">
              {health?.docker === false
                ? "Docker engine is offline. Containers cannot start until Docker recovers."
                : attentionServers.length === 1
                  ? `${attentionServers[0].name} needs attention (${attentionServers[0].status.replace(/_/g, " ")}).`
                  : attentionServers.length > 1
                    ? `${attentionServers.length} servers require attention.`
                    : `${criticalCount} server health check${criticalCount === 1 ? "" : "s"} reported critical.`}
            </p>
          </div>
          {(attentionServers.length > 0 || criticalCount > 0) && (
            <Link
              to={targetHref}
              className="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-status-danger/40 bg-surface-card px-3 text-xs font-semibold text-status-danger transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
            >
              <Icon name="terminal" size={13} />
              <span>
                {attentionServers.length === 1 ? "Open Console" : "Inspect Servers"}
              </span>
            </Link>
          )}
        </div>
      )}
    </header>
  );
}
