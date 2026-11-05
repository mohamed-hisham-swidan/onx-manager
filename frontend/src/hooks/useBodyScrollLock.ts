import { useEffect } from "react";

let openLockCount = 0;
let previousBodyOverflow = "";

export function useBodyScrollLock(active: boolean): void {
  useEffect(() => {
    if (!active) return;

    if (openLockCount === 0) {
      previousBodyOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    openLockCount += 1;

    return () => {
      openLockCount = Math.max(0, openLockCount - 1);
      if (openLockCount === 0) {
        document.body.style.overflow = previousBodyOverflow;
        previousBodyOverflow = "";
      }
    };
  }, [active]);
}
