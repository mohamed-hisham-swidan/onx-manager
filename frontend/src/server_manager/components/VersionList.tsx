import { Icon } from "@/components/ui/Icon";
import { formatBytes } from "@/server_manager/utils/format";
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
              ? "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-700/50 dark:bg-amber-900/20 dark:text-amber-300"
              : "border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-700/50 dark:bg-blue-900/20 dark:text-blue-300"
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

          return (
            <div
              key={v.version_id}
              role="button"
              tabIndex={0}
              aria-label={`Select version ${v.version_number}`}
              onClick={() => onSelectVersion(v)}
              onKeyDown={(e) => {
                if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  onSelectVersion(v);
                }
              }}
              className={`flex cursor-pointer items-center justify-between gap-4 rounded-xl border p-4 transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus ${
                isRecommended
                  ? "border-blue-500 bg-blue-50/50 dark:border-blue-500 dark:bg-blue-900/20"
                  : "border-gray-200 bg-white hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:hover:bg-gray-700/50"
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-gray-900 dark:text-gray-100">
                    {v.version_number}
                  </span>
                  {v.name && v.name !== v.version_number && (
                    <span className="truncate text-xs text-gray-500 dark:text-gray-400">
                      ({v.name})
                    </span>
                  )}
                  {isRecommended && (
                    <span className="inline-flex rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
                      Recommended
                    </span>
                  )}
                </div>

                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
                  {v.game_versions.length > 0 && (
                    <span>MC {v.game_versions.slice(0, 3).join(", ")}{v.game_versions.length > 3 ? ` +${v.game_versions.length - 3}` : ""}</span>
                  )}
                  {v.loaders.length > 0 && (
                    <span>{v.loaders.join(", ")}</span>
                  )}
                  {primary && <span>{formatBytes(primary.size_bytes)}</span>}
                </div>
              </div>

              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectVersion(v);
                }}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700"
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
