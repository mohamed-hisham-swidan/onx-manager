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
      <div className="relative mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-amber-200 bg-amber-50 text-amber-600 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-400">
        <Icon name={icon} size={28} />
      </div>
      <div className="mb-2 inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
        {badge}
      </div>
      <h3 className="mb-1 text-lg font-medium text-gray-900 dark:text-gray-100">{title}</h3>
      {description && (
        <p className="mb-4 max-w-sm text-sm text-gray-500 dark:text-gray-400">{description}</p>
      )}
      {action}
    </div>
  );
}
