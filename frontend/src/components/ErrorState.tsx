interface ErrorStateProps {
  message: string;
  className?: string;
}

export function ErrorState({ message, className }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={`rounded-xl border border-status-danger-border bg-status-danger-bg p-6 text-sm text-status-danger ${className ?? ""}`}
    >
      {message}
    </div>
  );
}