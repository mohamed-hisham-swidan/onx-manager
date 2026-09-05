import { useIsFetching, useIsMutating } from "@tanstack/react-query";

export function LoadingBar() {
  const isFetching = useIsFetching({
    predicate: (query) => query.state.data === undefined,
  });
  const isMutating = useIsMutating();
  const active = isFetching > 0 || isMutating > 0;

  return (
    <div
      data-testid="loading-bar"
      className={`pointer-events-none fixed inset-x-0 top-0 z-50 h-0.5 transition-opacity duration-200 ${
        active ? "opacity-100" : "opacity-0"
      }`}
      aria-hidden="true"
    >
      <div className="h-full w-1/3 animate-[loading-bar_1.2s_ease-in-out_infinite] bg-blue-500" />
    </div>
  );
}
