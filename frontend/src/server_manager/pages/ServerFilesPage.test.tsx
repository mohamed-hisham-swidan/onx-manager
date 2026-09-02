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

function renderPage(serverId = "srv-1") {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/servers/${serverId}/files`]}>
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
});
