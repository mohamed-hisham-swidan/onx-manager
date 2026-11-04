import React from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import { Button } from "@/components/ui/Button";

export interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: IconName;
  action?:
    | {
        label: string;
        onClick: () => void;
        icon?: IconName;
      }
    | React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  icon = "server",
  action,
  children,
  className = "",
}) => {
  return (
    <div
      className={`flex flex-col items-center justify-center rounded-2xl border border-dashed border-border-default/80 bg-surface-card/40 p-10 text-center ${className}`}
    >
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-muted text-text-muted border border-border-subtle shadow-xs">
        <Icon name={icon} size={28} />
      </div>
      <h3 className="text-base font-semibold text-text-primary">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm text-text-muted leading-relaxed">
          {description}
        </p>
      )}
      {action && (
        <div className="mt-6">
          {React.isValidElement(action) ? (
            action
          ) : typeof action === "object" && "label" in action ? (
            <Button onClick={action.onClick} icon={action.icon} variant="primary" size="sm">
              {action.label}
            </Button>
          ) : null}
        </div>
      )}
      {children}
    </div>
  );
};

export interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  className?: string;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = "Failed to load content",
  message = "An unexpected error occurred while communicating with the server.",
  onRetry,
  className = "",
}) => {
  return (
    <div
      role="alert"
      className={`flex flex-col items-center justify-center rounded-2xl border border-status-danger-border bg-status-danger-bg/50 p-8 text-center ${className}`}
    >
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-status-danger-bg text-status-danger border border-status-danger-border">
        <Icon name="alert" size={24} />
      </div>
      <h3 className="text-base font-semibold text-text-primary">{title}</h3>
      <p className="mt-1 max-w-md text-sm text-text-muted">{message}</p>
      {onRetry && (
        <div className="mt-5">
          <Button onClick={onRetry} icon="restart" variant="secondary" size="sm">
            Try Again
          </Button>
        </div>
      )}
    </div>
  );
};

export interface SkeletonProps {
  className?: string;
  count?: number;
}

export const Skeleton: React.FC<SkeletonProps> = ({ className = "h-4 w-full", count = 1 }) => {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className={`animate-pulse rounded-md bg-surface-hover/70 ${className}`}
          aria-hidden="true"
        />
      ))}
    </>
  );
};

export interface ForbiddenStateProps {
  title?: string;
  message?: string;
  onBack?: () => void;
}

export const ForbiddenState: React.FC<ForbiddenStateProps> = ({
  title = "Access Denied",
  message = "You do not have the required permissions to access this view or perform this action.",
  onBack,
}) => {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-border-subtle bg-surface-card p-12 text-center shadow-xs">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-status-warning-bg text-status-warning border border-status-warning-border">
        <Icon name="lock" size={28} />
      </div>
      <h2 className="text-lg font-bold text-text-primary">{title}</h2>
      <p className="mt-2 max-w-sm text-sm text-text-muted leading-relaxed">{message}</p>
      {onBack && (
        <div className="mt-6">
          <Button onClick={onBack} variant="secondary" size="sm">
            Go Back
          </Button>
        </div>
      )}
    </div>
  );
};
