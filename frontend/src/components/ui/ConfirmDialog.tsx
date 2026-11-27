import { useEffect, useRef } from "react";
import { Icon } from "@/components/ui/Icon";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: string;
  children?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "warning" | "info";
  isPending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  children,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "danger",
  isPending = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const confirmButtonRef = useRef<HTMLButtonElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const confirmLockRef = useRef(false);

  useEffect(() => {
    if (!open || !isPending) {
      confirmLockRef.current = false;
    }
  }, [open, isPending]);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    if (variant === "danger") {
      cancelButtonRef.current?.focus();
    } else {
      confirmButtonRef.current?.focus();
    }

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (isPending) return;
        onCancel();
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

    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previousFocusRef.current?.focus();
    };
  }, [open, onCancel, variant, isPending]);

  if (!open) return null;

  const iconColors =
    variant === "danger"
      ? "bg-status-danger-bg text-status-danger border border-status-danger-border"
      : variant === "warning"
      ? "bg-status-warning-bg text-status-warning border border-status-warning-border"
      : "bg-status-info-bg text-status-info border border-status-info-border";

  const confirmColors =
    variant === "danger"
      ? "bg-status-danger hover:opacity-90 text-text-inverse"
      : variant === "warning"
      ? "bg-status-warning hover:opacity-90 text-text-inverse"
      : "bg-accent-primary hover:bg-accent-hover text-accent-contrast-text";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4"
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-xs"
        onClick={isPending ? undefined : onCancel}
        aria-hidden="true"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        aria-busy={isPending ? "true" : undefined}
        className="relative z-10 flex w-full max-w-sm max-h-[calc(100vh-2rem)] max-h-[calc(100dvh-2rem)] flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface-card p-5 sm:p-6 shadow-2xl transition-all"
      >
        <div className="shrink-0">
          <div className={`mb-4 flex h-11 w-11 items-center justify-center rounded-xl ${iconColors}`}>
            <Icon name="alert" size={22} />
          </div>
          <h2 className="mb-1 text-base font-semibold text-text-primary">{title}</h2>
        </div>
        {(description || children) && (
          <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
            {description && (
              <p className="mb-4 text-sm text-text-muted">{description}</p>
            )}
            {children && <div className="mb-5">{children}</div>}
            {!children && description && <div className="mb-1" />}
          </div>
        )}
        <div className="shrink-0 flex justify-end gap-2 pt-2">
          <button
            ref={cancelButtonRef}
            type="button"
            disabled={isPending}
            onClick={onCancel}
            className="rounded-lg border border-border-subtle px-4 py-2 text-sm font-medium text-text-secondary transition-colors hover:border-border-hover hover:bg-surface-hover hover:text-text-primary disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmButtonRef}
            type="button"
            disabled={isPending}
            onClick={() => {
              if (isPending || confirmLockRef.current) return;
              confirmLockRef.current = true;
              onConfirm();
            }}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${confirmColors}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
