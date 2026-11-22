"use strict";

const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const DEFAULT_STATE = Object.freeze({
  lastMode: "local",
  lastRemoteId: null,
  remotes: [],
});

/**
 * Validate and normalize an ONX Manager HTTP/HTTPS connection URL.
 * Rejects javascript:, file:, ftp:, empty strings, and malformed URLs.
 */
function normalizePanelUrl(rawUrl) {
  if (typeof rawUrl !== "string") {
    throw new Error("Connection URL must be a string.");
  }
  const trimmed = rawUrl.trim();
  if (!trimmed) {
    throw new Error("Connection URL cannot be empty.");
  }
  const withScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(trimmed)
    ? trimmed
    : `https://${trimmed}`;

  let parsed;
  try {
    parsed = new URL(withScheme);
  } catch {
    throw new Error(`Invalid connection URL: ${rawUrl}`);
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(`Unsupported URL protocol '${parsed.protocol}'. Use http:// or https://.`);
  }
  if (!parsed.hostname) {
    throw new Error("Connection URL must include a hostname.");
  }

  parsed.hash = "";
  parsed.search = "";
  const formatted = parsed.toString().replace(/\/+$/, "");
  return formatted;
}

function loadStore(filePath) {
  try {
    if (!fs.existsSync(filePath)) {
      return { ...DEFAULT_STATE, remotes: [] };
    }
    const raw = JSON.parse(fs.readFileSync(filePath, "utf8"));
    if (!raw || typeof raw !== "object") {
      return { ...DEFAULT_STATE, remotes: [] };
    }
    const remotes = Array.isArray(raw.remotes)
      ? raw.remotes
          .filter((item) => item && typeof item.url === "string" && typeof item.name === "string")
          .map((item) => ({
            id: String(item.id || crypto.randomUUID()),
            name: String(item.name).trim() || item.url,
            url: normalizePanelUrl(item.url),
            lastUsedAt: item.lastUsedAt || null,
          }))
      : [];
    return {
      lastMode: raw.lastMode === "remote" ? "remote" : "local",
      lastRemoteId: raw.lastRemoteId ? String(raw.lastRemoteId) : null,
      remotes,
    };
  } catch {
    return { ...DEFAULT_STATE, remotes: [] };
  }
}

function saveStore(filePath, state) {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });
  const tmpPath = `${filePath}.tmp.${process.pid}`;
  fs.writeFileSync(tmpPath, JSON.stringify(state, null, 2), { encoding: "utf8", mode: 0o600 });
  fs.renameSync(tmpPath, filePath);
  return state;
}

function upsertRemote(filePath, { id, name, url }) {
  const normalizedUrl = normalizePanelUrl(url);
  const displayName = (name && String(name).trim()) || new URL(normalizedUrl).host;
  const store = loadStore(filePath);
  const now = new Date().toISOString();

  let target =
    (id && store.remotes.find((r) => r.id === id)) ||
    store.remotes.find((r) => r.url === normalizedUrl);

  if (target) {
    target.name = displayName;
    target.url = normalizedUrl;
    target.lastUsedAt = now;
  } else {
    target = {
      id: id || crypto.randomUUID(),
      name: displayName,
      url: normalizedUrl,
      lastUsedAt: now,
    };
    store.remotes.unshift(target);
  }

  saveStore(filePath, store);
  return { store, entry: target };
}

function removeRemote(filePath, remoteId) {
  const store = loadStore(filePath);
  store.remotes = store.remotes.filter((r) => r.id !== remoteId);
  if (store.lastRemoteId === remoteId) {
    store.lastRemoteId = null;
    if (store.lastMode === "remote") {
      store.lastMode = "local";
    }
  }
  return saveStore(filePath, store);
}

function setActiveTarget(filePath, mode, remoteId = null) {
  const store = loadStore(filePath);
  store.lastMode = mode === "remote" ? "remote" : "local";
  store.lastRemoteId = mode === "remote" ? remoteId : null;
  if (remoteId) {
    const entry = store.remotes.find((r) => r.id === remoteId);
    if (entry) {
      entry.lastUsedAt = new Date().toISOString();
    }
  }
  return saveStore(filePath, store);
}

module.exports = {
  normalizePanelUrl,
  loadStore,
  saveStore,
  upsertRemote,
  removeRemote,
  setActiveTarget,
};
