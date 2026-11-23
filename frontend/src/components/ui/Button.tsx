import React from "react";
import { Icon, type IconName } from "@/components/ui/Icon";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "outline" | "ghost" | "danger";
  size?: "xs" | "sm" | "md" | "lg";
  icon?: IconName;
  iconPosition?: "left" | "right";
  loading?: boolean;
}

const variantStyles: Record<NonNullable<ButtonProps["variant"]>, string> = {
  primary:
    "bg-accent-primary text-accent-contrast-text hover:bg-accent-hover active:bg-accent-active border-transparent shadow-xs",
  secondary:
    "bg-surface-card text-text-primary hover:bg-surface-hover border-border-subtle hover:border-border-hover active:bg-surface-active shadow-2xs",
  outline:
    "bg-transparent text-text-primary hover:bg-surface-hover border-border-subtle hover:border-border-hover active:bg-surface-active",
  ghost:
    "bg-transparent text-text-secondary hover:bg-surface-hover hover:text-text-primary border-transparent",
  danger:
    "bg-status-danger text-white hover:opacity-90 active:opacity-100 border-transparent shadow-xs",
};

const sizeStyles: Record<NonNullable<ButtonProps["size"]>, string> = {
  xs: "px-2 py-1 text-xs gap-1 rounded-md",
  sm: "px-2.5 py-1.5 text-xs font-medium gap-1.5 rounded-lg",
  md: "px-3.5 py-2 text-sm font-medium gap-2 rounded-lg",
  lg: "px-4.5 py-2.5 text-base font-medium gap-2.5 rounded-xl",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = "primary",
      size = "md",
      icon,
      iconPosition = "left",
      loading = false,
      disabled,
      className = "",
      children,
      ...props
    },
    ref
  ) => {
    const isDisabled = disabled || loading;

    return (
      <button
        ref={ref}
        disabled={isDisabled}
        className={`inline-flex items-center justify-center font-medium border transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus disabled:pointer-events-none disabled:opacity-50 cursor-pointer ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
        {...props}
      >
        {loading ? (
          <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
        ) : icon && iconPosition === "left" ? (
          <Icon name={icon} size={size === "xs" || size === "sm" ? 14 : 16} />
        ) : null}

        {children}

        {!loading && icon && iconPosition === "right" ? (
          <Icon name={icon} size={size === "xs" || size === "sm" ? 14 : 16} />
        ) : null}
      </button>
    );
  }
);

Button.displayName = "Button";

export interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
  "aria-label": string;
  variant?: "primary" | "secondary" | "outline" | "ghost" | "danger";
  size?: "xs" | "sm" | "md" | "lg";
}

const iconSizeStyles: Record<NonNullable<IconButtonProps["size"]>, { button: string; icon: number }> = {
  xs: { button: "p-1 rounded-md", icon: 14 },
  sm: { button: "p-1.5 rounded-lg", icon: 16 },
  md: { button: "p-2 rounded-lg", icon: 18 },
  lg: { button: "p-2.5 rounded-xl", icon: 20 },
};

export const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ icon, variant = "ghost", size = "md", className = "", ...props }, ref) => {
    const { button, icon: iconPx } = iconSizeStyles[size];

    return (
      <button
        ref={ref}
        className={`inline-flex items-center justify-center border transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus disabled:pointer-events-none disabled:opacity-50 cursor-pointer ${variantStyles[variant]} ${button} ${className}`}
        {...props}
      >
        <Icon name={icon} size={iconPx} />
      </button>
    );
  }
);

IconButton.displayName = "IconButton";
