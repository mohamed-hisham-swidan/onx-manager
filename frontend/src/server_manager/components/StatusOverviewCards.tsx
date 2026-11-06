import type { JSX } from "react";
import { Link } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import type { ServerResponse } from "@/server_manager/types";

export interface StatusOverviewCardsProps {
  counts: Record<string, number>;
  servers?: ServerResponse[];
}

export function StatusOverviewCards({
  counts,
  servers = [],
}: StatusOverviewCardsProps): JSX.Element {
  const onlineCount = counts["running"] ?? 0;
  const stoppedCount = counts["stopped"] ?? 0;
  const createdCount = counts["created"] ?? 0;
  const offlineCount = stoppedCount + createdCount;
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);

  // In-flight transitions: starting, stopping, provisioning, restoring
  const startingCount = counts["starting"] ?? 0;
  const stoppingCount = counts["stopping"] ?? 0;
  const provisioningCount = counts["provisioning"] ?? 0;
  const restoringCount = counts["restoring"] ?? 0;
  const transitionCount =
    startingCount + stoppingCount + provisioningCount + restoringCount;

  // Problem / unhealthy servers: crashed, broken, provisioning_failed
  const crashedCount = counts["crashed"] ?? 0;
  const brokenCount = counts["broken"] ?? 0;
  const failedCount = counts["provisioning_failed"] ?? 0;
  const problemCount = crashedCount + brokenCount + failedCount;

  // Filter specific servers from list when available
  const problemServers = servers.filter((s) =>
    ["crashed", "broken", "provisioning_failed"].includes(s.status),
  );
  const transitioningServers = servers.filter((s) =>
    ["starting", "stopping", "provisioning", "restoring"].includes(s.status),
  );

  const primaryProblemServer = problemServers[0];
  const problemTargetHref = primaryProblemServer
    ? `/servers/${primaryProblemServer.server_id}`
    : brokenCount > 0
    ? "/servers?status=broken"
    : crashedCount > 0
    ? "/servers?status=crashed"
    : failedCount > 0
    ? "/servers?status=provisioning_failed"
    : "/servers";

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {/* 1. Primary Fleet Status: Online & Offline */}
      <section
        aria-label="Fleet Status"
        className="flex flex-col justify-between rounded-2xl border border-border-subtle bg-surface-card p-5 shadow-2xs transition-all hover:border-border-default"
      >
        <div>
          <div className="flex items-center justify-between">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-primary/10 text-accent-primary">
              <Icon name="server" size={20} />
            </div>
            <Link
              to="/servers"
              aria-label={`${total} Total`}
              className="rounded-full bg-surface-muted px-2.5 py-1 text-xs font-semibold text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary"
            >
              {total} Total
            </Link>
          </div>

          <div className="mt-3.5">
            <h3 className="text-sm font-bold text-text-primary">Fleet Status</h3>
            <p className="mt-0.5 text-xs text-text-muted">
              Primary server availability
            </p>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2.5 rounded-xl border border-border-subtle/60 bg-surface-page/50 p-3">
            <Link
              to="/servers?status=running"
              aria-label={`${onlineCount} Online`}
              className="group flex flex-col rounded-lg p-1.5 transition-colors hover:bg-surface-hover/70"
            >
              <div className="flex items-center gap-1.5 text-xs font-medium text-text-secondary group-hover:text-text-primary">
                <span className="relative flex h-2 w-2">
                  {onlineCount > 0 && (
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-success opacity-75" />
                  )}
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-status-success" />
                </span>
                Online
              </div>
              <span className="mt-1 text-2xl font-bold tabular-nums text-text-primary transition-colors group-hover:text-status-success">
                {onlineCount}
              </span>
            </Link>

            <Link
              to="/servers?status=stopped"
              aria-label={`${offlineCount} Offline`}
              className="group flex flex-col rounded-lg p-1.5 transition-colors hover:bg-surface-hover/70"
            >
              <div className="flex items-center gap-1.5 text-xs font-medium text-text-secondary group-hover:text-text-primary">
                <span className="h-2 w-2 rounded-full bg-text-muted" />
                Offline
              </div>
              <span className="mt-1 text-2xl font-bold tabular-nums text-text-primary transition-colors group-hover:text-text-secondary">
                {offlineCount}
              </span>
            </Link>
          </div>
        </div>

        <div className="mt-4 border-t border-border-subtle/50 pt-3">
          <Link
            to="/servers"
            className="flex items-center justify-between text-xs font-semibold text-accent-primary hover:underline"
          >
            <span>View all servers</span>
            <Icon name="chevron-right" size={14} />
          </Link>
        </div>
      </section>

      {/* 2. Active Operations: In-flight Transitions */}
      <section
        aria-label="Active Operations"
        className={`flex-col justify-between rounded-2xl border border-border-subtle bg-surface-card p-5 shadow-2xs transition-all hover:border-border-default ${
          transitionCount === 0 ? "hidden md:flex" : "flex"
        }`}
      >
        <div>
          <div className="flex items-center justify-between">
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-xl ${
                transitionCount > 0
                  ? "bg-status-warning-bg text-status-warning"
                  : "bg-surface-muted text-text-secondary"
              }`}
            >
              <Icon
                name="restart"
                size={20}
                className={transitionCount > 0 ? "animate-spin" : ""}
              />
            </div>
            {transitionCount > 0 ? (
              <span className="flex items-center gap-1.5 rounded-full border border-status-warning-border bg-status-warning-bg px-2.5 py-1 text-xs font-semibold text-status-warning">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-status-warning" />
                {transitionCount} In-Flight
              </span>
            ) : (
              <span className="rounded-full bg-surface-muted px-2.5 py-1 text-xs font-medium text-text-muted">
                Idle
              </span>
            )}
          </div>

          <div className="mt-3.5">
            <h3 className="text-sm font-bold text-text-primary">
              Active Operations
            </h3>
            <p className="mt-0.5 text-xs text-text-muted">
              {transitionCount > 0
                ? "Lifecycle events in progress"
                : "No servers transitioning"}
            </p>
          </div>

          {transitionCount > 0 ? (
            <div className="mt-4 space-y-2 rounded-xl border border-status-warning-border/40 bg-status-warning-bg/15 p-3">
              <div className="flex flex-wrap gap-2 text-xs font-medium">
                {startingCount > 0 && (
                  <Link
                    to="/servers?status=starting"
                    aria-label={`${startingCount} Starting`}
                    className="flex items-center gap-1.5 rounded-md bg-surface-card px-2.5 py-1 text-status-warning shadow-2xs hover:bg-surface-hover"
                  >
                    <Icon name="restart" size={13} />
                    <span>{startingCount} Starting</span>
                  </Link>
                )}
                {stoppingCount > 0 && (
                  <Link
                    to="/servers?status=stopping"
                    aria-label={`${stoppingCount} Stopping`}
                    className="flex items-center gap-1.5 rounded-md bg-surface-card px-2.5 py-1 text-status-warning shadow-2xs hover:bg-surface-hover"
                  >
                    <Icon name="stop" size={13} />
                    <span>{stoppingCount} Stopping</span>
                  </Link>
                )}
                {provisioningCount > 0 && (
                  <Link
                    to="/servers?status=provisioning"
                    aria-label={`${provisioningCount} Installing`}
                    className="flex items-center gap-1.5 rounded-md bg-surface-card px-2.5 py-1 text-accent-primary shadow-2xs hover:bg-surface-hover"
                  >
                    <Icon name="server" size={13} />
                    <span>{provisioningCount} Installing</span>
                  </Link>
                )}
                {restoringCount > 0 && (
                  <Link
                    to="/servers?status=restoring"
                    aria-label={`${restoringCount} Restoring`}
                    className="flex items-center gap-1.5 rounded-md bg-surface-card px-2.5 py-1 text-accent-primary shadow-2xs hover:bg-surface-hover"
                  >
                    <Icon name="backup" size={13} />
                    <span>{restoringCount} Restoring</span>
                  </Link>
                )}
              </div>
              {transitioningServers.length > 0 && (
                <div className="truncate border-t border-status-warning-border/30 pt-1 text-[11px] text-text-secondary">
                  <span className="font-semibold">
                    {transitioningServers[0].name}
                  </span>
                  <span className="text-text-muted">
                    {" "}({transitioningServers[0].status})
                  </span>
                  {transitioningServers.length > 1 && (
                    <span className="font-normal text-text-muted">
                      {" "}and {transitioningServers.length - 1} more
                    </span>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="mt-4 flex items-center gap-2.5 rounded-xl border border-border-subtle/60 bg-surface-page/50 p-3.5">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-status-success-bg text-status-success">
                <Icon name="check" size={15} />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-text-primary">
                  Fleet Stable
                </p>
                <p className="truncate text-[11px] text-text-muted">
                  0 starting, stopping, or installing
                </p>
              </div>
            </div>
          )}
        </div>

        <div className="mt-4 border-t border-border-subtle/50 pt-3">
          <Link
            to={
              transitionCount > 0
                ? startingCount > 0
                  ? "/servers?status=starting"
                  : "/servers?status=stopping"
                : "/servers"
            }
            className="flex items-center justify-between text-xs font-semibold text-accent-primary hover:underline"
          >
            <span>
              {transitionCount > 0 ? "View live operations" : "Manage servers"}
            </span>
            <Icon name="chevron-right" size={14} />
          </Link>
        </div>
      </section>

      {/* 3. System Health & Issues: Crashed / Broken servers */}
      <section
        aria-label="System Health"
        className={`flex flex-col justify-between rounded-2xl border p-3 sm:p-5 shadow-2xs transition-all ${
          problemCount > 0
            ? "border-status-danger-border bg-status-danger-bg/20 hover:border-status-danger"
            : "border-border-subtle bg-surface-card hover:border-border-default"
        }`}
      >
        <div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 sm:block">
              <div
                className={`flex h-7 w-7 sm:h-10 sm:w-10 items-center justify-center rounded-lg sm:rounded-xl border ${
                  problemCount > 0
                    ? "border-status-danger-border bg-status-danger-bg text-status-danger"
                    : "border-status-success-border bg-status-success-bg text-status-success"
                }`}
              >
                <Icon
                  name={problemCount > 0 ? "alert" : "check"}
                  size={16}
                  className="sm:hidden"
                />
                <Icon
                  name={problemCount > 0 ? "alert" : "check"}
                  size={20}
                  className="hidden sm:block"
                />
              </div>
              <h3 className="text-sm font-bold text-text-primary sm:hidden">
                System Health
              </h3>
            </div>
            {problemCount > 0 ? (
              <span className="flex items-center gap-1.5 rounded-full border border-status-danger-border bg-status-danger-bg px-2 sm:px-2.5 py-0.5 sm:py-1 text-[11px] sm:text-xs font-bold text-status-danger">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-status-danger" />
                {problemCount} Attention Needed
              </span>
            ) : (
              <span className="flex items-center gap-1.5 rounded-full border border-status-success-border bg-status-success-bg px-2 sm:px-2.5 py-0.5 sm:py-1 text-[11px] sm:text-xs font-semibold text-status-success">
                <span className="h-1.5 w-1.5 rounded-full bg-status-success" />
                Healthy
              </span>
            )}
          </div>

          <div className="mt-1.5 sm:mt-3.5">
            <h3 className="hidden sm:block text-sm font-bold text-text-primary">
              System Health
            </h3>
            <p className="mt-0.5 text-[11px] sm:text-xs text-text-muted hidden sm:block">
              {problemCount > 0
                ? `${problemCount} issue${problemCount === 1 ? "" : "s"} detected across fleet`
                : "No errors or crashed servers"}
            </p>
          </div>

          {problemCount > 0 ? (
            <div className="mt-2.5 sm:mt-4 space-y-2 sm:space-y-2.5 rounded-xl border border-status-danger-border/40 bg-surface-card/90 p-2.5 sm:p-3">
              <div className="flex flex-wrap gap-1.5 sm:gap-2 text-[11px] sm:text-xs font-medium">
                {crashedCount > 0 && (
                  <Link
                    to="/servers?status=crashed"
                    aria-label={`${crashedCount} Crashed`}
                    className="flex items-center gap-1 rounded-md bg-status-danger-bg px-2 py-0.5 font-semibold text-status-danger hover:underline"
                  >
                    <Icon name="alert" size={12} />
                    <span>{crashedCount} Crashed</span>
                  </Link>
                )}
                {brokenCount > 0 && (
                  <Link
                    to="/servers?status=broken"
                    aria-label={`${brokenCount} Broken`}
                    className="flex items-center gap-1 rounded-md bg-status-danger-bg px-2 py-0.5 font-semibold text-status-danger hover:underline"
                  >
                    <Icon name="alert" size={12} />
                    <span>{brokenCount} Broken</span>
                  </Link>
                )}
                {failedCount > 0 && (
                  <Link
                    to="/servers?status=provisioning_failed"
                    aria-label={`${failedCount} Install Failed`}
                    className="flex items-center gap-1 rounded-md bg-status-danger-bg px-2 py-0.5 font-semibold text-status-danger hover:underline"
                  >
                    <Icon name="alert" size={12} />
                    <span>{failedCount} Install Failed</span>
                  </Link>
                )}
              </div>

              {/* Direct Move-to-Broken Server CTA */}
              <Link
                to={problemTargetHref}
                className="flex items-center justify-between rounded-lg bg-status-danger px-2.5 sm:px-3 py-1.5 sm:py-2 text-xs font-bold text-accent-contrast-text shadow-xs transition-opacity hover:opacity-95"
              >
                <span className="truncate">
                  {primaryProblemServer
                    ? `Inspect ${primaryProblemServer.name}`
                    : `View Problem Servers (${problemCount})`}
                </span>
                <Icon name="chevron-right" size={14} className="ml-1 shrink-0" />
              </Link>
            </div>
          ) : (
            <div className="mt-2 sm:mt-4 flex items-center gap-2 sm:gap-2.5 rounded-xl border border-border-subtle/60 bg-surface-page/50 p-2 sm:p-3.5">
              <div className="flex h-5 w-5 sm:h-7 sm:w-7 shrink-0 items-center justify-center rounded-md sm:rounded-lg bg-status-success-bg text-status-success">
                <Icon name="check" size={13} className="sm:hidden" />
                <Icon name="check" size={15} className="hidden sm:block" />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-text-primary">
                  All Systems Operational
                </p>
                <p className="truncate text-[11px] text-text-muted hidden sm:block">
                  0 crashed or broken servers
                </p>
              </div>
            </div>
          )}
        </div>

        <div className="mt-2.5 sm:mt-4 border-t border-border-subtle/50 pt-2 sm:pt-3">
          <Link
            to={problemCount > 0 ? problemTargetHref : "/servers"}
            className={`flex items-center justify-between text-xs font-semibold ${
              problemCount > 0
                ? "text-status-danger hover:underline"
                : "text-accent-primary hover:underline"
            }`}
          >
            <span>
              {problemCount > 0 ? "Fix broken servers" : "View fleet status"}
            </span>
            <Icon name="chevron-right" size={14} />
          </Link>
        </div>
      </section>
    </div>
  );
}
