import { Icon } from "@/components/ui/Icon";
import { Link } from "react-router-dom";
import {
  getLoaderDisplay,
  groupGameVersions,
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
  const envs = environmentLabels(clientSide, serverSide);
  const platformPillClasses =
    "inline-flex items-center rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 transition-colors dark:bg-blue-900/30 dark:text-blue-300";

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
        className={`${platformPillClasses} gap-1 hover:bg-blue-100 hover:text-blue-800 dark:hover:bg-blue-800/40 dark:hover:text-blue-200`}
      >
        <Icon name={icon} size={11} className="shrink-0" />
        {label}
      </Link>
    );
  }

  return (
    <div
      className="rounded-xl border border-gray-200 bg-white p-5 sm:p-6 dark:border-gray-700 dark:bg-gray-800 space-y-5"
      data-testid="compatibility-card"
    >
      <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
        Compatibility
      </h3>

      {/* Minecraft: Java Edition */}
      {gameVersions.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
            Minecraft: Java Edition
          </h4>
          <div className="flex flex-wrap gap-1.5" data-testid="game-versions-pills">
            {groupGameVersions(gameVersions).map((gv) => (
              <span
                key={gv}
                className="rounded-md bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700 dark:bg-gray-700/60 dark:text-gray-300"
              >
                {gv}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Platforms */}
      {loaders.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
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
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
            Supported environments
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {envs.map((env) => (
              <span
                key={env}
                className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
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
