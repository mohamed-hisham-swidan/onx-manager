import { useEffect, useMemo, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import type { PluginSearchResultResponse } from "@/types";
import { isModpackSupportedLoader } from "@/server_manager/utils/loaderCapabilities";
import type { SelectedWizardAddon } from "./types";

interface AddonsStepProps {
  serverType: string;
  minecraftVersion: string;
  selectedAddons: SelectedWizardAddon[];
  installModpack: boolean;
  onToggleModpack: (enabled: boolean) => void;
  onChangeAddons: (addons: SelectedWizardAddon[]) => void;
  onNext: () => void;
  onSkip: () => void;
  onBack: () => void;
}

function formatDownloads(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function AddonsStep({
  serverType,
  minecraftVersion,
  selectedAddons,
  installModpack,
  onToggleModpack,
  onChangeAddons,
  onNext,
  onSkip,
  onBack,
}: AddonsStepProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const isModded = isModpackSupportedLoader(serverType);
  const projectType: "mod" | "plugin" = isModded ? "mod" : "plugin";
  const nounPlural = isModded ? "Mods" : "Plugins";

  const [searchInput, setSearchInput] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [fetchState, setFetchState] = useState<{
    key: string | null;
    items: PluginSearchResultResponse[];
    error: string | null;
  }>({ key: null, items: [], error: null });

  const requestKey =
    typeof api.searchMarketplaceGlobal === "function"
      ? `${serverType}:${minecraftVersion}:${projectType}:${submittedQuery}`
      : null;
  const loading = requestKey !== null && fetchState.key !== requestKey;
  const results = requestKey !== null && fetchState.key === requestKey ? fetchState.items : [];
  const fetchError = requestKey !== null && fetchState.key === requestKey ? fetchState.error : null;

  useEffect(() => {
    if (typeof api.searchMarketplaceGlobal !== "function" || !requestKey) {
      return;
    }
    let cancelled = false;
    api
      .searchMarketplaceGlobal(
        submittedQuery,
        projectType,
        12,
        0,
        serverType,
        undefined,
        minecraftVersion || undefined,
      )
      .then((res) => {
        if (cancelled) return;
        setFetchState({ key: requestKey, items: res?.items ?? [], error: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setFetchState({
          key: requestKey,
          items: [],
          error:
            err instanceof Error
              ? err.message
              : `Failed to load ${nounPlural.toLowerCase()} catalog`,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [api, requestKey, submittedQuery, projectType, serverType, minecraftVersion, nounPlural]);

  const selectedIds = useMemo(
    () => new Set(selectedAddons.map((a) => a.project_id)),
    [selectedAddons],
  );

  const toggleItem = (item: PluginSearchResultResponse) => {
    if (selectedIds.has(item.project_id)) {
      onChangeAddons(selectedAddons.filter((a) => a.project_id !== item.project_id));
      return;
    }
    onChangeAddons([
      ...selectedAddons,
      {
        project_id: item.project_id,
        title: item.title,
        author: item.author,
        description: item.description,
        icon_url: item.icon_url,
        downloads: item.downloads,
        project_type: projectType,
      },
    ]);
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSubmittedQuery(searchInput.trim());
  };

  return (
    <div className="space-y-5">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-lg font-semibold text-text-primary">
            {isModded ? "Mods & Modpack (Optional)" : "Browse Plugins (Optional)"}
          </h3>
          <span className="rounded-full border border-border-default bg-surface-elevated px-2.5 py-0.5 text-[11px] font-medium text-text-secondary">
            {serverType} · MC {minecraftVersion || "latest"}
          </span>
        </div>
        <p className="mt-1 text-xs text-text-muted">
          {isModded
            ? "Attach a .mrpack / CurseForge modpack or pick individual Modrinth mods to install automatically after creating your server."
            : "Select Modrinth plugins to download and install automatically once your server is created, or skip for now."}
        </p>
      </div>

      {isModded && (
        <button
          type="button"
          data-testid="addons-modpack-toggle"
          aria-pressed={installModpack}
          onClick={() => onToggleModpack(!installModpack)}
          className={`w-full text-left rounded-xl border p-4 transition-colors cursor-pointer ${
            installModpack
              ? "border-accent-primary bg-accent-primary/10 ring-1 ring-accent-primary/30"
              : "border-border-default bg-surface-card hover:bg-surface-hover"
          }`}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-primary/15 text-accent-primary">
                <Icon name="modrinth" size={18} />
              </div>
              <div className="min-w-0">
                <div className="font-semibold text-sm text-text-primary">
                  Install a Modpack (.mrpack / CurseForge)
                </div>
                <div className="text-xs text-text-muted">
                  Opens the modpack upload &amp; installer wizard right after server creation.
                </div>
              </div>
            </div>
            <span
              className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${
                installModpack
                  ? "bg-accent-primary text-accent-contrast-text"
                  : "border border-border-default bg-surface-page text-text-secondary"
              }`}
            >
              {installModpack ? "Enabled" : "Optional"}
            </span>
          </div>
        </button>
      )}

      {selectedAddons.length > 0 && (
        <div
          data-testid="wizard-selected-addons"
          className="rounded-xl border border-accent-primary/30 bg-accent-primary/5 p-3"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-text-primary">
              Selected {nounPlural} ({selectedAddons.length})
            </span>
            <button
              type="button"
              onClick={() => onChangeAddons([])}
              className="text-xs text-text-muted hover:text-text-primary cursor-pointer"
            >
              Clear all
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {selectedAddons.map((addon) => (
              <span
                key={addon.project_id}
                className="inline-flex items-center gap-1.5 rounded-lg border border-accent-primary/30 bg-surface-card px-2.5 py-1 text-xs font-medium text-text-primary"
              >
                <span>{addon.title}</span>
                <button
                  type="button"
                  aria-label={`Remove ${addon.title}`}
                  onClick={() =>
                    onChangeAddons(selectedAddons.filter((a) => a.project_id !== addon.project_id))
                  }
                  className="text-text-muted hover:text-status-danger cursor-pointer"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-3 rounded-xl border border-border-default bg-surface-card p-4">
        <form onSubmit={handleSearchSubmit} className="flex gap-2">
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder={`Search Modrinth ${nounPlural.toLowerCase()}...`}
            aria-label={`Search ${nounPlural.toLowerCase()}`}
            className="flex-1 rounded-lg border border-border-default bg-surface-page px-3.5 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
          />
          <button
            type="submit"
            className="rounded-lg border border-border-default bg-surface-elevated px-4 py-2 text-sm font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
          >
            Search
          </button>
        </form>

        {fetchError && (
          <div
            role="status"
            className="rounded-lg border border-status-warning/30 bg-status-warning-bg px-3 py-2 text-xs text-status-warning"
          >
            Could not load Modrinth catalog ({fetchError}). You can skip this step and install {nounPlural.toLowerCase()} later.
          </div>
        )}

        {loading ? (
          <div className="py-8 text-center text-sm text-text-muted">
            Loading popular {nounPlural.toLowerCase()}...
          </div>
        ) : results.length === 0 && !fetchError ? (
          <div className="py-8 text-center text-sm text-text-muted">
            No matching {nounPlural.toLowerCase()} found. Try another search or skip this step.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-80 overflow-y-auto pr-1">
            {results.map((item) => {
              const isSelected = selectedIds.has(item.project_id);
              return (
                <button
                  key={item.project_id}
                  type="button"
                  data-testid={`addon-card-${item.project_id}`}
                  aria-pressed={isSelected}
                  onClick={() => toggleItem(item)}
                  className={`flex items-start gap-3 rounded-xl border p-3 text-left transition-colors cursor-pointer ${
                    isSelected
                      ? "border-accent-primary bg-accent-primary/10"
                      : "border-border-subtle bg-surface-page hover:border-border-default hover:bg-surface-hover/50"
                  }`}
                >
                  {item.icon_url ? (
                    <img
                      src={item.icon_url}
                      alt=""
                      className="h-9 w-9 shrink-0 rounded-lg object-cover bg-surface-elevated"
                    />
                  ) : (
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-elevated text-text-muted">
                      <Icon name="plugin" size={18} />
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-semibold text-text-primary">
                        {item.title}
                      </span>
                      <span
                        className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                          isSelected
                            ? "bg-accent-primary text-accent-contrast-text"
                            : "bg-surface-elevated text-text-secondary"
                        }`}
                      >
                        {isSelected ? "Selected" : "Select"}
                      </span>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-xs text-text-muted">
                      {item.description || `By ${item.author}`}
                    </p>
                    <div className="mt-1.5 flex items-center gap-2 text-[11px] text-text-muted">
                      <span className="truncate">by {item.author}</span>
                      <span>•</span>
                      <span>{formatDownloads(item.downloads)} downloads</span>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          onClick={onBack}
          className="text-sm text-accent-primary hover:underline cursor-pointer"
        >
          Back
        </button>
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={onSkip}
            className="rounded-lg border border-border-default px-4 py-2 text-sm font-medium text-text-secondary hover:bg-surface-hover transition-colors cursor-pointer"
          >
            Skip for now
          </button>
          <button
            type="button"
            onClick={onNext}
            className="rounded-lg bg-accent-primary px-5 py-2 text-sm font-semibold text-accent-contrast-text hover:bg-accent-hover transition-colors shadow-xs cursor-pointer"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
