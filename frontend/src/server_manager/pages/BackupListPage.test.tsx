import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BackupListPage } from "./BackupListPage";
import * as toastStore from "@/stores/toastStore";
import type { BackupResponse, ScheduleResponse } from "@/types";
import type { ServerResponse } from "@/server_manager/types";

const mockBackups: BackupResponse[] = [
  {
    backup_id: "bkp-1111111",
    server_id: "srv-1",
    server_name: "Alpha",
    server_deleted: false,
    backup_type: "full",
    status: "completed",
    size_bytes: 1048576,
    checksum: "sha256-alpha-1234567890",
    error_message: "",
    created_at: "2024-01-01T00:00:00Z",
    completed_at: "2024-01-01T01:00:00Z",
    tier: "tier_1",
    pinned: false,
  },
  {
    backup_id: "bkp-2222222",
    server_id: "srv-2",
    server_name: "Beta",
    server_deleted: false,
    backup_type: "worlds",
    status: "failed",
    size_bytes: 2048,
    checksum: "sha256-beta-abcdef",
    error_message: "Disk quota exceeded while writing snapshot",
    created_at: "2024-01-02T00:00:00Z",
    completed_at: "2024-01-02T00:05:00Z",
    tier: "tier_2",
    pinned: true,
  },
  {
    backup_id: "bkp-3333333",
    server_id: "srv-deleted-uuid-99999",
    server_name: null,
    server_deleted: true,
    backup_type: "full",
    status: "in_progress",
    size_bytes: 4096,
    checksum: "",
    error_message: "",
    created_at: "2024-01-03T00:00:00Z",
    completed_at: null,
    tier: "tier_2",
    pinned: false,
  },
];

const mockServers: ServerResponse[] = [
  {
    server_id: "srv-1",
    name: "Alpha",
    server_type: "paper",
    minecraft_version: "1.21.4",
    status: "running",
    group_id: "default",
    port: 25565,
    motd: "",
    max_players: 20,
    gamemode: "survival",
    difficulty: "normal",
    mode: "simple",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
  },
  {
    server_id: "srv-2",
    name: "Beta",
    server_type: "fabric",
    minecraft_version: "1.21.1",
    status: "stopped",
    group_id: "default",
    port: 25566,
    motd: "",
    max_players: 20,
    gamemode: "survival",
    difficulty: "normal",
    mode: "advanced",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
  },
];

const mockSchedules: ScheduleResponse[] = [
  {
    id: "sched-1",
    name: "Alpha Daily Snapshot",
    cron_expression: "0 3 * * *",
    task_name: "run_backup_task",
    params: { server_id: "srv-1", backup_type: "full", tier: "tier_1" },
    enabled: true,
    last_run_at: null,
    created_at: "2024-01-01T00:00:00Z",
  },
  {
    id: "sys-metrics",
    name: "metrics_collect",
    cron_expression: "interval:5s",
    task_name: "run_metrics_collection",
    params: {},
    enabled: true,
    last_run_at: null,
    created_at: "2024-01-01T00:00:00Z",
  },
];

let mockData = mockBackups;
let mockServerData: ServerResponse[] = mockServers;
let mockScheduleData: ScheduleResponse[] = mockSchedules;
let mockIsLoading = false;
let mockError: Error | null = null;

const mockRefetchBackups = vi.fn();
const mockRefetchServers = vi.fn();
const mockCreateBackupMutateAsync = vi.fn().mockResolvedValue({ backup_id: "bkp-new" });
const mockRestoreMutate = vi.fn();
const mockVerifyMutateAsync = vi.fn();
const mockDeleteMutate = vi.fn();
const mockCreateScheduleMutateAsync = vi.fn().mockResolvedValue({ id: "sched-new" });
const mockDeleteScheduleMutate = vi.fn();

vi.mock("@/server_manager/hooks/useBackups", () => ({
  useBackupsList: vi.fn(() => ({
    data: mockData,
    isLoading: mockIsLoading,
    error: mockError,
    refetch: mockRefetchBackups,
  })),
  useCreateBackup: vi.fn(() => ({
    mutateAsync: mockCreateBackupMutateAsync,
    isPending: false,
  })),
  useRestoreBackup: vi.fn(() => ({ mutate: mockRestoreMutate, isPending: false })),
  useVerifyBackup: vi.fn(() => ({ mutateAsync: mockVerifyMutateAsync, isPending: false })),
  useDeleteBackup: vi.fn(() => ({ mutate: mockDeleteMutate, isPending: false })),
  useSchedulesList: vi.fn(() => ({
    data: mockScheduleData,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })),
  useCreateSchedule: vi.fn(() => ({
    mutateAsync: mockCreateScheduleMutateAsync,
    isPending: false,
  })),
  useDeleteSchedule: vi.fn(() => ({
    mutate: mockDeleteScheduleMutate,
    isPending: false,
  })),
}));

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(() => ({
    data: mockServerData,
    isLoading: false,
    error: null,
    refetch: mockRefetchServers,
  })),
}));

function renderPage(initialEntry = "/backups") {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  qc.setQueryData(["currentUser"], {
    user_id: "u-owner",
    roles: ["owner"],
    permissions: ["admin:full", "backup:create", "backup:restore", "backup:delete", "global.settings"],
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
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
    mockServerData = mockServers;
    mockScheduleData = mockSchedules;
    mockIsLoading = false;
    mockError = null;
    mockVerifyMutateAsync.mockResolvedValue({
      backup_id: "bkp-1111111",
      valid: true,
      checksum_valid: true,
      size_valid: true,
      artifact_present: true,
      artifact_matches: true,
      artifact_error: null,
    });
  });

  it("renders page header, tabs, and plain-English stats without fake telemetry", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Backups" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Backups/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Schedules/i })).toBeInTheDocument();

    expect(screen.getByText("Total Backups")).toBeInTheDocument();
    expect(screen.getByText("Storage Used")).toBeInTheDocument();
    expect(screen.getByText("Last Successful")).toBeInTheDocument();
    expect(screen.getByText("Backup Health")).toBeInTheDocument();
    expect(screen.queryByText(/Dual-Engine Storage/i)).not.toBeInTheDocument();
    expect(screen.getByText("1 Failed")).toBeInTheDocument();
  });

  it("renders server names and Deleted Server fallback instead of raw UUIDs", () => {
    renderPage();
    const table = getTable();
    expect(within(table).getByText("Alpha")).toBeInTheDocument();
    expect(within(table).getByText("Beta")).toBeInTheDocument();
    expect(within(table).getAllByText("Deleted Server").length).toBeGreaterThanOrEqual(1);
    expect(within(table).queryByText("srv-deleted-uuid-99999")).not.toBeInTheDocument();
  });

  it("renders plain-English tier badges, Title Case statuses, and In Progress filter", () => {
    renderPage();
    const table = getTable();
    expect(within(table).getAllByText("Quick Snapshot")).toHaveLength(1);
    expect(within(table).getAllByText("Encrypted Archive")).toHaveLength(2);
    expect(within(table).getByText("Completed")).toBeInTheDocument();
    expect(within(table).getByText("Failed")).toBeInTheDocument();
    expect(within(table).getByText("In Progress")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filter by status"), {
      target: { value: "in_progress" },
    });
    expect(within(getTable()).getByText("Deleted Server")).toBeInTheDocument();
    expect(within(getTable()).queryByText("Alpha")).not.toBeInTheDocument();
  });

  it("reactively syncs server filter when ?server_id= URL query param changes", () => {
    function NavHarness() {
      const navigate = useNavigate();
      return (
        <>
          <button type="button" onClick={() => navigate("/backups?server_id=srv-2")}>
            Switch to Beta
          </button>
          <BackupListPage />
        </>
      );
    }

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/backups?server_id=srv-1"]}>
          <NavHarness />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(within(getTable()).getByText("Alpha")).toBeInTheDocument();
    expect(within(getTable()).queryByText("Beta")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Switch to Beta" }));
    expect(within(getTable()).getByText("Beta")).toBeInTheDocument();
    expect(within(getTable()).queryByText("Alpha")).not.toBeInTheDocument();
  });

  it("filters via search input and clears all filters via Clear filters button", async () => {
    const user = userEvent.setup();
    renderPage();

    const search = screen.getByLabelText("Search backups");
    await user.type(search, "quota exceeded");
    expect(within(getTable()).getByText("Beta")).toBeInTheDocument();
    expect(within(getTable()).queryByText("Alpha")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(within(getTable()).getByText("Alpha")).toBeInTheDocument();
    expect(within(getTable()).getByText("Beta")).toBeInTheDocument();
  });

  it("shows Verify and Restore only for completed backups and disables Delete for pinned backups", () => {
    renderPage();
    expect(screen.getAllByLabelText("Restore bkp-1111111").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByLabelText("Restore bkp-2222222")).not.toBeInTheDocument();
    expect(screen.getAllByLabelText("Verify bkp-1111111").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByLabelText("Verify bkp-2222222")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Verify bkp-3333333")).not.toBeInTheDocument();

    const table = getTable();
    const deleteButtons = within(table).getAllByLabelText("Delete backup");
    // Row 1 (bkp-1111111) unpinned, Row 2 (bkp-2222222) pinned, Row 3 unpinned
    expect(deleteButtons[0]).not.toBeDisabled();
    expect(deleteButtons[1]).toBeDisabled();
    expect(deleteButtons[1]).toHaveAttribute("title", "Pinned for upgrade rollback. Confirm the upgrade or release pins to unlock deletion.");
  });

  it("wires ErrorState Retry button to refetch backups and servers", async () => {
    const user = userEvent.setup();
    mockError = new Error("Load failed");
    renderPage();
    expect(screen.getByText("Load failed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Try Again/i }));
    expect(mockRefetchBackups).toHaveBeenCalled();
    expect(mockRefetchServers).toHaveBeenCalled();
  });

  it("opens BackupDetailsDrawer showing error_message and checksum", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(within(getTable()).getByLabelText("Details bkp-2222222"));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Disk quota exceeded while writing snapshot")).toBeInTheDocument();
    expect(within(dialog).getByText("sha256-beta-abcdef")).toBeInTheDocument();
  });

  it("opens CreateBackupModal, submits backup, and shows toast", async () => {
    const user = userEvent.setup();
    const toastSpy = vi.spyOn(toastStore, "toast");
    renderPage();

    await user.click(screen.getByRole("button", { name: /New Backup/i }));
    const dialog = screen.getByRole("dialog", { name: "New Backup" });
    expect(dialog).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Select server"), {
      target: { value: "srv-1" },
    });
    await user.click(within(dialog).getByRole("button", { name: "Start Backup" }));
    expect(mockCreateBackupMutateAsync).toHaveBeenCalledWith({
      server_id: "srv-1",
      backup_type: "full",
      tier: "tier_1",
    });
    expect(toastSpy).toHaveBeenCalledWith("success", "Backup started", "Backup started for Alpha");
  });

  it("opens SecretVaultBridgeModal linking Advanced servers or showing empty message", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Secret Vault" }));
    const dialog = screen.getByRole("dialog", { name: "Secret Vault" });
    expect(within(dialog).getByText("Beta")).toBeInTheDocument();
    expect(within(dialog).queryByText("Alpha")).not.toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: /Open Vault/i })).toHaveAttribute(
      "href",
      "/servers/srv-2/versioning?openVault=true",
    );

    await user.click(within(dialog).getByRole("button", { name: /Close/i }));

    mockServerData = [mockServers[0]];
    renderPage();
    await user.click(screen.getAllByRole("button", { name: "Secret Vault" })[1]);
    expect(screen.getByRole("link", { name: /Go to Servers/i })).toHaveAttribute("href", "/servers");
  });

  it("shows running-server warning in Restore ConfirmDialog and handles deferred restore", async () => {
    const user = userEvent.setup();
    const toastSpy = vi.spyOn(toastStore, "toast");
    renderPage();

    await user.click(within(getTable()).getByLabelText("Restore bkp-1111111"));
    const dialog = screen.getByRole("dialog", { name: "Restore backup?" });
    expect(
      within(dialog).getByText(/This server is currently running\. Restoring now will queue the restore/i),
    ).toBeInTheDocument();

    mockRestoreMutate.mockImplementationOnce((_id, options) => {
      options?.onSuccess?.({ deferred: true });
    });

    await user.click(within(dialog).getByRole("button", { name: "Restore" }));
    expect(mockRestoreMutate).toHaveBeenCalledWith("bkp-1111111", expect.any(Object));
    expect(toastSpy).toHaveBeenCalledWith(
      "info",
      "Restore Scheduled",
      "Server is active. Restore will execute once the server is stopped.",
    );
  });

  it("switches to Schedules tab and lists, creates, and deletes backup schedules", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("tab", { name: /Schedules/i }));
    expect(screen.getAllByText("Alpha Daily Snapshot").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("metrics_collect")).not.toBeInTheDocument();

    // Create a schedule
    await user.click(screen.getByRole("button", { name: /New Schedule/i }));
    const createDialog = screen.getByRole("dialog", { name: "New Backup Schedule" });
    await user.click(within(createDialog).getByRole("button", { name: "Save Schedule" }));
    expect(mockCreateScheduleMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        cron_expression: "0 3 * * *",
        task_name: "run_backup_task",
        params: { server_id: "srv-1", backup_type: "full", tier: "tier_1" },
      }),
    );

    // Delete schedule
    await user.click(screen.getAllByLabelText("Delete schedule Alpha Daily Snapshot")[0]);
    const deleteDialog = screen.getByRole("dialog", { name: "Delete schedule?" });
    await user.click(within(deleteDialog).getByRole("button", { name: "Delete" }));
    expect(mockDeleteScheduleMutate).toHaveBeenCalledWith("sched-1", expect.any(Object));
  });
});
