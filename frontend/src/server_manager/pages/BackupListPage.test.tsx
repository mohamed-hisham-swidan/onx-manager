import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BackupListPage } from "./BackupListPage";
import type { BackupResponse } from "@/types";

const mockBackups: BackupResponse[] = [
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
  {
    backup_id: "bkp-2",
    server_id: "srv-2",
    backup_type: "incremental",
    status: "failed",
    size_bytes: 2048,
    checksum: "def",
    error_message: "boom",
    created_at: "2024-01-02T00:00:00Z",
    completed_at: "2024-01-02T00:05:00Z",
  },
];

let mockData = mockBackups;
let mockIsLoading = false;
let mockError: Error | null = null;

const mockRestoreMutate = vi.fn();

vi.mock("@/server_manager/hooks/useBackups", () => ({
  useBackupsList: vi.fn(() => ({
    data: mockData,
    isLoading: mockIsLoading,
    error: mockError,
  })),
  useRestoreBackup: vi.fn(() => ({ mutate: mockRestoreMutate, isPending: false })),
  useVerifyBackup: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useDeleteBackup: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(() => ({
    data: [
      { server_id: "srv-1", name: "Alpha" },
      { server_id: "srv-2", name: "Beta" },
    ],
  })),
}));

vi.mock("@/server_manager/components/CreateBackupDialog", () => ({
  CreateBackupDialog: vi.fn(() => <div data-testid="create-backup-dialog">CreateBackup</div>),
}));

function renderPage() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BackupListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function getTable() {
  return screen.getByRole("table");
}

describe("BackupListPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockData = mockBackups;
    mockIsLoading = false;
    mockError = null;
  });

  it("renders page header", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Backups" })).toBeInTheDocument();
  });

  it("shows summary stats", () => {
    renderPage();
    expect(screen.getByText("Total backups")).toBeInTheDocument();
    expect(screen.getByText("Total size")).toBeInTheDocument();
    expect(screen.getByText("Last successful backup")).toBeInTheDocument();
    const statRows = screen.getAllByText("Alpha");
    expect(statRows.length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("1.0 MB").length).toBeGreaterThanOrEqual(1);
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

  it("renders backup rows with statuses", () => {
    renderPage();
    expect(screen.getByText("full")).toBeInTheDocument();
    expect(screen.getAllByText("completed").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("failed").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Beta").length).toBeGreaterThanOrEqual(1);
  });

  it("shows restore only for completed backups", () => {
    renderPage();
    expect(screen.getByLabelText("Restore bkp-1")).toBeInTheDocument();
    expect(screen.queryByLabelText("Restore bkp-2")).not.toBeInTheDocument();
  });

  it("shows verify and delete actions for every backup", () => {
    renderPage();
    expect(screen.getByLabelText("Verify bkp-1")).toBeInTheDocument();
    expect(screen.getByLabelText("Verify bkp-2")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/Delete/)).toHaveLength(2);
  });

  it("filters by server", () => {
    renderPage();
    expect(within(getTable()).getByText("Alpha")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter by server"), { target: { value: "srv-2" } });
    expect(within(getTable()).getByText("Beta")).toBeInTheDocument();
    expect(within(getTable()).queryByText("Alpha")).not.toBeInTheDocument();
  });

  it("filters by status", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "failed" } });
    expect(within(getTable()).getByText("Beta")).toBeInTheDocument();
    expect(within(getTable()).queryByText("Alpha")).not.toBeInTheDocument();
  });

  it("shows no-results state when filters match nothing", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "pending" } });
    expect(screen.getByText("No matching backups")).toBeInTheDocument();
  });

  it("shows empty state when no backups", () => {
    mockData = [];
    renderPage();
    expect(screen.getByText("No backups found")).toBeInTheDocument();
  });

  it("toggles create dialog", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText("New Backup"));
    expect(screen.getByTestId("create-backup-dialog")).toBeInTheDocument();
  });

  it("opens delete confirmation dialog", () => {
    renderPage();
    fireEvent.click(screen.getByLabelText("Delete bkp-1"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Delete backup?")).toBeInTheDocument();
  });

  it("ISS-056: clicking restore opens confirmation dialog and does not trigger restore immediately", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText("Restore bkp-1"));
    expect(screen.getByText("Restore backup?")).toBeInTheDocument();
    expect(
      screen.getByText(/Restoring will overwrite current server files/i),
    ).toBeInTheDocument();
    expect(mockRestoreMutate).not.toHaveBeenCalled();

    // Confirm restore in dialog
    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(mockRestoreMutate).toHaveBeenCalledWith("bkp-1", expect.any(Object));
  });

  it("ISS-056: cancelling restore dialog dismisses without calling restore API", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText("Restore bkp-1"));
    expect(screen.getByText("Restore backup?")).toBeInTheDocument();

    // Cancel in dialog
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText("Restore backup?")).not.toBeInTheDocument();
    expect(mockRestoreMutate).not.toHaveBeenCalled();
  });
});
