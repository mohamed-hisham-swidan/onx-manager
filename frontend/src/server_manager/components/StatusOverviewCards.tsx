import type { IconName } from "@/components/ui/Icon";
import { Icon } from "@/components/ui/Icon";
import { STATUS_MAP } from "@/server_manager/types";
import { Link } from "react-router-dom";

interface StatusOverviewCardsProps {
  counts: Record<string, number>;
}

const STATUS_ORDER = ["running", "stopped", "starting", "stopping", "crashed", "created"];

const STATUS_ICONS: Record<string, IconName> = {
  running: "activity",
  stopped: "stop",
  starting: "restart",
  stopping: "restart",
  crashed: "alert",
  created: "server",
};

const STATUS_ICON_COLORS: Record<string, string> = {
  running: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
  stopped: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400",
  starting: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
  stopping: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
  crashed: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  created: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
};

export function StatusOverviewCards({ counts }: StatusOverviewCardsProps) {
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {STATUS_ORDER.map((status) => {
        const config = STATUS_MAP[status];
        if (!config) return null;
        const count = counts[status] ?? 0;
        return (
          <Link
            key={status}
            to="/servers"
            className="group flex flex-col gap-3 rounded-xl border border-gray-200 bg-white p-4 transition-colors hover:border-gray-300 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:hover:border-gray-600 dark:hover:bg-gray-700/40"
          >
            <div
              className={`flex h-9 w-9 items-center justify-center rounded-lg ${
                STATUS_ICON_COLORS[status] ?? "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400"
              }`}
            >
              <Icon name={STATUS_ICONS[status] ?? "server"} size={18} />
            </div>
            <div>
              <p className="text-2xl font-bold leading-none text-gray-900 dark:text-gray-100">{count}</p>
              <p className="mt-1 text-xs font-medium text-gray-500 dark:text-gray-400">{config.label}</p>
            </div>
          </Link>
        );
      })}

      <Link
        to="/servers"
        className="flex flex-col gap-3 rounded-xl border border-dashed border-gray-300 bg-transparent p-4 transition-colors hover:border-blue-400 hover:bg-blue-50/50 dark:border-gray-600 dark:hover:border-blue-500 dark:hover:bg-blue-900/10"
      >
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">
          <Icon name="server" size={18} />
        </div>
        <div>
          <p className="text-2xl font-bold leading-none text-gray-900 dark:text-gray-100">{total}</p>
          <p className="mt-1 text-xs font-medium text-gray-500 dark:text-gray-400">Total</p>
        </div>
      </Link>
    </div>
  );
}
