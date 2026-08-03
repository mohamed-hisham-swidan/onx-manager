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
});
