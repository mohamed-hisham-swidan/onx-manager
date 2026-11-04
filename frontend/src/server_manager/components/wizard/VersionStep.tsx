import { useState, useMemo } from "react";
import { ErrorState } from "@/components/ui/States";
import {
  FORGE_EDITION_LABELS,
  isModernForgeVersion,
} from "@/server_manager/utils/forgeEdition";
import type { ForgeEdition } from "@/server_manager/utils/forgeEdition";

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

  const visibleVersions = useMemo(() => {
    if (!isForge) return versions;
    return versions.filter((v) =>
      edition === "modern" ? isModernForgeVersion(v) : !isModernForgeVersion(v),
    );
  }, [isForge, versions, edition]);

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
          <div className="inline-flex rounded-lg border border-border-default bg-surface-canvas p-1">
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
                      ? "bg-accent-primary text-white shadow-xs"
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
      {error ? (
        <ErrorState message="Failed to load versions — try again. If the problem persists, check your connection and refresh the page." />
      ) : visibleVersions.length === 0 ? (
        <p className="text-text-muted">
          {isForge ? `No ${edition} Forge versions available.` : "No versions available."}
        </p>
      ) : (
        <div className="max-h-64 overflow-y-auto grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
          {visibleVersions.map((v) => {
            const isSelected = selected === v;
            return (
              <button
                type="button"
                key={v}
                onClick={() => onSelect(v)}
                className={`px-3 py-2 rounded-lg text-sm font-medium border transition-all cursor-pointer ${
                  isSelected
                    ? "border-accent-primary bg-accent-muted/15 text-accent-primary shadow-xs"
                    : "border-border-default text-text-primary hover:border-accent-muted bg-surface-panel"
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
