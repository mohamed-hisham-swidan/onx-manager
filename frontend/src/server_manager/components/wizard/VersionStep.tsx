import { useState, useMemo } from "react";
import { ErrorState } from "@/components/ui/States";
import { Icon } from "@/components/ui/Icon";
import {
  FORGE_EDITION_LABELS,
  isModernForgeVersion,
} from "@/server_manager/utils/forgeEdition";
import type { ForgeEdition } from "@/server_manager/utils/forgeEdition";
import {
  categorizeServerVersions,
  parseGameVersion,
} from "@/server_manager/utils/compatibility";

type VersionFilterTab = "main" | "snapshots" | "all";

interface VersionStepProps {
  serverType: string;
  versions: string[];
  loading: boolean;
  error: boolean;
  selected: string;
  onSelect: (v: string) => void;
  onBack: () => void;
}

export function VersionStep({
  serverType,
  versions,
  loading,
  error,
  selected,
  onSelect,
  onBack,
}: VersionStepProps) {
  const isForge = serverType === "forge";
  const [edition, setEdition] = useState<ForgeEdition>(() => {
    if (isForge && selected && !isModernForgeVersion(selected)) return "legacy";
    return "modern";
  });
  const [versionFilter, setVersionFilter] = useState<VersionFilterTab>(() => {
    if (selected) {
      const parsed = parseGameVersion(selected);
      if (!parsed || parsed.major >= 26) return "snapshots";
    }
    return "main";
  });
  const [search, setSearch] = useState("");

  const visibleVersions = useMemo(() => {
    if (!isForge) return versions;
    return versions.filter((v) =>
      edition === "modern" ? isModernForgeVersion(v) : !isModernForgeVersion(v),
    );
  }, [isForge, versions, edition]);

  const { mainVersions, snapshotAndDropVersions, allVersions } = useMemo(
    () => categorizeServerVersions(visibleVersions, selected),
    [visibleVersions, selected],
  );

  const hasFilterTabs =
    allVersions.length > mainVersions.length || snapshotAndDropVersions.length > 0;

  const effectiveFilter: VersionFilterTab =
    versionFilter === "snapshots" && snapshotAndDropVersions.length > 0
      ? "snapshots"
      : versionFilter === "all" && allVersions.length > mainVersions.length
        ? "all"
        : mainVersions.length > 0
          ? "main"
          : "all";

  const baseVersions = useMemo(() => {
    if (effectiveFilter === "snapshots") return snapshotAndDropVersions;
    if (effectiveFilter === "all") return allVersions;
    return mainVersions.length > 0 ? mainVersions : allVersions;
  }, [effectiveFilter, mainVersions, snapshotAndDropVersions, allVersions]);

  const showSearchInput =
    baseVersions.length > 15 || (effectiveFilter === "all" && baseVersions.length > 12);

  const displayedVersions = useMemo(() => {
    const trimmed = search.trim().toLowerCase();
    if (!showSearchInput || !trimmed) return baseVersions;
    return baseVersions.filter((v) => v.toLowerCase().includes(trimmed));
  }, [baseVersions, search, showSearchInput]);

  if (loading) {
    return (
      <div>
        <h3 className="text-lg font-semibold text-text-primary mb-4">Choose Minecraft Version</h3>
        <p className="text-text-muted">Loading versions...</p>
        <button
          type="button"
          onClick={onBack}
          className="mt-4 text-sm text-accent-primary hover:underline cursor-pointer"
        >
          Back
        </button>
      </div>
    );
  }

  return (
    <div>
      <h3 className="text-lg font-semibold text-text-primary mb-4">Choose Minecraft Version</h3>
      {isForge && (
        <div className="mb-4">
          <div className="inline-flex rounded-lg border border-border-subtle bg-surface-page p-1">
            {(["modern", "legacy"] as const).map((ed) => {
              const meta = FORGE_EDITION_LABELS[ed];
              const isEdActive = edition === ed;
              return (
                <button
                  type="button"
                  key={ed}
                  onClick={() => setEdition(ed)}
                  aria-pressed={isEdActive}
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-colors cursor-pointer ${
                    isEdActive
                      ? "bg-accent-primary text-accent-contrast-text shadow-xs"
                      : "text-text-secondary hover:bg-surface-hover"
                  }`}
                >
                  {meta.label}
                </button>
              );
            })}
          </div>
          <p className="mt-2 text-xs text-text-muted">{FORGE_EDITION_LABELS[edition].description}</p>
        </div>
      )}

      {!error && hasFilterTabs && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div
            className="inline-flex flex-wrap rounded-lg border border-border-subtle bg-surface-page p-1 gap-1"
            role="tablist"
            aria-label="Minecraft version groups"
          >
            {mainVersions.length > 0 && (
              <button
                type="button"
                role="tab"
                aria-selected={effectiveFilter === "main"}
                onClick={() => setVersionFilter("main")}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                  effectiveFilter === "main"
                    ? "bg-accent-primary text-accent-contrast-text shadow-2xs"
                    : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                }`}
              >
                Main Versions
              </button>
            )}
            {snapshotAndDropVersions.length > 0 && (
              <button
                type="button"
                role="tab"
                aria-selected={effectiveFilter === "snapshots"}
                onClick={() => setVersionFilter("snapshots")}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                  effectiveFilter === "snapshots"
                    ? "bg-accent-primary text-accent-contrast-text shadow-2xs"
                    : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                }`}
              >
                Snapshots &amp; 26.x ({snapshotAndDropVersions.length})
              </button>
            )}
            {allVersions.length > mainVersions.length && (
              <button
                type="button"
                role="tab"
                aria-selected={effectiveFilter === "all"}
                onClick={() => setVersionFilter("all")}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                  effectiveFilter === "all"
                    ? "bg-accent-primary text-accent-contrast-text shadow-2xs"
                    : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                }`}
              >
                All Versions ({allVersions.length})
              </button>
            )}
          </div>

          {showSearchInput && (
            <div className="relative min-w-[180px]">
              <span className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-2.5 text-text-muted">
                <Icon name="search" size={14} />
              </span>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter version..."
                aria-label="Filter versions"
                className="w-full rounded-lg border border-border-subtle hover:border-border-hover bg-surface-page py-1.5 ps-8 pe-3 text-xs text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
              />
            </div>
          )}
        </div>
      )}

      {error ? (
        <ErrorState message="Failed to load versions — try again. If the problem persists, check your connection and refresh the page." />
      ) : displayedVersions.length === 0 ? (
        <p className="text-text-muted">
          {search.trim()
            ? `No versions match "${search.trim()}".`
            : isForge
              ? `No ${edition} Forge versions available.`
              : "No versions available."}
        </p>
      ) : (
        <div className="max-h-64 overflow-y-auto grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
          {displayedVersions.map((v) => {
            const isSelected = selected === v;
            return (
              <button
                type="button"
                key={v}
                onClick={() => onSelect(v)}
                className={`px-3 py-2 rounded-lg text-sm font-medium border transition-all cursor-pointer ${
                  isSelected
                    ? "border-accent-primary bg-accent-primary/15 text-accent-primary shadow-xs"
                    : "border-border-subtle text-text-primary hover:border-border-hover hover:bg-surface-hover bg-surface-card"
                }`}
              >
                {v}
              </button>
            );
          })}
        </div>
      )}
      <button
        type="button"
        onClick={onBack}
        className="mt-4 text-sm text-accent-primary hover:underline cursor-pointer"
      >
        Back
      </button>
    </div>
  );
}
