import React, { useEffect, useRef } from "react";
import { Icon } from "@/components/ui/Icon";
import { useBodyScrollLock } from "@/hooks/useBodyScrollLock";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: "sm" | "md" | "lg" | "xl" | "2xl" | "full";
  variant?: "modal" | "drawer";
  padded?: boolean;
  showCloseButton?: boolean;
  closeOnBackdrop?: boolean;
  closeOnEscape?: boolean;
  closeButtonAriaLabel?: string;
  ariaLabel?: string;
  className?: string;
  bodyClassName?: string;
  initialFocusRef?: React.RefObject<HTMLElement | null>;
}

const sizeClasses: Record<NonNullable<ModalProps["size"]>, string> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-2xl",
  "2xl": "max-w-3xl",
  full: "max-w-4xl",
};

export const Modal: React.FC<ModalProps> = ({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  variant = "modal",
  padded = true,
  showCloseButton = true,
  closeOnBackdrop = true,
  closeOnEscape = true,
  closeButtonAriaLabel,
  ariaLabel,
  className = "",
  bodyClassName = "",
  initialFocusRef,
}) => {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useBodyScrollLock(open);

  // Focus management effect: keyed ONLY on `open` and initialFocusRef
  useEffect(() => {
    if (!open) return;

    previousFocusRef.current = document.activeElement as HTMLElement | null;

    // Handle initial focus
    const timer = setTimeout(() => {
      if (initialFocusRef?.current) {
        initialFocusRef.current.focus();
      } else if (dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length > 0) {
          focusable[0].focus();
        } else {
          dialogRef.current.focus();
        }
      }
    }, 10);

    return () => {
      clearTimeout(timer);
      previousFocusRef.current?.focus();
    };
  }, [open, initialFocusRef]);

  // Keyboard navigation & Escape effect
  useEffect(() => {
    if (!open) return;

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (!closeOnEscape) return;
        e.stopPropagation();
        onClose();
        return;
      }

      if (e.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) {
          e.preventDefault();
          return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (!dialogRef.current.contains(document.activeElement)) {
          e.preventDefault();
          first.focus();
          return;
        }

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open, closeOnEscape, onClose]);

  if (!open) return null;

  const accessibleTitle = typeof title === "string" ? title : ariaLabel || "Dialog";

  const isDrawer = variant === "drawer";

  return (
    <div
      className={
        isDrawer
          ? "fixed inset-0 z-50 flex justify-end"
          : "fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4"
      }
    >
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity"
        onClick={closeOnBackdrop ? onClose : undefined}
        aria-hidden="true"
      />

      {/* Dialog Surface */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={accessibleTitle}
        tabIndex={-1}
        className={
          isDrawer
            ? `relative z-10 flex h-full w-full ${sizeClasses[size]} flex-col overflow-hidden border-l border-border-subtle bg-surface-card text-text-primary shadow-2xl transition-all ${className}`
            : `relative z-10 flex w-full ${sizeClasses[size]} max-h-[calc(100vh-2rem)] max-h-[calc(100dvh-2rem)] flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface-card text-text-primary shadow-2xl transition-all ${className}`
        }
      >
        {(title || description || showCloseButton) && (
          <div
            data-testid="modal-header"
            className={`shrink-0 flex items-start justify-between gap-3 ${
              padded ? "border-b border-border-subtle px-4 pt-4 pb-3 sm:px-6 sm:pt-5 sm:pb-3.5" : ""
            }`}
          >
            <div className="min-w-0">
              {title && (
                <h2 className="text-lg font-semibold text-text-primary">
                  {title}
                </h2>
              )}
              {description && (
                <p className="mt-1 text-sm text-text-muted">
                  {description}
                </p>
              )}
            </div>

            {showCloseButton && (
              <button
                type="button"
                onClick={onClose}
                aria-label={closeButtonAriaLabel || "Close dialog"}
                className="shrink-0 rounded-lg p-1 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus cursor-pointer"
              >
                <Icon name="x" size={18} />
              </button>
            )}
          </div>
        )}

        {padded ? (
          <div
            data-testid="modal-body"
            className={`flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 py-4 sm:px-6 ${bodyClassName}`}
          >
            {children}
          </div>
        ) : (
          children
        )}

        {footer && (
          <div
            data-testid="modal-footer"
            className={`shrink-0 ${
              padded ? "border-t border-border-subtle px-4 py-3 sm:px-6 sm:py-3.5" : ""
            }`}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
};
