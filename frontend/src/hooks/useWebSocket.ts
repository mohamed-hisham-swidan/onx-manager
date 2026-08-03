import { useEffect, useRef, useCallback } from "react";
import { WSClient } from "@/websocket/client";
import { WSHandler } from "@/websocket/handler";
import type { CacheUpdater } from "@/websocket/handler";
import { useAuthStore } from "@/stores/authStore";
import { useWSStore } from "@/stores/wsStore";

interface UseWebSocketOptions {
  url: string;
  onCacheUpdate?: CacheUpdater;
  onEvent?: (event: Record<string, unknown>) => void;
  onStateSync?: (events: Array<Record<string, unknown>>) => void;
  autoConnect?: boolean;
}

export function useWebSocket({ url, onCacheUpdate, onEvent, onStateSync, autoConnect = true }: UseWebSocketOptions) {
  const accessToken = useAuthStore((s) => s.accessToken);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const setConnectionState = useWSStore((s) => s.setConnectionState);

  const clientRef = useRef<WSClient | null>(null);
  const handlerRef = useRef<WSHandler | null>(null);

  useEffect(() => {
    if (!autoConnect || !isAuthenticated || !accessToken) return;

    const handler = new WSHandler({ onCacheUpdate, onEvent, onStateSync });
    handlerRef.current = handler;

    const client = new WSClient(
      { url, token: accessToken, autoReconnect: true },
      {
        onStateChange: (state) => setConnectionState(state),
      },
    );
    handler.attach(client);
    client.connect();
    clientRef.current = client;

    return () => {
      client.disconnect();
      clientRef.current = null;
      handlerRef.current = null;
    };
  }, [url, accessToken, isAuthenticated, autoConnect, onCacheUpdate, onEvent, onStateSync, setConnectionState]);

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
