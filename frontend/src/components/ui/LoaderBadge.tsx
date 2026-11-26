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
    color: "bg-status-info-bg text-status-info border-status-info-border",
  },
  purpur: {
    label: "Purpur",
    icon: "purpur",
    color: "bg-accent-primary/10 text-text-accent border-accent-primary/25",
  },
  folia: {
    label: "Folia",
    icon: "folia",
    color: "bg-status-success-bg text-status-success border-status-success-border",
  },
  fabric: {
    label: "Fabric",
    icon: "fabric",
    color: "bg-status-info-bg text-status-info border-status-info-border",
  },
  neoforge: {
    label: "NeoForge",
    icon: "neoforge",
    color: "bg-status-warning-bg text-status-warning border-status-warning-border",
  },
  forge: {
    label: "Forge",
    icon: "forge",
    color: "bg-status-warning-bg text-status-warning border-status-warning-border",
  },
  vanilla: {
    label: "Vanilla",
    icon: "vanilla",
    color: "bg-surface-elevated text-text-secondary border-border-default",
  },
  spigot: {
    label: "Spigot",
    icon: "spigot",
    color: "bg-status-warning-bg text-status-warning border-status-warning-border",
  },
  bukkit: {
    label: "Bukkit",
    icon: "bukkit",
    color: "bg-status-warning-bg text-status-warning border-status-warning-border",
  },
  quilt: {
    label: "Quilt",
    icon: "quilt",
    color: "bg-accent-primary/10 text-text-accent border-accent-primary/25",
  },
  velocity: {
    label: "Velocity",
    icon: "velocity",
    color: "bg-accent-primary/10 text-text-accent border-accent-primary/25",
  },
  bungeecord: {
    label: "BungeeCord",
    icon: "bungeecord",
    color: "bg-status-info-bg text-status-info border-status-info-border",
  },
  waterfall: {
    label: "Waterfall",
    icon: "waterfall",
    color: "bg-status-info-bg text-status-info border-status-info-border",
  },
  minestom: {
    label: "Minestom",
    icon: "server",
    color: "bg-surface-elevated text-text-secondary border-border-default",
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
    color: "bg-surface-elevated text-text-secondary border-border-default",
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
