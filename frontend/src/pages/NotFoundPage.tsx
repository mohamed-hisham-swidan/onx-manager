import { EmptyState } from "@/components/EmptyState";
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
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
        >
          Back to Dashboard
        </Link>
      }
    />
  );
}
