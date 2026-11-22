import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CreateBackupDialog } from "./CreateBackupDialog";

const mockMutateAsync = vi.fn().mockResolvedValue({});

vi.mock("@/server_manager/hooks/useBackups", () => ({
  useCreateBackup: vi.fn(() => ({ mutateAsync: mockMutateAsync, isPending: false })),
}));

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(() => ({
    data: [{ server_id: "srv-1", name: "Test Server" }],
  })),
}));

function renderDialog(defaultServerId?: string) {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <CreateBackupDialog onDone={vi.fn()} defaultServerId={defaultServerId} />
    </QueryClientProvider>,
  );
}

describe("CreateBackupDialog", () => {
  beforeEach(() => {
    mockMutateAsync.mockReset();
    mockMutateAsync.mockResolvedValue({});
  });

  it("renders form heading", () => {
    renderDialog();
    expect(screen.getByRole("heading", { name: "Create Backup" })).toBeInTheDocument();
  });

  it("renders server options", () => {
    renderDialog();
    expect(screen.getByText("Test Server")).toBeInTheDocument();
  });

  it("preselects defaultServerId in the server select", () => {
    renderDialog("srv-1");
    const select = screen.getByLabelText("Select server");
    expect(select).toHaveValue("srv-1");
  });

  it("renders submit button", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "Create Backup" })).toBeInTheDocument();
  });

  it("renders all seven backup type options", () => {
    renderDialog();
    const select = document.querySelector<HTMLSelectElement>('select[name="backup_type"]');
    expect(select).not.toBeNull();
    const options = Array.from(select!.options).map((o) => ({ value: o.value, label: o.text }));
    expect(options).toEqual([
      { value: "full", label: "Full Backup" },
      { value: "worlds", label: "Worlds" },
      { value: "world", label: "World" },
      { value: "nether", label: "Nether" },
      { value: "end", label: "End" },
      { value: "plugins", label: "Plugins" },
      { value: "config", label: "Config" },
    ]);
  });

  it("defaults to Tier-1 snapshot with Tier-2 options hidden", () => {
    renderDialog();
    expect(screen.getByRole("radio", { name: /Tier-1 Snapshot/i })).toBeChecked();
    expect(screen.queryByTestId("tier-2-options")).not.toBeInTheDocument();
  });

  it("selecting Tier-2 reveals archive format, CAS options, and encryption notice", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("radio", { name: /Tier-2 Archive/i }));
    expect(screen.getByTestId("tier-2-options")).toBeInTheDocument();
    expect(screen.getByLabelText("Archive format")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Include CAS Jars" })).toBeInTheDocument();
    expect(screen.getByText(/Automatic Envelope Encryption/i)).toBeInTheDocument();
    expect(screen.getByText(/AES-256-GCM/i)).toBeInTheDocument();
  });

  it("communicates Tier-1 retention policy", () => {
    renderDialog();
    expect(screen.getByText(/Retention: last 5 unpinned/i)).toBeInTheDocument();
  });

  it("communicates Tier-2 retention policy", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("radio", { name: /Tier-2 Archive/i }));
    expect(screen.getByText(/Retention: 7 daily \+ 4 weekly unpinned/i)).toBeInTheDocument();
  });

  async function fillDialogAndSubmit() {
    fireEvent.change(screen.getByLabelText("Select server"), { target: { value: "srv-1" } });
  }

  it("submits Tier-1 payload correctly", async () => {
    const user = userEvent.setup();
    renderDialog();
    await fillDialogAndSubmit();
    await user.click(screen.getByRole("button", { name: "Create Backup" }));
    expect(mockMutateAsync).toHaveBeenCalledWith({
      server_id: "srv-1",
      backup_type: "full",
      tier: "tier_1",
    });
  });

  it("submits Tier-2 payload correctly", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("radio", { name: /Tier-2 Archive/i }));
    await fillDialogAndSubmit();
    await user.click(screen.getByRole("checkbox", { name: "Include CAS Jars" }));
    await user.click(screen.getByRole("button", { name: "Create Backup" }));
    expect(mockMutateAsync).toHaveBeenCalledWith({
      server_id: "srv-1",
      backup_type: "full",
      tier: "tier_2",
      archive_format: "tar.zst",
      include_cas_jars: true,
    });
  });
});
