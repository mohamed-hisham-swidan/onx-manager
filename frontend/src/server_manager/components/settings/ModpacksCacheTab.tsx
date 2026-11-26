import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";
import { useOperationStore } from "@/operations/stores/operationStore";
import type {
  CurseForgeIntegrationStatusResponse,
  LecGcResponse,
  LecPrewarmResponse,
} from "@/server_manager/types";
import { useSettingsPermissions } from "./settingsModel";
import { PreWarmCacheModal } from "./PreWarmCacheModal";
import { CleanCacheModal } from "./CleanCacheModal";

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 100 || unit === 0 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "Action failed";
}

function StatusPill({
  configured,
  source,
  hint,
}: {
  configured: boolean;
  source: CurseForgeIntegrationStatusResponse["source"];
  hint: string | null;
}) {
  if (!configured || source === "none") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-border-subtle bg-surface-muted px-2.5 py-0.5 text-xs font-medium text-text-secondary">
        Not Set
      </span>
    );
  }

  const label = source === "env" ? "Env Override" : "Configured";
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 rounded-full border border-status-success-border bg-status-success-bg px-2.5 py-0.5 text-xs font-medium text-status-success">
      <Icon name="check" size={12} />
      <span>{label}</span>
      {hint && <span className="font-mono text-[11px] text-text-secondary">{hint}</span>}
    </span>
  );
}

function CurseForgeCard({ canWrite }: { canWrite: boolean }) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();
  const hasStatusApi = typeof api.getCurseForgeIntegrationStatus === "function";

  const statusQuery = useQuery({
    queryKey: queryKeys.p55.curseforgeIntegration(),
    queryFn: async () => api.getCurseForgeIntegrationStatus?.() ?? null,
    enabled: hasStatusApi,
  });

  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const status = statusQuery.data ?? null;

  async function handleSave() {
    if (!canWrite || !apiKey.trim() || typeof api.setCurseForgeIntegrationKey !== "function") return;
    setIsSaving(true);
    setError(null);
    try {
      await api.setCurseForgeIntegrationKey({ api_key: apiKey.trim() });
      setApiKey("");
      setShowKey(false);
      await queryClient.invalidateQueries({ queryKey: queryKeys.p55.curseforgeIntegration() });
      toast("success", "CurseForge key saved", "Encrypted and stored securely on this host.");
    } catch (err) {
      const msg = errorMessage(err);
      setError(msg);
      setApiKey("");
      toast("error", "Failed to save key", msg);
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete() {
    if (!canWrite || typeof api.deleteCurseForgeIntegrationKey !== "function") return;
    setIsDeleting(true);
    setError(null);
    try {
      await api.deleteCurseForgeIntegrationKey();
      await queryClient.invalidateQueries({ queryKey: queryKeys.p55.curseforgeIntegration() });
      toast("success", "CurseForge key removed", "Stored API key has been cleared.");
    } catch (err) {
      const msg = errorMessage(err);
      setError(msg);
      toast("error", "Failed to remove key", msg);
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <section
      data-testid="curseforge-integration-card"
      className="rounded-xl border border-border-subtle bg-surface-card p-5 shadow-2xs space-y-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-0.5">
          <h3 className="text-sm font-semibold text-text-primary">CurseForge API Key</h3>
          <p className="text-xs text-text-muted">
            Required for installing CurseForge modpacks. Stored encrypted.
          </p>
        </div>

        {statusQuery.isLoading ? (
          <Skeleton className="h-5 w-24 rounded-full" />
        ) : (
          <StatusPill
            configured={status?.configured ?? false}
            source={status?.source ?? "none"}
            hint={status?.hint ?? null}
          />
        )}
      </div>

      {error && <Banner variant="danger" title="Key update failed" description={error} />}

      <div className="flex flex-col sm:flex-row sm:items-center gap-2">
        <div className="relative flex-1">
          <input
            id="curseforge-api-key"
            aria-label="CurseForge API Key"
            data-testid="curseforge-api-key-input"
            type={showKey ? "text" : "password"}
            autoComplete="off"
            disabled={!canWrite}
            value={apiKey}
            onChange={(e) => {
              setError(null);
              setApiKey(e.target.value);
            }}
            placeholder="Paste CurseForge Eternal key ($2a$10$...)"
            className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-2 pr-10 text-sm text-text-primary placeholder:text-text-muted focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
          />
          <button
            type="button"
            disabled={!canWrite}
            onClick={() => setShowKey((prev) => !prev)}
            aria-label={showKey ? "Hide API key" : "Show API key"}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-text-muted hover:text-text-primary cursor-pointer disabled:opacity-40"
          >
            <Icon name={showKey ? "eye-off" : "eye"} size={15} />
          </button>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Button
            type="button"
            data-testid="save-curseforge-key-btn"
            variant="primary"
            size="sm"
            loading={isSaving}
            disabled={!canWrite || !apiKey.trim()}
            onClick={handleSave}
          >
            Save Key
          </Button>
          {status?.configured && status.source === "panel" && (
            <Button
              type="button"
              data-testid="delete-curseforge-key-btn"
              variant="outline"
              size="sm"
              icon="trash"
              loading={isDeleting}
              disabled={!canWrite}
              onClick={handleDelete}
            >
              Remove
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}

function LoaderCacheCard({ canWrite }: { canWrite: boolean }) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const hasLecApi = typeof api.listLecEntries === "function";

  const entriesQuery = useQuery({
    queryKey: queryKeys.p55.lecEntries(),
    queryFn: async () => api.listLecEntries?.() ?? [],
    enabled: hasLecApi,
  });

  const [prewarmOpen, setPrewarmOpen] = useState(false);
  const [cleanOpen, setCleanOpen] = useState(false);
  const [lastPrewarmOpId, setLastPrewarmOpId] = useState<string | null>(null);
  const [lastGcSummary, setLastGcSummary] = useState<string | null>(null);

  const entries = entriesQuery.data ?? [];
  const totalBytes = entries.reduce((sum, entry) => sum + (entry.size_bytes || 0), 0);

  const handlePrewarmSuccess = (res: LecPrewarmResponse) => {
    setLastPrewarmOpId(res.operation_id ?? null);
  };

  const handleGcSuccess = (res: LecGcResponse) => {
    setLastGcSummary(
      `${res.pruned_lec_keys.length} cached loaders removed · ${res.pruned_cas_digests.length} unused files freed · ${formatBytes(res.freed_bytes)} freed`,
    );
  };

  return (
    <section
      data-testid="host-lec-cache-card"
      className="rounded-xl border border-border-subtle bg-surface-card p-5 shadow-2xs space-y-4"
    >
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="space-y-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-text-primary">Loader Cache</h3>
            {!entriesQuery.isLoading && !entriesQuery.isError && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-muted px-2.5 py-0.5 text-[11px] font-medium text-text-secondary">
                {entries.length} cached · {formatBytes(totalBytes)}
              </span>
            )}
          </div>
          <p className="text-xs text-text-muted">
            Pre-built Fabric, Forge, NeoForge, Quilt, and Paper runtimes shared across servers.
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Button
            type="button"
            data-testid="open-prewarm-modal-btn"
            variant="secondary"
            size="sm"
            icon="download"
            disabled={!canWrite}
            onClick={() => setPrewarmOpen(true)}
          >
            Pre-Warm...
          </Button>
          <Button
            type="button"
            data-testid="open-clean-cache-modal-btn"
            variant="ghost"
            size="sm"
            icon="trash"
            disabled={!canWrite}
            onClick={() => setCleanOpen(true)}
          >
            Clean Cache...
          </Button>
        </div>
      </div>

      {(lastPrewarmOpId || lastGcSummary) && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-surface-page px-3 py-2 text-xs text-text-secondary">
          <span>{lastGcSummary ?? "Loader pre-warm completed."}</span>
          {lastPrewarmOpId && (
            <Button
              type="button"
              size="xs"
              variant="outline"
              icon="activity"
              onClick={() => useOperationStore.getState().openDrawer(lastPrewarmOpId)}
            >
              Open Operation Drawer
            </Button>
          )}
        </div>
      )}

      {entriesQuery.isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      ) : entriesQuery.isError ? (
        <ErrorState
          title="Could not load loader cache"
          message={errorMessage(entriesQuery.error)}
          onRetry={() => entriesQuery.refetch()}
        />
      ) : entries.length === 0 ? (
        <p className="rounded-lg bg-surface-page/70 px-4 py-4 text-xs text-text-muted">
          No cached loaders yet. Loaders cache automatically when you create or upgrade a server.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border-subtle">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-subtle bg-surface-page/70 text-left text-xs text-text-muted">
                <th className="px-3 py-2 font-medium">Loader</th>
                <th className="px-3 py-2 font-medium">Minecraft</th>
                <th className="px-3 py-2 font-medium">Build</th>
                <th className="px-3 py-2 font-medium">Java</th>
                <th className="px-3 py-2 font-medium">Size</th>
                <th className="px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {entries.map((entry) => (
                <tr key={entry.lec_key} className="hover:bg-surface-hover/50 transition-colors">
                  <td className="px-3 py-2.5" title={entry.lec_key}>
                    <LoaderBadge loader={entry.loader_id} />
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs text-text-primary">
                    {entry.mc_version}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs text-text-secondary" title={entry.lec_key}>
                    {entry.loader_version}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs text-text-secondary">
                    {entry.java_major != null ? `Java ${entry.java_major}` : "—"}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs text-text-secondary">
                    {formatBytes(entry.size_bytes)}
                  </td>
                  <td className="px-3 py-2.5 text-xs">
                    {entry.ready_on_disk ? (
                      <span className="inline-flex items-center gap-1 rounded-full border border-status-success-border bg-status-success-bg px-2 py-0.5 text-[11px] font-medium text-status-success">
                        <Icon name="check" size={11} />
                        Ready
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full border border-status-warning-border bg-status-warning-bg px-2 py-0.5 text-[11px] font-medium text-status-warning">
                        {entry.status}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <PreWarmCacheModal
        open={prewarmOpen}
        onClose={() => setPrewarmOpen(false)}
        onSuccess={handlePrewarmSuccess}
      />
      <CleanCacheModal
        open={cleanOpen}
        onClose={() => setCleanOpen(false)}
        onSuccess={handleGcSuccess}
      />
    </section>
  );
}

export function ModpacksCacheTab() {
  const { canWriteSettings } = useSettingsPermissions();

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-text-primary">Modpacks &amp; Cache</h2>
          <p className="text-sm text-text-muted mt-0.5">
            CurseForge API access and shared loader cache.
          </p>
        </div>
        {!canWriteSettings && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border-subtle bg-surface-muted px-3 py-1 text-xs font-medium text-text-muted self-start">
            <Icon name="lock" size={12} />
            Read-only access
          </span>
        )}
      </div>

      <CurseForgeCard canWrite={canWriteSettings} />
      <LoaderCacheCard canWrite={canWriteSettings} />
    </div>
  );
}
