import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { UsersPermissionsSection } from "./UsersPermissionsSection";

const mockListUsers = vi.fn();
const mockGetMe = vi.fn();
const mockListServers = vi.fn();
const mockAdminCreateUser = vi.fn();
const mockUpdateUserAccess = vi.fn();
const mockUpdateUser = vi.fn();
const mockDeleteUser = vi.fn();
const mockListInvites = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    listUsers: mockListUsers,
    getMe: mockGetMe,
    listServers: mockListServers,
    adminCreateUser: mockAdminCreateUser,
    updateUserAccess: mockUpdateUserAccess,
    updateUser: mockUpdateUser,
    deleteUser: mockDeleteUser,
    listInvites: mockListInvites,
  }),
}));

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
}));

const SAMPLE_SERVERS = [
  {
    server_id: "srv-1",
    name: "Survival SMP",
    status: "RUNNING",
    minecraft_version: "1.21.1",
  },
  {
    server_id: "srv-2",
    name: "Creative Plot",
    status: "STOPPED",
    minecraft_version: "1.20.4",
  },
];

const SAMPLE_USERS = [
  {
    user_id: "u-owner",
    username: "boss",
    email: "boss@example.com",
    display_name: "Instance Owner",
    is_active: true,
    roles: ["owner"],
    global_role: "owner",
    all_servers_access: true,
    assigned_server_ids: [],
    denied_permissions: [],
    created_at: "2026-01-01T00:00:00Z",
    last_login_at: null,
  },
  {
    user_id: "u-admin",
    username: "secadmin",
    email: "admin@example.com",
    display_name: "Sec Admin",
    is_active: true,
    roles: ["admin"],
    global_role: "admin",
    all_servers_access: true,
    assigned_server_ids: [],
    denied_permissions: [],
    created_at: "2026-01-02T00:00:00Z",
    last_login_at: null,
  },
  {
    user_id: "u-sadmin",
    username: "modop",
    email: "modop@example.com",
    display_name: "Server Operator",
    is_active: true,
    roles: ["server_admin"],
    global_role: "server_admin",
    all_servers_access: false,
    assigned_server_ids: ["srv-1"],
    denied_permissions: ["power"],
    created_at: "2026-01-03T00:00:00Z",
    last_login_at: null,
  },
  {
    user_id: "u-viewer",
    username: "watcher",
    email: "watcher@example.com",
    display_name: "Read Only Viewer",
    is_active: true,
    roles: ["viewer"],
    global_role: "viewer",
    all_servers_access: false,
    assigned_server_ids: ["srv-2"],
    denied_permissions: ["files"],
    created_at: "2026-01-04T00:00:00Z",
    last_login_at: null,
  },
];

function renderSection(initialSubTab?: "users" | "invitations") {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 0,
        gcTime: 0,
      },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <UsersPermissionsSection initialSubTab={initialSubTab} />
    </QueryClientProvider>,
  );
}

describe("UsersPermissionsSection (RBAC v2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListUsers.mockResolvedValue(SAMPLE_USERS);
    mockListServers.mockResolvedValue(SAMPLE_SERVERS);
    mockListInvites.mockResolvedValue([]);
    mockGetMe.mockResolvedValue(SAMPLE_USERS[0]); // Owner by default
    mockAdminCreateUser.mockResolvedValue({
      ...SAMPLE_USERS[2],
      user_id: "u-new",
      username: "alex",
      display_name: "Alex",
    });
    mockUpdateUserAccess.mockResolvedValue({
      ...SAMPLE_USERS[2],
      denied_permissions: [],
    });
    mockUpdateUser.mockResolvedValue({
      ...SAMPLE_USERS[3],
      is_active: false,
    });
    mockDeleteUser.mockResolvedValue({ success: true });
  });

  it("enforces Admin vs Owner hierarchy on Owner rows and role choices", async () => {
    mockGetMe.mockResolvedValue(SAMPLE_USERS[1]); // Logged in as Admin (non-Owner)
    renderSection();

    await waitFor(() => expect(screen.getByText("Instance Owner")).toBeInTheDocument());

    const ownerRow = screen.getByText("Instance Owner").closest("tr")!;
    const ownerEditBtn = within(ownerRow).getByRole("button", { name: /Edit Access/i });
    const ownerDisableBtn = within(ownerRow).getByRole("button", { name: /Disable/i });
    const ownerDeleteBtn = within(ownerRow).getByRole("button", { name: /Delete/i });

    expect(ownerEditBtn).toBeDisabled();
    expect(ownerEditBtn).toHaveAttribute("title", "Only an Owner can edit an Owner account");
    expect(ownerDisableBtn).toBeDisabled();
    expect(ownerDeleteBtn).toBeDisabled();

    const sadminRow = screen.getByText("Server Operator").closest("tr")!;
    expect(within(sadminRow).getByRole("button", { name: /Edit Access/i })).not.toBeDisabled();

    // Open Add User modal: Admin should NOT see Owner radio card
    fireEvent.click(screen.getByRole("button", { name: /Add User/i }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("radio", { name: /Viewer/i })).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: /Server Admin/i })).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: /Administrator/i })).toBeInTheDocument();
    expect(within(dialog).queryByRole("radio", { name: /^Owner/i })).not.toBeInTheDocument();
  });

  it("allows Owner to create a Server Admin with multi-server scope and denied capabilities", async () => {
    renderSection();
    await waitFor(() => expect(screen.getByText("Server Operator")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Add User/i }));
    const dialog = screen.getByRole("dialog");

    // Owner sees all 4 roles including Owner
    expect(within(dialog).getByRole("radio", { name: /^Owner/i })).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText(/Username \*/i), {
      target: { value: "alex" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Display Name/i), {
      target: { value: "Alex Op" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Email/i), {
      target: { value: "alex@example.com" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Temporary Password/i), {
      target: { value: "strong-pass-123" },
    });

    fireEvent.click(within(dialog).getByRole("radio", { name: /Server Admin/i }));
    fireEvent.click(within(dialog).getByLabelText(/Survival SMP/i));
    fireEvent.click(within(dialog).getByLabelText(/Creative Plot/i));
    fireEvent.click(within(dialog).getByLabelText(/Power Control/i));

    fireEvent.click(within(dialog).getByRole("button", { name: /Create User/i }));

    await waitFor(() => expect(mockAdminCreateUser).toHaveBeenCalledTimes(1));
    expect(mockAdminCreateUser).toHaveBeenCalledWith({
      username: "alex",
      display_name: "Alex Op",
      email: "alex@example.com",
      password: "strong-pass-123",
      role: "server_admin",
      all_servers_access: false,
      server_ids: ["srv-1", "srv-2"],
      denied_permissions: ["power"],
      is_active: true,
    });
  });

  it("opens Edit Access modal pre-populated and calls PUT /users/{id}/access on save", async () => {
    renderSection();
    await waitFor(() => expect(screen.getByText("Read Only Viewer")).toBeInTheDocument());

    const viewerRow = screen.getByText("Read Only Viewer").closest("tr")!;
    fireEvent.click(within(viewerRow).getByRole("button", { name: /Edit Access/i }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/Edit Access: Read Only Viewer/i)).toBeInTheDocument();

    // Promote viewer -> server_admin with all_servers_access enabled and clear files denial
    fireEvent.click(within(dialog).getByRole("radio", { name: /Server Admin/i }));
    fireEvent.click(
      within(dialog).getByLabelText(/Grant access to all servers \(current & future\)/i),
    );

    fireEvent.click(within(dialog).getByRole("button", { name: /Save Permissions/i }));

    await waitFor(() => expect(mockUpdateUserAccess).toHaveBeenCalledTimes(1));
    expect(mockUpdateUserAccess).toHaveBeenCalledWith("u-viewer", {
      role: "server_admin",
      all_servers_access: true,
      server_ids: [],
      denied_permissions: ["files"],
      is_active: true,
    });
  });

  it("supports Disable user, Delete confirmation dialog, and Invitations sub-tab switch", async () => {
    renderSection();
    await waitFor(() => expect(screen.getByText("Read Only Viewer")).toBeInTheDocument());

    const viewerRow = screen.getByText("Read Only Viewer").closest("tr")!;
    fireEvent.click(within(viewerRow).getByRole("button", { name: /Disable/i }));

    await waitFor(() =>
      expect(mockUpdateUser).toHaveBeenCalledWith("u-viewer", { is_active: false }),
    );

    fireEvent.click(within(viewerRow).getByRole("button", { name: /Delete/i }));
    const confirmBtn = await screen.findByRole("button", { name: /Delete User/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => expect(mockDeleteUser).toHaveBeenCalledWith("u-viewer"));

    // Switch to Invitations sub-tab
    fireEvent.click(screen.getByRole("button", { name: /^Invitations$/i }));
    await waitFor(() => expect(mockListInvites).toHaveBeenCalled());
  });

  it("renders Permission Required state and skips user fetch for Viewer/Server Admin", async () => {
    mockGetMe.mockResolvedValue(SAMPLE_USERS[3]); // Viewer
    renderSection();

    await waitFor(() =>
      expect(screen.getByText(/Permission Required/i)).toBeInTheDocument(),
    );
    expect(mockListUsers).not.toHaveBeenCalled();
  });

  it("pins Add User modal header/footer outside scrollable body and shows read-only Viewer capability copy", async () => {
    renderSection();
    await waitFor(() => expect(screen.getByText("Server Operator")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Add User/i }));
    const dialog = screen.getByRole("dialog");
    const body = within(dialog).getByTestId("modal-body");
    const footer = within(dialog).getByTestId("modal-footer");

    expect(dialog).toHaveClass("max-h-[calc(100dvh-2rem)]", "flex-col", "overflow-hidden");
    expect(body).toHaveClass("overflow-y-auto", "flex-1", "min-h-0");
    expect(footer).toContainElement(within(dialog).getByRole("button", { name: /Cancel/i }));
    expect(footer).toContainElement(within(dialog).getByRole("button", { name: /Create User/i }));
    expect(body).not.toContainElement(within(dialog).getByRole("button", { name: /Create User/i }));

    // Defaults to Viewer: capability descriptions must be strictly read-only
    expect(
      within(dialog).getByText("Read live and historical console output (commands disabled)"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("View server logs and crash reports (read-only)"),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText(/send server commands/i)).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/edit, upload files/i)).not.toBeInTheDocument();

    // Switching to Server Admin restores writable capability descriptions
    fireEvent.click(within(dialog).getByRole("radio", { name: /Server Admin/i }));
    expect(
      within(dialog).getByText("Stream console logs and send server commands"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("Browse, edit, upload files and read server logs"),
    ).toBeInTheDocument();
  });
});
