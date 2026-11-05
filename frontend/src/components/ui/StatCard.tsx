import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

interface StatCardProps {
  icon: IconName;
  label: string;
  value: ReactNode;
  sublabel?: ReactNode;
  color?: string;
}

export function StatCard({ icon, label, value, sublabel, color = "bg-accent-primary/10 text-accent-primary" }: StatCardProps) {
  return (
    <div className="flex items-center gap-4 rounded-xl border border-border-default bg-surface-card p-4 shadow-xs">
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
