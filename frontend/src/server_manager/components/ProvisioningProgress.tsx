import { useProvisionProgress } from "@/server_manager/hooks/useProvisionProgress";

interface ProvisioningProgressProps {
  serverId: string;
  className?: string;
}

export function ProvisioningProgress({ serverId, className = "" }: ProvisioningProgressProps) {
  const progress = useProvisionProgress(serverId);

  if (!progress) {
    return (
      <span className={`inline-flex h-7 w-7 items-center justify-center text-accent-primary ${className}`} title="Installing">
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-border-default border-t-accent-primary" />
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
              ? "border-status-danger-border border-t-status-danger"
              : progress.stage === "success"
              ? "border-status-success-border border-t-status-success"
              : "border-border-default border-t-accent-primary"
          }`}
        />
        <span className="text-xs font-medium text-text-secondary">
          {stageLabel}
        </span>
      </div>
      <div className="h-1.5 w-full bg-surface-muted rounded-full overflow-hidden">
        <div
          className={`h-full transition-all duration-300 ease-out ${
            progress.stage === "failed" || progress.stage === "timeout"
              ? "bg-status-danger"
              : progress.stage === "success"
              ? "bg-status-success"
              : "bg-accent-primary"
          }`}
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
      <p className="text-[10px] text-text-muted truncate">
        {progress.message}
      </p>
    </div>
  );
}