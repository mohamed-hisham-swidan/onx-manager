// ---------------------------------------------------------------------------
// WebSocket Client with Auto-Reconnect & Exponential Backoff
// ---------------------------------------------------------------------------

import { ChannelManager, extractChannelFromErrorMessage } from "./channels";
import type {
  ChannelState,
  ClientMessage,
  ErrorHandler,
  MessageHandler,
  ServerMessage,
  WSConnectionConfig,
  WSEventHandlers,
  WSErrorMessage,
} from "./types";
import { ChannelStatus as CH, ConnectionState as CS } from "./types";

const DEFAULT_BASE_DELAY = 1000;
const DEFAULT_MAX_DELAY = 30000;
const DEFAULT_MAX_RETRIES = 10;

// Per-channel rejected resubscribe backoff (distinct from transport reconnect).
const CHANNEL_RETRY_MAX = 3;
const CHANNEL_RETRY_BASE_DELAY = 2000;
const CHANNEL_RETRY_MAX_DELAY = 10000;

export class WSClient {
  private _ws: WebSocket | null = null;
  private _config: WSConnectionConfig;
  private _state: CS = CS.DISCONNECTED;
  private _retryCount = 0;
  private _retryTimer: ReturnType<typeof setTimeout> | null = null;
  private _pingTimer: ReturnType<typeof setInterval> | null = null;
  private _destroyed = false;
  private _messageQueue: ClientMessage[] = [];

  private _onMessage: MessageHandler | null = null;
  private _onStateChange: ((state: CS) => void) | null = null;
  private _onError: ErrorHandler | null = null;
  private _onUnattributedRejection: (() => void) | null = null;
  private _onChannelStateChange: ((channel: string, state: ChannelState | null) => void) | null = null;

  private _channelRetryTimers = new Map<string, ReturnType<typeof setTimeout>>();

  readonly channels = new ChannelManager();

  constructor(config: WSConnectionConfig, handlers?: WSEventHandlers) {
    this._config = {
      baseDelay: DEFAULT_BASE_DELAY,
      maxDelay: DEFAULT_MAX_DELAY,
      maxRetries: DEFAULT_MAX_RETRIES,
      autoReconnect: true,
      ...config,
    };
    if (handlers) {
      this._onMessage = handlers.onMessage ?? null;
      this._onStateChange = handlers.onStateChange ?? null;
      this._onError = handlers.onError ?? null;
      this._onChannelStateChange = handlers.onChannelStateChange ?? null;
    }
  }

  get state(): CS {
    return this._state;
  }

  get isConnected(): boolean {
    return this._state === CS.CONNECTED;
  }

  private _getToken(): string | null {
    if (typeof this._config.token === "function") {
      return this._config.token();
    }
    return this._config.token;
  }

  connect(): void {
    if (this._destroyed) return;
    if (this._ws && (this._ws.readyState === WebSocket.OPEN || this._ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const token = this._getToken();
    if (!token) {
      this._setState(CS.DISCONNECTED);
      return;
    }

    this._setState(CS.CONNECTING);

    const url = `${this._config.url}?token=${encodeURIComponent(token)}`;
    this._ws = new WebSocket(url);
    this._ws.binaryType = "arraybuffer";

    this._ws.onopen = () => {
      this._retryCount = 0;
      this._setState(CS.CONNECTED);
      this._flushQueue();
      this._startPing();
      this._resubscribe();
    };

    this._ws.onclose = () => {
      this._stopPing();
      if (this._state === CS.CONNECTED) {
        this._setState(CS.RECONNECTING);
      } else {
        this._setState(CS.DISCONNECTED);
      }
      this._scheduleReconnect();
    };

    this._ws.onerror = () => {
      this._onError?.(new Error("WebSocket connection error"));
    };

    this._ws.onmessage = (event: MessageEvent) => {
      try {
        const data = typeof event.data === "string" ? event.data : new TextDecoder().decode(event.data);
        const message: ServerMessage = JSON.parse(data);
        this._handleServerMessage(message);
      } catch (err) {
        this._onError?.(err instanceof Error ? err : new Error(String(err)));
      }
    };
  }

  disconnect(): void {
    this._destroyed = true;
    this._stopPing();
    this._clearRetry();
    this._clearAllChannelRetries();
    if (this._ws) {
      this._ws.onclose = null;
      this._ws.close(1000, "Client disconnect");
      this._ws = null;
    }
    this._setState(CS.DISCONNECTED);
  }

  send(message: ClientMessage): void {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(message));
    } else {
      this._messageQueue.push(message);
    }
  }

  subscribe(channels: string[]): void {
    const valid = channels.filter((ch) => {
      if (this.channels.isFull()) return false;
      if (!ChannelManager.validateChannel(ch)) return false;
      return this.channels.add(ch);
    });
    if (valid.length > 0) {
      this.send({ type: "subscribe", channels: valid });
      for (const ch of valid) {
        const state = this.channels.getChannelState(ch);
        if (state) this._emitChannelState(ch, state);
      }
    }
  }

  unsubscribe(channels: string[]): void {
    channels.forEach((ch) => {
      this.channels.remove(ch);
      this._clearChannelRetry(ch);
      this._emitChannelState(ch, null);
    });
    this.send({ type: "unsubscribe", channels });
  }

  refreshToken(token: string, sub: string): void {
    if (typeof this._config.token !== "function") {
      this._config.token = token;
    }
    this.send({ type: "refresh_token", token, sub });
    // New credentials give previously-rejected channels a fresh chance:
    // reset their retry counts and re-request each subscription.
    for (const state of Object.values(this.channels.getAllChannelStates())) {
      if (state.status === CH.REJECTED) {
        this.channels.resetRetryCount(state.channel);
        this._clearChannelRetry(state.channel);
        this.send({ type: "subscribe", channels: [state.channel] });
      }
    }
  }

  ping(): void {
    this.send({ type: "ping" });
  }

  setHandlers(handlers: WSEventHandlers): void {
    if (handlers.onMessage) this._onMessage = handlers.onMessage;
    if (handlers.onStateChange) this._onStateChange = handlers.onStateChange;
    if (handlers.onError) this._onError = handlers.onError;
    if (handlers.onChannelStateChange) this._onChannelStateChange = handlers.onChannelStateChange;
  }

  setUnattributedRejectionHandler(handler: (() => void) | null): void {
    this._onUnattributedRejection = handler;
  }

  setChannelStateChangeHandler(handler: ((channel: string, state: ChannelState | null) => void) | null): void {
    this._onChannelStateChange = handler;
  }

  private _handleServerMessage(message: ServerMessage): void {
    if (message.type === "auth_expired") {
      this._onStateChange?.(CS.DISCONNECTED);
      this.disconnect();
      return;
    }
    if (message.type === "error" && message.code === "PERMISSION_DENIED") {
      this._handlePermissionDenied(message as WSErrorMessage);
      return;
    }
    this._onMessage?.(message);
  }

  /**
   * Handles a per-channel permission rejection. This is a subscription-level
   * problem, not a transport one: we record the rejection and (boundedly)
   * resubscribe, but never touch transport ConnectionState (unlike
   * auth_expired, which correctly disconnects).
   */
  private _handlePermissionDenied(message: WSErrorMessage): void {
    const channel = extractChannelFromErrorMessage(message.message);
    if (channel === null) {
      // Parse failure: channel name embedded in free-text message could not
      // be recovered. Do NOT silently drop it — surface it so the caller can
      // trigger a global-degraded fallback rather than mis-attributing it.
      this._onUnattributedRejection?.();
      return;
    }
    this.channels.markRejected(channel, message.message);
    this._emitChannelState(channel, this.channels.getChannelState(channel) ?? null);
    this._scheduleChannelRetry(channel);
  }

  private _emitChannelState(channel: string, state: ChannelState | null): void {
    this._onChannelStateChange?.(channel, state);
  }

  /**
   * Schedules a bounded resubscribe attempt for a single rejected channel.
   * Independent per channel: rejecting channel A never affects channel B's
   * timer or retry count. After CHANNEL_RETRY_MAX rejections the channel
   * settles as REJECTED permanently (until refreshToken resets it).
   */
  private _scheduleChannelRetry(channel: string): void {
    const state = this.channels.getChannelState(channel);
    if (!state) return;
    if (state.retryCount > CHANNEL_RETRY_MAX) {
      return;
    }
    this._clearChannelRetry(channel);

    // Exponential backoff within CHANNEL_RETRY_BASE/MAX_DELAY bounds:
    // 2000ms, then 4000ms, then 8000ms (capped at 10000ms).
    const delay = Math.min(
      CHANNEL_RETRY_BASE_DELAY * Math.pow(2, state.retryCount - 1),
      CHANNEL_RETRY_MAX_DELAY,
    );
    this._channelRetryTimers.set(
      channel,
      setTimeout(() => {
        this._channelRetryTimers.delete(channel);
        if (this._destroyed) return;
        if (!this.channels.has(channel)) return;
        this.send({ type: "subscribe", channels: [channel] });
      }, delay),
    );
  }

  private _clearChannelRetry(channel: string): void {
    const timer = this._channelRetryTimers.get(channel);
    if (timer !== undefined) {
      clearTimeout(timer);
      this._channelRetryTimers.delete(channel);
    }
  }

  private _clearAllChannelRetries(): void {
    for (const timer of this._channelRetryTimers.values()) {
      clearTimeout(timer);
    }
    this._channelRetryTimers.clear();
  }

  private _setState(state: CS): void {
    if (this._state !== state) {
      this._state = state;
      this._onStateChange?.(state);
    }
  }

  private _flushQueue(): void {
    while (this._messageQueue.length > 0) {
      const msg = this._messageQueue.shift();
      if (msg) this.send(msg);
    }
  }

  private _resubscribe(): void {
    const channels = this.channels.snapshot();
    if (channels.length > 0) {
      this.send({ type: "subscribe", channels });
    }
  }

  private _startPing(): void {
    this._stopPing();
    this._pingTimer = setInterval(() => this.ping(), 30000);
  }

  private _stopPing(): void {
    if (this._pingTimer !== null) {
      clearInterval(this._pingTimer);
      this._pingTimer = null;
    }
  }

  private _scheduleReconnect(): void {
    if (this._destroyed) return;
    if (!this._config.autoReconnect) return;
    if (this._retryCount >= (this._config.maxRetries ?? DEFAULT_MAX_RETRIES)) {
      this._onError?.(new Error(`Max reconnection attempts reached (${this._config.maxRetries})`));
      return;
    }

    const delay = Math.min(
      (this._config.baseDelay ?? DEFAULT_BASE_DELAY) * Math.pow(2, this._retryCount),
      this._config.maxDelay ?? DEFAULT_MAX_DELAY,
    );
    this._retryCount++;

    this._retryTimer = setTimeout(() => {
      if (!this._destroyed) {
        this.connect();
      }
    }, delay);
  }

  private _clearRetry(): void {
    if (this._retryTimer !== null) {
      clearTimeout(this._retryTimer);
      this._retryTimer = null;
    }
  }
}
