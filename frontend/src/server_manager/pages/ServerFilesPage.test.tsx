import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerFilesPage } from "./ServerFilesPage";
import type { FileItem, FileContentResponse } from "@/server_manager/types";

const mockFilesList: FileItem[] = [
  { name: "server.properties", is_dir: false, size: 1024, path: "server.properties" },
  { name: "world", is_dir: true, size: 0, path: "world" },
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
let createServerCommitMock: ReturnType<typeof vi.fn>;

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    listServerFiles: listServerFilesMock,
    readServerFileContent: readServerFileContentMock,
    writeServerFileContent: writeServerFileContentMock,
    mkdirServerDirectory: mkdirServerDirectoryMock,
    deleteServerFile: (...args: unknown[]) => deleteServerFileMock(...args),
    uploadServerFile: vi.fn().mockResolvedValue({}),
    downloadServerFile: vi.fn().mockResolvedValue(new Blob(["data"])),
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

function renderPage(serverId = "srv-1", initialEntries = [`/servers/${serverId}/files`]) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>
        <Routes>
          <Route path="/servers/:serverId/files" element={<ServerFilesPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ServerFilesPage (ISS-044, ISS-045, ISS-046)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentFileList = [...mockFilesList];
    listServerFilesMock = vi.fn().mockImplementation(() => Promise.resolve([...currentFileList]));
    readServerFileContentMock = vi.fn().mockResolvedValue(mockFileContent);
    writeServerFileContentMock = vi.fn().mockResolvedValue({ path: "server.properties", content: "updated" });
    deleteServerFileMock = vi.fn().mockResolvedValue(undefined);
    createServerCommitMock = vi.fn().mockResolvedValue({
      commit_id: "c".repeat(40),
      branch_name: "dev",
      files: ["server.properties"],
    });
    mkdirServerDirectoryMock = vi.fn().mockImplementation((_serverId, path) => {
      const name = path.split("/").pop();
      const newFolder: FileItem = { name, is_dir: true, size: 0, path };
      currentFileList.push(newFolder);
      return Promise.resolve(newFolder);
    });
  });

  it("ISS-044: opening a file shows actual file content, not a JSON wrapper", async () => {
    renderPage();

    // File list loads
    expect(await screen.findByText("server.properties")).toBeInTheDocument();

    // Click file to edit
    const fileRow = screen.getByText("server.properties");
    fireEvent.click(fileRow);

    // Editor opens and displays actual content
    await waitFor(() => {
      const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
      expect(textarea).toBeInTheDocument();
      expect(textarea.value).toBe("server-port=25565\nmotd=A Minecraft Server\nmax-players=20");
      // Explicitly verify no JSON envelope corruption
      expect(textarea.value).not.toContain('{"path"');
      expect(textarea.value).not.toContain('{"content"');
    });

    expect(readServerFileContentMock).toHaveBeenCalledWith("srv-1", "server.properties");
  });

  it("ISS-045: saving a file issues PUT request and succeeds", async () => {
    const user = userEvent.setup();
    renderPage();

    // Open file
    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    fireEvent.click(screen.getByText("server.properties"));

    const textarea = (await screen.findByRole("textbox")) as HTMLTextAreaElement;
    expect(textarea.value).toBe(mockFileContent.content);

    // Edit content
    await user.clear(textarea);
    await user.type(textarea, "motd=Brand New Server");

    // Click Save
    const saveButton = screen.getByRole("button", { name: /save/i });
    await user.click(saveButton);

    // Assert write was called with updated content
    await waitFor(() => {
      expect(writeServerFileContentMock).toHaveBeenCalledWith(
        "srv-1",
        "server.properties",
        "motd=Brand New Server",
      );
    });
  });

  it("ISS-046: creating a folder issues the correct full path and appears in listing", async () => {
    const user = userEvent.setup();
    currentFileList = [];
    renderPage();

    // Open new folder input
    const newFolderBtn = await screen.findByRole("button", { name: /new folder/i });
    await user.click(newFolderBtn);

    const input = screen.getByPlaceholderText("Folder name");
    await user.type(input, "config");

    const createBtn = screen.getByRole("button", { name: /^create$/i });
    await user.click(createBtn);

    // Verify mkdirServerDirectory called with full target path client-side
    await waitFor(() => {
      expect(mkdirServerDirectoryMock).toHaveBeenCalledWith("srv-1", "config");
    });

    // Folder appears in listing
    expect(await screen.findByText("config")).toBeInTheDocument();
  });

  it("ISS-046: creating a nested folder in subdirectory combines currentPath and folderName", async () => {
    const user = userEvent.setup();
    currentFileList = [{ name: "plugins", is_dir: true, size: 0, path: "plugins" }];
    renderPage();

    // Navigate into plugins directory
    const pluginsDir = await screen.findByText("plugins");
    fireEvent.click(pluginsDir);

    // Open new folder
    const newFolderBtn = await screen.findByRole("button", { name: /new folder/i });
    await user.click(newFolderBtn);

    const input = screen.getByPlaceholderText("Folder name");
    await user.type(input, "Essentials");

    const createBtn = screen.getByRole("button", { name: /^create$/i });
    await user.click(createBtn);

    await waitFor(() => {
      expect(mkdirServerDirectoryMock).toHaveBeenCalledWith("srv-1", "plugins/Essentials");
    });
  });

  it("ISS-050: opening an unlisted binary file renders binary fallback UI instead of crashing", async () => {
    currentFileList = [{ name: "custom.bin", is_dir: false, size: 2048, path: "custom.bin" }];
    readServerFileContentMock = vi.fn().mockResolvedValue({
      path: "custom.bin",
      content: "",
      is_binary: true,
    });
    renderPage();

    expect(await screen.findByText("custom.bin")).toBeInTheDocument();
    fireEvent.click(screen.getByText("custom.bin"));

    // Fallback binary banner displayed
    expect(await screen.findByText("Binary File")).toBeInTheDocument();
    expect(
      screen.getByText(/This file cannot be displayed or edited as text because it contains binary data/i)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download file/i })).toBeInTheDocument();
    // Save button should not be shown for binary file
    expect(screen.queryByRole("button", { name: /^save$/i })).not.toBeInTheDocument();
  });

  it("ISS-051: editor mounts with syntax highlighting container and line numbers", async () => {
    renderPage();

    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    fireEvent.click(screen.getByText("server.properties"));

    // CodeEditor container mounts
    expect(await screen.findByTestId("code-editor")).toBeInTheDocument();
    // Status bar displays detected language and line count
    expect(screen.getByText("Properties")).toBeInTheDocument();
    expect(screen.getByText("3 lines")).toBeInTheDocument();
  });

  it("automatically opens file editor when file query parameter is present in URL", async () => {
    renderPage("srv-1", ["/servers/srv-1/files?file=server.properties"]);

    // Editor should open directly without clicking on the file list item
    await waitFor(() => {
      const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
      expect(textarea).toBeInTheDocument();
      expect(textarea.value).toBe("server-port=25565\nmotd=A Minecraft Server\nmax-players=20");
    });

    expect(readServerFileContentMock).toHaveBeenCalledWith("srv-1", "server.properties");
  });

  it("renders error state when reading file content fails instead of showing blank editor", async () => {
    readServerFileContentMock = vi.fn().mockRejectedValue(new Error("Permission Denied"));
    renderPage("srv-1", ["/servers/srv-1/files?file=server.properties"]);

    expect(await screen.findByText("Failed to load file")).toBeInTheDocument();
    expect(screen.getByText("Permission Denied")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /back to files/i })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("renders root breadcrumb and updates breadcrumb for subdirectories", async () => {
    currentFileList = [{ name: "mods", is_dir: true, size: 0, path: "mods" }];
    renderPage("srv-1", ["/servers/srv-1/files?path=mods"]);

    expect(await screen.findByText("root")).toBeInTheDocument();
    expect(screen.getAllByText("mods").length).toBeGreaterThanOrEqual(1);
    expect(listServerFilesMock).toHaveBeenCalledWith("srv-1", "mods");
  });

  it("navigating into a folder updates listing and displays nested breadcrumbs", async () => {
    currentFileList = [{ name: "mods", is_dir: true, size: 0, path: "mods" }];
    renderPage();

    expect(await screen.findByText("root")).toBeInTheDocument();
    const folder = await screen.findByText("mods");
    fireEvent.click(folder);

    expect(listServerFilesMock).toHaveBeenCalledWith("srv-1", "mods");
  });

  it("clicking breadcrumb link in editor exits editor and navigates to directory", async () => {
    currentFileList = [
      { name: "config.yml", is_dir: false, size: 100, path: "mods/config.yml" },
    ];
    readServerFileContentMock = vi.fn().mockResolvedValue({
      path: "mods/config.yml",
      content: "enabled: true",
      is_binary: false,
    });
    renderPage("srv-1", ["/servers/srv-1/files?file=mods/config.yml"]);

    expect(await screen.findByText("Editing: config.yml")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Editor breadcrumb" })).toBeInTheDocument();

    // Click 'mods' in editor breadcrumb
    const modsBtn = screen.getByRole("button", { name: "mods" });
    fireEvent.click(modsBtn);

    // Editor automatically closes and displays folder listing
    await waitFor(() => {
      expect(screen.queryByText("Editing: config.yml")).not.toBeInTheDocument();
    });
    expect(listServerFilesMock).toHaveBeenCalledWith("srv-1", "mods");
  });

  it("clicking Cancel button in editor exits editing and returns to files", async () => {
    renderPage("srv-1", ["/servers/srv-1/files?file=server.properties"]);

    expect(await screen.findByText("Editing: server.properties")).toBeInTheDocument();
    const cancelBtn = screen.getByRole("button", { name: /cancel/i });
    fireEvent.click(cancelBtn);

    await waitFor(() => {
      expect(screen.queryByText("Editing: server.properties")).not.toBeInTheDocument();
    });
    expect(screen.getByText("server.properties")).toBeInTheDocument();
  });

  it("guards against double-deletion and disables Confirm and Cancel buttons while deleteMutation is pending", async () => {
    let resolveDelete: () => void = () => {};
    deleteServerFileMock.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveDelete = () => resolve();
    }));

    renderPage();
    expect(await screen.findByText("server.properties")).toBeInTheDocument();

    const deleteButtons = screen.getAllByRole("button", { name: "Delete" });
    fireEvent.click(deleteButtons[0]);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Delete File")).toBeInTheDocument();

    const confirmBtn = within(dialog).getByRole("button", { name: "Delete" });
    const cancelBtn = within(dialog).getByRole("button", { name: "Cancel" });

    // Click confirm to start mutation
    fireEvent.click(confirmBtn);

    // Dialog enters isPending state
    await waitFor(() => {
      expect(dialog).toHaveAttribute("aria-busy", "true");
    });
    expect(confirmBtn).toBeDisabled();
    expect(cancelBtn).toBeDisabled();
    expect(confirmBtn).toHaveTextContent("Deleting...");

    // Escape is ignored while pending
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    // Resolve deletion
    await act(async () => {
      resolveDelete();
    });

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("omits LAST MODIFIED column because api and backend do not return modified time", async () => {
    renderPage();
    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    expect(screen.queryByText(/last modified/i)).not.toBeInTheDocument();
  });

  it("supports row selection checkboxes and bulk delete using existing api.deleteServerFile", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    expect(await screen.findByText("world")).toBeInTheDocument();

    const selectFileCheckbox = screen.getByRole("checkbox", { name: "Select server.properties" });
    await user.click(selectFileCheckbox);

    const bulkDeleteBtn = screen.getByRole("button", { name: /delete selected/i });
    expect(bulkDeleteBtn).toBeInTheDocument();
    await user.click(bulkDeleteBtn);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Delete Selected Items")).toBeInTheDocument();

    const confirmBtn = within(dialog).getByRole("button", { name: "Delete" });
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(deleteServerFileMock).toHaveBeenCalledWith("srv-1", "server.properties");
    });
  });

  it("renders folder row with open and delete action buttons", async () => {
    renderPage();
    expect(await screen.findByText("world")).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "Open world" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete world" })).toBeInTheDocument();
  });

  it("scopes file listing and content reads to the selected branch", async () => {
    renderPage("srv-1", ["/servers/srv-1/files?branch=dev"]);

    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    expect(screen.getByTestId("branch-context-banner")).toHaveTextContent("dev");
    expect(listServerFilesMock).toHaveBeenCalledWith("srv-1", "", "dev");

    fireEvent.click(screen.getByText("server.properties"));
    expect(await screen.findByText("Editing: server.properties")).toBeInTheDocument();
    await waitFor(() => {
      expect(readServerFileContentMock).toHaveBeenCalledWith(
        "srv-1",
        "server.properties",
        "dev",
      );
    });
  });

  it("writes branch-scoped file content with the branch parameter", async () => {
    const user = userEvent.setup();
    renderPage("srv-1", ["/servers/srv-1/files?branch=dev"]);

    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    fireEvent.click(screen.getByText("server.properties"));

    const textarea = (await screen.findByRole("textbox")) as HTMLTextAreaElement;
    await user.clear(textarea);
    await user.type(textarea, "motd=Branch Edit");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(writeServerFileContentMock).toHaveBeenCalledWith(
        "srv-1",
        "server.properties",
        "motd=Branch Edit",
        "dev",
      );
    });
  });

  it("saves and commits branch changes through the commit endpoint", async () => {
    const user = userEvent.setup();
    renderPage("srv-1", ["/servers/srv-1/files?branch=dev"]);

    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /save & commit/i }));

    const dialog = await screen.findByRole("dialog");
    await user.type(
      within(dialog).getByLabelText("Commit message"),
      "Update properties",
    );
    await user.click(within(dialog).getByRole("button", { name: /^commit$/i }));

    await waitFor(() => {
      expect(createServerCommitMock).toHaveBeenCalledWith("srv-1", {
        message: "Update properties",
        branch_name: "dev",
      });
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("marks main as read-only and hides mutating controls", async () => {
    renderPage("srv-1", ["/servers/srv-1/files?branch=main"]);

    expect(await screen.findByText("server.properties")).toBeInTheDocument();
    expect(screen.getByTestId("branch-context-banner")).toHaveTextContent(/read-only/i);
    expect(screen.queryByRole("button", { name: /new folder/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /upload file/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save & commit/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });
});
