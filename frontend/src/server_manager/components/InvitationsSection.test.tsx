import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { InvitationsSection } from "./InvitationsSection";

const mockListInvites = vi.fn();
const mockGetMe = vi.fn();
const mockListServers = vi.fn();
const mockCreateInvite = vi.fn();
const mockRevokeInvite = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    listInvites: mockListInvites,
    getMe: mockGetMe,
    listServers: mockListServers,
    createInvite: mockCreateInvite,
    revokeInvite: mockRevokeInvite,
  }),
}));

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
}));

function renderComponent() {
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
      <InvitationsSection />
    </QueryClientProvider>,
  );
}

async function renderAndOpenModal() {
  renderComponent();
  await waitFor(() => expect(mockListInvites).toHaveBeenCalled());
  const btn = await screen.findByRole("button", { name: /new invite/i });
  fireEvent.click(btn);
}

describe("InvitationsSection (RBAC v2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListInvites.mockResolvedValue([]);
    mockGetMe.mockResolvedValue({
      user_id: "u1",
      email: "owner@example.com",
      display_name: "Owner",
      is_active: true,
      roles: ["owner"],
      global_role: "owner",
      created_at: "2026-01-01T00:00:00Z",
      last_login_at: null,
    });
    mockListServers.mockResolvedValue([
      {
        server_id: "srv-1",
        name: "Survival Server",
        status: "RUNNING",
        minecraft_version: "1.21.1",
      },
      {
        server_id: "srv-2",
        name: "Creative Server",
        status: "STOPPED",
        minecraft_version: "1.20.4",
      },
    ]);
    mockCreateInvite.mockResolvedValue({
      invite_id: "inv-123",
      token: "mcis_secret_token_123",
      token_prefix: "mcis_secre",
      email: null,
      role: "viewer",
      global_role: "viewer",
      server_id: null,
      server_ids: [],
      server_role: "viewer",
      status: "ACTIVE",
      max_uses: 1,
      expires_at: null,
    });
  });

  describe("4-Tier role selector", () => {
    it("1. Owner sees all 4 canonical roles and defaults to Viewer", async () => {
      await renderAndOpenModal();

      const radios = await screen.findAllByRole("radio");
      expect(radios.map((r) => r.textContent)).toEqual([
        expect.stringContaining("Viewer"),
        expect.stringContaining("Server Admin"),
        expect.stringContaining("Administrator"),
        expect.stringContaining("Owner"),
      ]);
      expect(radios[0]).toHaveAttribute("aria-checked", "true");
    });

    it("2. Admin sees 3 roles (Viewer, Server Admin, Administrator — no Owner)", async () => {
      mockGetMe.mockResolvedValue({
        user_id: "u2",
        roles: ["admin"],
        global_role: "admin",
      });
      await renderAndOpenModal();

      const radios = await screen.findAllByRole("radio");
      expect(radios).toHaveLength(3);
      expect(screen.queryByRole("radio", { name: /^Owner/i })).not.toBeInTheDocument();
    });

    it("3. Server Admin sees Permission Required state", async () => {
      mockGetMe.mockResolvedValue({
        user_id: "u3",
        roles: ["server_admin"],
        global_role: "server_admin",
      });
      renderComponent();

      expect(await screen.findByText("Permission Required")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /new invite/i })).not.toBeInTheDocument();
    });

    it("4. Unauthorized viewer sees Permission Required state", async () => {
      mockGetMe.mockResolvedValue({
        user_id: "u4",
        roles: ["viewer"],
        global_role: "viewer",
      });
      renderComponent();

      expect(await screen.findByText("Permission Required")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /new invite/i })).not.toBeInTheDocument();
    });
  });

  describe("Multi-server scope and capability toggles", () => {
    it("5. Displays server list checkboxes and defaults invite role to viewer", async () => {
      await renderAndOpenModal();

      expect(await screen.findByText("Survival Server")).toBeInTheDocument();
      expect(screen.getByText("Creative Server")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /generate invitation/i }));
      await waitFor(() => {
        expect(mockCreateInvite).toHaveBeenCalledWith({
          email: undefined,
          role: "viewer",
          all_servers_access: false,
          server_ids: [],
          denied_permissions: [],
          expires_in_hours: 48,
        });
      });
    });

    it("6. Selecting Server Admin + multi-server checkboxes + capability restriction sends exact payload", async () => {
      await renderAndOpenModal();

      fireEvent.click(await screen.findByRole("radio", { name: /Server Admin/i }));
      fireEvent.click(screen.getByLabelText(/Survival Server/i));
      fireEvent.click(screen.getByLabelText(/Creative Server/i));
      // Uncheck Power Control capability
      const powerBox = screen.getByLabelText(/Power Control/i);
      fireEvent.click(powerBox);

      fireEvent.click(screen.getByRole("button", { name: /generate invitation/i }));
      await waitFor(() => {
        expect(mockCreateInvite).toHaveBeenCalledWith({
          email: undefined,
          role: "server_admin",
          all_servers_access: false,
          server_ids: ["srv-1", "srv-2"],
          denied_permissions: ["power"],
          expires_in_hours: 48,
        });
      });
    });

    it("7. Renders multi-server names and capability restriction in invitations table", async () => {
      mockListInvites.mockResolvedValue([
        {
          invite_id: "inv-1",
          token_prefix: "onx_inv1",
          creator_id: "u1",
          email: null,
          role: "server_admin",
          global_role: "server_admin",
          server_id: "srv-1",
          server_ids: ["srv-1", "srv-2"],
          server_role: "server_admin",
          all_servers_access: false,
          denied_permissions: ["power"],
          status: "ACTIVE",
          max_uses: 1,
          use_count: 0,
          expires_at: null,
          created_at: "2026-01-01T00:00:00Z",
        },
      ]);

      renderComponent();
      expect(await screen.findByText("Server Admin")).toBeInTheDocument();
      expect(await screen.findByText("Survival Server")).toBeInTheDocument();
      expect(await screen.findByText("Creative Server")).toBeInTheDocument();
      expect(screen.getByText("No power")).toBeInTheDocument();
    });
  });

  describe("Authorization & error handling", () => {
    it("8. HTTP 403 from invitation creation is handled gracefully", async () => {
      mockCreateInvite.mockRejectedValueOnce(
        new Error("403 Forbidden: Cannot create invitation with role 'owner'"),
      );

      await renderAndOpenModal();
      fireEvent.click(screen.getByRole("button", { name: /generate invitation/i }));

      await waitFor(() => {
        expect(screen.getByRole("alert")).toHaveTextContent(
          "403 Forbidden: Cannot create invitation with role 'owner'",
        );
      });
    });

    it("9. /auth/me failure fails closed gracefully without crashing", async () => {
      mockGetMe.mockRejectedValue(new Error("Failed to load user info"));

      renderComponent();

      expect(await screen.findByText(/permission required/i)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /new invite/i })).not.toBeInTheDocument();
    });

    it("10. Server-list failure shows recoverable notice and allows global or empty-server invite", async () => {
      mockListServers.mockRejectedValue(new Error("Failed to load servers"));

      await renderAndOpenModal();

      await waitFor(() => {
        expect(screen.getByText(/server list temporarily unavailable/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("button", { name: /generate invitation/i }));
      await waitFor(() => {
        expect(mockCreateInvite).toHaveBeenCalledWith({
          email: undefined,
          role: "viewer",
          all_servers_access: false,
          server_ids: [],
          denied_permissions: [],
          expires_in_hours: 48,
        });
      });
    });
  });

  describe("Modal behavior (FIX-3)", () => {
    it("renders dialog with accessible title, focuses inside, and supports Escape when idle", async () => {
      await renderAndOpenModal();
      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Generate Invitation" })).toBeInTheDocument();

      await waitFor(() => {
        expect(dialog.contains(document.activeElement)).toBe(true);
      });

      fireEvent.keyDown(window, { key: "Escape" });
      await waitFor(() => {
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      });
    });

    it("does not close on backdrop click or content click", async () => {
      await renderAndOpenModal();
      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();

      const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60")!;
      expect(backdrop).toBeInTheDocument();
      fireEvent.click(backdrop);
      expect(screen.getByRole("dialog")).toBeInTheDocument();

      fireEvent.click(dialog);
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    it("guards against Escape and disables Cancel/Generate buttons while pending", async () => {
      let resolveMutation!: (val: unknown) => void;
      mockCreateInvite.mockImplementation(
        () => new Promise((resolve) => { resolveMutation = resolve; }),
      );

      await renderAndOpenModal();
      const submitBtn = screen.getByRole("button", { name: "Generate Invitation" });
      const cancelBtn = screen.getByRole("button", { name: "Cancel" });

      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Generating..." })).toBeDisabled();
        expect(cancelBtn).toBeDisabled();
      });

      fireEvent.keyDown(window, { key: "Escape" });
      expect(screen.getByRole("dialog")).toBeInTheDocument();

      resolveMutation({ token: "tok-123", expires_at: "2026-11-08T00:00:00Z" });
      await waitFor(() => {
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      });
    });

    it("pins header and footer outside scrollable body and displays truthful read-only descriptions for Viewer", async () => {
      await renderAndOpenModal();
      const dialog = screen.getByRole("dialog");
      const header = screen.getByTestId("modal-header");
      const body = screen.getByTestId("modal-body");
      const footer = screen.getByTestId("modal-footer");

      expect(dialog).toHaveClass("max-h-[calc(100dvh-2rem)]", "flex-col", "overflow-hidden");
      expect(header).toContainElement(screen.getByRole("heading", { name: "Generate Invitation" }));
      expect(body).toHaveClass("overflow-y-auto", "flex-1", "min-h-0");
      expect(footer).toContainElement(screen.getByRole("button", { name: "Cancel" }));
      expect(footer).toContainElement(screen.getByRole("button", { name: "Generate Invitation" }));
      expect(body).not.toContainElement(screen.getByRole("button", { name: "Generate Invitation" }));

      // Viewer is selected by default: no mutating copy should appear
      expect(
        screen.getByText("Read live and historical console output (commands disabled)"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("View server logs and crash reports (read-only)"),
      ).toBeInTheDocument();
      expect(screen.queryByText(/send server commands/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/edit, upload files/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Install, upload, toggle, and remove/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Configure server tunnels/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Manage Git branches/i)).not.toBeInTheDocument();

      // Responsive grids and capped server access checklist
      const radiogroup = screen.getByRole("radiogroup", { name: "Account Role" });
      expect(radiogroup).toHaveClass("grid-cols-1", "sm:grid-cols-2");
    });
  });
});
