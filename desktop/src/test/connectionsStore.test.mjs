import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const require = createRequire(import.meta.url);
const {
  loadStore,
  normalizePanelUrl,
  removeRemote,
  setActiveTarget,
  upsertRemote,
} = require("../connectionsStore");

test("normalizePanelUrl accepts http/https and strips trailing slashes", () => {
  assert.equal(normalizePanelUrl("https://mc.example.com/"), "https://mc.example.com");
  assert.equal(normalizePanelUrl("http://127.0.0.1:8000///"), "http://127.0.0.1:8000");
  assert.equal(normalizePanelUrl("panel.example.com"), "https://panel.example.com");
});

test("normalizePanelUrl rejects non-http protocols and empty URLs", () => {
  assert.throws(() => normalizePanelUrl(""), /empty/i);
  assert.throws(() => normalizePanelUrl("javascript:alert(1)"), /protocol/i);
  assert.throws(() => normalizePanelUrl("file:///etc/passwd"), /protocol/i);
});

test("connections store persists remotes, updates active target, and removes cleanly", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "onx-desktop-store-"));
  const storeFile = path.join(tmpDir, "connections.json");

  try {
    const initial = loadStore(storeFile);
    assert.equal(initial.lastMode, "local");
    assert.deepEqual(initial.remotes, []);

    const { entry } = upsertRemote(storeFile, {
      name: "Survival VPS",
      url: "https://mc.example.org/",
    });
    assert.equal(entry.url, "https://mc.example.org");
    assert.equal(entry.name, "Survival VPS");

    const updated = setActiveTarget(storeFile, "remote", entry.id);
    assert.equal(updated.lastMode, "remote");
    assert.equal(updated.lastRemoteId, entry.id);

    const afterDelete = removeRemote(storeFile, entry.id);
    assert.equal(afterDelete.remotes.length, 0);
    assert.equal(afterDelete.lastMode, "local");
    assert.equal(afterDelete.lastRemoteId, null);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});
