import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OperationLogs } from "./OperationLogs";

describe("OperationLogs", () => {
  it("renders empty state when no logs provided", () => {
    render(<OperationLogs logs={[]} />);
    expect(screen.getByTestId("operation-logs-empty")).toHaveTextContent(
      "Waiting for operation logs..."
    );
  });

  it("renders log lines and levels", () => {
    const logs = [
      { level: "info", line: "Starting runner container...", timestamp: 1727438400 },
      { level: "error", line: "Container failed healthcheck", timestamp: 1727438405 },
    ];
    render(<OperationLogs logs={logs} />);

    expect(screen.getByText("Starting runner container...")).toBeInTheDocument();
    expect(screen.getByText("Container failed healthcheck")).toBeInTheDocument();
    expect(screen.getByText("info")).toBeInTheDocument();
    expect(screen.getByText("error")).toBeInTheDocument();
  });
});
