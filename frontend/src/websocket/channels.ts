// ---------------------------------------------------------------------------
// Channel Subscription Manager
// ---------------------------------------------------------------------------

import type { WSChannelSubscription } from "./types";

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
