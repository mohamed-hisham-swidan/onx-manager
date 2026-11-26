import { Link } from "react-router-dom";
import { Modal } from "@/components/ui/Modal";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Icon } from "@/components/ui/Icon";
import { stripMinecraftFormatting } from "@/server_manager/utils/motd";
import type {
  RuntimeDiagnosticsResponse,
  ServerDetailResponse,
} from "@/server_manager/types";
import type { ServerExposureResponse } from "@/types";

export interface ServerDiagnosticsDrawerProps {
  open: boolean;
  onClose: () => void;
  server: ServerDetailResponse;
  runtime?: RuntimeDiagnosticsResponse | null;
  exposure?: ServerExposureResponse | null;
}

function DrawerRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2">
      <dt className="shrink-0 text-xs text-text-muted">{label}</dt>
      <dd className="text-right text-xs font-medium text-text-primary break-all">{children}</dd>
    </div>
  );
}

function DrawerSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border-subtle bg-surface-muted/50 p-4">
      <h4 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-text-secondary">
        {title}
      </h4>
      <dl className="divide-y divide-border-subtle/60">{children}</dl>
    </section>
  );
}

export function ServerDiagnosticsDrawer({
  open,
  onClose,
  server,
  runtime,
  exposure,
}: ServerDiagnosticsDrawerProps) {
  const cleanedMotd = stripMinecraftFormatting(server.motd ?? "") || "—";
  const providerLabel =
    server.provider === "docker"
      ? "Docker Container"
      : server.provider
        ? "Host Process"
        : "Docker Container (Default)";

  return (
    <Modal
      open={open}
      onClose={onClose}
      variant="drawer"
      size="lg"
      title="Diagnostics & Runtime Info"
      description={`${server.name} · ${server.server_type} ${server.minecraft_version}`}
    >
      <div data-testid="server-diagnostics-drawer" className="space-y-4">
        <DrawerSection title="Runtime & Process">
          <DrawerRow label="Provider">{providerLabel}</DrawerRow>
          <DrawerRow label="Runtime Handle">
            <span className="font-mono">{runtime?.runtime_handle ?? "—"}</span>
          </DrawerRow>
          <DrawerRow label={server.provider === "docker" ? "Internal Container IP" : "Host"}>
            <span className="font-mono">
              {server.deployment_host
                ? `${server.deployment_host}:${server.deployment_port ?? server.port}`
                : "—"}
            </span>
          </DrawerRow>
          <DrawerRow label="Game Port">
            <span className="font-mono">{server.port}</span>
          </DrawerRow>
          <DrawerRow label="PID">
            <span className="font-mono">{runtime?.pid ?? server.deployment_pid ?? "—"}</span>
          </DrawerRow>
          <DrawerRow label="Supervised">{runtime?.supervised ? "Yes" : "No"}</DrawerRow>
          <DrawerRow label="Restart Count">
            <span className="font-mono">{runtime?.restart_count ?? 0}</span>
          </DrawerRow>
          {runtime?.startup_duration_seconds != null && (
            <DrawerRow label="Last Startup Duration">
              <span className="font-mono">{runtime.startup_duration_seconds.toFixed(1)}s</span>
            </DrawerRow>
          )}
          <DrawerRow label="Public Exposure">
            {exposure?.desired_state === "ENABLED" && exposure.targets?.[0]?.public_address ? (
              <div className="inline-flex items-center gap-1.5 flex-wrap justify-end">
                <StatusBadge status={exposure.aggregate_status} />
                <span className="font-mono">{exposure.targets[0].public_address}</span>
                <Link
                  to={`/servers/${server.server_id}/network`}
                  onClick={onClose}
                  className="text-accent-primary hover:underline text-xs"
                >
                  Manage
                </Link>
              </div>
            ) : server.public_address ? (
              <span className="font-mono">{server.public_address}</span>
            ) : (
              <div className="inline-flex items-center gap-1.5">
                <span className="text-text-muted">Not Exposed</span>
                <Link
                  to={`/servers/${server.server_id}/network`}
                  onClick={onClose}
                  className="text-accent-primary hover:underline text-xs"
                >
                  Configure
                </Link>
              </div>
            )}
          </DrawerRow>
        </DrawerSection>

        {runtime?.owner_conflicts && runtime.owner_conflicts.length > 0 && (
          <section className="rounded-xl border border-status-warning-border bg-status-warning-bg p-4 space-y-1.5">
            <h4 className="text-xs font-bold uppercase tracking-wider text-status-warning flex items-center gap-1.5">
              <Icon name="alert" size={14} />
              <span>Runtime Ownership Conflicts ({runtime.owner_conflicts.length})</span>
            </h4>
            <ul className="space-y-1 text-xs text-text-secondary">
              {runtime.owner_conflicts.map((conflict, idx) => (
                <li key={idx} className="font-mono text-[11px]">
                  {String(conflict.reason ?? "conflict")}: {String(conflict.detail ?? "")}
                </li>
              ))}
            </ul>
          </section>
        )}

        {runtime?.validation_chain && runtime.validation_chain.length > 0 && (
          <DrawerSection title="Validation Chain">
            <div className="pt-1 space-y-1">
              {runtime.validation_chain.map((step, idx) => (
                <div key={idx} className="font-mono text-[11px] text-text-secondary">
                  {step}
                </div>
              ))}
            </div>
          </DrawerSection>
        )}

        <DrawerSection title="JVM & Deployment">
          <DrawerRow label="Memory Heap">
            <span className="font-mono">
              {server.min_memory_mb} MB – {server.max_memory_mb} MB
            </span>
          </DrawerRow>
          {server.cpu_cores != null && server.cpu_cores > 0 && (
            <DrawerRow label="CPU Limit">
              <span className="font-mono">{server.cpu_cores} cores</span>
            </DrawerRow>
          )}
          <DrawerRow label="Root Path">
            <span className="font-mono">{server.root_path ?? "—"}</span>
          </DrawerRow>
          <DrawerRow label="Startup Jar">
            <span className="font-mono">{server.startup_jar ?? "—"}</span>
          </DrawerRow>
          <DrawerRow label="Java Args">
            <span className="font-mono text-[11px]">{server.java_args || "—"}</span>
          </DrawerRow>
        </DrawerSection>

        <DrawerSection title="Gameplay Snapshot">
          <DrawerRow label="Minecraft Version">
            <span className="font-mono">{server.minecraft_version}</span>
          </DrawerRow>
          <DrawerRow label="Server Type">{server.server_type}</DrawerRow>
          <DrawerRow label="Gamemode">
            <span className="capitalize">{server.gamemode}</span>
          </DrawerRow>
          <DrawerRow label="Difficulty">
            <span className="capitalize">{server.difficulty}</span>
          </DrawerRow>
          <DrawerRow label="Max Players">
            <span className="font-mono">{server.max_players}</span>
          </DrawerRow>
          <DrawerRow label="View / Sim Distance">
            <span className="font-mono">
              {server.view_distance} / {server.simulation_distance} chunks
            </span>
          </DrawerRow>
          <DrawerRow label="PvP / Whitelist / Online">
            <span>
              {server.pvp ? "PvP" : "No PvP"} ·{" "}
              {server.whitelist ? "Whitelisted" : "Open"} ·{" "}
              {server.online_mode ? "Online" : "Offline"}
            </span>
          </DrawerRow>
          <DrawerRow label="MOTD">{cleanedMotd}</DrawerRow>
        </DrawerSection>

        <div className="flex flex-wrap items-center justify-end gap-2 pt-2 border-t border-border-subtle">
          <Link
            to={`/servers/${server.server_id}/files?tab=logs`}
            onClick={onClose}
            data-testid="diagnostics-open-logs-link"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors"
          >
            <Icon name="file" size={13} />
            <span>Logs &amp; Crashes</span>
          </Link>
          <Link
            to={`/servers/${server.server_id}/network`}
            onClick={onClose}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors"
          >
            <Icon name="globe" size={13} />
            <span>Network & Exposure</span>
          </Link>
          <Link
            to={`/servers/${server.server_id}/settings`}
            onClick={onClose}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover transition-colors"
          >
            <Icon name="settings" size={13} />
            <span>Edit in Server Settings</span>
          </Link>
        </div>
      </div>
    </Modal>
  );
}
