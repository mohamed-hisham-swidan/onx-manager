interface ErrorStateProps {
  message: string;
  className?: string;
}

export function ErrorState({ message, className }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={`rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-400 ${className ?? ""}`}
    >
      {message}
    </div>
  );
}