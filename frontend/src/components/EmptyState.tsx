import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon = "◇", title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <span className="text-4xl text-gray-300 dark:text-gray-600 mb-3">{icon}</span>
      <p className="text-lg font-medium text-gray-900 dark:text-gray-100 mb-1">{title}</p>
      {description && (
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4 max-w-sm">{description}</p>
      )}
      {action}
    </div>
  );
}
