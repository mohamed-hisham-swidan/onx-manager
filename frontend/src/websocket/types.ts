// ---------------------------------------------------------------------------
// WebSocket Message Protocol Types
// ---------------------------------------------------------------------------

// Server → Client
export interface WSEventMessage {
  type: "event";
  event: Record<string, unknown>;
}

export interface WSStateMessage {
  type: "state";
  server_id: string;
  status: Record<string, unknown>;
}

export interface WSMetricsMessage {
  type: "metrics";
  server_id: string;
  tps: number;
  players: number;
  ram_mb: number;
}

export interface WSMetricsBatchMessage {
  type: "metrics_batch";
  server_id: string;
  samples: Array<{ ts: number; tps: number; players: number; ram_mb: number; cpu: number }>;
}

export interface WSStateSyncMessage {
  type: "state_sync";
  events: Array<Record<string, unknown>>;
}

export interface WSAuthExpiredMessage {
  type: "auth_expired";
}

export interface WSErrorMessage {
  type: "error";
  code: string;
  message: string;
}

export interface WSPongMessage {
  type: "pong";
}

export type ServerMessage =
  | WSEventMessage
  | WSStateMessage
  | WSMetricsMessage
  | WSMetricsBatchMessage
  | WSStateSyncMessage
  | WSAuthExpiredMessage
  | WSErrorMessage
  | WSPongMessage;

// Client → Server
export interface WSSubscribeMessage {
  type: "subscribe";
  channels: string[];
}

export interface WSUnsubscribeMessage {
  type: "unsubscribe";
  channels: string[];
}

export interface WSRefreshTokenMessage {
  type: "refresh_token";
  token: string;
  sub: string;
}

export interface WSPingMessage {
  type: "ping";
}

export type ClientMessage =
  | WSSubscribeMessage
  | WSUnsubscribeMessage
  | WSRefreshTokenMessage
  | WSPingMessage;

// ---------------------------------------------------------------------------
// Connection State
// ---------------------------------------------------------------------------

export enum ConnectionState {
  DISCONNECTED = "disconnected",
  CONNECTING = "connecting",
  CONNECTED = "connected",
  RECONNECTING = "reconnecting",
  // Transport is connected but at least one subscription is unhealthy
  // (REJECTED/RETRYING channel, or an unattributed rejection whose fate is
  // unknown). Computed as a derived state — the raw transport connectionState
  // field is never mutated to this value (see wsStore.computeEffectiveConnectionState).
  DEGRADED = "degraded",
}

export interface WSConnectionConfig {
  url: string;
  token: string | (() => string | null);
  autoReconnect?: boolean;
  maxRetries?: number;
  baseDelay?: number;
  maxDelay?: number;
}

export interface WSChannelSubscription {
  channel: string;
  authorized: boolean;
}

// ---------------------------------------------------------------------------
// Per-Channel Subscription State
// ---------------------------------------------------------------------------

export enum ChannelStatus {
  UNSUBSCRIBED = "unsubscribed",
  SUBSCRIBING = "subscribing",
  SUBSCRIBED = "subscribed",
  REJECTED = "rejected",
  RETRYING = "retrying",
}

export interface ChannelState {
  channel: string;
  status: ChannelStatus;
  authorized: boolean;
  error?: string;
  retryCount: number;
}

// ---------------------------------------------------------------------------
// Event Handlers
// ---------------------------------------------------------------------------

export type MessageHandler = (message: ServerMessage) => void;
export type ConnectionStateHandler = (state: ConnectionState) => void;
export type ErrorHandler = (error: Error) => void;

/**
 * Reports a change to a channel's subscription state so consumers (e.g. the
 * WS store) can mirror it. `state` is null when the channel was removed
 * (unsubscribed) and its entry should be dropped.
 */
export type ChannelStateChangeHandler = (channel: string, state: ChannelState | null) => void;

export interface WSEventHandlers {
  onMessage?: MessageHandler;
  onStateChange?: ConnectionStateHandler;
  onError?: ErrorHandler;
  onChannelStateChange?: ChannelStateChangeHandler;
}
