import { useToastStore, type ToastType } from "@/stores/toastStore";
import { Icon } from "./Icon";

const STYLES: Record<ToastType, { ring: string; icon: "check" | "alert" | "info"; iconColor: string }> = {
  success: { ring: "border-green-500/40", icon: "check", iconColor: "text-green-500" },
  error: { ring: "border-red-500/40", icon: "alert", iconColor: "text-red-500" },
  info: { ring: "border-blue-500/40", icon: "info", iconColor: "text-blue-500" },
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
            className={`pointer-events-auto flex items-start gap-3 rounded-xl border bg-white p-4 shadow-lg dark:bg-gray-800 ${style.ring}`}
          >
            <Icon name={style.icon} size={18} className={`mt-0.5 shrink-0 ${style.iconColor}`} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{t.title}</p>
              {t.message && (
                <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">{t.message}</p>
              )}
            </div>
            <button
              onClick={() => dismiss(t.id)}
              className="shrink-0 rounded p-0.5 text-gray-400 transition-colors hover:text-gray-600 dark:hover:text-gray-200"
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
