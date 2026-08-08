import { useEffect, useRef, useCallback } from "react";
import { WSClient } from "@/websocket/client";
import { WSHandler } from "@/websocket/handler";
import type { CacheUpdater } from "@/websocket/handler";
import { ConnectionState } from "@/websocket/types";
import { useAuthStore } from "@/stores/authStore";
import { useWSStore } from "@/stores/wsStore";

interface UseWebSocketOptions {
  url: string;
  onCacheUpdate?: CacheUpdater;
  onEvent?: (event: Record<string, unknown>) => void;
  onStateSync?: (events: Array<Record<string, unknown>>) => void;
  autoConnect?: boolean;
}

/**
 * Module-level bridge to the single active WSClient.
 *
 * WebSocketManager owns the one and only WSClient (it must be a singleton —
 * two clients would open two connections). Other components (e.g.
 * ServerDetailPage) need to subscribe/unsubscribe scoped channels
 * (metrics:<serverId>) without creating a second connection, so they route
 * through these helpers, which delegate to whatever client useWebSocket has
 * registered. No-op until a client is registered.
 */
let activeSubscribe: ((channels: string[]) => void) | null = null;
let activeUnsubscribe: ((channels: string[]) => void) | null = null;

export function subscribeChannels(channels: string[]): void {
  activeSubscribe?.(channels);
}

export function unsubscribeChannels(channels: string[]): void {
  activeUnsubscribe?.(channels);
}

export function useWebSocket({ url, onCacheUpdate, onEvent, onStateSync, autoConnect = true }: UseWebSocketOptions) {
  const accessToken = useAuthStore((s) => s.accessToken);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const setConnectionState = useWSStore((s) => s.setConnectionState);
  const setChannelState = useWSStore((s) => s.setChannelState);
  const removeChannelState = useWSStore((s) => s.removeChannelState);
  const setUnattributedRejection = useWSStore((s) => s.setUnattributedRejection);

  const clientRef = useRef<WSClient | null>(null);
  const handlerRef = useRef<WSHandler | null>(null);

  useEffect(() => {
    if (!autoConnect || !isAuthenticated || !accessToken) return;

    const handler = new WSHandler({ onCacheUpdate, onEvent, onStateSync });
    handlerRef.current = handler;

    const client = new WSClient(
      { url, token: accessToken, autoReconnect: true },
      {
        onStateChange: (state) => {
          setConnectionState(state);
          // A fresh transport connection re-negotiates every subscription
          // (WSClient._resubscribe), so an earlier unattributed rejection no
          // longer describes this connection's fate — clear the
          // global-degraded flag. Per-channel REJECTED states survive (they
          // describe persistent authorization failures until refreshToken()).
          if (state === ConnectionState.CONNECTED) {
            setUnattributedRejection(false);
          }
        },
        onChannelStateChange: (channel, channelState) => {
          if (channelState === null) {
            removeChannelState(channel);
          } else {
            setChannelState(channel, channelState);
          }
        },
      },
    );
    client.setUnattributedRejectionHandler(() => setUnattributedRejection(true));
    handler.attach(client);
    activeSubscribe = (channels) => client.subscribe(channels);
    activeUnsubscribe = (channels) => client.unsubscribe(channels);
    client.connect();
    clientRef.current = client;

    return () => {
      activeSubscribe = null;
      activeUnsubscribe = null;
      client.disconnect();
      clientRef.current = null;
      handlerRef.current = null;
      // The client instance is gone; its channel states no longer describe
      // the next connection. Reset so a fresh connection starts clean
      // (prevents stale REJECTED entries from keeping effective state DEGRADED
      // across a token refresh / reconnect).
      useWSStore.setState({ channelStates: {}, unattributedRejection: false });
    };
  }, [url, accessToken, isAuthenticated, autoConnect, onCacheUpdate, onEvent, onStateSync, setConnectionState, setChannelState, removeChannelState, setUnattributedRejection]);

  const subscribe = useCallback((channels: string[]) => {
    clientRef.current?.subscribe(channels);
  }, []);

  const unsubscribe = useCallback((channels: string[]) => {
    clientRef.current?.unsubscribe(channels);
  }, []);

  const send = useCallback((message: Parameters<WSClient["send"]>[0]) => {
    clientRef.current?.send(message);
  }, []);

  return { subscribe, unsubscribe, send };
}
