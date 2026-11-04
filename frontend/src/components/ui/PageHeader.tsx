import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon, type IconName } from "./Icon";

export interface PageHeaderProps {
  title: string;
  description?: string;
  icon?: IconName;
  badge?: ReactNode;
  backTo?: string;
  backLabel?: string;
  breadcrumbs?: { label: string; href?: string }[];
  actions?: ReactNode;
  className?: string;
}

export function PageHeader({
  title,
  description,
  icon,
  badge,
  backTo,
  backLabel = "Back",
  breadcrumbs,
  actions,
  className = "",
}: PageHeaderProps) {
  return (
    <div className={`mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between ${className}`}>
      <div className="min-w-0">
        {breadcrumbs && breadcrumbs.length > 0 ? (
          <nav aria-label="Breadcrumbs" className="mb-2 flex items-center gap-1.5 text-xs text-text-muted">
            {breadcrumbs.map((crumb, idx) => (
              <span key={idx} className="inline-flex items-center gap-1.5">
                {idx > 0 && <Icon name="chevron-right" size={12} className="text-text-muted/60" />}
                {crumb.href ? (
                  <Link
                    to={crumb.href}
                    className="hover:text-text-primary transition-colors font-medium"
                  >
                    {crumb.label}
                  </Link>
                ) : (
                  <span className="text-text-primary font-semibold">{crumb.label}</span>
                )}
              </span>
            ))}
          </nav>
        ) : backTo ? (
          <Link
            to={backTo}
            className="mb-1.5 inline-flex items-center gap-1 text-xs font-medium text-text-muted transition-colors hover:text-text-primary"
          >
            <Icon name="chevron-left" size={14} />
            {backLabel}
          </Link>
        ) : null}

        <div className="flex items-center gap-3">
          {icon && (
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-primary/10 text-accent-primary border border-accent-primary/20 shadow-2xs">
              <Icon name={icon} size={20} />
            </div>
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2.5">
              <h1 className="truncate text-xl font-bold tracking-tight text-text-primary">
                {title}
              </h1>
              {badge}
            </div>
            {description && (
              <p className="mt-0.5 truncate text-xs text-text-muted sm:text-sm">
                {description}
              </p>
            )}
          </div>
        </div>
      </div>

      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      )}
    </div>
  );
}
