import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OperationStepper } from "./OperationStepper";
import type { OperationStep } from "../types";

describe("OperationStepper", () => {
  const mockSteps: OperationStep[] = [
    {
      id: "s1",
      step_id: "ADMISSION_CHECK",
      sequence: 1,
      status: "COMPLETED",
      progress: 1.0,
      elapsed_ms: 1200,
      message_key: null,
      safe_to_retry: true,
      context: {},
      started_at: "2026-09-27T12:00:00Z",
      completed_at: "2026-09-27T12:00:01Z",
    },
    {
      id: "s2",
      step_id: "MATERIALIZE_STAGING",
      sequence: 2,
      status: "IN_PROGRESS",
      progress: 0.65,
      elapsed_ms: 2500,
      message_key: null,
      safe_to_retry: false,
      context: {},
      started_at: "2026-09-27T12:00:01Z",
      completed_at: null,
    },
    {
      id: "s3",
      step_id: "BOOTSTRAP_VERIFY",
      sequence: 3,
      status: "PENDING",
      progress: null,
      elapsed_ms: 0,
      message_key: null,
      safe_to_retry: false,
      context: {},
      started_at: null,
      completed_at: null,
    },
  ];

  it("renders all defined steps with formatted titles", () => {
    render(<OperationStepper steps={mockSteps} currentStepId="MATERIALIZE_STAGING" />);

    expect(screen.getByText("Admission Check")).toBeInTheDocument();
    expect(screen.getByText("Materialize Staging")).toBeInTheDocument();
    expect(screen.getByText("Bootstrap Verify")).toBeInTheDocument();
  });

  it("renders status icons and elapsed seconds", () => {
    render(<OperationStepper steps={mockSteps} currentStepId="MATERIALIZE_STAGING" />);

    expect(screen.getByTestId("step-icon-completed")).toBeInTheDocument();
    expect(screen.getByTestId("step-icon-in-progress")).toBeInTheDocument();
    expect(screen.getByTestId("step-icon-pending")).toBeInTheDocument();

    expect(screen.getByText("1.2s")).toBeInTheDocument();
    expect(screen.getByText("2.5s")).toBeInTheDocument();
    expect(screen.getByText("PENDING")).toBeInTheDocument();
  });

  it("handles empty steps gracefully", () => {
    render(<OperationStepper steps={[]} />);
    expect(screen.getByText("No steps defined.")).toBeInTheDocument();
  });
});
