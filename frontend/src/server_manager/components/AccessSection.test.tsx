import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AccessSection } from "./AccessSection";

const mockGetMe = vi.fn();
const mockGetSetupStatus = vi.fn();
const mockUpdateAccessMode = vi.fn();
const mockToast = vi.fn();

vi.mock("@/services/api", () => ({
  createApiClient: () => ({
    getMe: mockGetMe,
    getSetupStatus: mockGetSetupStatus,
    updateAccessMode: mockUpdateAccessMode,
  }),
}));

vi.mock("@/stores/toastStore", () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}));

function renderAccessSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AccessSection />
    </QueryClientProvider>
  );
}

describe("AccessSection Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("1 & 3. Displays active access mode correctly for Owner", async () => {
    mockGetMe.mockResolvedValueOnce({
      user_id: "u-owner",
      roles: ["owner"],
      permissions: ["admin:full", "global.*"],
    });
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: true,
      access_mode: "LOCAL",
      user_count: 1,
      version: "4.0.0",
    });

    renderAccessSection();

    expect(await screen.findByText("Instance Access Control")).toBeInTheDocument();
    expect(screen.getByText("LOCAL MODE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Switch to GLOBAL Mode/i })).toBeInTheDocument();
  });

  it("2. Displays Access Denied for Non-Owner user", async () => {
    mockGetMe.mockResolvedValueOnce({
      user_id: "u-admin",
      roles: ["admin"],
      permissions: ["admin:full"],
    });
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: true,
      access_mode: "LOCAL",
      user_count: 2,
      version: "4.0.0",
    });

    renderAccessSection();

    expect(await screen.findByText("Access Denied")).toBeInTheDocument();
    expect(
      screen.getByText("Only the instance Owner can view or modify Access Mode settings.")
    ).toBeInTheDocument();
  });

  it("4 & 5 & 12. Selecting a different mode (LOCAL -> GLOBAL) opens confirmation modal with warning", async () => {
    mockGetMe.mockResolvedValueOnce({
      user_id: "u-owner",
      roles: ["owner"],
      permissions: ["admin:full", "global.*"],
    });
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: true,
      access_mode: "LOCAL",
      user_count: 1,
      version: "4.0.0",
    });

    renderAccessSection();

    const switchBtn = await screen.findByRole("button", { name: /Switch to GLOBAL Mode/i });
    fireEvent.click(switchBtn);

    // Confirmation modal is open, API not called yet
    expect(mockUpdateAccessMode).not.toHaveBeenCalled();
    expect(screen.getByText("Switch to GLOBAL Access Mode?")).toBeInTheDocument();
    expect(
      screen.getByText(/Changing the instance Access Mode to GLOBAL will immediately disable open self-registration/i)
    ).toBeInTheDocument();
  });

  it("6. Clicking Cancel closes modal without performing mutation", async () => {
    mockGetMe.mockResolvedValueOnce({
      user_id: "u-owner",
      roles: ["owner"],
      permissions: ["admin:full", "global.*"],
    });
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: true,
      access_mode: "LOCAL",
      user_count: 1,
      version: "4.0.0",
    });

    renderAccessSection();

    const switchBtn = await screen.findByRole("button", { name: /Switch to GLOBAL Mode/i });
    fireEvent.click(switchBtn);

    const cancelBtn = screen.getByRole("button", { name: /Cancel/i });
    fireEvent.click(cancelBtn);

    expect(screen.queryByText("Switch to GLOBAL Access Mode?")).not.toBeInTheDocument();
    expect(mockUpdateAccessMode).not.toHaveBeenCalled();
  });

  it("7 & 8. Confirming switch performs mutation and updates UI", async () => {
    mockGetMe.mockResolvedValueOnce({
      user_id: "u-owner",
      roles: ["owner"],
      permissions: ["admin:full", "global.*"],
    });
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: true,
      access_mode: "LOCAL",
      user_count: 1,
      version: "4.0.0",
    });
    mockUpdateAccessMode.mockResolvedValueOnce({
      initialized: true,
      access_mode: "GLOBAL",
      user_count: 1,
      version: "4.0.0",
    });

    renderAccessSection();

    const switchBtn = await screen.findByRole("button", { name: /Switch to GLOBAL Mode/i });
    fireEvent.click(switchBtn);

    const confirmBtn = screen.getByRole("button", { name: /Confirm Switch to GLOBAL/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockUpdateAccessMode).toHaveBeenCalledWith({ access_mode: "GLOBAL" });
      expect(mockToast).toHaveBeenCalledWith("success", expect.any(String), expect.any(String));
    });
  });

  it("9 & 10. Handles mutation errors (403 / network failure) gracefully", async () => {
    mockGetMe.mockResolvedValueOnce({
      user_id: "u-owner",
      roles: ["owner"],
      permissions: ["admin:full", "global.*"],
    });
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: true,
      access_mode: "LOCAL",
      user_count: 1,
      version: "4.0.0",
    });
    mockUpdateAccessMode.mockRejectedValueOnce(new Error("403 Forbidden: Only Owner can modify mode"));

    renderAccessSection();

    const switchBtn = await screen.findByRole("button", { name: /Switch to GLOBAL Mode/i });
    fireEvent.click(switchBtn);

    const confirmBtn = screen.getByRole("button", { name: /Confirm Switch to GLOBAL/i });
    fireEvent.click(confirmBtn);

    expect(await screen.findByRole("alert")).toHaveTextContent("403 Forbidden: Only Owner can modify mode");
    expect(mockToast).toHaveBeenCalledWith("error", expect.any(String), expect.any(String));
  });

  it("11. Displays correct confirmation warning for GLOBAL -> LOCAL switch", async () => {
    mockGetMe.mockResolvedValueOnce({
      user_id: "u-owner",
      roles: ["owner"],
      permissions: ["admin:full", "global.*"],
    });
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: true,
      access_mode: "GLOBAL",
      user_count: 1,
      version: "4.0.0",
    });

    renderAccessSection();

    const switchBtn = await screen.findByRole("button", { name: /Switch to LOCAL Mode/i });
    fireEvent.click(switchBtn);

    expect(screen.getByText("Switch to LOCAL Access Mode?")).toBeInTheDocument();
    expect(
      screen.getByText(/Changing the instance Access Mode to LOCAL will immediately enable open self-registration/i)
    ).toBeInTheDocument();
  });
});
