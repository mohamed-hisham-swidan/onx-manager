import type { ReactNode } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";

interface ComingSoonStateProps {
  icon?: IconName;
  title: string;
  description?: string;
  badge?: string;
  action?: ReactNode;
  className?: string;
}

export function ComingSoonState({
  icon = "info",
  title,
  description,
  badge = "Coming Soon",
  action,
  className = "",
}: ComingSoonStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center py-16 text-center ${className}`}>
      <div className="relative mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-status-warning-border bg-status-warning-bg text-status-warning">
        <Icon name={icon} size={28} />
      </div>
      <div className="mb-2 inline-flex items-center rounded-full bg-status-warning-bg border border-status-warning-border px-2.5 py-0.5 text-xs font-semibold text-status-warning">
        {badge}
      </div>
      <h3 className="mb-1 text-lg font-medium text-text-primary">{title}</h3>
      {description && (
        <p className="mb-4 max-w-sm text-sm text-text-muted">{description}</p>
      )}
      {action}
    </div>
  );
}
