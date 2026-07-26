import { useEffect, useRef, useCallback } from "react";
import { WSClient } from "@/websocket/client";
import { WSHandler } from "@/websocket/handler";
import type { CacheUpdater } from "@/websocket/handler";
import { useAuthStore } from "@/stores/authStore";
import { useWSStore } from "@/stores/wsStore";

interface UseWebSocketOptions {
  url: string;
  onCacheUpdate?: CacheUpdater;
  autoConnect?: boolean;
}

export function useWebSocket({ url, onCacheUpdate, autoConnect = true }: UseWebSocketOptions) {
  const accessToken = useAuthStore((s) => s.accessToken);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const setConnectionState = useWSStore((s) => s.setConnectionState);

  const clientRef = useRef<WSClient | null>(null);
  const handlerRef = useRef<WSHandler | null>(null);

  useEffect(() => {
    if (!autoConnect || !isAuthenticated || !accessToken) return;

    const handler = new WSHandler({ onCacheUpdate });
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
  }, [url, accessToken, isAuthenticated, autoConnect, onCacheUpdate, setConnectionState]);

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
