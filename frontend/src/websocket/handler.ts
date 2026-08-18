// ---------------------------------------------------------------------------
// WebSocket Message Handler — State Sync & Store Updates
// ---------------------------------------------------------------------------

import type { WSClient } from "./client";
import type {
  ServerMessage,
  WSStateSyncMessage,
  WSMetricsBatchMessage,
  WSMetricsMessage,
  WSStateMessage,
  WSEventMessage,
  WSErrorMessage,
} from "./types";

export interface CacheUpdate {
  key: string;
  data: unknown;
  action: "set" | "update" | "invalidate" | "merge";
}

export type CacheUpdater = (update: CacheUpdate) => void;

export interface WSHandlerConfig {
  onCacheUpdate?: CacheUpdater;
  onStateSync?: (events: Array<Record<string, unknown>>) => void;
  onServerState?: (serverId: string, status: Record<string, unknown>) => void;
  onMetrics?: (serverId: string, tps: number, players: number, ramMb: number) => void;
  onMetricsBatch?: (serverId: string, samples: Array<Record<string, unknown>>) => void;
  onEvent?: (event: Record<string, unknown>) => void;
  onError?: (code: string, message: string) => void;
}

export class WSHandler {
  private _config: WSHandlerConfig;
  private _reconnectBuffer: Array<Record<string, unknown>> = [];

  constructor(config: WSHandlerConfig = {}) {
    this._config = config;
  }

  attach(client: WSClient): void {
    client.setHandlers({
      onMessage: (msg) => this._route(msg),
    });
  }

  private _route(message: ServerMessage): void {
    switch (message.type) {
      case "state_sync":
        this._handleStateSync(message);
        break;
      case "state":
        this._handleState(message);
        break;
      case "metrics":
        this._handleMetrics(message);
        break;
      case "metrics_batch":
        this._handleMetricsBatch(message);
        break;
      case "event":
        this._handleEvent(message);
        break;
      case "error":
        this._handleError(message);
        break;
      case "pong":
        break;
      default:
        break;
    }
  }

  private _handleStateSync(message: WSStateSyncMessage): void {
    this._reconnectBuffer = message.events;
    this._config.onStateSync?.(message.events);

    for (const event of message.events) {
      this._updateCacheFromEvent(event);
    }
  }

  private _handleState(message: WSStateMessage): void {
    this._config.onServerState?.(message.server_id, message.status);
    this._config.onCacheUpdate?.({
      key: `server:${message.server_id}`,
      data: null,
      action: "invalidate",
    });
  }

  private _handleMetrics(message: WSMetricsMessage): void {
    this._config.onMetrics?.(message.server_id, message.tps, message.players, message.ram_mb);
    this._config.onCacheUpdate?.({
      key: `metrics:${message.server_id}`,
      data: { tps: message.tps, players: message.players, ram_mb: message.ram_mb },
      action: "set",
    });
  }

  private _handleMetricsBatch(message: WSMetricsBatchMessage): void {
    this._config.onMetricsBatch?.(message.server_id, message.samples);
    this._config.onCacheUpdate?.({
      key: `metrics_batch:${message.server_id}`,
      data: { samples: message.samples },
      action: "merge",
    });
  }

  private _handleEvent(message: WSEventMessage): void {
    this._config.onEvent?.(message.event);
    this._updateCacheFromEvent(message.event);
  }

  private _handleError(message: WSErrorMessage): void {
    this._config.onError?.(message.code, message.message);
  }

  private _updateCacheFromEvent(event: Record<string, unknown>): void {
    const eventType = event.event_type as string | undefined;
    if (!eventType) return;

    if (eventType.includes("ServerCreated") || eventType.includes("ServerDeleted")) {
      this._config.onCacheUpdate?.({
        key: "servers:list",
        data: null,
        action: "invalidate",
      });
    } else if (
      eventType.includes("ServerStarting") ||
      eventType.includes("ServerStarted") ||
      eventType.includes("ServerStopping") ||
      eventType.includes("ServerStopped") ||
      eventType.includes("ServerCrashed") ||
      eventType.includes("ServerRestarted")
    ) {
      this._config.onCacheUpdate?.({
        key: "servers:list",
        data: null,
        action: "invalidate",
      });
      const serverId = event.server_id as string | undefined;
      if (serverId) {
        this._config.onCacheUpdate?.({
          key: `server:${serverId}`,
          data: null,
          action: "invalidate",
        });
      }
    } else if (eventType.includes("Backup")) {
      this._config.onCacheUpdate?.({
        key: "backups:list",
        data: null,
        action: "invalidate",
      });
    } else if (eventType.includes("Plugin")) {
      this._config.onCacheUpdate?.({
        key: "plugins:list",
        data: null,
        action: "invalidate",
      });
    }
  }

  clearReconnectBuffer(): void {
    this._reconnectBuffer = [];
  }

  get reconnectBuffer(): Array<Record<string, unknown>> {
    return [...this._reconnectBuffer];
  }
}
