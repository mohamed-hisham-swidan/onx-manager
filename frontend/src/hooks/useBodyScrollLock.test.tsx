import { describe, it, expect, beforeEach } from "vitest";
import { render, renderHook } from "@testing-library/react";
import React from "react";
import { useBodyScrollLock } from "./useBodyScrollLock";

describe("useBodyScrollLock", () => {
  beforeEach(() => {
    document.body.style.overflow = "";
  });

  it("locks body scroll when active is true", () => {
    document.body.style.overflow = "visible";
    const { unmount } = renderHook(({ active }) => useBodyScrollLock(active), {
      initialProps: { active: true },
    });

    expect(document.body.style.overflow).toBe("hidden");
    unmount();
  });

  it("restores previous overflow when active becomes false", () => {
    document.body.style.overflow = "scroll";
    const { rerender, unmount } = renderHook(
      ({ active }) => useBodyScrollLock(active),
      { initialProps: { active: true } },
    );

    expect(document.body.style.overflow).toBe("hidden");

    rerender({ active: false });
    expect(document.body.style.overflow).toBe("scroll");

    unmount();
  });

  it("two users restore overflow only after the last releases", () => {
    document.body.style.overflow = "auto";

    const TestComponent = ({ id, active }: { id: string; active: boolean }) => {
      useBodyScrollLock(active);
      return <div data-testid={id}>{id}</div>;
    };

    const { unmount: unmountFirst } = render(
      <TestComponent id="user-1" active={true} />,
    );
    expect(document.body.style.overflow).toBe("hidden");

    const { unmount: unmountSecond } = render(
      <TestComponent id="user-2" active={true} />,
    );
    expect(document.body.style.overflow).toBe("hidden");

    // First user releases lock
    unmountFirst();
    expect(document.body.style.overflow).toBe("hidden");

    // Second user releases lock
    unmountSecond();
    expect(document.body.style.overflow).toBe("auto");
  });

  it("unmount while active releases lock and restores overflow", () => {
    document.body.style.overflow = "auto";
    const { unmount } = renderHook(() => useBodyScrollLock(true));

    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("auto");
  });
});
