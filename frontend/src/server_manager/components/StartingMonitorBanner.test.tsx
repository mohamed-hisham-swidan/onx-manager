import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { StartingMonitorBanner } from "./StartingMonitorBanner";

describe("StartingMonitorBanner", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders server starting status with elapsed time", () => {
    const baseTime = 1000000000000;
    vi.setSystemTime(baseTime);

    render(
      <StartingMonitorBanner
        targetName="Alpha Server"
        startedAt={baseTime}
        timeoutSeconds={120}
      />
    );

    expect(screen.getByTestId("starting-monitor-banner")).toHaveAttribute(
      "data-status",
      "starting"
    );
    expect(screen.getByText(/Alpha Server: Server Boot in Progress/i)).toBeInTheDocument();
    expect(screen.getByTestId("starting-monitor-timer")).toHaveTextContent("0:00 / 2:00");

    // Advance 30 seconds
    act(() => {
      vi.advanceTimersByTime(30000);
    });

    expect(screen.getByTestId("starting-monitor-timer")).toHaveTextContent("0:30 / 2:00");
  });

  it("switches to overdue warning when elapsed time passes timeout", () => {
    const baseTime = 1000000000000;
    vi.setSystemTime(baseTime);

    render(
      <StartingMonitorBanner
        targetName="Alpha Server"
        startedAt={baseTime}
        timeoutSeconds={60}
      />
    );

    expect(screen.getByTestId("starting-monitor-banner")).toHaveAttribute(
      "data-status",
      "starting"
    );

    // Advance past timeout (65 seconds)
    act(() => {
      vi.advanceTimersByTime(65000);
    });

    const banner = screen.getByTestId("starting-monitor-banner");
    expect(banner).toHaveAttribute("data-status", "warning");
    expect(screen.getByText(/Startup is taking longer than configured timeout/i)).toBeInTheDocument();
  });

  it("handles manual check now button", async () => {
    const onCheckNow = vi.fn().mockResolvedValue(undefined);
    render(
      <StartingMonitorBanner
        targetName="Alpha Server"
        timeoutSeconds={120}
        onCheckNow={onCheckNow}
      />
    );

    const checkBtn = screen.getByTestId("starting-monitor-check-now");
    expect(checkBtn).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(checkBtn);
    });

    expect(onCheckNow).toHaveBeenCalledTimes(1);
  });

  it("handles manual dismiss button idempotently", () => {
    const onDismiss = vi.fn();
    render(
      <StartingMonitorBanner
        targetName="Alpha Server"
        timeoutSeconds={120}
        onDismiss={onDismiss}
      />
    );

    const dismissBtn = screen.getByTestId("starting-monitor-dismiss");
    fireEvent.click(dismissBtn);

    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("starting-monitor-banner")).not.toBeInTheDocument();
  });

  it("renders test run mode when isTestRun is true", () => {
    render(
      <StartingMonitorBanner
        targetName="Test Run abcd1234"
        timeoutSeconds={120}
        isTestRun={true}
      />
    );

    expect(screen.getByText(/Test Boot Verification/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Waiting for isolated container log-marker confirmation/i)
    ).toBeInTheDocument();
  });
});
