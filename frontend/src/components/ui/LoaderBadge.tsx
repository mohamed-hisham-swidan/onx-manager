import { Icon, type IconName } from "@/components/ui/Icon";

export interface LoaderBadgeProps {
  loader?: string | null;
  className?: string;
  showIcon?: boolean;
}

interface LoaderStyle {
  label: string;
  icon: IconName;
  color: string;
}

const LOADER_STYLES: Record<string, LoaderStyle> = {
  paper: {
    label: "Paper",
    icon: "paper",
    color: "bg-teal-50 text-teal-700 border-teal-200 dark:bg-teal-950/50 dark:text-teal-300 dark:border-teal-800/60",
  },
  purpur: {
    label: "Purpur",
    icon: "purpur",
    color: "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/50 dark:text-purple-300 dark:border-purple-800/60",
  },
  fabric: {
    label: "Fabric",
    icon: "fabric",
    color: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/50 dark:text-sky-300 dark:border-sky-800/60",
  },
  neoforge: {
    label: "NeoForge",
    icon: "neoforge",
    color: "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950/50 dark:text-orange-300 dark:border-orange-800/60",
  },
  forge: {
    label: "Forge",
    icon: "forge",
    color: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800/60",
  },
  vanilla: {
    label: "Vanilla",
    icon: "vanilla",
    color: "bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700",
  },
  spigot: {
    label: "Spigot",
    icon: "spigot",
    color: "bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-950/50 dark:text-yellow-300 dark:border-yellow-800/60",
  },
  bukkit: {
    label: "Bukkit",
    icon: "bukkit",
    color: "bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-950/50 dark:text-yellow-300 dark:border-yellow-800/60",
  },
  quilt: {
    label: "Quilt",
    icon: "quilt",
    color: "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/50 dark:text-purple-300 dark:border-purple-800/60",
  },
};

export function LoaderBadge({ loader, className = "", showIcon = true }: LoaderBadgeProps) {
  const norm = loader ? loader.trim().toLowerCase() : "";

  let matched: LoaderStyle | undefined;
  if (norm && LOADER_STYLES[norm]) {
    matched = LOADER_STYLES[norm];
  } else if (norm) {
    for (const [key, style] of Object.entries(LOADER_STYLES)) {
      if (norm.includes(key)) {
        matched = style;
        break;
      }
    }
  }

  const style: LoaderStyle = matched ?? {
    label: loader ? loader.charAt(0).toUpperCase() + loader.slice(1) : "Universal",
    icon: "server",
    color: "bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700",
  };

  return (
    <span
      data-testid="loader-badge"
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium ${style.color} ${className}`}
      title={`Server Software: ${style.label}`}
    >
      {showIcon && <Icon name={style.icon} size={12} />}
      <span>{style.label}</span>
    </span>
  );
}
