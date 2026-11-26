import React, { useCallback, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/States";
import { useHostResources } from "@/server_manager/hooks/useHostResources";
import {
  useDeleteServer,
  useServerDetail,
  useUpdateServer,
} from "@/server_manager/hooks/useServers";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { useFleetPermissions } from "@/server_manager/components/servers/serversUtils";
import { ServerSettingsShell } from "@/server_manager/components/server-settings/ServerSettingsShell";
import { GeneralServerTab } from "@/server_manager/components/server-settings/GeneralServerTab";
import { ResourcesJvmTab } from "@/server_manager/components/server-settings/ResourcesJvmTab";
import { GameplayWorldTab } from "@/server_manager/components/server-settings/GameplayWorldTab";
import { RulesSecurityTab } from "@/server_manager/components/server-settings/RulesSecurityTab";
import { UpgradesModeTab } from "@/server_manager/components/server-settings/UpgradesModeTab";
import { DangerZoneTab } from "@/server_manager/components/server-settings/DangerZoneTab";
import { ServerSettingsSearchResults } from "@/server_manager/components/server-settings/ServerSettingsSearchResults";
import { StickyServerSaveBar } from "@/server_manager/components/server-settings/StickyServerSaveBar";
import {
  buildInitialFormState,
  buildServerSnapshotKey,
  buildServerUpdatePayload,
  clampDraftsIntoState,
  clampNumericValue,
  computeDirtyFields,
  extractCustomProperties,
  getNumericBounds,
  validateServerForm,
  type NumericDraftKey,
  type ServerSettingsFormState,
  type ServerSettingsTabId,
} from "@/server_manager/components/server-settings/serverSettingsModel";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";

export function ServerSettingsPage() {
  const { serverId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const branchCtx = useServerBranchContext();
  const gitBacked = Boolean(branchCtx?.gitBacked);
  const activeBranch = gitBacked ? branchCtx?.branch : undefined;
  const isMainBranch = Boolean(gitBacked && (!activeBranch || activeBranch === "main"));
  const isWorkingBranch = Boolean(gitBacked && activeBranch && activeBranch !== "main");

  const { data: server, isLoading, error } = useServerDetail(
    serverId ?? "",
    activeBranch,
  );
  const { data: hostBudget } = useHostResources();
  const updateServer = useUpdateServer();
  const deleteServer = useDeleteServer();
  const permissions = useFleetPermissions();

  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();

  const branchesQuery = useQuery({
    queryKey: queryKeys.versioning.branches(serverId ?? ""),
    queryFn: () =>
      typeof api.getServerBranches === "function"
        ? api.getServerBranches(serverId!)
        : Promise.resolve([]),
    enabled: Boolean(serverId && isWorkingBranch),
  });

  const branchRuntimeQuery = useQuery({
    queryKey: queryKeys.versioning.branchRuntime(
      serverId ?? "",
      activeBranch ?? "main",
    ),
    queryFn: () =>
      typeof api.getBranchRuntime === "function"
        ? api.getBranchRuntime(serverId!, activeBranch!)
        : Promise.resolve(null),
    enabled: Boolean(serverId && isWorkingBranch && activeBranch),
  });

  const activeBranchRecord = (branchesQuery.data ?? []).find(
    (b) => b.name === activeBranch,
  );
  const branchRuntimeStatus = branchRuntimeQuery.data?.runtime_status;
  const isWorktreeLocked = Boolean(
    isWorkingBranch &&
      (activeBranchRecord?.worktree_locked ||
        branchRuntimeStatus === "running" ||
        branchRuntimeStatus === "starting"),
  );

  const [searchParams, setSearchParams] = useSearchParams();
  const validTabIds = new Set<ServerSettingsTabId>([
    "general",
    "resources",
    "gameplay",
    "rules",
    "lifecycle",
    "danger",
  ]);
  const urlTabParam = searchParams.get("tab") as ServerSettingsTabId | null;
  const initialTabFromUrl: ServerSettingsTabId =
    urlTabParam && validTabIds.has(urlTabParam) ? urlTabParam : "general";
  const urlActionParam = searchParams.get("action");

  const [activeTab, setActiveTab] = useState<ServerSettingsTabId>(initialTabFromUrl);
  const [syncedUrlKey, setSyncedUrlKey] = useState(
    `${urlTabParam ?? ""}:${urlActionParam ?? ""}`,
  );
  const curUrlKey = `${urlTabParam ?? ""}:${urlActionParam ?? ""}`;
  if (syncedUrlKey !== curUrlKey) {
    setSyncedUrlKey(curUrlKey);
    if (urlTabParam && validTabIds.has(urlTabParam)) {
      setActiveTab(urlTabParam);
    }
  }
  const handleTabChange = useCallback(
    (tab: ServerSettingsTabId) => {
      setActiveTab(tab);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (tab === "general") {
            next.delete("tab");
          } else {
            next.set("tab", tab);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );
  const changeVersionRequested = urlActionParam === "change-version";
  const consumeChangeVersionAction = useCallback(() => {
    setSearchParams(
      (prev) => {
        if (!prev.has("action")) return prev;
        const next = new URLSearchParams(prev);
        next.delete("action");
        return next;
      },
      { replace: true },
    );
  }, [setSearchParams]);

  const [searchQuery, setSearchQuery] = useState("");
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const deletingRef = useRef(false);

  const serverSnapshotKey = server ? buildServerSnapshotKey(server) : "";
  const scopeKey = `${serverId ?? ""}-${activeBranch ?? "main"}`;

  const [syncedScopeKey, setSyncedScopeKey] = useState(scopeKey);
  const [syncedSnapshotKey, setSyncedSnapshotKey] = useState(serverSnapshotKey);
  const [baseline, setBaseline] = useState<ServerSettingsFormState | null>(() =>
    server ? buildInitialFormState(server) : null,
  );
  const [form, setForm] = useState<ServerSettingsFormState | null>(() =>
    server ? buildInitialFormState(server) : null,
  );
  const [rawDrafts, setRawDrafts] = useState<
    Partial<Record<NumericDraftKey, string>>
  >({});

  if (server && (!form || !baseline || syncedScopeKey !== scopeKey)) {
    const fresh = buildInitialFormState(server);
    setSyncedScopeKey(scopeKey);
    setSyncedSnapshotKey(serverSnapshotKey);
    setBaseline(fresh);
    setForm(fresh);
    setRawDrafts({});
  } else if (server && form && baseline && syncedSnapshotKey !== serverSnapshotKey) {
    const currentlyDirty =
      computeDirtyFields(form, baseline).length > 0 ||
      Object.keys(rawDrafts).length > 0;
    setSyncedSnapshotKey(serverSnapshotKey);
    if (!currentlyDirty) {
      const fresh = buildInitialFormState(server);
      setBaseline(fresh);
      setForm(fresh);
    }
  }

  const restartAndApplyMutation = useMutation({
    mutationFn: () => api.restartServer(serverId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.servers.all });
      queryClient.invalidateQueries({
        queryKey: queryKeys.servers.detail(serverId!, "main"),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.versioning.branches(serverId!),
      });
      toast(
        "success",
        "Server restarting",
        "Pending settings branch will auto-merge during restart.",
      );
    },
    onError: (err) =>
      toast(
        "error",
        "Restart failed",
        err instanceof Error ? err.message : "Failed to restart server",
      ),
  });

  const discardPendingMutation = useMutation({
    mutationFn: () => api.discardPendingSettings(serverId!),
    onSuccess: () => {
      if (server) {
        const fresh = buildInitialFormState(server);
        setBaseline(fresh);
        setForm(fresh);
        setRawDrafts({});
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.servers.all });
      queryClient.invalidateQueries({
        queryKey: queryKeys.servers.detail(serverId!, "main"),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.versioning.branches(serverId!),
      });
      toast(
        "success",
        "Pending settings discarded",
        "Cleared unmerged settings branch.",
      );
    },
    onError: (err) =>
      toast(
        "error",
        "Discard failed",
        err instanceof Error ? err.message : "Failed to discard pending settings",
      ),
  });

  const customProperties = useMemo(
    () => (server ? extractCustomProperties(server) : {}),
    [server],
  );

  if (isLoading) {
    return (
      <div className="mx-auto max-w-6xl space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  if (error || !server || !form || !baseline) {
    return (
      <div className="rounded-xl border border-status-danger-border bg-status-danger-bg p-6">
        <p className="text-sm text-status-danger">
          {error instanceof Error
            ? error.message
            : "Failed to load server details"}
        </p>
      </div>
    );
  }

  const effectiveServerId = serverId ?? server.server_id;
  const canWrite = permissions.canWrite(effectiveServerId);
  const canDelete = permissions.canDelete;
  const canManageVersioning = permissions.canManageVersioning ?? canWrite;
  const formDisabled = !canWrite || isWorktreeLocked;

  const clampedPreview = clampDraftsIntoState(form, rawDrafts, hostBudget);
  const validationErrors = validateServerForm(clampedPreview, hostBudget);
  const dirtyFields = computeDirtyFields(clampedPreview, baseline);
  const dirtyCount = dirtyFields.length;

  const NUMERIC_DRAFT_KEYS: readonly NumericDraftKey[] = [
    "minRam",
    "maxRam",
    "cpuCores",
    "startupTimeout",
    "maxPlayers",
    "viewDistance",
    "simulationDistance",
    "spawnProtection",
    "port",
  ];

  const handleUpdateForm = (patch: Partial<ServerSettingsFormState>) => {
    if (formDisabled) return;
    setForm((prev) => (prev ? { ...prev, ...patch } : prev));
    const keysToClear = NUMERIC_DRAFT_KEYS.filter((k) => k in patch);
    if (keysToClear.length > 0) {
      setRawDrafts((prev) => {
        const next = { ...prev };
        let changed = false;
        for (const k of keysToClear) {
          if (k in next) {
            delete next[k];
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }
  };

  const handleNumericChange = (key: NumericDraftKey, raw: string) => {
    if (formDisabled) return;
    setRawDrafts((prev) => ({ ...prev, [key]: raw }));
    if (raw.trim() !== "") {
      const num = Number(raw);
      if (Number.isFinite(num)) {
        setForm((prev) => (prev ? { ...prev, [key]: Math.round(num) } : prev));
      }
    }
  };

  const handleNumericBlur = (key: NumericDraftKey) => {
    const draft = rawDrafts[key];
    if (draft === undefined) return;
    const bounds = getNumericBounds(hostBudget);
    const clamped = clampNumericValue(draft, form[key], bounds[key]);
    setForm((prev) => {
      if (!prev) return prev;
      const next = { ...prev, [key]: clamped };
      if (key === "minRam" && next.minRam > next.maxRam) {
        next.maxRam = next.minRam;
      } else if (key === "maxRam" && next.maxRam < next.minRam) {
        next.minRam = next.maxRam;
      }
      return next;
    });
    setRawDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const handleNumericStep = (key: NumericDraftKey, delta: number) => {
    if (formDisabled) return;
    const bounds = getNumericBounds(hostBudget);
    const b = bounds[key];
    const nextVal = Math.min(b.max, Math.max(b.min, form[key] + delta));
    setForm((prev) => {
      if (!prev) return prev;
      const next = { ...prev, [key]: nextVal };
      if (key === "minRam" && next.minRam > next.maxRam) {
        next.maxRam = next.minRam;
      } else if (key === "maxRam" && next.maxRam < next.minRam) {
        next.minRam = next.maxRam;
      }
      return next;
    });
    setRawDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const handleApplyRamPreset = (minMb: number, maxMb: number) => {
    if (formDisabled) return;
    setForm((prev) =>
      prev ? { ...prev, minRam: minMb, maxRam: maxMb } : prev,
    );
    setRawDrafts((prev) => {
      const next = { ...prev };
      delete next.minRam;
      delete next.maxRam;
      return next;
    });
  };

  const handleDiscard = () => {
    const fresh = buildInitialFormState(server);
    setBaseline(fresh);
    setForm(fresh);
    setRawDrafts({});
  };

  const performSave = async () => {
    if (formDisabled || updateServer.isPending) return;
    const finalForm = clampDraftsIntoState(form, rawDrafts, hostBudget);
    setForm(finalForm);
    setRawDrafts({});

    const finalErrors = validateServerForm(finalForm, hostBudget);
    if (finalErrors.hasAny) return;
    if (computeDirtyFields(finalForm, baseline).length === 0) return;

    const payload = buildServerUpdatePayload(
      finalForm,
      baseline,
      customProperties,
      { gitBacked, isWorkingBranch },
    );

    if (Object.keys(payload).length === 0) return;

    try {
      await updateServer.mutateAsync({
        serverId: effectiveServerId,
        body: payload,
        branch: gitBacked ? activeBranch : undefined,
      });
      setBaseline(finalForm);
      if (isMainBranch) {
        toast(
          "success",
          "Settings queued",
          "Changes queued to pending settings branch. Restart server to apply.",
        );
      } else if (isWorkingBranch) {
        toast(
          "success",
          "Branch updated",
          `Settings committed to branch "${activeBranch}".`,
        );
      } else {
        toast(
          "success",
          "Settings saved",
          "Settings updated. Restart server to apply.",
        );
      }
    } catch (err) {
      toast(
        "error",
        "Update failed",
        err instanceof Error ? err.message : "Failed to save settings",
      );
    }
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const target = e.target as HTMLElement | null;
    if (
      activeTab === "lifecycle" ||
      activeTab === "danger" ||
      target?.closest?.('[data-testid="server-mode-conversion-card"]')
    ) {
      return;
    }
    void performSave();
  };

  const isSearching = searchQuery.trim().length > 0;
  const showSaveBar = !formDisabled && dirtyCount > 0;

  const topBanners = (
    <div className="space-y-2.5">
      {!canWrite && (
        <div
          data-testid="settings-readonly-pill"
          className="inline-flex items-center gap-1.5 rounded-full border border-border-subtle bg-surface-muted px-3 py-1 text-xs font-medium text-text-secondary"
        >
          <Icon name="lock" size={12} />
          <span>Read-only access</span>
        </div>
      )}

      {isMainBranch && server.pending_settings_branch && (
        <div
          data-testid="pending-settings-banner"
          role="region"
          aria-label="Pending Settings Branch"
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-status-warning-border bg-status-warning-bg px-4 py-2.5 text-xs text-text-primary"
        >
          <div className="min-w-0 space-y-0.5">
            <p className="font-semibold text-status-warning">
              Pending changes queued for next restart
              <span className="ml-2 font-mono font-normal text-text-secondary">
                ({server.pending_settings_branch.branch_name})
              </span>
            </p>
            {server.pending_settings_branch.error_message && (
              <p className="text-text-secondary">
                Auto-merge issue: {server.pending_settings_branch.error_message}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 shrink-0">
            <Link
              to={`/servers/${effectiveServerId}/versioning?branch=${encodeURIComponent(server.pending_settings_branch.branch_name)}`}
              className="inline-flex items-center rounded-lg border border-border-default bg-surface-card px-2.5 py-1 font-medium text-text-primary hover:bg-surface-hover"
            >
              View Diff
            </Link>
            <button
              type="button"
              data-testid="pending-settings-restart-btn"
              disabled={restartAndApplyMutation.isPending || !permissions.canPower(effectiveServerId)}
              onClick={() => restartAndApplyMutation.mutate()}
              className="inline-flex items-center rounded-lg bg-accent-primary px-2.5 py-1 font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-50 cursor-pointer"
            >
              {restartAndApplyMutation.isPending
                ? "Restarting..."
                : "Restart & Apply"}
            </button>
            <button
              type="button"
              data-testid="pending-settings-discard-btn"
              disabled={discardPendingMutation.isPending || !canWrite}
              onClick={() => discardPendingMutation.mutate()}
              className="inline-flex items-center rounded-lg border border-status-danger-border bg-surface-card px-2.5 py-1 font-medium text-status-danger hover:bg-status-danger-bg disabled:opacity-50 cursor-pointer"
            >
              {discardPendingMutation.isPending ? "Discarding..." : "Discard"}
            </button>
          </div>
        </div>
      )}

      {isWorktreeLocked && (
        <div
          data-testid="worktree-locked-banner"
          role="status"
          className="flex items-center gap-2 rounded-xl border border-status-warning-border bg-status-warning-bg px-4 py-2.5 text-xs font-medium text-status-warning"
        >
          <Icon name="lock" size={14} className="shrink-0" />
          <span>
            Branch test container is running. Stop it to edit branch settings.
          </span>
        </div>
      )}

      {(!gitBacked || isMainBranch) &&
        !isWorktreeLocked &&
        server.status === "running" && (
          <div
            data-testid="running-advisory-strip"
            role="status"
            className="flex items-center gap-2 rounded-xl border border-border-subtle bg-surface-muted px-4 py-2 text-xs text-text-secondary"
          >
            <Icon name="info" size={14} className="text-text-muted shrink-0" />
            <span>Server is running — changes apply on next restart.</span>
          </div>
        )}
    </div>
  );

  return (
    <>
      <form
        onSubmit={handleFormSubmit}
        onKeyDown={(e) => {
          if (
            e.key === "Enter" &&
            (e.target as HTMLElement | null)?.closest?.(
              '[data-testid="server-mode-conversion-card"]',
            )
          ) {
            e.preventDefault();
          }
        }}
        data-testid="server-settings-form"
        noValidate
      >
        <ServerSettingsShell
          serverId={effectiveServerId}
          activeTab={activeTab}
          onTabChange={handleTabChange}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          gitBacked={gitBacked}
          activeBranch={activeBranch}
          canDelete={canDelete}
          topNotice={
            showSaveBar ? (
              <StickyServerSaveBar
                dirtyCount={dirtyCount}
                hasValidationErrors={validationErrors.hasAny}
                isPending={updateServer.isPending}
                gitBacked={gitBacked}
                isMainBranch={isMainBranch}
                branchName={activeBranch}
                onDiscard={handleDiscard}
                onSave={() => void performSave()}
              />
            ) : null
          }
          topBanners={topBanners}
        >
          {isSearching ? (
            <ServerSettingsSearchResults
              query={searchQuery}
              serverId={effectiveServerId}
              server={server}
              form={form}
              rawDrafts={rawDrafts}
              errors={validationErrors}
              disabled={formDisabled}
              isWorkingBranch={isWorkingBranch}
              gitBacked={gitBacked}
              activeBranch={activeBranch}
              hostBudget={hostBudget}
              onClearSearch={() => setSearchQuery("")}
              onJumpToTab={handleTabChange}
              onUpdateForm={handleUpdateForm}
              onNumericChange={handleNumericChange}
              onNumericBlur={handleNumericBlur}
              onNumericStep={handleNumericStep}
              onApplyRamPreset={handleApplyRamPreset}
            />
          ) : (
            <>
              {activeTab === "general" && (
                <GeneralServerTab
                  serverId={effectiveServerId}
                  server={server}
                  form={form}
                  rawDrafts={rawDrafts}
                  errors={validationErrors}
                  disabled={formDisabled}
                  gitBacked={gitBacked}
                  isMainBranch={isMainBranch}
                  isWorkingBranch={isWorkingBranch}
                  activeBranch={activeBranch}
                  onUpdateForm={handleUpdateForm}
                  onNumericChange={handleNumericChange}
                  onNumericBlur={handleNumericBlur}
                  onNumericStep={handleNumericStep}
                />
              )}

              {activeTab === "resources" && (
                <ResourcesJvmTab
                  form={form}
                  rawDrafts={rawDrafts}
                  errors={validationErrors}
                  disabled={formDisabled}
                  gitBacked={gitBacked}
                  hostBudget={hostBudget}
                  onUpdateForm={handleUpdateForm}
                  onNumericChange={handleNumericChange}
                  onNumericBlur={handleNumericBlur}
                  onNumericStep={handleNumericStep}
                  onApplyRamPreset={handleApplyRamPreset}
                />
              )}

              {activeTab === "gameplay" && (
                <GameplayWorldTab
                  form={form}
                  rawDrafts={rawDrafts}
                  errors={validationErrors}
                  disabled={formDisabled}
                  onUpdateForm={handleUpdateForm}
                  onNumericChange={handleNumericChange}
                  onNumericBlur={handleNumericBlur}
                  onNumericStep={handleNumericStep}
                />
              )}

              {activeTab === "rules" && (
                <RulesSecurityTab
                  form={form}
                  disabled={formDisabled}
                  onUpdateForm={handleUpdateForm}
                />
              )}

              {activeTab === "lifecycle" && (
                <UpgradesModeTab
                  serverId={effectiveServerId}
                  server={server}
                  canWrite={canWrite}
                  canManageVersioning={canManageVersioning}
                  initialChangeVersionOpen={changeVersionRequested}
                  onChangeVersionConsumed={consumeChangeVersionAction}
                />
              )}

              {activeTab === "danger" && (
                <DangerZoneTab
                  canDelete={canDelete}
                  isDeleting={deleteServer.isPending}
                  onRequestDelete={() => setShowDeleteModal(true)}
                />
              )}
            </>
          )}
        </ServerSettingsShell>
      </form>

      <ConfirmDialog
        open={showDeleteModal}
        title={`Delete "${server.name}"?`}
        description="Are you sure you want to permanently delete this server? All player data, worlds, configurations, and installed files will be permanently erased. This action cannot be undone."
        confirmLabel={deleteServer.isPending ? "Deleting..." : "Delete Server"}
        cancelLabel="Cancel"
        variant="danger"
        isPending={deleteServer.isPending}
        onConfirm={() => {
          if (deleteServer.isPending || deletingRef.current) return;
          deletingRef.current = true;
          deleteServer.mutate(effectiveServerId, {
            onSuccess: () => {
              deletingRef.current = false;
              setShowDeleteModal(false);
              toast(
                "success",
                "Server deleted",
                `"${server.name}" was permanently deleted.`,
              );
              navigate("/servers", { replace: true });
            },
            onError: (err) => {
              deletingRef.current = false;
              toast(
                "error",
                "Delete failed",
                err instanceof Error ? err.message : "Failed to delete server",
              );
              setShowDeleteModal(false);
            },
          });
        }}
        onCancel={() => {
          if (deleteServer.isPending) return;
          setShowDeleteModal(false);
        }}
      />
    </>
  );
}
