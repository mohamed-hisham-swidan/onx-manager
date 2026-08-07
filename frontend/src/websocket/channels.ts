// ---------------------------------------------------------------------------
// Channel Subscription Manager
// ---------------------------------------------------------------------------

import type { WSChannelSubscription } from "./types";
import { ChannelStatus } from "./types";
import type { ChannelState } from "./types";

export const VALID_CHANNEL_PREFIXES = [
  "server",
  "backup",
  "plugin",
  "monitoring",
  "metrics",
  "auth",
  "user",
] as const;

export const MAX_CHANNELS = 50;

export class ChannelManager {
  private _subscriptions = new Map<string, WSChannelSubscription>();
  private _states = new Map<string, ChannelState>();

  get channels(): string[] {
    return Array.from(this._subscriptions.keys());
  }

  get subscriptions(): WSChannelSubscription[] {
    return Array.from(this._subscriptions.values());
  }

  add(channel: string, authorized = true): boolean {
    if (this._subscriptions.size >= MAX_CHANNELS) {
      return false;
    }
    if (this._subscriptions.has(channel)) {
      return true;
    }
    this._subscriptions.set(channel, { channel, authorized });
    return true;
  }

  remove(channel: string): boolean {
    return this._subscriptions.delete(channel);
  }

  has(channel: string): boolean {
    return this._subscriptions.has(channel);
  }

  clear(): void {
    this._subscriptions.clear();
  }

  get size(): number {
    return this._subscriptions.size;
  }

  isFull(): boolean {
    return this._subscriptions.size >= MAX_CHANNELS;
  }

  snapshot(): string[] {
    return Array.from(this._subscriptions.keys());
  }

  /**
   * Records that a channel subscription was rejected by the backend.
   * Updates only the target channel's state; other channels are untouched.
   */
  markRejected(channel: string, errorMessage: string): void {
    const prev = this._states.get(channel);
    this._states.set(channel, {
      channel,
      status: ChannelStatus.REJECTED,
      authorized: false,
      error: errorMessage,
      retryCount: (prev?.retryCount ?? 0) + 1,
    });
  }

  /**
   * Returns the current state for one channel, or undefined if the channel is
   * neither tracked nor subscribed. A subscribed channel with no recorded
   * state derives a default SUBSCRIBED state from its subscription entry.
   */
  getChannelState(channel: string): ChannelState | undefined {
    const tracked = this._states.get(channel);
    if (tracked) return tracked;
    const sub = this._subscriptions.get(channel);
    if (!sub) return undefined;
    return {
      channel,
      status: ChannelStatus.SUBSCRIBED,
      authorized: sub.authorized,
      retryCount: 0,
    };
  }

  /**
   * Returns a complete snapshot of every tracked channel's state, keyed by
   * channel name. Subscribed channels with no recorded state are included via
   * their derived default state.
   */
  getAllChannelStates(): Record<string, ChannelState> {
    const result: Record<string, ChannelState> = {};
    for (const channel of this._states.keys()) {
      result[channel] = this._states.get(channel)!;
    }
    for (const channel of this._subscriptions.keys()) {
      if (!(channel in result)) {
        const state = this.getChannelState(channel);
        if (state) result[channel] = state;
      }
    }
    return result;
  }

  /**
   * Zeroes the retry counter for a channel without altering its status or
   * authorization. No-op for channels with no recorded state.
   */
  resetRetryCount(channel: string): void {
    const tracked = this._states.get(channel);
    if (tracked) {
      tracked.retryCount = 0;
    }
  }

  static validateChannel(channel: string): boolean {
    if (!channel || channel.length > 128) return false;
    const parts = channel.split(":");
    if (parts.length !== 2) return false;
    return (VALID_CHANNEL_PREFIXES as readonly string[]).includes(parts[0]);
  }

  static isWildcard(channel: string): boolean {
    return channel.endsWith(":*");
  }

  static isServerChannel(channel: string): boolean {
    return channel.startsWith("server:");
  }

  static isBackupChannel(channel: string): boolean {
    return channel.startsWith("backup:");
  }

  static isPluginChannel(channel: string): boolean {
    return channel.startsWith("plugin:");
  }

  static isMonitoringChannel(channel: string): boolean {
    return channel.startsWith("monitoring:") || channel.startsWith("metrics:");
  }
}

/**
 * Defensively extracts the channel name from a backend permission-denied
 * error message of the form `Not authorized for channel: <channel>`.
 *
 * The channel name is embedded in the backend's free-text `message` string,
 * not a structured field, so parsing is inherently fragile: a future wording
 * change could silently break it. To avoid failing silently, this returns
 * `null` (never throws, never returns an empty string) when the message does
 * not match the expected shape, so callers can degrade safely rather than
 * mis-attributing or ignoring the rejection.
 *
 * Confirmed against backend/app/websocket/handlers.py:127 —
 * `"Not authorized for channel: {channel}"`.
 */
export function extractChannelFromErrorMessage(message: string): string | null {
  const prefix = "Not authorized for channel: ";
  if (!message.startsWith(prefix)) return null;
  const channel = message.slice(prefix.length).trim();
  if (!channel) return null;
  return channel;
}
