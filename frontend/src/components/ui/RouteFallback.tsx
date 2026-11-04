export function RouteFallback() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex h-64 w-full flex-col items-center justify-center gap-3 py-12"
    >
      <div className="h-1 w-28 overflow-hidden rounded-full bg-surface-active" aria-hidden="true">
        <div className="h-full w-1/3 animate-[loading-bar_1.2s_ease-in-out_infinite] rounded-full bg-accent-primary" />
      </div>
      <span className="text-xs font-medium text-text-muted select-none">Loading view...</span>
    </div>
  );
}
