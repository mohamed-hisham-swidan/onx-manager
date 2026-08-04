import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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

function renderDialog() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <CreateBackupDialog onDone={vi.fn()} />
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
});
