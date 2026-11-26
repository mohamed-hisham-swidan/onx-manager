import { useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { TargetCard } from "@/server_manager/components/TargetCard";
import { AddCompanionTargetModal } from "@/server_manager/components/AddCompanionTargetModal";
import { EditPublicAddressModal } from "@/server_manager/components/EditPublicAddressModal";
import type {
  ServerExposureResponse,
  TargetResponse,
  TargetCreateRequest,
} from "@/types";

export interface TargetListSectionProps {
  exposure: ServerExposureResponse | null | undefined;
  serverGamePort?: number;
  onCreateTarget: (data: TargetCreateRequest) => Promise<void> | void;
  onUpdateTargetAddress: (params: { targetId: string; publicAddress: string }) => Promise<void> | void;
  onDeleteTarget: (targetId: string) => Promise<void> | void;
  isCreatingTarget?: boolean;
  isUpdatingTargetAddress?: boolean;
  isDeletingTarget?: boolean;
  isReadOnly?: boolean;
}

export function TargetListSection({
  exposure,
  serverGamePort = 25565,
  onCreateTarget,
  onUpdateTargetAddress,
  onDeleteTarget,
  isCreatingTarget = false,
  isUpdatingTargetAddress = false,
  isReadOnly = false,
}: TargetListSectionProps) {
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [editingTarget, setEditingTarget] = useState<TargetResponse | null>(null);

  const targets = exposure?.targets || [];
  const isEnabled = exposure?.desired_state === "ENABLED";
  const existingServiceTypes = targets.map((t) => t.service_type);

  const handleAddSubmit = async (data: TargetCreateRequest) => {
    await onCreateTarget(data);
    setIsAddModalOpen(false);
  };

  const handleEditSubmit = async (publicAddress: string) => {
    if (!editingTarget) return;
    await onUpdateTargetAddress({
      targetId: editingTarget.id,
      publicAddress,
    });
    setEditingTarget(null);
  };

  return (
    <div className="space-y-4">
      {/* Section Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border-default pb-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-text-primary">
              Service Targets & Port Mappings
            </h3>
            <span className="font-mono text-xs px-2 py-0.5 rounded-full bg-surface-muted text-text-secondary font-medium">
              {targets.length} {targets.length === 1 ? "Target" : "Targets"}
            </span>
          </div>
        </div>

        {!isReadOnly && isEnabled && (
          <button
            type="button"
            onClick={() => setIsAddModalOpen(true)}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium transition-colors shadow-xs"
          >
            <Icon name="plus" size={14} />
            <span>Add Companion Target</span>
          </button>
        )}
      </div>

      {/* Targets List */}
      {targets.length > 0 ? (
        <div className="grid grid-cols-1 gap-3">
          {targets.map((target) => (
            <TargetCard
              key={target.id}
              target={target}
              onEditAddress={(t) => setEditingTarget(t)}
              onRemoveTarget={(targetId) => onDeleteTarget(targetId)}
              isReadOnly={isReadOnly}
            />
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-border-default p-8 text-center">
          <Icon name="activity" size={28} className="mx-auto text-text-muted mb-2" />
          <p className="text-sm font-medium text-text-secondary">
            No active targets configured
          </p>
          <p className="text-xs text-text-muted mt-1 max-w-sm mx-auto">
            {isEnabled
              ? "Select an exposure method and apply changes to provision primary Java and companion service targets."
              : "Enable an exposure method above to publish this server to the internet."}
          </p>
        </div>
      )}

      {/* Add Companion Target Modal */}
      <AddCompanionTargetModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onSubmit={handleAddSubmit}
        serverGamePort={serverGamePort}
        existingServiceTypes={existingServiceTypes}
        isSubmitting={isCreatingTarget}
      />

      {/* Edit Public Address Modal */}
      <EditPublicAddressModal
        isOpen={Boolean(editingTarget)}
        onClose={() => setEditingTarget(null)}
        onSubmit={handleEditSubmit}
        target={editingTarget}
        isSubmitting={isUpdatingTargetAddress}
      />
    </div>
  );
}
