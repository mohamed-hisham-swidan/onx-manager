import { useState, useRef, useEffect } from "react";
import { Icon } from "@/components/ui/Icon";
import {
  SERVICE_METADATA,
  validateLocalPort,
  type ServiceType,
  type TargetCreateRequest,
} from "@/types";

export interface AddCompanionTargetModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: TargetCreateRequest) => Promise<void> | void;
  serverGamePort?: number;
  existingServiceTypes?: string[];
  isSubmitting?: boolean;
}

const COMPANION_SERVICES: Array<Exclude<ServiceType, "java">> = [
  "bedrock",
  "voice",
  "bluemap",
];

export function AddCompanionTargetModal({
  isOpen,
  onClose,
  onSubmit,
  serverGamePort = 25565,
  existingServiceTypes = [],
  isSubmitting = false,
}: AddCompanionTargetModalProps) {
  const [selectedService, setSelectedService] = useState<Exclude<ServiceType, "java">>("bedrock");
  const [port, setPort] = useState<number>(SERVICE_METADATA.bedrock.defaultPort);
  const [customPortStr, setCustomPortStr] = useState<string>(
    String(SERVICE_METADATA.bedrock.defaultPort)
  );

  const modalRef = useRef<HTMLDivElement>(null);
  const firstInputRef = useRef<HTMLInputElement>(null);

  // Sync default port when service selection changes
  const handleSelectService = (service: Exclude<ServiceType, "java">) => {
    setSelectedService(service);
    const defPort = SERVICE_METADATA[service].defaultPort;
    setPort(defPort);
    setCustomPortStr(String(defPort));
  };

  const handlePortChange = (valStr: string) => {
    setCustomPortStr(valStr);
    const parsed = parseInt(valStr, 10);
    setPort(isNaN(parsed) ? 0 : parsed);
  };

  // Validation
  const validation = validateLocalPort(port, serverGamePort);
  const isAlreadyAdded = existingServiceTypes.includes(selectedService);
  const isValid = validation.valid && !isAlreadyAdded;

  // Focus trapping & restoration (F-75-16)
  useEffect(() => {
    if (!isOpen) return;

    const previousFocusedElement = document.activeElement as HTMLElement | null;
    firstInputRef.current?.focus();

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

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValid || isSubmitting) return;

    await onSubmit({
      service_type: selectedService,
      protocol: SERVICE_METADATA[selectedService].defaultProtocol,
      local_port: port,
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="add-target-modal-title"
    >
      <div
        ref={modalRef}
        className="w-full max-w-lg rounded-xl border border-gray-200 bg-white p-6 shadow-xl dark:border-gray-700 dark:bg-gray-800 space-y-5"
      >
        <div className="flex items-center justify-between border-b border-gray-200 pb-3 dark:border-gray-700">
          <div>
            <h3
              id="add-target-modal-title"
              className="text-base font-semibold text-gray-900 dark:text-gray-100"
            >
              Add Companion Service Target
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              Expose additional game services like Bedrock cross-play, voice chat, or web maps.
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
          {/* Service Selector */}
          <div className="space-y-2">
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-700 dark:text-gray-300">
              Select Companion Service
            </label>
            <div className="grid grid-cols-1 gap-2.5">
              {COMPANION_SERVICES.map((srv) => {
                const meta = SERVICE_METADATA[srv];
                const isSelected = selectedService === srv;
                const alreadyConfigured = existingServiceTypes.includes(srv);

                return (
                  <button
                    key={srv}
                    type="button"
                    onClick={() => handleSelectService(srv)}
                    className={`flex items-start justify-between p-3 rounded-lg border text-left transition-all ${
                      isSelected
                        ? "border-blue-500 bg-blue-50/50 dark:border-blue-500 dark:bg-blue-900/20 shadow-sm"
                        : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 bg-white dark:bg-gray-800"
                    } ${alreadyConfigured ? "opacity-75" : ""}`}
                  >
                    <div className="space-y-0.5">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-gray-900 dark:text-gray-100">
                          {meta.label}
                        </span>
                        <span className="text-[10px] font-mono font-medium px-1.5 py-0.5 rounded bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 uppercase">
                          {meta.defaultProtocol}
                        </span>
                        {alreadyConfigured && (
                          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                            Already Configured
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-gray-500 dark:text-gray-400">
                        {meta.description}
                      </p>
                    </div>
                    <span className="font-mono text-xs font-semibold text-gray-600 dark:text-gray-300 shrink-0 ml-2">
                      Port {meta.defaultPort}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Note on Primary Java Edition immutability (F-75-13) */}
            <p className="text-[11px] text-gray-500 dark:text-gray-400 italic pt-1">
              Note: The primary Java Edition server target is managed automatically by the exposure method and cannot be added as a companion.
            </p>
          </div>

          {/* Local Port Field */}
          <div className="space-y-1.5">
            <label
              htmlFor="target-local-port"
              className="block text-xs font-semibold text-gray-700 dark:text-gray-300"
            >
              Local Service Port <span className="text-red-500">*</span>
            </label>
            <input
              ref={firstInputRef}
              id="target-local-port"
              type="number"
              min={1}
              max={65535}
              value={customPortStr}
              onChange={(e) => handlePortChange(e.target.value)}
              placeholder="e.g. 19132"
              className={`w-full px-3 py-2 rounded-lg border bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all ${
                !validation.valid
                  ? "border-red-500 dark:border-red-500"
                  : "border-gray-300 dark:border-gray-600"
              }`}
            />

            {!validation.valid && (
              <p className="text-[11px] text-red-600 dark:text-red-400 flex items-center gap-1">
                <Icon name="alert" size={12} className="shrink-0" />
                <span>{validation.error}</span>
              </p>
            )}

            {isAlreadyAdded && (
              <p className="text-[11px] text-amber-600 dark:text-amber-400 flex items-center gap-1">
                <Icon name="alert" size={12} className="shrink-0" />
                <span>A target for {SERVICE_METADATA[selectedService].label} is already active on this server.</span>
              </p>
            )}
          </div>

          {/* Actions */}
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
              disabled={!isValid || isSubmitting}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
            >
              {isSubmitting ? "Creating Target..." : "Add Target"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
