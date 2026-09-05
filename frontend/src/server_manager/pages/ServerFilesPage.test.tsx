import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    listServerFiles: listServerFilesMock,
    readServerFileContent: readServerFileContentMock,
    writeServerFileContent: writeServerFileContentMock,
    mkdirServerDirectory: mkdirServerDirectoryMock,
    deleteServerFile: vi.fn().mockResolvedValue(undefined),
    uploadServerFile: vi.fn().mockResolvedValue({}),
    downloadServerFile: vi.fn().mockResolvedValue(new Blob(["data"])),
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
});
