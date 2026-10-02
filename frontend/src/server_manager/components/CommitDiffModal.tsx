import React, { useState, useEffect, useCallback, useMemo } from "react";
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

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

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
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="diff-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-3xl max-h-[85vh] flex flex-col rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-800 p-6 space-y-4 text-gray-900 dark:text-gray-100 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 pb-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-400">
              <Icon name="activity" size={20} />
            </div>
            <div>
              <h2
                id="diff-modal-title"
                className="text-lg font-semibold text-gray-900 dark:text-white"
              >
                Commit Diff Inspector
              </h2>
              <p className="text-xs text-gray-500 dark:text-gray-400 font-mono">
                <span className="text-indigo-600 dark:text-indigo-400 font-bold">{fromCommitId.slice(0, 7)}</span>
                {" → "}
                <span className="text-emerald-600 dark:text-emerald-400 font-bold">{toCommitId.slice(0, 7)}</span>
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 dark:hover:text-gray-300 transition-colors"
            aria-label="Close modal"
          >
            <Icon name="x" size={18} />
          </button>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
            <Icon name="alert" size={16} className="shrink-0" />
            <span className="flex-1">{error}</span>
          </div>
        )}

        {/* Tabs */}
        <div className="flex items-center gap-2 border-b border-gray-200 dark:border-gray-700 pb-2 text-xs">
          <button
            type="button"
            onClick={() => setActiveTab("summary")}
            className={`px-3 py-1.5 rounded font-medium transition-colors ${
              activeTab === "summary"
                ? "bg-indigo-600 text-white"
                : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
            }`}
          >
            Summary
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("configs")}
            className={`px-3 py-1.5 rounded font-medium transition-colors ${
              activeTab === "configs"
                ? "bg-indigo-600 text-white"
                : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
            }`}
          >
            Config Files ({totalConfigChanges})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("mods")}
            className={`px-3 py-1.5 rounded font-medium transition-colors ${
              activeTab === "mods"
                ? "bg-indigo-600 text-white"
                : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
            }`}
          >
            Mods ({totalModChanges})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("env")}
            className={`px-3 py-1.5 rounded font-medium transition-colors ${
              activeTab === "env"
                ? "bg-indigo-600 text-white"
                : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
            }`}
          >
            Env Vars ({totalEnvChanges})
          </button>
        </div>

        {/* Diff Content */}
        <div className="flex-1 overflow-y-auto space-y-4 min-h-[280px]">
          {isLoading ? (
            <div className="flex items-center justify-center p-12 text-xs text-gray-400 italic">
              Calculating commit diff...
            </div>
          ) : !diff ? (
            <div className="flex items-center justify-center p-12 text-xs text-gray-400 italic">
              No diff data available.
            </div>
          ) : (
            <>
              {/* SUMMARY TAB */}
              {activeTab === "summary" && (
                <div className="space-y-4 text-xs">
                  {/* Runtime Changes */}
                  <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 bg-gray-50/50 dark:bg-gray-900/30 space-y-3">
                    <h3 className="font-semibold text-gray-800 dark:text-gray-200">
                      Runtime Environment
                    </h3>
                    <div className="grid grid-cols-2 gap-3 font-mono">
                      <div className="p-2.5 rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
                        <span className="text-gray-400 block text-[11px]">Server Type</span>
                        {diff.server_type ? (
                          <div className="mt-0.5">
                            <span className="text-red-500 line-through mr-2">
                              {diff.server_type.from || "none"}
                            </span>
                            <span className="text-emerald-500 font-bold">
                              {diff.server_type.to || "none"}
                            </span>
                          </div>
                        ) : (
                          <span className="text-gray-600 dark:text-gray-300">Unchanged</span>
                        )}
                      </div>

                      <div className="p-2.5 rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
                        <span className="text-gray-400 block text-[11px]">Minecraft Version</span>
                        {diff.minecraft_version ? (
                          <div className="mt-0.5">
                            <span className="text-red-500 line-through mr-2">
                              {diff.minecraft_version.from || "none"}
                            </span>
                            <span className="text-emerald-500 font-bold">
                              {diff.minecraft_version.to || "none"}
                            </span>
                          </div>
                        ) : (
                          <span className="text-gray-600 dark:text-gray-300">Unchanged</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Summary Metric Cards */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className="p-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-center">
                      <span className="text-[11px] text-gray-400 block">Config Changes</span>
                      <span className="text-lg font-bold text-gray-900 dark:text-white">
                        {totalConfigChanges}
                      </span>
                    </div>
                    <div className="p-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-center">
                      <span className="text-[11px] text-gray-400 block">Mod Changes</span>
                      <span className="text-lg font-bold text-gray-900 dark:text-white">
                        {totalModChanges}
                      </span>
                    </div>
                    <div className="p-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-center">
                      <span className="text-[11px] text-gray-400 block">Env Var Changes</span>
                      <span className="text-lg font-bold text-gray-900 dark:text-white">
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
                    <div className="p-8 text-center text-gray-400 italic">
                      No configuration file modifications between these commits.
                    </div>
                  ) : (
                    <>
                      {configsAdded.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 block mb-1">
                            Added Files ({configsAdded.length})
                          </span>
                          <div className="space-y-1 font-mono">
                            {configsAdded.map((path) => (
                              <div key={path} className="p-2 rounded bg-emerald-50/50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-900/50 text-emerald-700 dark:text-emerald-300">
                                + {path}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {configsModified.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-amber-600 dark:text-amber-400 block mb-1">
                            Modified Files ({configsModified.length})
                          </span>
                          <div className="space-y-1 font-mono">
                            {configsModified.map((path) => (
                              <div key={path} className="p-2 rounded bg-amber-50/50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/50 text-amber-700 dark:text-amber-300">
                                ~ {path}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {configsDeleted.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-red-600 dark:text-red-400 block mb-1">
                            Deleted Files ({configsDeleted.length})
                          </span>
                          <div className="space-y-1 font-mono">
                            {configsDeleted.map((path) => (
                              <div key={path} className="p-2 rounded bg-red-50/50 dark:bg-red-950/20 border border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-300">
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
                    <div className="p-8 text-center text-gray-400 italic">
                      No mod changes between these commits.
                    </div>
                  ) : (
                    <>
                      {modsAdded.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 block mb-1">
                            Added Mods ({modsAdded.length})
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {modsAdded.map((mod, idx) => {
                              const name = getModName(mod);
                              return (
                                <span key={`${name}-${idx}`} className="px-2 py-1 rounded bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 font-mono text-[11px]">
                                  + {name}
                                </span>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {modsRemoved.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-red-600 dark:text-red-400 block mb-1">
                            Removed Mods ({modsRemoved.length})
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {modsRemoved.map((mod, idx) => {
                              const name = getModName(mod);
                              return (
                                <span key={`${name}-${idx}`} className="px-2 py-1 rounded bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-300 font-mono text-[11px]">
                                  - {name}
                                </span>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {modsModified.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-amber-600 dark:text-amber-400 block mb-1">
                            Updated Mods ({modsModified.length})
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {modsModified.map((mod, idx) => {
                              const name = getModName(mod);
                              return (
                                <span key={`${name}-${idx}`} className="px-2 py-1 rounded bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 font-mono text-[11px]">
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
                    <div className="p-8 text-center text-gray-400 italic">
                      No environment variable differences between these commits.
                    </div>
                  ) : (
                    <>
                      {envAdded.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 block mb-1">
                            Added Variables ({envAdded.length})
                          </span>
                          <div className="space-y-1 font-mono">
                            {envAdded.map((key) => (
                              <div key={key} className="p-2 rounded bg-emerald-50/50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-900/50 text-emerald-700 dark:text-emerald-300">
                                + {key} = {diff.env_vars?.added?.[key]}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {envModified.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-amber-600 dark:text-amber-400 block mb-1">
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
                                <div key={key} className="p-2 rounded bg-amber-50/50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/50 text-amber-700 dark:text-amber-300">
                                  ~ {key}: <span className="line-through text-red-500 mr-1">{fromVal}</span> → <span className="font-bold text-emerald-500">{toVal}</span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {envDeleted.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-red-600 dark:text-red-400 block mb-1">
                            Deleted Variables ({envDeleted.length})
                          </span>
                          <div className="space-y-1 font-mono">
                            {envDeleted.map((key) => (
                              <div key={key} className="p-2 rounded bg-red-50/50 dark:bg-red-950/20 border border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-300">
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
        <div className="flex items-center justify-end border-t border-gray-100 dark:border-gray-800 pt-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
