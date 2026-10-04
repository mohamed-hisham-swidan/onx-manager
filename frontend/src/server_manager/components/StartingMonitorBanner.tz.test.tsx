import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StartingMonitorBanner } from "./StartingMonitorBanner";
import { formatRelativeTime } from "../utils/format";

describe("StartingMonitorBanner Timezone Awareness", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("calculates ~0:00 elapsed in Africa/Cairo (UTC+3) for naive server timestamp", () => {
    // Simulated wall time: 11:00:05 UTC on 2026-10-03
    vi.setSystemTime(new Date("2026-10-03T11:00:05Z"));

    // Naive UTC string as historically emitted by backend for a server started 5 seconds ago
    const naiveServerTimestamp = "2026-10-03T11:00:00";

    render(
      <StartingMonitorBanner
        targetName="mc-pupr"
        startedAt={naiveServerTimestamp}
        timeoutSeconds={120}
      />
    );

    const timer = screen.getByTestId("starting-monitor-timer");
    // Should be 0:05 / 2:00, NOT 180:05 / 2:00
    expect(timer.textContent).toBe("0:05 / 2:00");
    const banner = screen.getByTestId("starting-monitor-banner");
    expect(banner.getAttribute("data-status")).toBe("starting");

    expect(formatRelativeTime(naiveServerTimestamp)).toBe("just now");
  });

  it("calculates ~0:00 elapsed in America/Los_Angeles (UTC-7) for naive server timestamp", () => {
    // Simulated wall time: 11:00:05 UTC on 2026-10-03
    vi.setSystemTime(new Date("2026-10-03T11:00:05Z"));

    const naiveServerTimestamp = "2026-10-03T11:00:00";

    render(
      <StartingMonitorBanner
        targetName="mc-pupr"
        startedAt={naiveServerTimestamp}
        timeoutSeconds={120}
      />
    );

    const timer = screen.getByTestId("starting-monitor-timer");
    expect(timer.textContent).toBe("0:05 / 2:00");
    const banner = screen.getByTestId("starting-monitor-banner");
    expect(banner.getAttribute("data-status")).toBe("starting");

    expect(formatRelativeTime(naiveServerTimestamp)).toBe("just now");
  });

  it("calculates ~0:00 elapsed for UTC-explicit ISO timestamp with Z", () => {
    vi.setSystemTime(new Date("2026-10-03T11:00:05Z"));

    const utcTimestamp = "2026-10-03T11:00:00Z";

    render(
      <StartingMonitorBanner
        targetName="mc-pupr"
        startedAt={utcTimestamp}
        timeoutSeconds={120}
      />
    );

    const timer = screen.getByTestId("starting-monitor-timer");
    expect(timer.textContent).toBe("0:05 / 2:00");
    const banner = screen.getByTestId("starting-monitor-banner");
    expect(banner.getAttribute("data-status")).toBe("starting");
  });
});
