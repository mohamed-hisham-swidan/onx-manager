import { describe, it, expect, beforeEach } from "vitest";
import { useToastStore } from "./toastStore";

describe("toastStore", () => {
  beforeEach(() => {
    useToastStore.getState().clear();
  });

  it("pushes a toast with a unique id", () => {
    const id = useToastStore.getState().push({ type: "success", title: "Saved" });
    const state = useToastStore.getState();
    expect(state.toasts).toHaveLength(1);
    expect(state.toasts[0].id).toBe(id);
  });

  it("dismisses a toast by id", () => {
    const id = useToastStore.getState().push({ type: "info", title: "Heads up" });
    useToastStore.getState().dismiss(id);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("clears all toasts", () => {
    useToastStore.getState().push({ type: "error", title: "A" });
    useToastStore.getState().push({ type: "error", title: "B" });
    useToastStore.getState().clear();
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});
