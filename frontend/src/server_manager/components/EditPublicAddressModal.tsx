import { useState, useRef, useEffect } from "react";
import { Icon } from "@/components/ui/Icon";
import type { TargetResponse } from "@/types";

export interface EditPublicAddressModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (publicAddress: string) => Promise<void> | void;
  target: TargetResponse | null;
  isSubmitting?: boolean;
}

// Regex for <host>:<port> or hostname:port / IP:port / FQDN (F-75-14)
const PUBLIC_ADDRESS_REGEX = /^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*|\d{1,3}(\.\d{1,3}){3})(:\d{1,5})?$/;

function validatePublicAddress(addr: string): { valid: boolean; error?: string } {
  const trimmed = addr.trim();
  if (!trimmed) {
    return { valid: false, error: "Public address is required." };
  }
  if (trimmed.length > 512) {
    return { valid: false, error: "Address cannot exceed 512 characters." };
  }
  if (!PUBLIC_ADDRESS_REGEX.test(trimmed)) {
    return {
      valid: false,
      error: "Please enter a valid address in <host>:<port> or domain format (e.g. custom.ply.gg:12345).",
    };
  }
  return { valid: true };
}

export function EditPublicAddressModal({
  isOpen,
  onClose,
  onSubmit,
  target,
  isSubmitting = false,
}: EditPublicAddressModalProps) {
  const [address, setAddress] = useState(target?.public_address || "");
  const [prevTargetId, setPrevTargetId] = useState<string | null>(null);

  // Sync state during rendering when target changes (React 19 pattern)
  if (target && target.id !== prevTargetId) {
    setPrevTargetId(target.id);
    setAddress(target.public_address || "");
  }

  const modalRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validation = validatePublicAddress(address);

  // Focus trapping & restoration (F-75-16)
  useEffect(() => {
    if (!isOpen) return;

    const previousFocusedElement = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }

      if (e.key === "Tab" && modalRef.current) {
        const focusableElements = modalRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusableElements.length === 0) return;

        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey && document.activeElement === firstElement) {
          e.preventDefault();
          lastElement.focus();
        } else if (!e.shiftKey && document.activeElement === lastElement) {
          e.preventDefault();
          firstElement.focus();
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocusedElement?.focus();
    };
  }, [isOpen, onClose]);

  if (!isOpen || !target) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validation.valid || isSubmitting) return;

    await onSubmit(address.trim());
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="edit-address-modal-title"
    >
      <div
        ref={modalRef}
        className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-xl dark:border-gray-700 dark:bg-gray-800 space-y-4"
      >
        <div className="flex items-center justify-between border-b border-gray-200 pb-3 dark:border-gray-700">
          <div>
            <h3
              id="edit-address-modal-title"
              className="text-base font-semibold text-gray-900 dark:text-gray-100"
            >
              Update Public Address
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              Service: <span className="font-semibold uppercase">{target.service_type}</span> ({target.protocol.toUpperCase()} {target.local_port})
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 dark:hover:text-gray-200 transition-colors"
          >
            <Icon name="x" size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label
              htmlFor="public-address-input"
              className="block text-xs font-semibold text-gray-700 dark:text-gray-300"
            >
              Public Address <span className="text-red-500">*</span>
            </label>
            <input
              ref={inputRef}
              id="public-address-input"
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="e.g. custom.ply.gg:12345 or 147.185.221.16:25565"
              className={`w-full px-3 py-2 rounded-lg border bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all ${
                !validation.valid && address
                  ? "border-red-500 dark:border-red-500"
                  : "border-gray-300 dark:border-gray-600"
              }`}
            />

            {!validation.valid && address ? (
              <p className="text-[11px] text-red-600 dark:text-red-400 flex items-center gap-1">
                <Icon name="alert" size={12} className="shrink-0" />
                <span>{validation.error}</span>
              </p>
            ) : (
              <p className="text-[11px] text-gray-500 dark:text-gray-400">
                Paste the allocated public domain or IP:port from your tunnel provider.
              </p>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-3 border-t border-gray-200 dark:border-gray-700">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!validation.valid || isSubmitting}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
            >
              {isSubmitting ? "Saving Address..." : "Save Address"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
