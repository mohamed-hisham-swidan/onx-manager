import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BackupListPage } from "./BackupListPage";

const mockBackups = [
  {
    backup_id: "bkp-1",
    server_id: "srv-1",
    backup_type: "full",
    status: "completed",
    size_bytes: 1048576,
    checksum: "abc",
    error_message: "",
    created_at: "2024-01-01T00:00:00Z",
    completed_at: "2024-01-01T01:00:00Z",
  },
];

let mockData = mockBackups;
let mockIsLoading = false;
let mockError: Error | null = null;

vi.mock("@/server_manager/hooks/useBackups", () => ({
  useBackupsList: vi.fn(() => ({
    data: mockData,
    isLoading: mockIsLoading,
    error: mockError,
  })),
  useRestoreBackup: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useVerifyBackup: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useDeleteBackup: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(() => ({
    data: [{ server_id: "srv-1", name: "Test Server" }],
  })),
}));

let mockDialogRendered = false;
vi.mock("@/server_manager/components/CreateBackupDialog", () => ({
  CreateBackupDialog: vi.fn(() => {
    mockDialogRendered = true;
    return <div data-testid="create-backup-dialog">CreateBackup</div>;
  }),
}));

function renderPage() {
  const qc = new QueryClient();
  mockDialogRendered = false;
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BackupListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BackupListPage", () => {
  beforeEach(() => {
    mockData = mockBackups;
    mockIsLoading = false;
    mockError = null;
  });

  it("renders title", () => {
    renderPage();
    expect(screen.getByText("Backups")).toBeInTheDocument();
  });

  it("shows loading skeletons", () => {
    mockIsLoading = true;
    const { container } = renderPage();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows error on failure", () => {
    mockError = new Error("Load failed");
    renderPage();
    expect(screen.getByText("Load failed")).toBeInTheDocument();
  });

  it("renders backup rows", () => {
    renderPage();
    expect(screen.getByText("full")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
  });

  it("shows empty state when no backups", () => {
    mockData = [];
    renderPage();
    expect(screen.getByText("No backups found")).toBeInTheDocument();
  });

  it("toggles create dialog", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText("+ New Backup"));
    expect(screen.getByTestId("create-backup-dialog")).toBeInTheDocument();
  });
});
