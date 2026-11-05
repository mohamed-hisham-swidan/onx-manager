import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { InstallModal } from "./InstallModal";
import type { PluginSearchResultResponse } from "@/types";
import type { ServerResponse } from "@/server_manager/types";

let mockServers: ServerResponse[] = [];
let mockIsPending = false;
const mockInstallMutate = vi.fn();

const mockProject: PluginSearchResultResponse = {
  project_id: "test-plugin",
  slug: "test-plugin",
  title: "Test Plugin",
  description: "A test plugin description",
  author: "TestAuthor",
  project_types: ["plugin"],
  downloads: 500,
  follows: 20,
  icon_url: "",
  latest_version_id: "v1",
  categories: ["admin"],
  loaders: ["paper"],
  client_side: "unsupported",
  server_side: "required",
  date_modified: "2026-01-01T00:00:00Z",
  color: null,
};

const mockVersions = {
  project_id: "test-plugin",
  versions: [
    {
      version_id: "v1",
      project_id: "test-plugin",
      name: "1.0.0",
      version_number: "1.0.0",
      game_versions: ["1.21"],
      loaders: ["paper"],
      files: [{ url: "https://example.com/p.jar", filename: "p.jar", size_bytes: 1024, sha1: "", sha512: "", primary: true }],
      dependencies: [],
      date_published: "2026-01-01T00:00:00Z",
    },
  ],
  selected: {
    version_id: "v1",
    project_id: "test-plugin",
    name: "1.0.0",
    version_number: "1.0.0",
    game_versions: ["1.21"],
    loaders: ["paper"],
    files: [{ url: "https://example.com/p.jar", filename: "p.jar", size_bytes: 1024, sha1: "", sha512: "", primary: true }],
    dependencies: [],
    date_published: "2026-01-01T00:00:00Z",
  },
  notice: "",
  notice_kind: "",
};

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: () => ({ data: mockServers }),
}));

vi.mock("@/server_manager/hooks/usePlugins", () => ({
  useProjectVersions: () => ({
    data: mockVersions,
    isLoading: false,
    isError: false,
    error: null,
  }),
  useInstallFromMarketplace: () => ({
    mutate: mockInstallMutate,
    isPending: mockIsPending,
  }),
}));

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
}));

vi.mock("@/stores/lastUsedServerStore", () => ({
  useLastUsedServerStore: <T,>(selector: (state: { lastUsedServerId: string; setLastUsedServer: () => void }) => T): T =>
    selector({
      lastUsedServerId: "srv-paper",
      setLastUsedServer: vi.fn(),
    }),
}));

vi.mock("@/stores/marketplaceSourceStore", () => ({
  useMarketplaceSourceStore: <T,>(selector: (state: { source: string }) => T): T =>
    selector({
      source: "modrinth",
    }),
}));

describe("InstallModal Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsPending = false;
    mockServers = [
      {
        server_id: "srv-paper",
        name: "Paper Server 1",
        server_type: "paper",
        minecraft_version: "1.21.1",
      },
    ] as unknown as ServerResponse[];
  });

  it("does not render when isOpen is false", () => {
    render(
      <InstallModal
        isOpen={false}
        project={mockProject}
        onClose={vi.fn()}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders role='dialog' with accessible name, acquires scroll lock, and releases on unmount", () => {
    document.body.style.overflow = "";
    const { unmount } = render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Install Test Plugin" });
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("closes on Escape key when idle", () => {
    const onClose = vi.fn();
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={onClose}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape when install is pending", () => {
    mockIsPending = true;
    const onClose = vi.fn();
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={onClose}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes when clicking backdrop when idle", () => {
    const onClose = vi.fn();
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={onClose}
      />
    );

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close when clicking backdrop while install is pending", () => {
    mockIsPending = true;
    const onClose = vi.fn();
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={onClose}
      />
    );

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not close when clicking inside dialog content", () => {
    const onClose = vi.fn();
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={onClose}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Install Test Plugin" });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("moves focus into the dialog on open", async () => {
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Install Test Plugin" });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const activeEl = document.activeElement;
    expect(dialog.contains(activeEl)).toBe(true);
  });

  it("disables Install button and ignores close button when install is pending", async () => {
    mockIsPending = true;
    const onClose = vi.fn();
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={onClose}
      />
    );

    const installBtn = screen.getByRole("button", { name: /Installing.../i });
    expect(installBtn).toBeDisabled();

    const closeBtn = screen.getByRole("button", { name: "Close modal" });
    fireEvent.click(closeBtn);
    expect(onClose).not.toHaveBeenCalled();
  });
});
