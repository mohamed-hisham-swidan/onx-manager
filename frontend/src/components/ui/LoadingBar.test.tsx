import { describe, it, expect, beforeEach, vi } from "vitest";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { LoadingBar } from "./LoadingBar";

function PendingQuery() {
  useQuery({ queryKey: ["pending"], queryFn: () => new Promise<never>(() => {}) });
  return null;
}

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("LoadingBar", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("is hidden when no queries are active", () => {
    const { container } = renderWithQuery(<LoadingBar />);
    expect(container.querySelector('[data-testid="loading-bar"]')).toBeInTheDocument();
  });

  it("becomes visible while a query is in flight", async () => {
    const { container } = renderWithQuery(
      <>
        <LoadingBar />
        <PendingQuery />
      </>,
    );
    const bar = container.querySelector('[data-testid="loading-bar"]');
    await vi.waitFor(() => {
      expect(bar!.className).toContain("opacity-100");
    });
  });

  it("remains hidden during background refetch of already cached queries", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["cached-query"], { id: "123", name: "test" });

    function CachedRefetchingQuery() {
      useQuery({
        queryKey: ["cached-query"],
        queryFn: () => new Promise<never>(() => {}),
      });
      return null;
    }

    const { container } = render(
      <QueryClientProvider client={client}>
        <LoadingBar />
        <CachedRefetchingQuery />
      </QueryClientProvider>,
    );

    const bar = container.querySelector('[data-testid="loading-bar"]');
    expect(bar!.className).toContain("opacity-0");
  });
});
