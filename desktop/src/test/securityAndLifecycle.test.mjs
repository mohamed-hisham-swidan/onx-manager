import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import backendManagerModule from "../backendManager.js";

const { LocalBackendManager } = backendManagerModule;
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC_DIR = path.resolve(__dirname, "..");

test("launcher.html enforces hardened CSP and accepts schemeless remote URLs", () => {
  const html = fs.readFileSync(path.join(SRC_DIR, "launcher.html"), "utf8");
  assert.match(html, /object-src 'none'/);
  assert.match(html, /base-uri 'none'/);
  assert.match(html, /form-action 'none'/);
  assert.match(html, /id="remote-url"[^>]*type="text"/);
});

test("main.js guards all desktop IPC handlers to the local launcher and handles signals", () => {
  const mainJs = fs.readFileSync(path.join(SRC_DIR, "main.js"), "utf8");
  assert.match(mainJs, /function assertLauncherSender\(event\)/);
  assert.match(mainJs, /webContents\.on\("will-navigate"/);
  assert.match(mainJs, /process\.on\("SIGINT"/);
  assert.match(mainJs, /process\.on\("SIGTERM"/);

  const handlerMatches = [...mainJs.matchAll(/ipcMain\.handle\("desktop:[^"]+"/g)];
  const guardMatches = [...mainJs.matchAll(/assertLauncherSender\(evt\)/g)];
  assert.ok(handlerMatches.length >= 8, "expected at least 8 desktop IPC handlers");
  assert.equal(
    guardMatches.length,
    handlerMatches.length,
    "every desktop:* IPC handler must call assertLauncherSender(evt)",
  );
});

test("LocalBackendManager snapshot honors custom probeHost and aborts cleanly on stop", async () => {
  const mgr = new LocalBackendManager({ installDir: path.resolve(SRC_DIR, "..", "..") });
  mgr.port = 8123;
  mgr.probeHost = "192.168.1.50";
  assert.equal(mgr.getSnapshot().url, "http://192.168.1.50:8123");

  await mgr.stop();
  assert.equal(mgr._aborted, true);
  assert.equal(mgr.status, "stopped");
});

test("LocalBackendManager configures 12s graceful shutdown window and detached POSIX group", () => {
  const bmJs = fs.readFileSync(path.join(SRC_DIR, "backendManager.js"), "utf8");
  assert.match(bmJs, /spawnOpts\.detached\s*=\s*true/);
  assert.match(bmJs, /process\.kill\(-proc\.pid,\s*sig\)/);
  assert.match(bmJs, /12000/);
});
