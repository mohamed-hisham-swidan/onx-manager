import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

interface StatCardProps {
  icon: IconName;
  label: string;
  value: ReactNode;
  sublabel?: ReactNode;
  color?: string;
}

export function StatCard({ icon, label, value, sublabel, color = "bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400" }: StatCardProps) {
  return (
    <div className="flex items-center gap-4 rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${color}`}>
        <Icon name={icon} size={20} />
      </div>
      <div className="min-w-0">
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{label}</p>
        <p className="truncate text-lg font-bold leading-tight text-gray-900 dark:text-gray-100">{value}</p>
        {sublabel && <p className="truncate text-xs text-gray-400 dark:text-gray-500">{sublabel}</p>}
      </div>
    </div>
  );
}
