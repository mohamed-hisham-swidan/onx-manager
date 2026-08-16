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
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-gray-200 pb-3 dark:border-gray-700">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              Service Targets & Port Mappings
            </h3>
            <span className="font-mono text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 font-medium">
              {targets.length} {targets.length === 1 ? "Target" : "Targets"}
            </span>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            Configured protocol ports and live public addresses for this server.
          </p>
        </div>

        {!isReadOnly && isEnabled && (
          <button
            type="button"
            onClick={() => setIsAddModalOpen(true)}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors shadow-sm"
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
        <div className="rounded-xl border border-dashed border-gray-300 p-8 text-center dark:border-gray-700">
          <Icon name="activity" size={28} className="mx-auto text-gray-400 dark:text-gray-500 mb-2" />
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
            No active targets configured
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 max-w-sm mx-auto">
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
