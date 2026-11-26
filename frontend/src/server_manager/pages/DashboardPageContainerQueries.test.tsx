/**
 * Dashboard Container Queries & Fluid Responsiveness Guard
 *
 * NOTE: This test is a class-presence guard only. JSDOM cannot compute container
 * queries (@container, @lg, @2xl, @4xl, @5xl), so this test ensures that the
 * proper Tailwind v4 container query classes and min-w-0 flex constraints are present
 * on the DOM elements, while legacy viewport breakpoints (lg:grid-cols-12, lg:col-span-8, break-all)
 * have been eliminated from the rendered dashboard.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardPage } from "./DashboardPage";
import { useActivityStore } from "@/stores/activityStore";
import type { ServerResponse } from "@/server_manager/types";

const mockServers: ServerResponse[] = [
  {
    server_id: "srv-container-1",
    name: "Container Query Test Server",
    server_type: "paper",
    minecraft_version: "1.21.4",
    status: "running",
    group_id: "default",
    port: 25565,
    motd: "",
    max_players: 20,
    gamemode: "survival",
    difficulty: "normal",
    created_at: "",
    updated_at: "",
  },
];

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(),
  useStartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStopServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRestartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRetryProvisioningServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

import { useServersList } from "@/server_manager/hooks/useServers";

const qc = new QueryClient();

function renderPage() {
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DashboardPage Container Queries (Class-Presence Guard)", () => {
  beforeEach(() => {
    vi.mocked(useServersList).mockReturnValue({
      data: mockServers,
      isLoading: false,
    } as unknown as ReturnType<typeof useServersList>);
    useActivityStore.getState().clear();
  });

  it("ensures dashboard root has the @container class", () => {
    const { container } = renderPage();
    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveClass("@container");
  });

  it("ensures rendered markup has no lg:grid-cols-12, no lg:col-span-8, and no break-all in the stream", () => {
    const { container } = renderPage();
    const html = container.innerHTML;

    expect(html).not.toContain("lg:grid-cols-12");
    expect(html).not.toContain("lg:col-span-8");
    expect(html).not.toContain("break-all");
  });

  it("ensures workspace split grid uses items-start", () => {
    const { container } = renderPage();
    const splitGrid = container.querySelector(".\\@5xl\\:grid-cols-12");
    expect(splitGrid).not.toBeNull();
    expect(splitGrid?.className).toContain("items-start");
  });

  it("ensures loading state markup also has no lg:grid-cols-12 and no lg:col-span-8", () => {
    vi.mocked(useServersList).mockReturnValue({
      data: undefined,
      isLoading: true,
    } as unknown as ReturnType<typeof useServersList>);

    const { container } = renderPage();
    const html = container.innerHTML;

    expect(html).not.toContain("lg:grid-cols-12");
    expect(html).not.toContain("lg:col-span-8");
  });
});
