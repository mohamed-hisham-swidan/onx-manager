import { create } from "zustand";
import type { ChannelState, ChannelStatus, ConnectionState } from "@/websocket/types";
import { ChannelStatus as CH, ConnectionState as CS } from "@/websocket/types";

interface WSState {
  /** Raw transport connection state — NEVER set to DEGRADED by this store. */
  connectionState: ConnectionState;
  connected: boolean;
  /** Per-channel subscription states, mirrored from WSClient emissions. */
  channelStates: Record<string, ChannelState>;
  /**
   * True when a PERMISSION_DENIED arrived whose channel could not be parsed
   * (see WSClient's unattributed-rejection handler). The affected
   * subscription's fate is unknown, so effective state degrades globally.
   */
  unattributedRejection: boolean;

  setConnectionState: (state: ConnectionState) => void;
  setChannelState: (channel: string, state: ChannelState) => void;
  removeChannelState: (channel: string) => void;
  setUnattributedRejection: (value: boolean) => void;
}

export const useWSStore = create<WSState>((set) => ({
  connectionState: CS.DISCONNECTED,
  connected: false,
  channelStates: {},
  unattributedRejection: false,

  setConnectionState: (connectionState) =>
    set({ connectionState, connected: connectionState === CS.CONNECTED }),

  setChannelState: (channel, state) =>
    set((s) => ({ channelStates: { ...s.channelStates, [channel]: state } })),

  removeChannelState: (channel) =>
    set((s) => {
      if (!(channel in s.channelStates)) return s;
      const next = { ...s.channelStates };
      delete next[channel];
      return { channelStates: next };
    }),

  setUnattributedRejection: (unattributedRejection) => set({ unattributedRejection }),
}));

function anyChannelUnhealthy(channelStates: Record<string, ChannelState>): boolean {
  return Object.values(channelStates).some(
    (state) => state.status === CH.REJECTED || state.status === CH.RETRYING,
  );
}

/**
 * Effective connection state including subscription health.
 *
 * DEGRADED is a DERIVED state, never written back into the raw
 * `connectionState` field: transport states (DISCONNECTED/CONNECTING/
 * RECONNECTING) always take precedence — a disconnected transport is simply
 * disconnected, not "degraded". Only when the transport is CONNECTED do
 * unhealthy channels (REJECTED/RETRYING) or an unattributed rejection elevate
 * the effective state to DEGRADED.
 */
export function computeEffectiveConnectionState(
  connectionState: ConnectionState,
  channelStates: Record<string, ChannelState>,
  unattributedRejection: boolean,
): ConnectionState {
  if (connectionState !== CS.CONNECTED) return connectionState;
  if (unattributedRejection || anyChannelUnhealthy(channelStates)) {
    return CS.DEGRADED;
  }
  return connectionState;
}

/**
 * A channel query matches a tracked channel by exact name, by segment prefix
 * (query ending with ":", e.g. "server:" matches "server:s01"), or by wildcard
 * (query ending with ":*", e.g. "server:*" matches "server:s01"). This mirrors
 * the prefix semantics already used by ChannelManager helpers
 * (isServerChannel etc.) and the wildcard subscriptions the backend supports.
 */
function channelMatchesQuery(query: string, channel: string): boolean {
  if (query === channel) return true;
  if (query.endsWith(":*")) return channel.startsWith(query.slice(0, -1));
  if (query.endsWith(":")) return channel.startsWith(query);
  return false;
}

/** Status of a single channel as mirrored in the store, or undefined if unknown. */
export function useChannelStatus(channel: string): ChannelStatus | undefined {
  return useWSStore((s) => s.channelStates[channel]?.status);
}

/** True if any channel matching the query (exact/prefix/wildcard) is unhealthy. */
export function useIsChannelDegraded(channelPrefixOrName: string): boolean {
  return useWSStore((s) =>
    Object.values(s.channelStates).some(
      (state) =>
        (state.status === CH.REJECTED || state.status === CH.RETRYING) &&
        channelMatchesQuery(channelPrefixOrName, state.channel),
    ),
  );
}

/** Effective connection state including subscription health (DEGRADED-aware). */
export function useEffectiveConnectionState(): ConnectionState {
  return useWSStore((s) =>
    computeEffectiveConnectionState(s.connectionState, s.channelStates, s.unattributedRejection),
  );
}
