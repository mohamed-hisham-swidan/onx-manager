import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export interface StatCardProps {
  icon: IconName;
  label: string;
  value: ReactNode;
  sublabel?: ReactNode;
  color?: string;
  variant?: "default" | "inset" | "flush";
  className?: string;
}

const variantStyles: Record<NonNullable<StatCardProps["variant"]>, string> = {
  default: "border border-border-subtle bg-surface-card shadow-xs",
  inset: "bg-surface-muted",
  flush: "bg-surface-muted",
};

export function StatCard({
  icon,
  label,
  value,
  sublabel,
  color = "bg-accent-primary/10 text-accent-primary",
  variant = "default",
  className = "",
}: StatCardProps) {
  return (
    <div
      className={`flex items-center gap-4 rounded-xl p-4 transition-all ${variantStyles[variant]} ${className}`}
    >
      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${color}`}>
        <Icon name={icon} size={20} />
      </div>
      <div className="min-w-0">
        <p className="text-xs font-medium text-text-muted">{label}</p>
        <p className="truncate text-lg font-bold leading-tight text-text-primary">{value}</p>
        {sublabel && <p className="truncate text-xs text-text-muted">{sublabel}</p>}
      </div>
    </div>
  );
}
