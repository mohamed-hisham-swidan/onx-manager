// ---------------------------------------------------------------------------
// WebSocket Client with Auto-Reconnect & Exponential Backoff
// ---------------------------------------------------------------------------

import { ChannelManager } from "./channels";
import type {
  ClientMessage,
  ErrorHandler,
  MessageHandler,
  ServerMessage,
  WSConnectionConfig,
  WSEventHandlers,
} from "./types";
import { ConnectionState as CS } from "./types";

const DEFAULT_BASE_DELAY = 1000;
const DEFAULT_MAX_DELAY = 30000;
const DEFAULT_MAX_RETRIES = 10;

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
    }
  }

  get state(): CS {
    return this._state;
  }

  get isConnected(): boolean {
    return this._state === CS.CONNECTED;
  }

  connect(): void {
    if (this._destroyed) return;
    if (this._ws && (this._ws.readyState === WebSocket.OPEN || this._ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this._setState(CS.CONNECTING);

    const url = `${this._config.url}?token=${encodeURIComponent(this._config.token)}`;
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
    }
  }

  unsubscribe(channels: string[]): void {
    channels.forEach((ch) => this.channels.remove(ch));
    this.send({ type: "unsubscribe", channels });
  }

  refreshToken(token: string, sub: string): void {
    this._config.token = token;
    this.send({ type: "refresh_token", token, sub });
  }

  ping(): void {
    this.send({ type: "ping" });
  }

  setHandlers(handlers: WSEventHandlers): void {
    if (handlers.onMessage) this._onMessage = handlers.onMessage;
    if (handlers.onStateChange) this._onStateChange = handlers.onStateChange;
    if (handlers.onError) this._onError = handlers.onError;
  }

  private _handleServerMessage(message: ServerMessage): void {
    if (message.type === "auth_expired") {
      this._onStateChange?.(CS.DISCONNECTED);
      this.disconnect();
      return;
    }
    this._onMessage?.(message);
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
