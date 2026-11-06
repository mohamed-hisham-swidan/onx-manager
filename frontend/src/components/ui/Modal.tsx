import React, { useEffect, useRef } from "react";
import { Icon } from "@/components/ui/Icon";
import { useBodyScrollLock } from "@/hooks/useBodyScrollLock";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  size?: "sm" | "md" | "lg" | "xl" | "2xl" | "full";
  showCloseButton?: boolean;
  closeOnBackdrop?: boolean;
  closeOnEscape?: boolean;
  closeButtonAriaLabel?: string;
  ariaLabel?: string;
  className?: string;
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
  size = "md",
  showCloseButton = true,
  closeOnBackdrop = true,
  closeOnEscape = true,
  closeButtonAriaLabel,
  ariaLabel,
  className = "",
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
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
        className={`relative z-10 w-full ${sizeClasses[size]} rounded-xl border border-border-subtle bg-surface-card p-6 text-text-primary shadow-2xl transition-all ${className}`}
      >
        {(title || showCloseButton) && (
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
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
                className="rounded-lg p-1 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus"
              >
                <Icon name="x" size={18} />
              </button>
            )}
          </div>
        )}

        {children}
      </div>
    </div>
  );
};
