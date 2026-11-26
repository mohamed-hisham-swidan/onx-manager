import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Banner } from "@/components/ui/Banner";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";
import type { LecGcResponse } from "@/server_manager/types";

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 100 || unit === 0 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "Cache cleanup failed";
}

export interface CleanCacheModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: (result: LecGcResponse) => void;
}

export function CleanCacheModal({ open, onClose, onSuccess }: CleanCacheModalProps) {
  const api = createAuthenticatedApi();
  const queryClient = useQueryClient();

  const [minAgeDays, setMinAgeDays] = useState(7);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClose = () => {
    if (isPending) return;
    setError(null);
    onClose();
  };

  async function handleClean(e: React.FormEvent) {
    e.preventDefault();
    if (typeof api.gcLecEntries !== "function") return;
    if (!Number.isFinite(minAgeDays) || minAgeDays < 0 || minAgeDays > 3650) {
      setError("Age must be between 0 and 3650 days.");
      return;
    }

    setIsPending(true);
    setError(null);
    try {
      const result = await api.gcLecEntries({ min_age_days: minAgeDays });
      await queryClient.invalidateQueries({ queryKey: queryKeys.p55.lecEntries() });
      toast(
        "success",
        "Cache cleaned",
        `Removed ${result.pruned_lec_keys.length} loaders, freed ${formatBytes(result.freed_bytes)}.`,
      );
      onSuccess?.(result);
      onClose();
    } catch (err) {
      const msg = errorMessage(err);
      setError(msg);
      toast("error", "Cache cleanup failed", msg);
    } finally {
      setIsPending(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Clean Unused Cache"
      description="Remove cached loader runtimes no longer referenced by servers."
      size="sm"
      closeOnBackdrop={!isPending}
      closeOnEscape={!isPending}
    >
      <form onSubmit={handleClean} className="space-y-4">
        {error && <Banner variant="danger" title="Cleanup failed" description={error} />}

        <div className="flex flex-wrap items-center gap-2 text-sm text-text-secondary">
          <label htmlFor="lec-min-age">Remove cached loaders unused for at least</label>
          <input
            id="lec-min-age"
            type="number"
            min={0}
            max={3650}
            value={minAgeDays}
            onChange={(e) => {
              setError(null);
              setMinAgeDays(Number(e.target.value));
            }}
            className="w-20 rounded-lg border border-border-subtle bg-surface-page px-2.5 py-1 text-center font-mono text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus"
          />
          <span>days.</span>
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-border-subtle">
          <Button type="button" variant="outline" size="sm" disabled={isPending} onClick={handleClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            data-testid="lec-gc-btn"
            variant="danger"
            size="sm"
            icon="trash"
            loading={isPending}
          >
            Clean Cache
          </Button>
        </div>
      </form>
    </Modal>
  );
}
