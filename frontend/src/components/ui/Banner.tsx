import React from "react";
import { Icon, type IconName } from "@/components/ui/Icon";

export interface BannerProps {
  variant?: "info" | "warning" | "danger" | "success" | "neutral";
  title?: React.ReactNode;
  description?: React.ReactNode;
  icon?: IconName;
  action?: React.ReactNode;
  onDismiss?: () => void;
  className?: string;
  children?: React.ReactNode;
}

const variantConfig: Record<
  NonNullable<BannerProps["variant"]>,
  { container: string; iconColor: string; defaultIcon: IconName }
> = {
  info: {
    container: "bg-status-info-bg border-status-info-border text-text-primary",
    iconColor: "text-status-info",
    defaultIcon: "alert",
  },
  warning: {
    container: "bg-status-warning-bg border-status-warning-border text-text-primary",
    iconColor: "text-status-warning",
    defaultIcon: "alert",
  },
  danger: {
    container: "bg-status-danger-bg border-status-danger-border text-text-primary",
    iconColor: "text-status-danger",
    defaultIcon: "alert",
  },
  success: {
    container: "bg-status-success-bg border-status-success-border text-text-primary",
    iconColor: "text-status-success",
    defaultIcon: "check",
  },
  neutral: {
    container: "bg-surface-card border-border-subtle text-text-primary",
    iconColor: "text-text-muted",
    defaultIcon: "server",
  },
};

export const Banner: React.FC<BannerProps> = ({
  variant = "info",
  title,
  description,
  icon,
  action,
  onDismiss,
  className = "",
  children,
}) => {
  const config = variantConfig[variant];
  const iconName = icon || config.defaultIcon;

  return (
    <div
      role={variant === "danger" ? "alert" : "status"}
      className={`relative flex items-start gap-3 rounded-xl border p-4 text-sm transition-all shadow-2xs ${config.container} ${className}`}
    >
      <div className={`mt-0.5 shrink-0 ${config.iconColor}`}>
        <Icon name={iconName} size={18} />
      </div>

      <div className="flex-1 min-w-0">
        {title && <div className="font-semibold text-text-primary">{title}</div>}
        {description && <div className="mt-0.5 text-text-secondary">{description}</div>}
        {children}
      </div>

      {action && <div className="shrink-0">{action}</div>}

      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss banner"
          className="shrink-0 rounded-lg p-1 text-text-muted hover:bg-black/10 dark:hover:bg-white/10 hover:text-text-primary transition-colors focus:outline-hidden"
        >
          <Icon name="x" size={16} />
        </button>
      )}
    </div>
  );
};
