import { Component, type ErrorInfo, type ReactNode } from "react";
import { isChunkLoadError, tryChunkReloadOnce } from "@/utils/chunkReload";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    if (isChunkLoadError(error) && tryChunkReloadOnce()) {
      return;
    }
    console.error("ErrorBoundary caught:", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      const chunkErr = isChunkLoadError(this.state.error);
      return (
        <div
          role="alert"
          aria-live="assertive"
          className="flex flex-col items-center justify-center py-16 text-center"
        >
          <p className="text-xl font-semibold text-text-primary mb-2">
            {chunkErr ? "App update available" : "Something went wrong"}
          </p>
          <p className="text-sm text-text-muted mb-4 max-w-md">
            {chunkErr
              ? "The panel assets were updated. Reload the page to load the latest interface."
              : (this.state.error?.message ?? "An unexpected error occurred")}
          </p>
          <button
            type="button"
            onClick={() => {
              if (chunkErr) {
                window.location.reload();
              } else {
                this.setState({ hasError: false, error: null });
              }
            }}
            className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium transition-colors"
          >
            {chunkErr ? "Reload app" : "Try again"}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
