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
    </QueryClientProvider>
  );
}

async function renderAndOpenModal() {
  renderComponent();
  // Wait for initial queries to settle
  await waitFor(() => expect(mockListInvites).toHaveBeenCalled());
  const btn = await screen.findByRole("button", { name: /create invitation/i });
  fireEvent.click(btn);
}

describe("InvitationsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListInvites.mockResolvedValue([]);
    mockGetMe.mockResolvedValue({
      user_id: "u1",
      email: "user@example.com",
      display_name: "Test User",
      is_active: true,
      roles: ["owner"],
      created_at: "2026-01-01T00:00:00Z",
      last_login_at: null,
    });
    mockListServers.mockResolvedValue([
      {
        server_id: "srv-1",
        name: "Survival Server",
        status: "RUNNING",
      },
      {
        server_id: "srv-2",
        name: "Creative Server",
        status: "STOPPED",
      },
    ]);
    mockCreateInvite.mockResolvedValue({
      invite_id: "inv-123",
      token: "mcis_secret_token_123",
      token_prefix: "mcis_secre",
      email: null,
      global_role: "member",
      server_id: null,
      server_role: null,
      status: "ACTIVE",
      max_uses: 1,
      expires_at: null,
    });
  });

  describe("Global roles UX filtering", () => {
    it("1. Owner sees all 4 global roles (Owner, Administrator, Member, Viewer)", async () => {
      mockGetMe.mockResolvedValue({
        user_id: "u1",
        roles: ["owner"],
      });
      await renderAndOpenModal();

      const select = await screen.findByLabelText(/global access role/i);
      await waitFor(() => {
        const options = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
        expect(options).toEqual([
          "Owner",
          "Administrator",
          "Member (Standard)",
          "Viewer (Limited)",
        ]);
      });
    });

    it("2. Admin sees 3 global roles (Administrator, Member, Viewer)", async () => {
      mockGetMe.mockResolvedValue({
        user_id: "u2",
        roles: ["admin"],
      });
      await renderAndOpenModal();

      const select = await screen.findByLabelText(/global access role/i);
      await waitFor(() => {
        const options = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
        expect(options).toEqual([
          "Administrator",
          "Member (Standard)",
          "Viewer (Limited)",
        ]);
      });
    });

    it("3. Member sees 2 global roles (Member, Viewer)", async () => {
      mockGetMe.mockResolvedValue({
        user_id: "u3",
        roles: ["member"],
      });
      await renderAndOpenModal();

      const select = await screen.findByLabelText(/global access role/i);
      await waitFor(() => {
        const options = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
        expect(options).toEqual([
          "Member (Standard)",
          "Viewer (Limited)",
        ]);
      });
    });

    it("4. Viewer sees 2 global roles (Member, Viewer)", async () => {
      mockGetMe.mockResolvedValue({
        user_id: "u4",
        roles: ["viewer"],
      });
      await renderAndOpenModal();

      const select = await screen.findByLabelText(/global access role/i);
      await waitFor(() => {
        const options = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
        expect(options).toEqual([
          "Member (Standard)",
          "Viewer (Limited)",
        ]);
      });
    });
  });

  describe("Server access UI", () => {
    it("5 & 6. Fetches server list from API and displays returned servers in selector", async () => {
      await renderAndOpenModal();

      const serverSelect = await screen.findByLabelText(/server access/i);
      await waitFor(() => {
        expect(serverSelect).not.toBeDisabled();
      });

      expect(mockListServers).toHaveBeenCalledTimes(1);

      const options = Array.from(serverSelect.querySelectorAll("option")).map((o) => o.textContent);
      expect(options).toContain("[ No server access ]");
      expect(options).toContain("Survival Server (srv-1)");
      expect(options).toContain("Creative Server (srv-2)");
    });

    it("7. Selecting a server enables the server-role selector", async () => {
      await renderAndOpenModal();

      const serverSelect = await screen.findByLabelText(/server access/i);
      await waitFor(() => {
        expect(serverSelect).not.toBeDisabled();
      });

      expect(screen.queryByLabelText(/server role/i)).not.toBeInTheDocument();

      fireEvent.change(serverSelect, { target: { value: "srv-1" } });

      const serverRoleSelect = await screen.findByLabelText(/server role/i);
      expect(serverRoleSelect).toBeInTheDocument();

      const options = Array.from(serverRoleSelect.querySelectorAll("option")).map((o) => o.textContent);
      expect(options).toEqual(["Server Viewer", "Developer", "Server Administrator"]);
    });

    it("8. Selecting server_id and server_role sends exact values in creation payload", async () => {
      await renderAndOpenModal();

      const serverSelect = await screen.findByLabelText(/server access/i);
      await waitFor(() => {
        expect(serverSelect).not.toBeDisabled();
      });

      fireEvent.change(serverSelect, { target: { value: "srv-1" } });

      const serverRoleSelect = await screen.findByLabelText(/server role/i);
      fireEvent.change(serverRoleSelect, { target: { value: "dev" } });

      fireEvent.click(screen.getByRole("button", { name: /generate invitation/i }));

      await waitFor(() => {
        expect(mockCreateInvite).toHaveBeenCalledWith({
          email: undefined,
          global_role: "owner",
          server_id: "srv-1",
          server_role: "dev",
          expires_in_hours: 48,
        });
      });
    });

    it("9. Creating a global-only invitation does NOT send server_id or server_role", async () => {
      await renderAndOpenModal();

      await waitFor(() => {
        expect(screen.getByLabelText(/server access/i)).not.toBeDisabled();
      });

      fireEvent.click(screen.getByRole("button", { name: /generate invitation/i }));

      await waitFor(() => {
        expect(mockCreateInvite).toHaveBeenCalledWith({
          email: undefined,
          global_role: "owner",
          expires_in_hours: 48,
        });
      });
    });
  });

  describe("Authorization & error handling", () => {
    it("10. HTTP 403 from invitation creation is handled gracefully", async () => {
      mockCreateInvite.mockRejectedValueOnce(
        new Error("403 Forbidden: Cannot create invitation with global_role 'owner'")
      );

      await renderAndOpenModal();

      await waitFor(() => {
        expect(screen.getByLabelText(/server access/i)).not.toBeDisabled();
      });

      fireEvent.click(screen.getByRole("button", { name: /generate invitation/i }));

      await waitFor(() => {
        expect(screen.getByRole("alert")).toHaveTextContent(
          "403 Forbidden: Cannot create invitation with global_role 'owner'"
        );
      });
    });

    it("11. /auth/me failure is handled gracefully without crashing", async () => {
      mockGetMe.mockRejectedValue(new Error("Failed to load user info"));

      await renderAndOpenModal();

      const select = await screen.findByLabelText(/global access role/i);
      await waitFor(() => {
        const options = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
        expect(options).toEqual([
          "Member (Standard)",
          "Viewer (Limited)",
        ]);
      });
    });

    it("12. Server-list failure is handled gracefully without crashing", async () => {
      mockListServers.mockRejectedValue(new Error("Failed to load servers"));

      await renderAndOpenModal();

      await waitFor(() => {
        expect(
          screen.getByText(/server list temporarily unavailable/i)
        ).toBeInTheDocument();
      });

      // Can still submit global-only invitation
      fireEvent.click(screen.getByRole("button", { name: /generate invitation/i }));

      await waitFor(() => {
        expect(mockCreateInvite).toHaveBeenCalledWith({
          email: undefined,
          global_role: "owner",
          expires_in_hours: 48,
        });
      });
    });
  });
});
