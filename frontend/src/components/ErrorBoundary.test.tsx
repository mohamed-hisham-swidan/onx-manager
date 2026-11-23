import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorBoundary } from "./ErrorBoundary";

const Thrower = ({ shouldThrow }: { shouldThrow: boolean }) => {
  if (shouldThrow) throw new Error("Test error");
  return <div data-testid="normal-content">Normal</div>;
};

describe("ErrorBoundary", () => {
  it("renders children when no error", () => {
    render(
      <ErrorBoundary>
        <div data-testid="child">Ok</div>
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });

  it("renders fallback on error", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Thrower shouldThrow={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("Test error")).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("uses custom fallback when provided", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary fallback={<div data-testid="custom">Custom Error</div>}>
        <Thrower shouldThrow={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("custom")).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("recovers on try again click", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Thrower shouldThrow={true} />
      </ErrorBoundary>,
    );
    const btn = screen.getByText("Try again");
    btn.click();
    expect(screen.getByText("Try again")).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("auto-reloads once and offers Reload app fallback for dynamic import chunk errors", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const reloadSpy = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, reload: reloadSpy },
      configurable: true,
    });
    window.sessionStorage.clear();

    const ChunkFail = () => {
      throw new TypeError(
        "Failed to fetch dynamically imported module: http://127.0.0.1:8001/assets/ServerFilesPage-DyGFmkDG.js",
      );
    };

    render(
      <ErrorBoundary>
        <ChunkFail />
      </ErrorBoundary>,
    );

    expect(reloadSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByText("App update available")).toBeInTheDocument();
    screen.getByRole("button", { name: "Reload app" }).click();
    expect(reloadSpy).toHaveBeenCalledTimes(2);
    vi.restoreAllMocks();
  });
});
