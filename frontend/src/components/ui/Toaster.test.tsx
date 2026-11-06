import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { Toaster } from "./Toaster";
import { useToastStore } from "@/stores/toastStore";

describe("Toaster", () => {
  beforeEach(() => {
    useToastStore.getState().clear();
  });

  it("renders toasts from the store", () => {
    useToastStore.getState().push({ type: "success", title: "Saved", message: "Done" });
    render(<Toaster />);
    expect(screen.getByText("Saved")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("dismisses a toast when its close button is clicked", () => {
    const id = useToastStore.getState().push({ type: "info", title: "Heads up" });
    render(<Toaster />);
    const dismiss = screen.getByLabelText("Dismiss notification");
    dismiss.click();
    expect(useToastStore.getState().toasts.some((t) => t.id === id)).toBe(false);
  });

  it("renders with role='status' and aria-live='polite' for success, and role='alert' and aria-live='assertive' for error", () => {
    useToastStore.getState().push({ type: "success", title: "Saved successfully" });
    useToastStore.getState().push({ type: "error", title: "Operation failed" });
    render(<Toaster />);

    const statusToast = screen.getByRole("status");
    expect(statusToast).toBeInTheDocument();
    expect(statusToast).toHaveAttribute("aria-live", "polite");

    const alertToast = screen.getByRole("alert");
    expect(alertToast).toBeInTheDocument();
    expect(alertToast).toHaveAttribute("aria-live", "assertive");
  });
});
