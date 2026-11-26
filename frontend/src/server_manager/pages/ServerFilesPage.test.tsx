import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerFilesPage } from "./ServerFilesPage";
import { ServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import * as serversUtils from "@/server_manager/components/servers/serversUtils";
import { toast } from "@/stores/toastStore";
import type { FileItem, FileContentResponse } from "@/server_manager/types";

const mockFilesList: FileItem[] = [
  {
    name: "server.properties",
    is_dir: false,
    size: 1024,
    path: "server.properties",
    modified_at: new Date(Date.now() - 120_000).toISOString(),
    file_class: "B",
    editable: true,
  },
  {
    name: "world",
    is_dir: true,
    size: 0,
    path: "world",
    modified_at: new Date(Date.now() - 300_000).toISOString(),
    editable: false,
  },
];

const mockFileContent: FileContentResponse = {
  path: "server.properties",
  content: "server-port=25565\nmotd=A Minecraft Server\nmax-players=20",
};

let currentFileList: FileItem[] = [];
let listServerFilesMock: ReturnType<typeof vi.fn>;
let readServerFileContentMock: ReturnType<typeof vi.fn>;
let writeServerFileContentMock: ReturnType<typeof vi.fn>;
let mkdirServerDirectoryMock: ReturnType<typeof vi.fn>;
let deleteServerFileMock: ReturnType<typeof vi.fn>;
let uploadServerFileMock: ReturnType<typeof vi.fn>;
let downloadServerFileMock: ReturnType<typeof vi.fn>;
let createServerCommitMock: ReturnType<typeof vi.fn>;
let listLiveStateFilesMock: ReturnType<typeof vi.fn>;
let readLiveStateFileContentMock: ReturnType<typeof vi.fn>;
let writeLiveStateFileContentMock: ReturnType<typeof vi.fn>;

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    listServerFiles: listServerFilesMock,
    readServerFileContent: readServerFileContentMock,
    writeServerFileContent: writeServerFileContentMock,
    listLiveStateFiles: listLiveStateFilesMock,
    readLiveStateFileContent: readLiveStateFileContentMock,
    writeLiveStateFileContent: writeLiveStateFileContentMock,
    mkdirServerDirectory: mkdirServerDirectoryMock,
    deleteServerFile: (...args: unknown[]) => deleteServerFileMock(...args),
    uploadServerFile: (...args: unknown[]) => uploadServerFileMock(...args),
    downloadServerFile: (...args: unknown[]) => downloadServerFileMock(...args),
    createServerCommit: createServerCommitMock,
  }),
  ApiError: class ApiError extends Error {
    constructor(public status: number, public code: string, message: string) {
      super(message);
    }
  },
}));

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
  useToastStore: vi.fn(() => ({ toasts: [], dismiss: vi.fn() })),
}));

function renderPage(
  serverId = "srv-1",
  initialEntries = [`/servers/${serverId}/files`],
  branchCtx?: {
    branch: string;
    setBranch: (b: string) => void;
    gitBacked: boolean;
    serverMode?: "simple" | "advanced";
  },
) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  qc.setQueryData(["auth", "me"], {
    user_id: "u1",
    username: "admin",
    email: null,
    display_name: "Admin",
    is_active: true,
    roles: ["owner"],
    permissions: ["admin:full"],
    created_at: "",
    last_login_at: null,
  });
  const content = (
    <Routes>
      <Route path="/servers/:serverId/files" element={<ServerFilesPage />} />
    </Routes>
  );
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>
        {branchCtx ? (
          <ServerBranchContext.Provider value={branchCtx}>{content}</ServerBranchContext.Provider>
        ) : (
          content
        )}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ServerFilesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.removeItem("onx_files_split_ratio");
    currentFileList = [...mockFilesList];
    listServerFilesMock = vi.fn().mockImplementation(() => Promise.resolve([...currentFileList]));
    readServerFileContentMock = vi.fn().mockResolvedValue(mockFileContent);
    writeServerFileContentMock = vi.fn().mockResolvedValue({ path: "server.properties", content: "updated" });
    deleteServerFileMock = vi.fn().mockResolvedValue(undefined);
    uploadServerFileMock = vi.fn().mockResolvedValue({ name: "uploaded.txt", path: "uploaded.txt", is_dir: false, size: 5 });
    downloadServerFileMock = vi.fn().mockResolvedValue(new Blob(["png-bytes"], { type: "image/png" }));
    createServerCommitMock = vi.fn().mockResolvedValue({
      commit_id: "c".repeat(40),
      branch_name: "dev",
      files: ["server.properties"],
    });
    listLiveStateFilesMock = vi.fn().mockResolvedValue({
      items: [
        { name: "plugins", path: "/plugins", is_dir: true, size: 0, modified_at: 1_700_000_000, file_class: "C", is_dynamic_class_c: false, writable: false },
        { name: "whitelist.json", path: "/whitelist.json", is_dir: false, size: 2048, modified_at: 1_700_000_000, file_class: "C", is_dynamic_class_c: true, writable: true },
      ],
    });
    readLiveStateFileContentMock = vi.fn().mockResolvedValue({
      server_id: "srv-1",
      path: "/whitelist.json",
      content: "whitelist content",
      encoding: "utf-8",
      size: 17,
      is_dynamic_class_c: true,
    });
    writeLiveStateFileContentMock = vi.fn().mockResolvedValue({
      status: "ok",
      server_id: "srv-1",
      path: "/whitelist.json",
      rcon_flushed: true,
      rcon_reloaded: true,
      reload_command: "whitelist reload",
    });
    mkdirServerDirectoryMock = vi.fn().mockImplementation((_serverId, path) => {
      const name = path.split("/").pop();
      const newFolder: FileItem = { name, is_dir: true, size: 0, path };
      currentFileList.push(newFolder);
      return Promise.resolve(newFolder);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("ISS-044: opening a file shows actual file content, not a JSON wrapper", async () => {
    renderPage();
    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    fireEvent.click(screen.getByText("server.properties"));

    await waitFor(() => {
      const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
      expect(textarea.value).toBe("server-port=25565\nmotd=A Minecraft Server\nmax-players=20");
    });
    expect(readServerFileContentMock).toHaveBeenCalledWith("srv-1", "server.properties");
  });

  it("ISS-045: saving a file issues PUT request and keeps editor open", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    fireEvent.click(screen.getByText("server.properties"));

    const textarea = (await screen.findByRole("textbox")) as HTMLTextAreaElement;
    const saveButton = screen.getByRole("button", { name: /^save$/i });
    expect(saveButton).toBeDisabled();

    await user.clear(textarea);
    await user.type(textarea, "motd=Brand New Server");
    expect(screen.getByTestId("editor-unsaved-badge")).toBeInTheDocument();
    expect(saveButton).toBeEnabled();

    await user.click(saveButton);

    await waitFor(() => {
      expect(writeServerFileContentMock).toHaveBeenCalledWith(
        "srv-1",
        "server.properties",
        "motd=Brand New Server",
      );
    });

    // Editor stays open after save and clears dirty indicator
    expect(screen.getByText("Editing: server.properties")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByTestId("editor-unsaved-badge")).not.toBeInTheDocument();
    });
  });

  it("supports Ctrl+S save and unsaved-changes discard guard on Back/Cancel", async () => {
    const user = userEvent.setup();
    renderPage("srv-1", ["/servers/srv-1/files?file=server.properties"]);

    const textarea = (await screen.findByRole("textbox")) as HTMLTextAreaElement;
    await user.type(textarea, "\npvp=true");
    expect(screen.getByTestId("editor-unsaved-badge")).toBeInTheDocument();

    fireEvent.keyDown(textarea, { key: "s", ctrlKey: true });
    await waitFor(() => {
      expect(writeServerFileContentMock).toHaveBeenCalled();
    });

    // Make another edit and attempt Cancel -> ConfirmDialog guard
    await user.type(textarea, "\nview-distance=10");
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Discard unsaved changes?")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Keep Editing" }));
    expect(screen.getByText("Editing: server.properties")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^cancel$/i }));
    const confirmDialog = await screen.findByRole("dialog");
    await user.click(within(confirmDialog).getByRole("button", { name: "Discard" }));
    await waitFor(() => {
      expect(screen.queryByText("Editing: server.properties")).not.toBeInTheDocument();
    });
  });

  it("ISS-046: creating a folder via modal issues the correct full path", async () => {
    const user = userEvent.setup();
    currentFileList = [];
    renderPage();

    await user.click(await screen.findByRole("button", { name: /new folder/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Folder name"), "config");
    await user.click(within(dialog).getByRole("button", { name: /^create$/i }));

    await waitFor(() => {
      expect(mkdirServerDirectoryMock).toHaveBeenCalledWith("srv-1", "config");
    });
    expect(await screen.findByText("config")).toBeInTheDocument();
  });

  it("creates a new file via New File modal using PUT /content and opens editor", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /new file/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("File name"), "ops.json");
    await user.click(within(dialog).getByRole("button", { name: /create & edit/i }));

    await waitFor(() => {
      expect(writeServerFileContentMock).toHaveBeenCalledWith("srv-1", "ops.json", "");
    });
    expect(await screen.findByText("Editing: ops.json")).toBeInTheDocument();
  });

  it("ISS-050: opening an unlisted binary file renders binary fallback UI", async () => {
    currentFileList = [{ name: "custom.bin", is_dir: false, size: 2048, path: "custom.bin" }];
    readServerFileContentMock = vi.fn().mockResolvedValue({ path: "custom.bin", content: "", is_binary: true });
    renderPage();

    fireEvent.click(await screen.findByText("custom.bin"));
    expect(await screen.findByText("Binary File")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download file/i })).toBeInTheDocument();
  });

  it("renders inline image preview for server-icon.png and revokes object URL on unmount", async () => {
    const origCreate = URL.createObjectURL;
    const origRevoke = URL.revokeObjectURL;
    const createObjectUrlMock = vi.fn().mockReturnValue("blob:http://localhost/icon-1");
    const revokeObjectUrlMock = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { writable: true, configurable: true, value: createObjectUrlMock });
    Object.defineProperty(URL, "revokeObjectURL", { writable: true, configurable: true, value: revokeObjectUrlMock });

    try {
      currentFileList = [{ name: "server-icon.png", is_dir: false, size: 4096, path: "server-icon.png" }];
      const { unmount } = renderPage();

      fireEvent.click(await screen.findByText("server-icon.png"));
      expect(await screen.findByTestId("image-preview-card")).toBeInTheDocument();
      expect(screen.getByRole("img", { name: "server-icon.png" })).toHaveAttribute("src", "blob:http://localhost/icon-1");
      expect(downloadServerFileMock).toHaveBeenCalledWith("srv-1", "server-icon.png");
      expect(createObjectUrlMock).toHaveBeenCalled();

      unmount();
      expect(revokeObjectUrlMock).toHaveBeenCalledWith("blob:http://localhost/icon-1");
    } finally {
      Object.defineProperty(URL, "createObjectURL", { writable: true, configurable: true, value: origCreate });
      Object.defineProperty(URL, "revokeObjectURL", { writable: true, configurable: true, value: origRevoke });
    }
  });

  it("displays Modified column and formatted timestamps in file listing", async () => {
    renderPage();
    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Modified" })).toBeInTheDocument();
    expect(screen.getAllByText(/ago|just now/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders ForbiddenState for viewer role lacking canFiles permission", async () => {
    vi.spyOn(serversUtils, "useFleetPermissions").mockReturnValue({
      canCreate: false,
      canImport: false,
      canDelete: false,
      canPower: () => false,
      canConsole: () => false,
      canWrite: () => false,
      canFiles: () => false,
      canManagePlugins: () => false,
      canViewExposure: () => false,
    });

    renderPage();
    expect(await screen.findByText("Access Denied")).toBeInTheDocument();
    expect(listServerFilesMock).not.toHaveBeenCalled();
  });

  it("renders ErrorState with working Try Again retry button on list failure", async () => {
    listServerFilesMock.mockRejectedValueOnce(new Error("Network timeout"));
    renderPage();

    expect(await screen.findByText("Network timeout")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("server.properties")).toBeInTheDocument();
  });

  it("preserves backend 403 branch/Class-B error message in mutation toast", async () => {
    const user = userEvent.setup();
    const { ApiError } = await import("@/services/api");
    writeServerFileContentMock.mockRejectedValueOnce(
      new ApiError(403, "PERMISSION_DENIED", "Only Class-B configuration files can be edited on an Advanced branch"),
    );

    renderPage("srv-1", ["/servers/srv-1/files?file=random.txt&branch=dev"]);
    const textarea = await screen.findByRole("textbox");
    await user.type(textarea, "abc");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith(
        "error",
        "Failed to save file",
        "Only Class-B configuration files can be edited on an Advanced branch",
      );
    });
  });

  it("supports selection checkboxes on BOTH files and folders and bulk delete", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select server.properties" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select world" })).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Select all" }));
    await user.click(screen.getByRole("button", { name: /delete selected \(2\)/i }));

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(deleteServerFileMock).toHaveBeenCalledWith("srv-1", "server.properties");
      expect(deleteServerFileMock).toHaveBeenCalledWith("srv-1", "world");
    });
  });

  it("prompts overwrite confirmation when uploading or dropping an existing file", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("server.properties")).toBeInTheDocument();

    const dropzone = screen.getByTestId("files-dropzone");
    const dupFile = new File(["motd=new"], "server.properties", { type: "text/plain" });
    fireEvent.drop(dropzone, { dataTransfer: { files: [dupFile], types: ["Files"] } });

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Overwrite Existing Files?")).toBeInTheDocument();
    expect(uploadServerFileMock).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Overwrite" }));
    await waitFor(() => {
      expect(uploadServerFileMock).toHaveBeenCalledWith("srv-1", "", dupFile);
    });
  });

  it("guards double-deletion and keeps Cancel/Escape disabled while pending", async () => {
    let resolveDelete: () => void = () => {};
    deleteServerFileMock.mockImplementationOnce(() => new Promise<void>((resolve) => { resolveDelete = () => resolve(); }));
    renderPage();
    expect(await screen.findByText("server.properties")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    const dialog = screen.getByRole("dialog");
    const confirmBtn = within(dialog).getByRole("button", { name: "Delete" });
    const cancelBtn = within(dialog).getByRole("button", { name: "Cancel" });
    fireEvent.click(confirmBtn);

    await waitFor(() => expect(dialog).toHaveAttribute("aria-busy", "true"));
    expect(confirmBtn).toBeDisabled();
    expect(cancelBtn).toBeDisabled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await act(async () => { resolveDelete(); });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("enforces readOnly on main branch and non-main Live State (hiding RCON & Save)", async () => {
    const { unmount } = renderPage("srv-1", ["/servers/srv-1/files?file=server.properties&branch=main"]);
    const textarea = await screen.findByRole("textbox");
    expect(textarea).toHaveAttribute("readonly");
    expect(screen.getByTestId("editor-readonly-pill")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^save$/i })).not.toBeInTheDocument();
    unmount();

    renderPage(
      "srv-1",
      ["/servers/srv-1/files?view=live-state&file=%2Fwhitelist.json&branch=dev"],
      { branch: "dev", setBranch: vi.fn(), gitBacked: true },
    );
    const liveTextarea = await screen.findByRole("textbox");
    expect(liveTextarea).toHaveAttribute("readonly");
    expect(screen.queryByLabelText("RCON Reload Command")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save Live State" })).not.toBeInTheDocument();
  });

  it("Live State view supports search filtering, formatBytes, parent '..' row, and skips standard readServerFileContent", async () => {
    const user = userEvent.setup();
    renderPage("srv-1", ["/servers/srv-1/files?view=live-state&path=%2Fplugins"]);

    expect(await screen.findByText("whitelist.json")).toBeInTheDocument();
    expect(screen.getAllByText("2.0 KB").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/Read-Only Binary/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Navigate to parent directory" })).toBeInTheDocument();

    // Filter works in Live State
    const table = screen.getByRole("table");
    expect(within(table).getByText("plugins")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Filter current directory"), "white");
    expect(within(table).getByText("whitelist.json")).toBeInTheDocument();
    expect(within(table).queryByText("plugins")).not.toBeInTheDocument();

    // Open Live State file: must NOT fire readServerFileContent
    await user.click(screen.getByText("whitelist.json"));
    expect(await screen.findByText("Editing: whitelist.json")).toBeInTheDocument();
    expect(readLiveStateFileContentMock).toHaveBeenCalledWith("srv-1", "/whitelist.json");
    expect(readServerFileContentMock).not.toHaveBeenCalled();

    const saveBtn = screen.getByRole("button", { name: "Save Live State" });
    expect(saveBtn).toBeDisabled();
    await user.type(screen.getByRole("textbox"), "!");
    expect(saveBtn).toBeEnabled();
    await user.click(saveBtn);

    await waitFor(() => {
      expect(writeLiveStateFileContentMock).toHaveBeenCalledWith(
        "srv-1",
        expect.objectContaining({ path: "/whitelist.json", content: "whitelist content!", reload_command: null }),
      );
    });
  });

  it("displays liveStateContentError message instead of swallowing it", async () => {
    readLiveStateFileContentMock.mockRejectedValueOnce(new Error("Live state file exceeds 2 MB limit"));
    renderPage("srv-1", ["/servers/srv-1/files?view=live-state&file=%2Fwhitelist.json"]);

    expect(await screen.findByText("Failed to load file")).toBeInTheDocument();
    expect(screen.getByText("Live state file exceeds 2 MB limit")).toBeInTheDocument();
  });

  it("saves and commits branch changes through CommitBranchModal", async () => {
    const user = userEvent.setup();
    renderPage("srv-1", ["/servers/srv-1/files?branch=dev"]);

    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /save & commit/i }));

    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Commit message"), "Update properties");
    await user.click(within(dialog).getByRole("button", { name: /^commit$/i }));

    await waitFor(() => {
      expect(createServerCommitMock).toHaveBeenCalledWith("srv-1", {
        message: "Update properties",
        branch_name: "dev",
      });
    });
  });

  it("renders unified Logs & Crashes tab in Simple & Advanced modes and filters levels in LogFileViewer", async () => {
    const user = userEvent.setup();
    listServerFilesMock.mockImplementation((_srv: string, _path?: string, _branch?: string, scope?: string) => {
      if (scope === "logs") {
        return Promise.resolve([
          {
            name: "crash-2026-11-24.txt",
            path: "crash-reports/crash-2026-11-24.txt",
            is_dir: false,
            size: 1024,
            modified_at: new Date().toISOString(),
            editable: false,
            log_category: "crash_report",
          },
          {
            name: "latest.log",
            path: "logs/latest.log",
            is_dir: false,
            size: 2048,
            modified_at: new Date().toISOString(),
            editable: false,
            log_category: "server_log",
          },
          {
            name: "essentials.log",
            path: "plugins/Essentials/essentials.log",
            is_dir: false,
            size: 512,
            modified_at: new Date().toISOString(),
            editable: false,
            log_category: "plugin_log",
          },
        ]);
      }
      return Promise.resolve([...currentFileList]);
    });
    readServerFileContentMock.mockImplementation((_srv: string, path: string, _branch?: string, scope?: string) => {
      if (scope === "logs") {
        return Promise.resolve({
          path,
          content: [
            "[12:00:00] [Server thread/INFO]: [Essentials] Loaded plugin",
            "[12:00:01] [Server thread/WARN]: Low memory warning",
            "[12:00:02] [Server thread/ERROR]: NullPointerException in tick",
          ].join("\n"),
          is_binary: false,
          truncated: false,
        });
      }
      return Promise.resolve(mockFileContent);
    });

    renderPage("srv-1", ["/servers/srv-1/files?tab=logs"]);

    expect(await screen.findByText("All Files")).toBeInTheDocument();
    expect(screen.getByText("Logs & Crashes")).toBeInTheDocument();
    expect(await screen.findByText("crash-2026-11-24.txt")).toBeInTheDocument();
    expect(screen.getByText("latest.log")).toBeInTheDocument();
    expect(screen.getByText("essentials.log")).toBeInTheDocument();

    // Filter by Crash Reports category
    await user.click(screen.getByTestId("logs-category-crash_report"));
    expect(screen.getByText("crash-2026-11-24.txt")).toBeInTheDocument();
    expect(screen.queryByText("latest.log")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("logs-category-all"));
    await user.click(screen.getByText("latest.log"));

    expect(await screen.findByTestId("log-file-viewer")).toBeInTheDocument();
    expect(screen.getByTestId("log-viewer-readonly-badge")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^save$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^delete$/i })).not.toBeInTheDocument();

    // Level filtering in LogFileViewer
    expect(screen.getByText(/Loaded plugin/)).toBeInTheDocument();
    await user.click(screen.getByTestId("log-viewer-filter-error"));
    expect(screen.getByText(/NullPointerException in tick/)).toBeInTheDocument();
    expect(screen.queryByText(/Loaded plugin/)).not.toBeInTheDocument();
  });

  it("supports Split View toggle (default OFF -> ON) with side-by-side navigation and unsaved guard", async () => {
    const user = userEvent.setup();
    currentFileList = [
      ...mockFilesList,
      {
        name: "bukkit.yml",
        is_dir: false,
        size: 512,
        path: "bukkit.yml",
        modified_at: new Date().toISOString(),
        file_class: "B",
        editable: true,
      },
    ];
    readServerFileContentMock.mockImplementation((_srv: string, path: string) =>
      Promise.resolve({ path, content: `content of ${path}`, is_binary: false }),
    );

    renderPage();
    expect(await screen.findByText("server.properties")).toBeInTheDocument();

    // Default OFF
    expect(screen.queryByTestId("files-split-workspace")).not.toBeInTheDocument();
    const toggleBtn = screen.getByTestId("files-split-view-toggle");
    expect(toggleBtn).toHaveAttribute("aria-pressed", "false");

    // Toggle ON -> shows placeholder
    await user.click(toggleBtn);
    expect(screen.getByTestId("files-split-workspace")).toBeInTheDocument();
    expect(screen.getByTestId("files-split-placeholder")).toBeInTheDocument();

    // Open server.properties in right pane while left pane stays visible
    await user.click(screen.getByText("server.properties"));
    expect(await screen.findByText("Editing: server.properties")).toBeInTheDocument();
    expect(screen.getByText("bukkit.yml")).toBeInTheDocument();

    // Dirty edit + click bukkit.yml triggers unsaved-changes ConfirmDialog
    const textarea = await screen.findByLabelText("Code Editor");
    await user.type(textarea, "\nextra=1");
    await user.click(screen.getByText("bukkit.yml"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Discard unsaved changes?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Discard" }));

    expect(await screen.findByText("Editing: bukkit.yml")).toBeInTheDocument();

    // Clicking X on a clean file closes the file AND automatically exits Split View
    await user.click(screen.getByTestId("editor-close-btn"));
    await waitFor(() => {
      expect(screen.queryByTestId("files-split-workspace")).not.toBeInTheDocument();
    });
    expect(screen.queryByTestId("files-split-placeholder")).not.toBeInTheDocument();
    expect(screen.getByTestId("files-split-view-toggle")).toHaveAttribute("aria-pressed", "false");

    // Re-open Split View, make file dirty, click X -> ConfirmDialog guard, Discard exits Split View
    await user.click(screen.getByTestId("files-split-view-toggle"));
    await user.click(screen.getByText("server.properties"));
    const dirtyEditor = await screen.findByLabelText("Code Editor");
    await user.type(dirtyEditor, "\nunsaved=true");
    await user.click(screen.getByTestId("editor-close-btn"));

    const closeDialog = await screen.findByRole("dialog");
    expect(within(closeDialog).getByText("Discard unsaved changes?")).toBeInTheDocument();
    await user.click(within(closeDialog).getByRole("button", { name: "Keep Editing" }));
    expect(screen.getByTestId("files-split-workspace")).toBeInTheDocument();

    await user.click(screen.getByTestId("editor-close-btn"));
    const confirmCloseDialog = await screen.findByRole("dialog");
    await user.click(within(confirmCloseDialog).getByRole("button", { name: "Discard" }));
    await waitFor(() => {
      expect(screen.queryByTestId("files-split-workspace")).not.toBeInTheDocument();
    });
  });

  it("closes open log and exits Split View when clicking X in LogFileViewer", async () => {
    const user = userEvent.setup();
    listServerFilesMock.mockImplementation((_srv: string, _path?: string, _branch?: string, scope?: string) => {
      if (scope === "logs") {
        return Promise.resolve([
          {
            name: "latest.log",
            path: "logs/latest.log",
            is_dir: false,
            size: 512,
            modified_at: new Date().toISOString(),
            editable: false,
            log_category: "server_log",
          },
        ]);
      }
      return Promise.resolve([...currentFileList]);
    });
    readServerFileContentMock.mockImplementation((_srv: string, path: string, _branch?: string, scope?: string) => {
      if (scope === "logs") {
        return Promise.resolve({
          path,
          content: "[12:00:00] [Server thread/INFO]: Server started",
          is_binary: false,
        });
      }
      return Promise.resolve(mockFileContent);
    });

    renderPage("srv-1", ["/servers/srv-1/files?tab=logs"]);
    expect(await screen.findByText("latest.log")).toBeInTheDocument();

    await user.click(screen.getByTestId("files-split-view-toggle"));
    expect(screen.getByTestId("files-split-workspace")).toBeInTheDocument();

    await user.click(screen.getByText("latest.log"));
    expect(await screen.findByTestId("log-file-viewer")).toBeInTheDocument();

    await user.click(screen.getByTestId("log-viewer-close-btn"));
    await waitFor(() => {
      expect(screen.queryByTestId("files-split-workspace")).not.toBeInTheDocument();
    });
    expect(screen.queryByTestId("files-split-placeholder")).not.toBeInTheDocument();
    expect(screen.getByTestId("files-split-view-toggle")).toHaveAttribute("aria-pressed", "false");
  });

  it("blocks drag-and-drop on main branch and Logs & Crashes while allowing working branch upload", async () => {
    const { unmount } = renderPage(
      "srv-1",
      ["/servers/srv-1/files?branch=main"],
      { branch: "main", setBranch: vi.fn(), gitBacked: true },
    );
    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    const dropzoneMain = screen.getByTestId("files-dropzone");
    const file = new File(["enabled: true\n"], "app.yml", { type: "text/yaml" });
    fireEvent.dragEnter(dropzoneMain, { dataTransfer: { files: [file], types: ["Files"] } });
    expect(await screen.findByTestId("files-drop-blocked-notice")).toBeInTheDocument();
    fireEvent.drop(dropzoneMain, { dataTransfer: { files: [file], types: ["Files"] } });
    expect(uploadServerFileMock).not.toHaveBeenCalled();
    unmount();

    // Working branch allows upload
    renderPage(
      "srv-1",
      ["/servers/srv-1/files?branch=dev"],
      { branch: "dev", setBranch: vi.fn(), gitBacked: true },
    );
    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    const dropzoneDev = screen.getByTestId("files-dropzone");
    fireEvent.drop(dropzoneDev, { dataTransfer: { files: [file], types: ["Files"] } });
    await waitFor(() => {
      expect(uploadServerFileMock).toHaveBeenCalledWith("srv-1", "", file, "dev");
    });
  });

  it("hides 5-class badges and Git jargon in Simple Mode while keeping them in Advanced Mode", async () => {
    currentFileList = [
      { name: "paper.jar", is_dir: false, size: 1024, path: "paper.jar", file_class: "A", editable: false },
      { name: "server.properties", is_dir: false, size: 512, path: "server.properties", file_class: "B", editable: true },
      { name: "whitelist.json", is_dir: false, size: 256, path: "whitelist.json", file_class: "C", editable: true },
      { name: "cache.tmp", is_dir: false, size: 128, path: "cache.tmp", file_class: "E", editable: true },
    ];
    listServerFilesMock.mockImplementation((_srv: string, _path?: string, _branch?: string, scope?: string) => {
      if (scope === "logs") {
        return Promise.resolve([
          {
            name: "latest.log",
            path: "logs/latest.log",
            is_dir: false,
            size: 512,
            modified_at: new Date().toISOString(),
            editable: false,
            log_category: "server_log",
          },
        ]);
      }
      return Promise.resolve([...currentFileList]);
    });

    // Simple Mode: no Class A/B/C/E badges and no Git mention in Logs banner
    const { unmount: unmountSimple } = renderPage(
      "srv-1",
      ["/servers/srv-1/files"],
      { branch: "main", setBranch: vi.fn(), gitBacked: false, serverMode: "simple" },
    );
    expect(await screen.findByText("paper.jar")).toBeInTheDocument();
    expect(screen.queryByText("Class A")).not.toBeInTheDocument();
    expect(screen.queryByText("Class B")).not.toBeInTheDocument();
    expect(screen.queryByText("Class C")).not.toBeInTheDocument();
    expect(screen.queryByText("Class E")).not.toBeInTheDocument();
    unmountSimple();

    const { unmount: unmountSimpleLogs } = renderPage(
      "srv-1",
      ["/servers/srv-1/files?tab=logs"],
      { branch: "main", setBranch: vi.fn(), gitBacked: false, serverMode: "simple" },
    );
    expect(await screen.findByText("Read-only view of live runtime logs.")).toBeInTheDocument();
    expect(screen.queryByText(/Git/i)).not.toBeInTheDocument();
    unmountSimpleLogs();

    // Advanced Mode: Class A/C/E badges and Git banner copy are shown
    const { unmount: unmountAdv } = renderPage(
      "srv-1",
      ["/servers/srv-1/files?branch=dev"],
      { branch: "dev", setBranch: vi.fn(), gitBacked: true, serverMode: "advanced" },
    );
    expect(await screen.findByText("paper.jar")).toBeInTheDocument();
    expect(screen.getByText("Managed Binary")).toBeInTheDocument();
    expect(screen.getAllByText("Live Data").length).toBeGreaterThan(0);
    expect(screen.getByText("Class E")).toBeInTheDocument();
    unmountAdv();

    renderPage(
      "srv-1",
      ["/servers/srv-1/files?tab=logs&branch=dev"],
      { branch: "dev", setBranch: vi.fn(), gitBacked: true, serverMode: "advanced" },
    );
    expect(await screen.findByText("Read-only view of live runtime logs (not tracked in Git)")).toBeInTheDocument();
  });

  it("renders resizable Split View separator with 43% default, keyboard/drag clamping, double-click reset, and localStorage persistence", async () => {
    const user = userEvent.setup();
    const { unmount } = renderPage();
    expect(await screen.findByText("server.properties")).toBeInTheDocument();

    await user.click(screen.getByTestId("files-split-view-toggle"));
    const workspace = screen.getByTestId("files-split-workspace");
    const leftPane = screen.getByTestId("files-split-left-pane");
    const separator = screen.getByRole("separator", {
      name: "Resize file explorer and editor panes",
    });

    expect(separator).toHaveAttribute("aria-orientation", "vertical");
    expect(separator).toHaveAttribute("aria-valuemin", "26");
    expect(separator).toHaveAttribute("aria-valuemax", "68");
    expect(separator).toHaveAttribute("aria-valuenow", "43");
    expect(leftPane).toHaveStyle({ width: "43%" });

    // Keyboard ArrowRight / ArrowLeft / Home
    fireEvent.keyDown(separator, { key: "ArrowRight" });
    expect(separator).toHaveAttribute("aria-valuenow", "45");
    expect(leftPane).toHaveStyle({ width: "45%" });
    expect(window.localStorage.getItem("onx_files_split_ratio")).toBe("45");

    fireEvent.keyDown(separator, { key: "ArrowLeft" });
    expect(separator).toHaveAttribute("aria-valuenow", "43");

    // Pointer drag with clamping (beyond 68% max -> 68%, below 26% min -> 26%)
    vi.spyOn(workspace, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 1000,
      bottom: 500,
      width: 1000,
      height: 500,
      toJSON: () => ({}),
    });
    fireEvent.pointerDown(separator, { button: 0, clientX: 430 });
    fireEvent.pointerMove(window, { clientX: 850 });
    expect(separator).toHaveAttribute("aria-valuenow", "68");
    expect(leftPane).toHaveStyle({ width: "68%" });

    fireEvent.pointerMove(window, { clientX: 100 });
    expect(separator).toHaveAttribute("aria-valuenow", "26");
    expect(leftPane).toHaveStyle({ width: "26%" });

    fireEvent.pointerMove(window, { clientX: 520 });
    fireEvent.pointerUp(window);
    expect(separator).toHaveAttribute("aria-valuenow", "52");
    expect(window.localStorage.getItem("onx_files_split_ratio")).toBe("52");

    // Persists across remount
    unmount();
    renderPage();
    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    await user.click(screen.getByTestId("files-split-view-toggle"));
    const remountedSeparator = screen.getByRole("separator", {
      name: "Resize file explorer and editor panes",
    });
    expect(remountedSeparator).toHaveAttribute("aria-valuenow", "52");
    expect(screen.getByTestId("files-split-left-pane")).toHaveStyle({ width: "52%" });

    // Double-click resets back to default 43%
    fireEvent.doubleClick(remountedSeparator);
    expect(remountedSeparator).toHaveAttribute("aria-valuenow", "43");
    expect(screen.getByTestId("files-split-left-pane")).toHaveStyle({ width: "43%" });
    expect(window.localStorage.getItem("onx_files_split_ratio")).toBe("43");

    // Home key also resets to 43% after nudging
    fireEvent.keyDown(remountedSeparator, { key: "ArrowRight" });
    expect(remountedSeparator).toHaveAttribute("aria-valuenow", "45");
    fireEvent.keyDown(remountedSeparator, { key: "Home" });
    expect(remountedSeparator).toHaveAttribute("aria-valuenow", "43");
  });

  it("opens rows with editable=false or writable=false strictly in read-only mode", async () => {
    const user = userEvent.setup();
    currentFileList = [
      {
        name: "locked.conf",
        path: "locked.conf",
        is_dir: false,
        size: 128,
        editable: false,
      },
    ];
    readServerFileContentMock.mockResolvedValueOnce({
      path: "locked.conf",
      content: "readonly=true",
      is_binary: false,
    });

    const { unmount } = renderPage();
    await user.click(await screen.findByText("locked.conf"));

    const branchTextarea = await screen.findByRole("textbox");
    expect(branchTextarea).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: /^save$/i })).not.toBeInTheDocument();
    unmount();

    listLiveStateFilesMock.mockResolvedValueOnce({
      items: [
        {
          name: "world-data.json",
          path: "/world/world-data.json",
          is_dir: false,
          size: 64,
          modified_at: 1_700_000_000,
          file_class: "C",
          is_dynamic_class_c: true,
          writable: false,
        },
      ],
    });
    readLiveStateFileContentMock.mockResolvedValueOnce({
      server_id: "srv-1",
      path: "/world/world-data.json",
      content: '{"ok":true}',
      encoding: "utf-8",
      size: 11,
      is_dynamic_class_c: true,
    });

    renderPage("srv-1", ["/servers/srv-1/files?view=live-state"]);
    await user.click(await screen.findByText("world-data.json"));
    const liveTextarea = await screen.findByRole("textbox");
    expect(liveTextarea).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Save Live State" })).not.toBeInTheDocument();
  });
});
