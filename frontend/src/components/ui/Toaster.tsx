import { useToastStore, type ToastType } from "@/stores/toastStore";
import { Icon } from "./Icon";

const STYLES: Record<ToastType, { ring: string; icon: "check" | "alert" | "info"; iconColor: string }> = {
  success: { ring: "border-status-online/40", icon: "check", iconColor: "text-status-online" },
  error: { ring: "border-status-danger/40", icon: "alert", iconColor: "text-status-danger" },
  info: { ring: "border-accent-primary/40", icon: "info", iconColor: "text-accent-primary" },
};

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2">
      {toasts.map((t) => {
        const style = STYLES[t.type];
        return (
          <div
            key={t.id}
            role="status"
            className={`pointer-events-auto flex items-start gap-3 rounded-xl border bg-surface-panel p-4 shadow-lg text-text-primary ${style.ring}`}
          >
            <Icon name={style.icon} size={18} className={`mt-0.5 shrink-0 ${style.iconColor}`} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-text-primary">{t.title}</p>
              {t.message && (
                <p className="mt-0.5 text-sm text-text-muted">{t.message}</p>
              )}
            </div>
            <button
              onClick={() => dismiss(t.id)}
              className="shrink-0 rounded p-0.5 text-text-muted transition-colors hover:text-text-primary cursor-pointer"
              aria-label="Dismiss notification"
            >
              <Icon name="x" size={16} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
