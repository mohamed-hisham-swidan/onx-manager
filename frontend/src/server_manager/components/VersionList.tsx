import { Icon } from "@/components/ui/Icon";
import { formatBytes } from "@/server_manager/utils/format";
import { groupReleaseVersions } from "@/server_manager/utils/compatibility";
import type { PluginVersionResponse } from "@/types";

export interface VersionListProps {
  versions: PluginVersionResponse[];
  selectedVersion?: PluginVersionResponse | null;
  notice?: string;
  noticeKind?: string;
  onSelectVersion: (version: PluginVersionResponse) => void;
}

export function VersionList({
  versions,
  selectedVersion,
  notice,
  noticeKind = "warning",
  onSelectVersion,
}: VersionListProps) {
  if (!versions || versions.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3" data-testid="version-list">
      {notice && (
        <div
          className={`flex items-start gap-2 rounded-xl border p-3 text-xs ${
            noticeKind === "warning"
              ? "border-status-warning-border bg-status-warning-bg text-status-warning"
              : "border-status-info-border bg-status-info-bg text-status-info"
          }`}
        >
          <Icon name="alert" size={16} className="mt-0.5 shrink-0" />
          <p className="leading-snug">{notice}</p>
        </div>
      )}

      <div className="space-y-2">
        {versions.map((v) => {
          const isRecommended = selectedVersion?.version_id === v.version_id;
          const primary = v.files.find((f) => f.primary) ?? v.files[0];
          const { releasePills, snapshots } = groupReleaseVersions(v.game_versions);
          const summaryVersions = releasePills.length > 0 ? releasePills : snapshots;

          return (
            <div
              key={v.version_id}
              className={`flex items-center justify-between gap-4 rounded-xl border p-4 transition-colors ${
                isRecommended
                  ? "border-accent-primary bg-accent-primary/10"
                  : "border-border-subtle bg-surface-card hover:bg-surface-hover"
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-text-primary">
                    {v.version_number}
                  </span>
                  {v.name && v.name !== v.version_number && (
                    <span className="truncate text-xs text-text-muted">
                      ({v.name})
                    </span>
                  )}
                  {isRecommended && (
                    <span className="inline-flex rounded-full bg-accent-primary/10 px-2 py-0.5 text-xs font-medium text-accent-primary">
                      Recommended
                    </span>
                  )}
                </div>

                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-muted">
                  {summaryVersions.length > 0 && (
                    <span>
                      MC {summaryVersions.slice(0, 3).join(", ")}
                      {summaryVersions.length > 3 ? ` +${summaryVersions.length - 3}` : ""}
                    </span>
                  )}
                  {v.loaders.length > 0 && (
                    <span>{v.loaders.join(", ")}</span>
                  )}
                  {primary && <span>{formatBytes(primary.size_bytes)}</span>}
                </div>
              </div>

              <button
                type="button"
                aria-label={`Install version ${v.version_number}`}
                onClick={() => onSelectVersion(v)}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover focus:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus"
              >
                <Icon name="plus" size={14} />
                Install
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
