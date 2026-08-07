import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CreateServerPage } from "./CreateServerPage";

const listSoftwareMock = vi.fn();
const listSoftwareVersionsMock = vi.fn();
const getAvailablePortMock = vi.fn();

vi.mock("@/services/api", async () => {
  const actual = await vi.importActual<typeof import("@/services/api")>("@/services/api");
  return {
    ...actual,
    createAuthenticatedApi: () => ({
      listSoftware: listSoftwareMock,
      listSoftwareVersions: listSoftwareVersionsMock,
      getAvailablePort: getAvailablePortMock,
    }),
  };
});

vi.mock("@/server_manager/hooks/useServers", () => ({
  useCreateServer: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
}));

function renderPage() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CreateServerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CreateServerPage version step", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listSoftwareMock.mockResolvedValue([
      { type: "vanilla", name: "Vanilla", description: "Official" },
    ]);
    listSoftwareVersionsMock.mockResolvedValue([]);
    getAvailablePortMock.mockResolvedValue({ port: 25565 });
  });

  it("shows a distinct error message when the versions fetch fails", async () => {
    listSoftwareVersionsMock.mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Vanilla"));

    expect(
      await screen.findByText(/Failed to load versions — try again/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("No versions available.")).not.toBeInTheDocument();
  });

  it("shows the empty message only when versions are genuinely empty", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Vanilla"));

    expect(await screen.findByText("No versions available.")).toBeInTheDocument();
    expect(screen.queryByText(/Failed to load versions/i)).not.toBeInTheDocument();
  });
});