import { useProvisionProgress } from "@/server_manager/hooks/useProvisionProgress";

interface ProvisioningProgressProps {
  serverId: string;
  className?: string;
}

export function ProvisioningProgress({ serverId, className = "" }: ProvisioningProgressProps) {
  const progress = useProvisionProgress(serverId);

  if (!progress) {
    return (
      <span className={`inline-flex h-7 w-7 items-center justify-center text-cyan-500 dark:text-cyan-400 ${className}`} title="Installing">
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-cyan-300 border-t-cyan-600 dark:border-cyan-600 dark:border-t-cyan-300" />
      </span>
    );
  }

  const getStageLabel = (stage: string): string => {
    switch (stage) {
      case "downloading_libraries":
        return "Downloading libraries";
      case "downloading_forge":
        return "Downloading Forge";
      case "installing_profile":
        return "Installing profile";
      case "installing_minecraft":
        return "Installing Minecraft";
      case "success":
        return "Installation complete";
      case "failed":
        return "Installation failed";
      case "timeout":
        return "Installation timed out";
      default:
        return stage.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    }
  };

  const stageLabel = getStageLabel(progress.stage);
  const percent = progress.percent ?? 0;

  return (
    <div className={`flex flex-col gap-1 min-w-[120px] ${className}`}>
      <div className="flex items-center gap-2">
        <span
          className={`h-5 w-5 flex-shrink-0 animate-spin rounded-full border-2 ${
            progress.stage === "failed" || progress.stage === "timeout"
              ? "border-red-300 border-t-red-600 dark:border-red-600 dark:border-t-red-300"
              : progress.stage === "success"
              ? "border-green-300 border-t-green-600 dark:border-green-600 dark:border-t-green-300"
              : "border-cyan-300 border-t-cyan-600 dark:border-cyan-600 dark:border-t-cyan-300"
          }`}
        />
        <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
          {stageLabel}
        </span>
      </div>
      <div className="h-1.5 w-full bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full transition-all duration-300 ease-out ${
            progress.stage === "failed" || progress.stage === "timeout"
              ? "bg-red-500"
              : progress.stage === "success"
              ? "bg-green-500"
              : "bg-cyan-500"
          }`}
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
      <p className="text-[10px] text-gray-500 dark:text-gray-400 truncate">
        {progress.message}
      </p>
    </div>
  );
}