import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { OperationFailure } from "./OperationFailure";

describe("OperationFailure", () => {
  it("renders failure code, message, and step ID", () => {
    render(
      <OperationFailure
        failureCode="ADMISSION_DENIED"
        errorMessage="Insufficient host memory earmarks"
        failedStepId="ADMISSION_CHECK"
      />
    );

    expect(screen.getByTestId("failure-code-badge")).toHaveTextContent("ADMISSION_DENIED");
    expect(screen.getByTestId("failure-error-message")).toHaveTextContent(
      "Insufficient host memory earmarks"
    );
    expect(screen.getByText("Step: ADMISSION_CHECK")).toBeInTheDocument();
  });

  it("calls onRetry callback when retry button is clicked", () => {
    const handleRetry = vi.fn();
    render(
      <OperationFailure
        failureCode="CONTAINER_CRASHED"
        errorMessage="Container exited with code 1"
        onRetry={handleRetry}
        isRetrying={false}
      />
    );

    const retryBtn = screen.getByTestId("operation-retry-button");
    expect(retryBtn).toBeInTheDocument();
    fireEvent.click(retryBtn);
    expect(handleRetry).toHaveBeenCalledTimes(1);
  });

  it("disables button while retrying", () => {
    render(
      <OperationFailure
        failureCode="CONTAINER_CRASHED"
        errorMessage="Container exited with code 1"
        onRetry={vi.fn()}
        isRetrying={true}
      />
    );

    const retryBtn = screen.getByTestId("operation-retry-button");
    expect(retryBtn).toBeDisabled();
    expect(retryBtn).toHaveTextContent("Retrying...");
  });
});
