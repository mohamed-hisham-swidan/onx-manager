import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  useResizableWidth,
  MIN_SIDEBAR_WIDTH,
  MAX_SIDEBAR_WIDTH,
  DEFAULT_SIDEBAR_WIDTH,
  SIDEBAR_WIDTH_STORAGE_KEY,
  KEYBOARD_STEP,
  KEYBOARD_SHIFT_STEP,
} from "./useResizableWidth";

describe("useResizableWidth", () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.style.userSelect = "";
    document.documentElement.style.removeProperty("--sidebar-width");
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("exports correct named constants", () => {
    expect(MIN_SIDEBAR_WIDTH).toBe(200);
    expect(MAX_SIDEBAR_WIDTH).toBe(420);
    expect(DEFAULT_SIDEBAR_WIDTH).toBe(224);
    expect(KEYBOARD_STEP).toBe(16);
    expect(KEYBOARD_SHIFT_STEP).toBe(48);
    expect(SIDEBAR_WIDTH_STORAGE_KEY).toBe("onx_sidebar_width");
  });

  it("initializes with default width when localStorage is empty", () => {
    const { result } = renderHook(() => useResizableWidth());
    expect(result.current.width).toBe(DEFAULT_SIDEBAR_WIDTH);
    expect(result.current.handleProps["aria-valuenow"]).toBe(DEFAULT_SIDEBAR_WIDTH);
    expect(result.current.handleProps["aria-valuemin"]).toBe(MIN_SIDEBAR_WIDTH);
    expect(result.current.handleProps["aria-valuemax"]).toBe(MAX_SIDEBAR_WIDTH);
    expect(result.current.handleProps.role).toBe("separator");
    expect(result.current.handleProps["aria-orientation"]).toBe("vertical");
    expect(result.current.handleProps.tabIndex).toBe(0);
  });

  it("initializes from valid stored width in localStorage", () => {
    localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, "300");
    const { result } = renderHook(() => useResizableWidth());
    expect(result.current.width).toBe(300);
  });

  it("clamps stored width at min and max bounds on initialization", () => {
    localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, "120");
    const { result: minResult } = renderHook(() => useResizableWidth());
    expect(minResult.current.width).toBe(MIN_SIDEBAR_WIDTH);

    localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, "600");
    const { result: maxResult } = renderHook(() => useResizableWidth());
    expect(maxResult.current.width).toBe(MAX_SIDEBAR_WIDTH);
  });

  it("falls back to default width on invalid stored values or localStorage errors", () => {
    localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, "not-a-number");
    const { result: nanResult } = renderHook(() => useResizableWidth());
    expect(nanResult.current.width).toBe(DEFAULT_SIDEBAR_WIDTH);

    localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, "Infinity");
    const { result: infResult } = renderHook(() => useResizableWidth());
    expect(infResult.current.width).toBe(DEFAULT_SIDEBAR_WIDTH);

    vi.spyOn(Storage.prototype, "getItem").mockImplementationOnce(() => {
      throw new Error("QuotaExceeded / SecurityError");
    });
    const { result: errResult } = renderHook(() => useResizableWidth());
    expect(errResult.current.width).toBe(DEFAULT_SIDEBAR_WIDTH);
  });

  it("clamps width at bounds when manually set", () => {
    const { result } = renderHook(() => useResizableWidth());

    act(() => {
      result.current.setWidth(150);
    });
    expect(result.current.width).toBe(MIN_SIDEBAR_WIDTH);
    expect(localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY)).toBe(String(MIN_SIDEBAR_WIDTH));

    act(() => {
      result.current.setWidth(500);
    });
    expect(result.current.width).toBe(MAX_SIDEBAR_WIDTH);
    expect(localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY)).toBe(String(MAX_SIDEBAR_WIDTH));
  });

  it("resets width to default on double-click", () => {
    localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, "320");
    const { result } = renderHook(() => useResizableWidth());
    expect(result.current.width).toBe(320);

    act(() => {
      result.current.handleProps.onDoubleClick({
        preventDefault: vi.fn(),
        stopPropagation: vi.fn(),
      } as unknown as React.MouseEvent<HTMLElement>);
    });

    expect(result.current.width).toBe(DEFAULT_SIDEBAR_WIDTH);
    expect(localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY)).toBe(String(DEFAULT_SIDEBAR_WIDTH));
  });

  describe("keyboard navigation", () => {
    it("resizes with ArrowLeft and ArrowRight by step (16px)", () => {
      const { result } = renderHook(() => useResizableWidth());
      expect(result.current.width).toBe(224);

      act(() => {
        result.current.handleProps.onKeyDown({
          key: "ArrowRight",
          shiftKey: false,
          preventDefault: vi.fn(),
        } as unknown as React.KeyboardEvent<HTMLElement>);
      });
      expect(result.current.width).toBe(240);

      act(() => {
        result.current.handleProps.onKeyDown({
          key: "ArrowLeft",
          shiftKey: false,
          preventDefault: vi.fn(),
        } as unknown as React.KeyboardEvent<HTMLElement>);
      });
      expect(result.current.width).toBe(224);
    });

    it("resizes with Shift + ArrowLeft/Right by shiftStep (48px)", () => {
      const { result } = renderHook(() => useResizableWidth());
      expect(result.current.width).toBe(224);

      act(() => {
        result.current.handleProps.onKeyDown({
          key: "ArrowRight",
          shiftKey: true,
          preventDefault: vi.fn(),
        } as unknown as React.KeyboardEvent<HTMLElement>);
      });
      expect(result.current.width).toBe(272);

      act(() => {
        result.current.handleProps.onKeyDown({
          key: "ArrowLeft",
          shiftKey: true,
          preventDefault: vi.fn(),
        } as unknown as React.KeyboardEvent<HTMLElement>);
      });
      expect(result.current.width).toBe(224);
    });

    it("jumps to min on Home and max on End", () => {
      const { result } = renderHook(() => useResizableWidth());

      act(() => {
        result.current.handleProps.onKeyDown({
          key: "End",
          shiftKey: false,
          preventDefault: vi.fn(),
        } as unknown as React.KeyboardEvent<HTMLElement>);
      });
      expect(result.current.width).toBe(MAX_SIDEBAR_WIDTH);

      act(() => {
        result.current.handleProps.onKeyDown({
          key: "Home",
          shiftKey: false,
          preventDefault: vi.fn(),
        } as unknown as React.KeyboardEvent<HTMLElement>);
      });
      expect(result.current.width).toBe(MIN_SIDEBAR_WIDTH);
    });

    it("clamps keyboard adjustments at boundaries", () => {
      const { result } = renderHook(() => useResizableWidth());

      // Jump to min
      act(() => {
        result.current.handleProps.onKeyDown({
          key: "Home",
          shiftKey: false,
          preventDefault: vi.fn(),
        } as unknown as React.KeyboardEvent<HTMLElement>);
      });
      expect(result.current.width).toBe(MIN_SIDEBAR_WIDTH);

      // Decrement further
      act(() => {
        result.current.handleProps.onKeyDown({
          key: "ArrowLeft",
          shiftKey: false,
          preventDefault: vi.fn(),
        } as unknown as React.KeyboardEvent<HTMLElement>);
      });
      expect(result.current.width).toBe(MIN_SIDEBAR_WIDTH);
    });
  });

  describe("pointer drag and text selection prevention", () => {
    it("handles pointer drag lifecycle with setPointerCapture and userSelect prevention", () => {
      const { result } = renderHook(() => useResizableWidth());
      expect(result.current.isDragging).toBe(false);

      const setPointerCapture = vi.fn();
      const releasePointerCapture = vi.fn();
      const hasPointerCapture = vi.fn().mockReturnValue(true);

      const target = {
        setPointerCapture,
        releasePointerCapture,
        hasPointerCapture,
      } as unknown as HTMLElement;

      act(() => {
        result.current.handleProps.onPointerDown({
          pointerId: 1,
          button: 0,
          currentTarget: target,
          clientX: 224,
          preventDefault: vi.fn(),
        } as unknown as React.PointerEvent<HTMLElement>);
      });

      expect(result.current.isDragging).toBe(true);
      expect(setPointerCapture).toHaveBeenCalledWith(1);
      expect(document.body.style.userSelect).toBe("none");

      // Pointer move
      act(() => {
        result.current.handleProps.onPointerMove({
          clientX: 300,
          preventDefault: vi.fn(),
        } as unknown as React.PointerEvent<HTMLElement>);
      });
      expect(result.current.width).toBe(300);

      // Pointer up completes drag and restores userSelect
      act(() => {
        result.current.handleProps.onPointerUp({
          pointerId: 1,
          currentTarget: target,
        } as unknown as React.PointerEvent<HTMLElement>);
      });

      expect(result.current.isDragging).toBe(false);
      expect(document.body.style.userSelect).toBe("");
      expect(localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY)).toBe("300");
    });
  });
});
