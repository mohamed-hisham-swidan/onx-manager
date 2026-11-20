import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { useOperationStore } from "@/operations/stores/operationStore";
import type {
  CurseForgeIntegrationStatusResponse,
  LecGcResponse,
  LecPrewarmResponse,
  P55LoaderId,
} from "@/server_manager/types";

const LOADERS: P55LoaderId[] = ["fabric", "quilt", "forge", "neoforge", "paper"];

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
      <span className="inline-flex items-center gap-1.5 rounded-full border border-border-default bg-surface-elevated px-2.5 py-1 text-xs font-semibold text-text-secondary">
        <Icon name="alert" size={12} />
        Not Configured
      </span>
    );
  }

  const label =
    source === "env"
      ? "Configured (Environment Variable Fallback)"
      : "Configured (Panel Encrypted Store)";

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 rounded-full border border-status-success-border bg-status-success-bg px-2.5 py-1 text-xs font-semibold text-status-success">
      <Icon name="check" size={12} />
      <span>{label}</span>
      {hint && <span className="font-mono text-[11px] text-text-secondary">{hint}</span>}
    </span>
  );
}

function CurseForgeIntegrationCard() {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();
  const hasStatusApi = typeof api.getCurseForgeIntegrationStatus === "function";

  const statusQuery = useQuery({
    queryKey: queryKeys.p55.curseforgeIntegration(),
    queryFn: async () => api.getCurseForgeIntegrationStatus?.() ?? null,
    enabled: hasStatusApi,
  });

  const [apiKey, setApiKey] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const status = statusQuery.data ?? null;

  async function handleSave() {
    if (!apiKey.trim() || typeof api.setCurseForgeIntegrationKey !== "function") return;
    setIsSaving(true);
    setNotice(null);
    setError(null);
    try {
      await api.setCurseForgeIntegrationKey({ api_key: apiKey.trim() });
      // Secret hygiene: never retain the plaintext key after submission.
      setApiKey("");
      setNotice("CurseForge API key encrypted and stored in the panel secret store.");
      await queryClient.invalidateQueries({ queryKey: queryKeys.p55.curseforgeIntegration() });
    } catch (err) {
      setError(errorMessage(err));
      setApiKey("");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete() {
    if (typeof api.deleteCurseForgeIntegrationKey !== "function") return;
    setIsDeleting(true);
    setNotice(null);
    setError(null);
    try {
      await api.deleteCurseForgeIntegrationKey();
      setNotice("Stored CurseForge API key removed.");
      await queryClient.invalidateQueries({ queryKey: queryKeys.p55.curseforgeIntegration() });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <section
      data-testid="curseforge-integration-card"
      className="rounded-2xl border border-border-default bg-surface-card p-6 shadow-xs space-y-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-primary/10 text-accent-primary">
              <Icon name="modrinth" size={18} />
            </span>
            <h3 className="text-base font-bold text-text-primary">
              CurseForge Panel Integration
            </h3>
          </div>
          <p className="text-xs text-text-muted max-w-2xl">
            CurseForge modpack inspection and manual-download resolution require an
            Eternal API key. The key is encrypted at rest and is never returned to the
            browser in plaintext.
          </p>
        </div>
        {statusQuery.isLoading ? (
          <span className="text-xs text-text-muted">Checking status…</span>
        ) : (
          <StatusPill
            configured={status?.configured ?? false}
            source={status?.source ?? "none"}
            hint={status?.hint ?? null}
          />
        )}
      </div>

      {notice && <Banner variant="success" title={notice} />}
      {error && <Banner variant="danger" title={error} />}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label
            htmlFor="curseforge-api-key"
            className="mb-1 block text-xs font-semibold text-text-secondary"
          >
            CurseForge Eternal API Key
          </label>
          <input
            id="curseforge-api-key"
            data-testid="curseforge-api-key-input"
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder="Enter CurseForge Eternal API key ($2a$10$...)"
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
          />
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            data-testid="save-curseforge-key-btn"
            variant="primary"
            size="md"
            icon="lock"
            loading={isSaving}
            disabled={!apiKey.trim()}
            onClick={handleSave}
          >
            Save API Key
          </Button>
          {status?.configured && status.source === "panel" && (
            <Button
              type="button"
              data-testid="delete-curseforge-key-btn"
              variant="danger"
              size="md"
              icon="trash"
              loading={isDeleting}
              onClick={handleDelete}
            >
              Remove Stored Key
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}

function HostLecCacheCard() {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();
  const hasLecApi = typeof api.listLecEntries === "function";

  const entriesQuery = useQuery({
    queryKey: queryKeys.p55.lecEntries(),
    queryFn: async () => api.listLecEntries?.() ?? [],
    enabled: hasLecApi,
  });

  const [loaderId, setLoaderId] = useState<P55LoaderId>("fabric");
  const [mcVersion, setMcVersion] = useState("1.21.1");
  const [loaderVersion, setLoaderVersion] = useState("0.16.9");
  const [installerVersion, setInstallerVersion] = useState("1.0.1");
  const [asyncMode, setAsyncMode] = useState(false);
  const [isPrewarming, setIsPrewarming] = useState(false);
  const [prewarmResult, setPrewarmResult] = useState<LecPrewarmResponse | null>(null);
  const [prewarmError, setPrewarmError] = useState<string | null>(null);

  const [minAgeDays, setMinAgeDays] = useState(7);
  const [isGcRunning, setIsGcRunning] = useState(false);
  const [gcResult, setGcResult] = useState<LecGcResponse | null>(null);
  const [gcError, setGcError] = useState<string | null>(null);

  const entries = entriesQuery.data ?? [];

  async function handlePrewarm() {
    if (typeof api.prewarmLecEntry !== "function") return;
    if (!mcVersion.trim() || !loaderVersion.trim()) {
      setPrewarmError("Minecraft version and loader/build version are required.");
      return;
    }
    if (loaderId === "fabric" && !installerVersion.trim()) {
      setPrewarmError("Fabric installer version is required for Fabric LEC entries.");
      return;
    }
    setIsPrewarming(true);
    setPrewarmError(null);
    setPrewarmResult(null);
    try {
      const result = await api.prewarmLecEntry({
        loader_id: loaderId,
        mc_version: mcVersion.trim(),
        loader_version: loaderVersion.trim(),
        installer_version:
          loaderId === "fabric" ? installerVersion.trim() : null,
        async_mode: asyncMode,
      });
      setPrewarmResult(result);
      await queryClient.invalidateQueries({ queryKey: queryKeys.p55.lecEntries() });
    } catch (err) {
      setPrewarmError(errorMessage(err));
    } finally {
      setIsPrewarming(false);
    }
  }

  async function handleGc() {
    if (typeof api.gcLecEntries !== "function") return;
    if (!Number.isFinite(minAgeDays) || minAgeDays < 0) {
      setGcError("Minimum age must be zero or greater.");
      return;
    }
    setIsGcRunning(true);
    setGcError(null);
    setGcResult(null);
    try {
      const result = await api.gcLecEntries({ min_age_days: minAgeDays });
      setGcResult(result);
      await queryClient.invalidateQueries({ queryKey: queryKeys.p55.lecEntries() });
    } catch (err) {
      setGcError(errorMessage(err));
    } finally {
      setIsGcRunning(false);
    }
  }

  return (
    <section
      data-testid="host-lec-cache-card"
      className="rounded-2xl border border-border-default bg-surface-card p-6 shadow-xs space-y-5"
    >
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-primary/10 text-accent-primary">
            <Icon name="database" size={18} />
          </span>
          <h3 className="text-base font-bold text-text-primary">
            Host Loader Environment Cache (LEC)
          </h3>
        </div>
        <p className="text-xs text-text-muted max-w-2xl">
          Verified loader environments shared by every server on this host. Pre-warm
          entries before an upgrade so the isolated test container can boot without
          network downloads.
        </p>
      </div>

      {entriesQuery.isLoading ? (
        <p className="text-xs text-text-muted">Loading cached environments…</p>
      ) : entries.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border-default bg-surface-page p-4 text-sm text-text-muted">
          No LEC entries cached on this host yet.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border-default">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-subtle bg-surface-page/60 text-left text-xs text-text-muted">
                <th className="px-3 py-2 font-medium">LEC Key</th>
                <th className="px-3 py-2 font-medium">Loader</th>
                <th className="px-3 py-2 font-medium">MC</th>
                <th className="px-3 py-2 font-medium">Loader Ver.</th>
                <th className="px-3 py-2 font-medium">Java</th>
                <th className="px-3 py-2 font-medium">Files</th>
                <th className="px-3 py-2 font-medium">Size</th>
                <th className="px-3 py-2 font-medium">Disk Status</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.lec_key} className="border-b border-border-subtle last:border-b-0">
                  <td className="px-3 py-2 font-mono text-[11px] text-text-primary">
                    {entry.lec_key}
                  </td>
                  <td className="px-3 py-2">
                    <LoaderBadge loader={entry.loader_id} />
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{entry.mc_version}</td>
                  <td className="px-3 py-2 font-mono text-xs">{entry.loader_version}</td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {entry.java_major != null ? `Java ${entry.java_major}` : "—"}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{entry.file_count}</td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {formatBytes(entry.size_bytes)}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {entry.ready_on_disk ? (
                      <span className="inline-flex items-center gap-1 rounded-full border border-status-success-border bg-status-success-bg px-2 py-0.5 font-medium text-status-success">
                        <Icon name="check" size={11} />
                        Verified (.onx-complete.json)
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full border border-status-warning-border bg-status-warning-bg px-2 py-0.5 font-medium text-status-warning">
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

      <div className="rounded-xl border border-border-subtle bg-surface-page/50 p-4 space-y-3">
        <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary">
          Pre-Warm New LEC Entry
        </h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <div>
            <label htmlFor="lec-loader" className="mb-1 block text-[11px] font-medium text-text-muted">
              Loader
            </label>
            <select
              id="lec-loader"
              value={loaderId}
              onChange={(event) => setLoaderId(event.target.value as P55LoaderId)}
              className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
            >
              {LOADERS.map((loader) => (
                <option key={loader} value={loader}>
                  {loader}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="lec-mc-version" className="mb-1 block text-[11px] font-medium text-text-muted">
              Minecraft Version
            </label>
            <input
              id="lec-mc-version"
              value={mcVersion}
              onChange={(event) => setMcVersion(event.target.value)}
              placeholder="1.21.1"
              className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
            />
          </div>
          <div>
            <label htmlFor="lec-loader-version" className="mb-1 block text-[11px] font-medium text-text-muted">
              Loader / Build Version
            </label>
            <input
              id="lec-loader-version"
              value={loaderVersion}
              onChange={(event) => setLoaderVersion(event.target.value)}
              placeholder="0.16.9 / 21.1.77 / 130"
              className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
            />
          </div>
          <div>
            <label htmlFor="lec-installer-version" className="mb-1 block text-[11px] font-medium text-text-muted">
              Fabric Installer
            </label>
            <input
              id="lec-installer-version"
              value={installerVersion}
              disabled={loaderId !== "fabric"}
              onChange={(event) => setInstallerVersion(event.target.value)}
              placeholder="1.0.1"
              className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary disabled:opacity-50"
            />
          </div>
          <div className="flex items-end">
            <label className="inline-flex items-center gap-2 text-xs text-text-secondary">
              <input
                type="checkbox"
                checked={asyncMode}
                onChange={(event) => setAsyncMode(event.target.checked)}
                className="h-4 w-4 rounded border-border-default"
              />
              Run in background
            </label>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            data-testid="lec-prewarm-btn"
            size="sm"
            variant="primary"
            icon="download"
            loading={isPrewarming}
            onClick={handlePrewarm}
          >
            Pre-Warm Cache
          </Button>
          {prewarmResult && (
            <span className="text-xs text-text-secondary">
              {prewarmResult.status === "queued"
                ? `Queued as operation ${prewarmResult.operation_id ?? "unknown"}.`
                : `Ready: ${prewarmResult.file_count} files, ${formatBytes(prewarmResult.total_bytes)}.`}
            </span>
          )}
          {prewarmResult?.operation_id && (
            <Button
              type="button"
              size="xs"
              variant="secondary"
              icon="activity"
              onClick={() =>
                useOperationStore
                  .getState()
                  .openDrawer(prewarmResult.operation_id as string)
              }
            >
              Open Operation Drawer
            </Button>
          )}
        </div>
        {prewarmError && <p className="text-xs text-status-danger">{prewarmError}</p>}
      </div>

      <div className="rounded-xl border border-border-subtle bg-surface-page/50 p-4 space-y-3">
        <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary">
          Garbage Collection
        </h4>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="lec-min-age" className="mb-1 block text-[11px] font-medium text-text-muted">
              Minimum Age (days)
            </label>
            <input
              id="lec-min-age"
              type="number"
              min={0}
              max={3650}
              value={minAgeDays}
              onChange={(event) => setMinAgeDays(Number(event.target.value))}
              className="w-28 rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
            />
          </div>
          <Button
            type="button"
            data-testid="lec-gc-btn"
            size="sm"
            variant="secondary"
            icon="trash"
            loading={isGcRunning}
            onClick={handleGc}
          >
            Clean Unused Cache
          </Button>
          {gcResult && (
            <span className="text-xs text-text-secondary">
              {gcResult.pruned_lec_keys.length} LEC keys pruned,{" "}
              {gcResult.pruned_cas_digests.length} CAS blobs pruned,{" "}
              {formatBytes(gcResult.freed_bytes)} freed.
            </span>
          )}
        </div>
        {gcError && <p className="text-xs text-status-danger">{gcError}</p>}
      </div>
    </section>
  );
}

export function PanelP55IntegrationsSection() {
  return (
    <div className="space-y-6">
      <CurseForgeIntegrationCard />
      <HostLecCacheCard />
    </div>
  );
}
