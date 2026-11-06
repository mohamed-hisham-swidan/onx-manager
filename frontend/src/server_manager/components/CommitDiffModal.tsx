import React, { useState, useEffect, useCallback, useMemo } from "react";
import { Modal } from "@/components/ui/Modal";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import type { DiffResponse } from "@/server_manager/types";

function getModName(m: string | { filename: string }): string {
  return typeof m === "string" ? m : m.filename;
}

interface CommitDiffModalProps {
  isOpen: boolean;
  onClose: () => void;
  serverId: string;
  fromCommitId: string;
  toCommitId: string;
}

export function CommitDiffModal({
  isOpen,
  onClose,
  serverId,
  fromCommitId,
  toCommitId,
}: CommitDiffModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [diff, setDiff] = useState<DiffResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"summary" | "configs" | "mods" | "env">("summary");

  const loadDiff = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.diffCommits(serverId, fromCommitId, toCommitId);
      setDiff(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load commit diff.";
      setError(msg);
      setDiff(null);
    } finally {
      setIsLoading(false);
    }
  }, [serverId, fromCommitId, toCommitId, api]);

  useEffect(() => {
    let alive = true;
    if (isOpen && fromCommitId && toCommitId) {
      void Promise.resolve().then(() => {
        if (alive) {
          loadDiff();
        }
      });
    }
    return () => {
      alive = false;
    };
  }, [isOpen, fromCommitId, toCommitId, loadDiff]);

  if (!isOpen) return null;

  // Counts for tabs
  const modsAdded = diff?.mods?.added || [];
  const modsRemoved = diff?.mods?.removed || [];
  const modsModified = diff?.mods?.modified || [];
  const totalModChanges = modsAdded.length + modsRemoved.length + modsModified.length;

  const configsAdded: string[] = diff?.configs?.added ? Object.keys(diff.configs.added) : [];
  const configsModified: string[] = diff?.configs?.modified ? Object.keys(diff.configs.modified) : [];
  const configsDeleted: string[] = diff?.configs?.removed ? Object.keys(diff.configs.removed) : [];
  const totalConfigChanges = configsAdded.length + configsModified.length + configsDeleted.length;

  const envAdded: string[] = diff?.env_vars?.added ? Object.keys(diff.env_vars.added) : [];
  const envModified: string[] = diff?.env_vars?.modified ? Object.keys(diff.env_vars.modified) : [];
  const envDeleted: string[] = diff?.env_vars?.removed ? Object.keys(diff.env_vars.removed) : [];
  const totalEnvChanges = envAdded.length + envModified.length + envDeleted.length;

  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Commit Diff Inspector"
      description={
        <span className="font-mono">
          <span className="text-accent-primary font-bold">{fromCommitId.slice(0, 7)}</span>
          {" → "}
          <span className="text-status-success font-bold">{toCommitId.slice(0, 7)}</span>
        </span>
      }
      size="2xl"
      closeOnBackdrop={true}
      closeOnEscape={true}
      closeButtonAriaLabel="Close modal"
    >
      <div className="space-y-4 flex flex-col">

        {/* Error Alert */}
        {error && (
          <div role="alert" className="flex items-center gap-2 rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger">
            <Icon name="alert" size={16} className="shrink-0" />
            <span className="flex-1">{error}</span>
          </div>
        )}

        {/* Tabs */}
        <div role="tablist" className="flex items-center gap-2 border-b border-border-default pb-2 text-xs">
          <button
            type="button"
            aria-selected={activeTab === "summary"}
            onClick={() => setActiveTab("summary")}
            className={`px-3 py-1.5 rounded font-medium transition-colors ${
              activeTab === "summary"
                ? "bg-accent-primary text-accent-contrast-text"
                : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            }`}
          >
            Summary
          </button>
          <button
            type="button"
            aria-selected={activeTab === "configs"}
            onClick={() => setActiveTab("configs")}
            className={`px-3 py-1.5 rounded font-medium transition-colors ${
              activeTab === "configs"
                ? "bg-accent-primary text-accent-contrast-text"
                : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            }`}
          >
            Config Files ({totalConfigChanges})
          </button>
          <button
            type="button"
            aria-selected={activeTab === "mods"}
            onClick={() => setActiveTab("mods")}
            className={`px-3 py-1.5 rounded font-medium transition-colors ${
              activeTab === "mods"
                ? "bg-accent-primary text-accent-contrast-text"
                : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            }`}
          >
            Mods ({totalModChanges})
          </button>
          <button
            type="button"
            aria-selected={activeTab === "env"}
            onClick={() => setActiveTab("env")}
            className={`px-3 py-1.5 rounded font-medium transition-colors ${
              activeTab === "env"
                ? "bg-accent-primary text-accent-contrast-text"
                : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            }`}
          >
            Env Vars ({totalEnvChanges})
          </button>
        </div>

        {/* Diff Content */}
        <div className="flex-1 overflow-y-auto space-y-4 min-h-[280px]">
          {isLoading ? (
            <div className="flex items-center justify-center p-12 text-xs text-text-muted italic">
              Calculating commit diff...
            </div>
          ) : !diff ? (
            <div className="flex items-center justify-center p-12 text-xs text-text-muted italic">
              No diff data available.
            </div>
          ) : (
            <>
              {/* SUMMARY TAB */}
              {activeTab === "summary" && (
                <div className="space-y-4 text-xs">
                  {/* Runtime Changes */}
                  <div className="rounded-lg border border-border-default p-4 bg-surface-card space-y-3">
                    <h3 className="font-semibold text-text-primary">
                      Runtime Environment
                    </h3>
                    <div className="grid grid-cols-2 gap-3 font-mono">
                      <div className="p-2.5 rounded bg-surface-muted border border-border-default">
                        <span className="text-text-muted block text-[11px]">Server Type</span>
                        {diff.server_type ? (
                          <div className="mt-0.5">
                            <span className="text-status-danger line-through mr-2">
                              {diff.server_type.from || "none"}
                            </span>
                            <span className="text-status-success font-bold">
                              {diff.server_type.to || "none"}
                            </span>
                          </div>
                        ) : (
                          <span className="text-text-secondary">Unchanged</span>
                        )}
                      </div>

                      <div className="p-2.5 rounded bg-surface-muted border border-border-default">
                        <span className="text-text-muted block text-[11px]">Minecraft Version</span>
                        {diff.minecraft_version ? (
                          <div className="mt-0.5">
                            <span className="text-status-danger line-through mr-2">
                              {diff.minecraft_version.from || "none"}
                            </span>
                            <span className="text-status-success font-bold">
                              {diff.minecraft_version.to || "none"}
                            </span>
                          </div>
                        ) : (
                          <span className="text-text-secondary">Unchanged</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Summary Metric Cards */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className="p-3 rounded-lg border border-border-default bg-surface-card text-center">
                      <span className="text-[11px] text-text-muted block">Config Changes</span>
                      <span className="text-lg font-bold text-text-primary">
                        {totalConfigChanges}
                      </span>
                    </div>
                    <div className="p-3 rounded-lg border border-border-default bg-surface-card text-center">
                      <span className="text-[11px] text-text-muted block">Mod Changes</span>
                      <span className="text-lg font-bold text-text-primary">
                        {totalModChanges}
                      </span>
                    </div>
                    <div className="p-3 rounded-lg border border-border-default bg-surface-card text-center">
                      <span className="text-[11px] text-text-muted block">Env Var Changes</span>
                      <span className="text-lg font-bold text-text-primary">
                        {totalEnvChanges}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* CONFIGS TAB */}
              {activeTab === "configs" && (
                <div className="space-y-3 text-xs">
                  {totalConfigChanges === 0 ? (
                    <div className="p-8 text-center text-text-muted italic">
                      No configuration file modifications between these commits.
                    </div>
                  ) : (
                    <>
                      {configsAdded.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-status-success block mb-1">
                            Added Files ({configsAdded.length})
                          </span>
                          <div className="space-y-1 font-mono">
                            {configsAdded.map((path) => (
                              <div key={path} className="p-2 rounded bg-status-success-bg border border-status-success-border text-status-success">
                                + {path}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {configsModified.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-status-warning block mb-1">
                            Modified Files ({configsModified.length})
                          </span>
                          <div className="space-y-1 font-mono">
                            {configsModified.map((path) => (
                              <div key={path} className="p-2 rounded bg-status-warning-bg border border-status-warning-border text-status-warning">
                                ~ {path}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {configsDeleted.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-status-danger block mb-1">
                            Deleted Files ({configsDeleted.length})
                          </span>
                          <div className="space-y-1 font-mono">
                            {configsDeleted.map((path) => (
                              <div key={path} className="p-2 rounded bg-status-danger-bg border border-status-danger-border text-status-danger">
                                - {path}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* MODS TAB */}
              {activeTab === "mods" && (
                <div className="space-y-3 text-xs">
                  {totalModChanges === 0 ? (
                    <div className="p-8 text-center text-text-muted italic">
                      No mod changes between these commits.
                    </div>
                  ) : (
                    <>
                      {modsAdded.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-status-success block mb-1">
                            Added Mods ({modsAdded.length})
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {modsAdded.map((mod, idx) => {
                              const name = getModName(mod);
                              return (
                                <span key={`${name}-${idx}`} className="px-2 py-1 rounded bg-status-success-bg text-status-success border border-status-success-border font-mono text-[11px]">
                                  + {name}
                                </span>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {modsRemoved.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-status-danger block mb-1">
                            Removed Mods ({modsRemoved.length})
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {modsRemoved.map((mod, idx) => {
                              const name = getModName(mod);
                              return (
                                <span key={`${name}-${idx}`} className="px-2 py-1 rounded bg-status-danger-bg text-status-danger border border-status-danger-border font-mono text-[11px]">
                                  - {name}
                                </span>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {modsModified.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-status-warning block mb-1">
                            Updated Mods ({modsModified.length})
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {modsModified.map((mod, idx) => {
                              const name = getModName(mod);
                              return (
                                <span key={`${name}-${idx}`} className="px-2 py-1 rounded bg-status-warning-bg text-status-warning border border-status-warning-border font-mono text-[11px]">
                                  ~ {name}
                                </span>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* ENV VARS TAB */}
              {activeTab === "env" && (
                <div className="space-y-3 text-xs">
                  {totalEnvChanges === 0 ? (
                    <div className="p-8 text-center text-text-muted italic">
                      No environment variable differences between these commits.
                    </div>
                  ) : (
                    <>
                      {envAdded.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-status-success block mb-1">
                            Added Variables ({envAdded.length})
                          </span>
                          <div className="space-y-1 font-mono">
                            {envAdded.map((key) => (
                              <div key={key} className="p-2 rounded bg-status-success-bg border border-status-success-border text-status-success">
                                + {key} = {diff.env_vars?.added?.[key]}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {envModified.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-status-warning block mb-1">
                            Modified Variables ({envModified.length})
                          </span>
                          <div className="space-y-1 font-mono">
                            {envModified.map((key) => {
                              const change = diff.env_vars?.modified?.[key] as
                                | { from?: string; to?: string }
                                | Record<string, string>
                                | undefined;
                              const fromVal = change && "from" in change ? change.from : "";
                              const toVal = change && "to" in change ? change.to : "";
                              return (
                                <div key={key} className="p-2 rounded bg-status-warning-bg border border-status-warning-border text-status-warning">
                                  ~ {key}: <span className="line-through text-status-danger mr-1">{fromVal}</span> → <span className="font-bold text-status-success">{toVal}</span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {envDeleted.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-status-danger block mb-1">
                            Deleted Variables ({envDeleted.length})
                          </span>
                          <div className="space-y-1 font-mono">
                            {envDeleted.map((key) => (
                              <div key={key} className="p-2 rounded bg-status-danger-bg border border-status-danger-border text-status-danger">
                                - {key}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end border-t border-border-default pt-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-muted hover:bg-surface-hover border border-border-default rounded-lg transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </Modal>
  );
}
