import { Icon, type IconName } from "@/components/ui/Icon";

export interface CompatibilityCardProps {
  gameVersions: string[];
  loaders: string[];
  clientSide?: string | null;
  serverSide?: string | null;
}

const LOADER_DISPLAY: Record<string, { label: string; icon: IconName }> = {
  paper: { label: "Paper", icon: "download" },
  purpur: { label: "Purpur", icon: "download" },
  spigot: { label: "Spigot", icon: "download" },
  bukkit: { label: "Bukkit", icon: "download" },
  folia: { label: "Folia", icon: "download" },
  fabric: { label: "Fabric", icon: "download" },
  forge: { label: "Forge", icon: "download" },
  neoforge: { label: "NeoForge", icon: "download" },
  quilt: { label: "Quilt", icon: "download" },
};

export function getLoaderDisplay(loader: string): { label: string; icon: IconName } {
  return LOADER_DISPLAY[loader.toLowerCase()] ?? { label: loader, icon: "download" as const };
}

export function environmentLabels(clientSide?: string | null, serverSide?: string | null): string[] {
  const labels: string[] = [];
  if (clientSide === "required" || clientSide === "optional") labels.push("Client-side");
  if (serverSide === "required" || serverSide === "optional") labels.push("Server-side");
  if (labels.length === 2) return ["Client and server"];
  return labels.length ? labels : [];
}

export function CompatibilityCard({
  gameVersions,
  loaders,
  clientSide,
  serverSide,
}: CompatibilityCardProps) {
  const envs = environmentLabels(clientSide, serverSide);

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
            {gameVersions.map((gv) => (
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
            {loaders.map((loader) => {
              const display = getLoaderDisplay(loader);
              return (
                <span
                  key={loader}
                  className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
                >
                  <Icon name={display.icon} size={12} className="shrink-0" />
                  {display.label}
                </span>
              );
            })}
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
