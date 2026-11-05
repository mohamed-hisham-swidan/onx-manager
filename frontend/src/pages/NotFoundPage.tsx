import { EmptyState } from "@/components/ui/States";
import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <EmptyState
      icon="alert"
      title="Page not found"
      description="The page you're looking for doesn't exist or has been moved."
      action={
        <Link
          to="/"
          className="rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover"
        >
          Back to Dashboard
        </Link>
      }
    />
  );
}
