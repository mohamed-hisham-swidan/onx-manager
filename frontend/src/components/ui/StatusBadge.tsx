import { STATUS_MAP } from "@/server_manager/types";

interface StatusBadgeProps {
  status: string;
  dot?: boolean;
  className?: string;
}

export function StatusBadge({ status, dot = true, className = "" }: StatusBadgeProps) {
  const config = STATUS_MAP[status] ?? {
    label: status || "Unknown",
    color: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400",
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${config.color} ${className}`}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden="true" />}
      {config.label}
    </span>
  );
}
