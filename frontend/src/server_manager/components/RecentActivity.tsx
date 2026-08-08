import { Icon, type IconName } from "@/components/ui/Icon";
import { useActivityStore } from "@/stores/activityStore";
import { useEffectiveConnectionState, useIsChannelDegraded } from "@/stores/wsStore";
import type { ActivityEvent } from "@/stores/activityStore";

interface RecentActivityProps {
  serverNames?: Record<string, string>;
}

function eventPresentation(event_type: string): { icon: IconName; color: string; verb: string } {
  if (event_type.includes("Crashed")) {
    return { icon: "alert", color: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400", verb: "crashed" };
  }
  if (event_type.includes("Deleted")) {
    return { icon: "trash", color: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400", verb: "deleted" };
  }
  if (event_type.includes("Created")) {
    return { icon: "plus", color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400", verb: "created" };
  }
  if (event_type.includes("Started")) {
    return { icon: "play", color: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400", verb: "started" };
  }
  if (event_type.includes("Starting")) {
    return { icon: "restart", color: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400", verb: "is starting" };
  }
  if (event_type.includes("Stopping")) {
    return { icon: "stop", color: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400", verb: "is stopping" };
  }
  if (event_type.includes("Stopped")) {
    return { icon: "stop", color: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400", verb: "stopped" };
  }
  if (event_type.includes("Restarted")) {
    return { icon: "restart", color: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400", verb: "restarted" };
  }
  if (event_type.includes("Config")) {
    return { icon: "settings", color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400", verb: "updated config for" };
  }
  if (event_type.includes("Discovered")) {
    return { icon: "search", color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400", verb: "discovered" };
  }
  if (event_type.includes("Vanished")) {
    return { icon: "x", color: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400", verb: "lost sight of" };
  }
  return { icon: "activity", color: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400", verb: "event" };
}

function formatTime(timestamp: number): string {
  const diff = Date.now() - timestamp * 1000;
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function EventRow({ event, serverNames }: { event: ActivityEvent; serverNames?: Record<string, string> }) {
  const pres = eventPresentation(event.event_type);
  const serverName = event.name ?? (event.server_id ? serverNames?.[event.server_id] : undefined) ?? "server";

  return (
    <li className="flex items-center gap-3 py-2.5">
      <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${pres.color}`}>
        <Icon name={pres.icon} size={15} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-gray-800 dark:text-gray-200">
          <span className="font-medium">{serverName}</span>{" "}
          <span className="text-gray-500 dark:text-gray-400">{pres.verb}</span>
        </p>
      </div>
      <span className="shrink-0 text-xs tabular-nums text-gray-400 dark:text-gray-500">
        {formatTime(event.timestamp)}
      </span>
    </li>
  );
}

export function RecentActivity({ serverNames }: RecentActivityProps) {
  const events = useActivityStore((s) => s.events);
  const connectionState = useEffectiveConnectionState();
  const serverChannelDegraded = useIsChannelDegraded("server:*");

  const liveNote =
    connectionState === "reconnecting"
      ? { text: "Live updates paused — reconnecting…", color: "text-amber-700 dark:text-amber-400" }
      : connectionState === "connecting"
        ? { text: "Connecting to live updates…", color: "text-gray-500 dark:text-gray-400" }
        : connectionState === "disconnected"
          ? { text: "Live updates unavailable", color: "text-red-600 dark:text-red-400" }
          : serverChannelDegraded
            ? { text: "Live updates unavailable — subscription rejected", color: "text-amber-700 dark:text-amber-400" }
            : null;

  return (
    <>
      {liveNote && (
        <p role="status" className={`mb-2 px-1 text-xs font-medium ${liveNote.color}`}>
          {liveNote.text}
        </p>
      )}
      <ul className="divide-y divide-gray-100 dark:divide-gray-700/50">
        {events.slice(0, 8).map((event) => (
          <EventRow key={event.id} event={event} serverNames={serverNames} />
        ))}
      </ul>
    </>
  );
}
