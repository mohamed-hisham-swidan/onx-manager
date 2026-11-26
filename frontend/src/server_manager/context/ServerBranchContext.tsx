import { createContext, useContext } from "react";
import type { ServerMode } from "@/server_manager/types";

export interface ServerBranchContextValue {
  /** Selected branch name. */
  branch: string;
  /** Select a branch; updates the header selector and branch-scoped pages. */
  setBranch: (branch: string) => void;
  /** True when the server has a native Git repository with branch worktrees. */
  gitBacked: boolean;
  /** Resolved server mode ('simple' | 'advanced'), if provided by ServerShell. */
  serverMode?: ServerMode;
}

export const ServerBranchContext =
  createContext<ServerBranchContextValue | null>(null);

export function useServerBranchContext(): ServerBranchContextValue | null {
  return useContext(ServerBranchContext);
}
