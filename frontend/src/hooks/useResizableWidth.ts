import React, { useState, useEffect, useRef, useCallback } from "react";

export const MIN_SIDEBAR_WIDTH = 200;
export const MAX_SIDEBAR_WIDTH = 420;
export const DEFAULT_SIDEBAR_WIDTH = 224; // matches lg:w-56 (14rem = 224px)
export const KEYBOARD_STEP = 16;
export const KEYBOARD_SHIFT_STEP = 48;
export const SIDEBAR_WIDTH_STORAGE_KEY = "onx_sidebar_width";

export interface UseResizableWidthOptions {
  min?: number;
  max?: number;
  defaultValue?: number;
  storageKey?: string;
  step?: number;
  shiftStep?: number;
  disabled?: boolean;
  cssVariableName?: string;
}

export interface UseResizableWidthReturn {
  width: number;
  isDragging: boolean;
  setWidth: (width: number) => void;
  resetWidth: () => void;
  handleProps: {
    role: "separator";
    "aria-orientation": "vertical";
    "aria-valuenow": number;
    "aria-valuemin": number;
    "aria-valuemax": number;
    "aria-label": string;
    tabIndex: number;
    onPointerDown: (e: React.PointerEvent<HTMLElement>) => void;
    onPointerMove: (e: React.PointerEvent<HTMLElement>) => void;
    onPointerUp: (e: React.PointerEvent<HTMLElement>) => void;
    onPointerCancel: (e: React.PointerEvent<HTMLElement>) => void;
    onLostPointerCapture: (e: React.PointerEvent<HTMLElement>) => void;
    onDoubleClick: (e: React.MouseEvent<HTMLElement>) => void;
    onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => void;
  };
}

function getInitialWidth(
  storageKey: string,
  defaultValue: number,
  min: number,
  max: number,
): number {
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw !== null && raw.trim() !== "") {
      const parsed = Number(raw);
      if (Number.isFinite(parsed)) {
        return Math.min(max, Math.max(min, Math.round(parsed)));
      }
    }
  } catch {
    // localStorage read failure (e.g. security/quota error)
  }
  return defaultValue;
}

function persistWidth(storageKey: string, value: number): void {
  try {
    localStorage.setItem(storageKey, String(value));
  } catch {
    // localStorage write failure
  }
}

export function useResizableWidth(
  options: UseResizableWidthOptions = {},
): UseResizableWidthReturn {
  const {
    min = MIN_SIDEBAR_WIDTH,
    max = MAX_SIDEBAR_WIDTH,
    defaultValue = DEFAULT_SIDEBAR_WIDTH,
    storageKey = SIDEBAR_WIDTH_STORAGE_KEY,
    step = KEYBOARD_STEP,
    shiftStep = KEYBOARD_SHIFT_STEP,
    disabled = false,
    cssVariableName = "--sidebar-width",
  } = options;

  const [width, setWidthState] = useState<number>(() =>
    getInitialWidth(storageKey, defaultValue, min, max),
  );
  const [isDragging, setIsDragging] = useState<boolean>(false);

  const isDraggingRef = useRef<boolean>(false);
  const widthRef = useRef<number>(width);
  const prevUserSelectRef = useRef<string | null>(null);

  useEffect(() => {
    isDraggingRef.current = isDragging;
    widthRef.current = width;
  }, [isDragging, width]);

  const clamp = useCallback(
    (val: number) => Math.min(max, Math.max(min, Math.round(val))),
    [min, max],
  );

  const setWidth = useCallback(
    (newWidth: number) => {
      const clamped = clamp(newWidth);
      setWidthState(clamped);
      persistWidth(storageKey, clamped);
    },
    [clamp, storageKey],
  );

  const resetWidth = useCallback(() => {
    setWidthState(defaultValue);
    persistWidth(storageKey, defaultValue);
  }, [defaultValue, storageKey]);

  // Sync CSS custom property on :root
  useEffect(() => {
    if (disabled) return;
    document.documentElement.style.setProperty(cssVariableName, `${width}px`);
  }, [width, disabled, cssVariableName]);

  // Clean up userSelect if component unmounts during drag
  useEffect(() => {
    return () => {
      if (isDraggingRef.current) {
        document.body.style.userSelect = prevUserSelectRef.current ?? "";
      }
    };
  }, []);

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (disabled) return;
      if (e.button !== undefined && e.button !== 0) return; // primary mouse button only
      e.preventDefault();

      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch {
        // Ignore environments where pointer capture is not supported
      }

      prevUserSelectRef.current = document.body.style.userSelect;
      document.body.style.userSelect = "none";
      isDraggingRef.current = true;
      setIsDragging(true);
    },
    [disabled],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!isDraggingRef.current) return;
      e.preventDefault();
      // Since sidebar is flush against left edge of viewport (x=0), clientX is width
      const nextWidth = clamp(e.clientX);
      widthRef.current = nextWidth;
      setWidthState(nextWidth);
    },
    [clamp],
  );

  const endDrag = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!isDraggingRef.current) return;

      try {
        if (e.currentTarget.hasPointerCapture(e.pointerId)) {
          e.currentTarget.releasePointerCapture(e.pointerId);
        }
      } catch {
        // Ignore
      }

      document.body.style.userSelect = prevUserSelectRef.current ?? "";
      isDraggingRef.current = false;
      setIsDragging(false);
      persistWidth(storageKey, widthRef.current);
    },
    [storageKey],
  );

  const onDoubleClick = useCallback(
    (e: React.MouseEvent<HTMLElement>) => {
      if (disabled) return;
      e.preventDefault();
      resetWidth();
    },
    [disabled, resetWidth],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLElement>) => {
      if (disabled) return;

      let nextWidth: number | null = null;
      if (e.key === "ArrowLeft") {
        nextWidth = width - (e.shiftKey ? shiftStep : step);
      } else if (e.key === "ArrowRight") {
        nextWidth = width + (e.shiftKey ? shiftStep : step);
      } else if (e.key === "Home") {
        nextWidth = min;
      } else if (e.key === "End") {
        nextWidth = max;
      }

      if (nextWidth !== null) {
        e.preventDefault();
        setWidth(nextWidth);
      }
    },
    [disabled, width, step, shiftStep, min, max, setWidth],
  );

  return {
    width,
    isDragging,
    setWidth,
    resetWidth,
    handleProps: {
      role: "separator",
      "aria-orientation": "vertical",
      "aria-valuenow": width,
      "aria-valuemin": min,
      "aria-valuemax": max,
      "aria-label": "Resize sidebar",
      tabIndex: disabled ? -1 : 0,
      onPointerDown,
      onPointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
      onLostPointerCapture: endDrag,
      onDoubleClick,
      onKeyDown,
    },
  };
}
