import React from "react";
import { Icon, type IconName } from "@/components/ui/Icon";

export interface ChipProps {
  label: React.ReactNode;
  icon?: IconName;
  variant?: "default" | "primary" | "success" | "warning" | "danger" | "outline";
  size?: "xs" | "sm" | "md";
  onRemove?: () => void;
  onClick?: () => void;
  selected?: boolean;
  className?: string;
}

const variantStyles: Record<NonNullable<ChipProps["variant"]>, string> = {
  default: "bg-surface-muted text-text-secondary border-border-subtle",
  primary: "bg-accent-primary/10 text-accent-primary border-accent-primary/20",
  success: "bg-status-success-bg text-status-success border-status-success-border",
  warning: "bg-status-warning-bg text-status-warning border-status-warning-border",
  danger: "bg-status-danger-bg text-status-danger border-status-danger-border",
  outline: "bg-transparent text-text-secondary border-border-default hover:border-text-secondary",
};

const sizeStyles: Record<NonNullable<ChipProps["size"]>, { text: string; icon: number; remove: number }> = {
  xs: { text: "px-2 py-0.5 text-[11px] gap-1", icon: 12, remove: 12 },
  sm: { text: "px-2.5 py-1 text-xs gap-1.5", icon: 14, remove: 12 },
  md: { text: "px-3 py-1.5 text-sm gap-2", icon: 16, remove: 14 },
};

export const Chip: React.FC<ChipProps> = ({
  label,
  icon,
  variant = "default",
  size = "sm",
  onRemove,
  onClick,
  selected = false,
  className = "",
}) => {
  const { text, icon: iconSize, remove: removeSize } = sizeStyles[size];
  const isInteractive = !!onClick;

  const selectedClasses = selected
    ? "ring-2 ring-border-focus border-transparent font-medium"
    : "";

  return (
    <span
      onClick={onClick}
      role={isInteractive ? "button" : undefined}
      tabIndex={isInteractive ? 0 : undefined}
      className={`inline-flex items-center font-medium rounded-full border transition-all ${
        isInteractive ? "cursor-pointer hover:opacity-85 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus" : ""
      } ${variantStyles[variant]} ${text} ${selectedClasses} ${className}`}
    >
      {icon && <Icon name={icon} size={iconSize} />}
      <span>{label}</span>
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          aria-label="Remove"
          className="ml-0.5 rounded-full p-0.5 hover:bg-black/10 dark:hover:bg-white/15 focus:outline-hidden"
        >
          <Icon name="x" size={removeSize} />
        </button>
      )}
    </span>
  );
};
