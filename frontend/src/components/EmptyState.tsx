import type { ReactNode } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";

interface EmptyStateProps {
  icon?: IconName;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon = "server", title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-border-default bg-surface-muted text-text-muted">
        <Icon name={icon} size={28} />
      </div>
      <p className="mb-1 text-lg font-medium text-text-primary">{title}</p>
      {description && (
        <p className="mb-4 max-w-sm text-sm text-text-muted">{description}</p>
      )}
      {action}
    </div>
  );
}
