import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { PlayitClaimCard } from "./PlayitClaimCard";

const mockCopy = vi.fn();
vi.mock("@/hooks/useClipboard", () => ({
  useClipboard: () => ({
    copy: mockCopy,
  }),
}));

describe("PlayitClaimCard Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("T-74-13: renders unclaimed state with generate claim button", () => {
    const onGenerateClaim = vi.fn();
    render(
      <PlayitClaimCard
        claimed={false}
        claimActive={false}
        onGenerateClaim={onGenerateClaim}
      />
    );

    expect(screen.getByText("playit.gg Account Authorization")).toBeInTheDocument();
    expect(screen.getByText("Authorization Required")).toBeInTheDocument();
    const generateBtn = screen.getByRole("button", { name: /Authorize with playit.gg/i });
    expect(generateBtn).toBeInTheDocument();

    fireEvent.click(generateBtn);
    expect(onGenerateClaim).toHaveBeenCalledTimes(1);
  });

  it("T-74-14: renders active claim code and direct url link", () => {
    const expiresAt = new Date(Date.now() + 300 * 1000).toISOString();
    render(
      <PlayitClaimCard
        claimed={false}
        claimActive={true}
        claimCode="ABC123"
        claimUrl="https://playit.gg/claim/ABC123"
        claimExpiresAt={expiresAt}
        onGenerateClaim={vi.fn()}
      />
    );

    expect(screen.getByText("ABC123")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open playit.gg Authorization Page/i })).toHaveAttribute(
      "href",
      "https://playit.gg/claim/ABC123"
    );
    expect(screen.getByRole("timer")).toBeInTheDocument();
  });

  it("T-74-15: claim code copy button copies code", () => {
    const expiresAt = new Date(Date.now() + 300 * 1000).toISOString();
    render(
      <PlayitClaimCard
        claimed={false}
        claimActive={true}
        claimCode="XYZ789"
        claimUrl="https://playit.gg/claim/XYZ789"
        claimExpiresAt={expiresAt}
        onGenerateClaim={vi.fn()}
      />
    );

    const copyBtn = screen.getByRole("button", { name: /Copy claim code to clipboard/i });
    fireEvent.click(copyBtn);

    expect(mockCopy).toHaveBeenCalledWith("XYZ789", "Claim code copied to clipboard");
  });

  it("T-74-16: countdown timer ticks down and shows expired state without silent auto-regeneration", () => {
    const onGenerateClaim = vi.fn();
    // Set expiry in 3 seconds
    const now = Date.now();
    vi.setSystemTime(now);
    const expiresAt = new Date(now + 3 * 1000).toISOString();

    render(
      <PlayitClaimCard
        claimed={false}
        claimActive={true}
        claimCode="EXP123"
        claimUrl="https://playit.gg/claim/EXP123"
        claimExpiresAt={expiresAt}
        onGenerateClaim={onGenerateClaim}
      />
    );

    expect(screen.getByRole("timer")).toHaveTextContent("00:03");

    // Advance 4 seconds to trigger expiration
    act(() => {
      vi.advanceTimersByTime(4000);
    });

    expect(screen.getByText(/Claim code expired. Please generate a new claim to continue./i)).toBeInTheDocument();
    expect(onGenerateClaim).not.toHaveBeenCalled(); // No silent auto-regeneration (F-74-09)

    const regenBtn = screen.getByRole("button", { name: /Generate New Claim/i });
    expect(regenBtn).toBeInTheDocument();
    fireEvent.click(regenBtn);
    expect(onGenerateClaim).toHaveBeenCalledTimes(1);
  });

  it("T-74-17: clicking reset agent triggers reset callback", () => {
    const onResetAgent = vi.fn();
    render(
      <PlayitClaimCard
        claimed={true}
        claimActive={false}
        onGenerateClaim={vi.fn()}
        onResetAgent={onResetAgent}
      />
    );

    expect(screen.getByText("playit.gg Host Agent Claimed")).toBeInTheDocument();
    const resetBtn = screen.getByRole("button", { name: /Reset Agent/i });
    fireEvent.click(resetBtn);

    expect(onResetAgent).toHaveBeenCalledTimes(1);
  });

  it("T-74-18: clicking restart claiming triggers onGenerateClaim from claimed and active states", () => {
    const onGenerateClaim = vi.fn();
    const { rerender } = render(
      <PlayitClaimCard
        claimed={true}
        claimActive={false}
        onGenerateClaim={onGenerateClaim}
      />
    );

    // In claimed state
    const restartBtnClaimed = screen.getByRole("button", { name: /Restart Claiming/i });
    expect(restartBtnClaimed).toBeInTheDocument();
    fireEvent.click(restartBtnClaimed);
    expect(onGenerateClaim).toHaveBeenCalledTimes(1);

    // In active claim state
    const expiresAt = new Date(Date.now() + 300 * 1000).toISOString();
    rerender(
      <PlayitClaimCard
        claimed={false}
        claimActive={true}
        claimCode="ABC123"
        claimUrl="https://playit.gg/claim/ABC123"
        claimExpiresAt={expiresAt}
        onGenerateClaim={onGenerateClaim}
      />
    );

    const restartBtnActive = screen.getByRole("button", { name: /Restart Claiming/i });
    expect(restartBtnActive).toBeInTheDocument();
    fireEvent.click(restartBtnActive);
    expect(onGenerateClaim).toHaveBeenCalledTimes(2);
  });
});
