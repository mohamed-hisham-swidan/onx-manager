import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { SafeUpgradeWizardModal } from "@/server_manager/components/p55/SafeUpgradeWizardModal";
import { ServerP55SettingsCard } from "@/server_manager/components/p55/ServerP55SettingsCard";
import { ServerModeConversionCard } from "@/server_manager/components/ServerModeConversionCard";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import type { ServerDetailResponse } from "@/server_manager/types";

export interface UpgradesModeTabProps {
  serverId: string;
  server: ServerDetailResponse;
  canWrite: boolean;
  canManageVersioning: boolean;
  initialChangeVersionOpen?: boolean;
  onChangeVersionConsumed?: () => void;
}

const TERMINAL_STATUSES = new Set(["confirmed", "rolled_back", "failed"]);

export function UpgradesModeTab({
  serverId,
  server,
  canWrite,
  canManageVersioning,
  initialChangeVersionOpen = false,
  onChangeVersionConsumed,
}: UpgradesModeTabProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [isDrawerOpen, setIsDrawerOpen] = useState(
    Boolean(initialChangeVersionOpen && canWrite),
  );
  const [prevTrigger, setPrevTrigger] = useState(
    Boolean(initialChangeVersionOpen && canWrite),
  );
  if (initialChangeVersionOpen && canWrite && !prevTrigger) {
    setPrevTrigger(true);
    setIsDrawerOpen(true);
  } else if (!initialChangeVersionOpen && prevTrigger) {
    setPrevTrigger(false);
  }

  useEffect(() => {
    if (!initialChangeVersionOpen || !canWrite) return;
    onChangeVersionConsumed?.();
  }, [initialChangeVersionOpen, canWrite, onChangeVersionConsumed]);

  const upgradesQuery = useQuery({
    queryKey: queryKeys.p55.upgrades(serverId),
    queryFn: async () => api.listServerUpgrades?.(serverId) ?? null,
    enabled: typeof api.listServerUpgrades === "function" && Boolean(serverId),
    staleTime: 30_000,
  });

  const activeUpgrade = upgradesQuery.data?.active_upgrade ?? null;
  const hasResumableUpgrade = Boolean(
    activeUpgrade && !TERMINAL_STATUSES.has(activeUpgrade.status),
  );

  return (
    <div className="space-y-6" data-testid="server-settings-tab-lifecycle">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight text-text-primary">
          Upgrades &amp; Mode
        </h2>
        <p className="text-xs text-text-muted">
          Version changes, safe upgrade gates, download hosts, and server mode.
        </p>
      </header>

      <section
        data-testid="server-version-loader-card"
        className="rounded-xl border border-border-default bg-surface-card p-5 shadow-2xs space-y-4"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Icon name="restart" size={16} className="text-accent-primary" />
              <h3 className="text-sm font-bold text-text-primary">
                Server Version &amp; Loader
              </h3>
            </div>
            <p className="text-xs text-text-muted">
              Plan a Minecraft version or loader change with plugin compatibility
              checks, optional isolated branch testing, and atomic rollback protection.
            </p>
          </div>
          {canWrite && (
            <Button
              type="button"
              data-testid="open-change-version-btn"
              variant="primary"
              size="sm"
              icon="restart"
              onClick={() => setIsDrawerOpen(true)}
            >
              {hasResumableUpgrade ? "Resume Change Version" : "Change Version"}
            </Button>
          )}
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-border-subtle bg-surface-muted p-3">
            <p className="text-[11px] font-medium uppercase tracking-wider text-text-muted">
              Minecraft Version
            </p>
            <p className="mt-1 font-mono text-sm font-semibold text-text-primary">
              {server.minecraft_version ?? "Unknown"}
            </p>
          </div>
          <div className="rounded-lg border border-border-subtle bg-surface-muted p-3">
            <p className="text-[11px] font-medium uppercase tracking-wider text-text-muted">
              Software / Loader
            </p>
            <div className="mt-1 flex items-center gap-2">
              <LoaderBadge loader={server.server_type} />
            </div>
          </div>
          <div className="rounded-lg border border-border-subtle bg-surface-muted p-3">
            <p className="text-[11px] font-medium uppercase tracking-wider text-text-muted">
              Active Change Status
            </p>
            <p className="mt-1 font-mono text-xs font-semibold text-text-primary">
              {hasResumableUpgrade && activeUpgrade
                ? `${activeUpgrade.status} → MC ${activeUpgrade.target_mc}`
                : "Up to date"}
            </p>
          </div>
        </div>
      </section>

      <ServerP55SettingsCard
        key={serverId}
        serverId={serverId}
        serverType={server.server_type}
        readOnly={!canWrite}
      />

      <ServerModeConversionCard
        key={serverId}
        serverId={serverId}
        server={server}
        readOnly={!canManageVersioning}
      />

      <SafeUpgradeWizardModal
        key={serverId}
        serverId={serverId}
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        serverMode={server.mode}
        serverType={server.server_type}
        currentMc={server.minecraft_version}
      />
    </div>
  );
}
