import { useMemo, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { Link } from "react-router-dom";
import {
  getLoaderDisplay,
  groupReleaseVersions,
  environmentLabels,
} from "@/server_manager/utils/compatibility";

export interface CompatibilityCardProps {
  gameVersions: string[];
  loaders: string[];
  clientSide?: string | null;
  serverSide?: string | null;
  /** When provided, platform pills render as links to this href */
  buildPlatformHref?: (loader: string) => string;
}

export function CompatibilityCard({
  gameVersions,
  loaders,
  clientSide,
  serverSide,
  buildPlatformHref,
}: CompatibilityCardProps) {
  const [showSnapshots, setShowSnapshots] = useState(false);
  const { releasePills, snapshots } = useMemo(
    () => groupReleaseVersions(gameVersions),
    [gameVersions],
  );
  const envs = environmentLabels(clientSide, serverSide);
  const platformPillClasses =
    "inline-flex items-center rounded-md bg-accent-primary/10 px-2 py-0.5 text-xs font-medium text-accent-primary transition-colors";

  function renderPlatformPill(loader: string) {
    const { label, icon } = getLoaderDisplay(loader);
    const href = buildPlatformHref?.(loader);
    if (!href) {
      return (
        <span key={loader} className={`${platformPillClasses} gap-1`}>
          <Icon name={icon} size={11} className="shrink-0" />
          {label}
        </span>
      );
    }
    return (
      <Link
        key={loader}
        to={href}
        className={`${platformPillClasses} gap-1 hover:bg-accent-primary/20 hover:text-accent-primary`}
      >
        <Icon name={icon} size={11} className="shrink-0" />
        {label}
      </Link>
    );
  }

  return (
    <div
      className="rounded-xl border border-border-subtle bg-surface-card p-5 sm:p-6 shadow-xs space-y-5"
      data-testid="compatibility-card"
    >
      <h3 className="text-base font-semibold text-text-primary">
        Compatibility
      </h3>

      {/* Minecraft: Java Edition */}
      {gameVersions.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
            Minecraft: Java Edition
          </h4>
          <div className="flex flex-wrap gap-1.5" data-testid="game-versions-pills">
            {(releasePills.length > 0 ? releasePills : snapshots).map((gv) => (
              <span
                key={gv}
                className="rounded-md bg-surface-muted px-2 py-0.5 text-xs font-medium text-text-secondary"
              >
                {gv}
              </span>
            ))}
            {releasePills.length > 0 &&
              showSnapshots &&
              snapshots.map((snap) => (
                <span
                  key={snap}
                  className="rounded-md border border-border-subtle bg-surface-muted/70 px-2 py-0.5 text-xs font-medium text-text-muted"
                >
                  {snap}
                </span>
              ))}
            {releasePills.length > 0 && snapshots.length > 0 && (
              <button
                type="button"
                data-testid="toggle-snapshots-btn"
                onClick={() => setShowSnapshots((s) => !s)}
                className="rounded-md border border-border-subtle px-2 py-0.5 text-xs font-medium text-text-muted hover:border-border-hover hover:text-text-primary transition-colors cursor-pointer"
              >
                {showSnapshots ? "Hide snapshots" : `+${snapshots.length} snapshots`}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Platforms */}
      {loaders.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
            Platforms
          </h4>
          <div className="flex flex-wrap gap-1.5" data-testid="platforms-pills">
            {loaders.map(renderPlatformPill)}
          </div>
        </div>
      )}

      {/* Supported environments */}
      {envs.length > 0 && (
        <div className="space-y-2" data-testid="supported-environments-section">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
            Supported environments
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {envs.map((env) => (
              <span
                key={env}
                className="rounded-md bg-status-success-bg px-2 py-0.5 text-xs font-medium text-status-success"
              >
                {env}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
