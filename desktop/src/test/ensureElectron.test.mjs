import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const require = createRequire(import.meta.url);
const {
  checkElectronBinary,
  ensureElectron,
  finalizeElectronInstall,
  findCachedElectronZip,
  formatEaccesHint,
  getCacheDirectories,
  getPlatformBinaryRelativePath,
  resolveElectronBinary,
} = require("../../scripts/ensure-electron");

test("getPlatformBinaryRelativePath maps supported desktop platforms", () => {
  assert.equal(getPlatformBinaryRelativePath("linux"), "electron");
  assert.equal(getPlatformBinaryRelativePath("win32"), "electron.exe");
  assert.equal(getPlatformBinaryRelativePath("darwin"), "Electron.app/Contents/MacOS/Electron");
  assert.throws(() => getPlatformBinaryRelativePath("sunos"), /unsupported platform/i);
});

test("getCacheDirectories resolves OS-specific Electron cache locations", () => {
  const home = "/home/tester";
  assert.deepEqual(
    getCacheDirectories({ platform: "linux", env: {}, homeDir: home }),
    [path.join(home, ".cache", "electron")],
  );
  assert.deepEqual(
    getCacheDirectories({
      platform: "win32",
      env: { LOCALAPPDATA: "C:\\Users\\tester\\AppData\\Local" },
      homeDir: home,
    }),
    [path.join("C:\\Users\\tester\\AppData\\Local", "electron", "Cache")],
  );
  assert.deepEqual(
    getCacheDirectories({ platform: "darwin", env: {}, homeDir: home }),
    [path.join(home, "Library", "Caches", "electron")],
  );
});

test("findCachedElectronZip finds exact version inside hashed subdirectory", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "onx-electron-cache-"));
  try {
    const cacheDir = path.join(tmpDir, ".cache", "electron");
    const hashDir = path.join(cacheDir, "deadbeef1234");
    fs.mkdirSync(hashDir, { recursive: true });

    const oldZip = path.join(hashDir, "electron-v34.0.0-linux-x64.zip");
    const exactZip = path.join(hashDir, "electron-v35.7.5-linux-x64.zip");
    fs.writeFileSync(oldZip, "old");
    fs.writeFileSync(exactZip, "exact");

    assert.equal(
      findCachedElectronZip({
        version: "35.7.5",
        platform: "linux",
        arch: "x64",
        env: {},
        homeDir: tmpDir,
      }),
      exactZip,
    );
    assert.equal(
      findCachedElectronZip({
        version: null,
        platform: "linux",
        arch: "x64",
        env: {},
        homeDir: tmpDir,
      }),
      exactZip,
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test("checkElectronBinary detects missing path.txt, missing binary, and valid binary", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "onx-electron-bin-"));
  const electronDir = path.join(tmpDir, "node_modules", "electron");
  const distDir = path.join(electronDir, "dist");

  try {
    fs.mkdirSync(distDir, { recursive: true });
    assert.equal(
      checkElectronBinary(electronDir, { platform: "linux", env: {} }).reason,
      "MISSING_PATH_TXT",
    );

    fs.writeFileSync(path.join(electronDir, "path.txt"), "electron", "utf8");
    assert.equal(
      checkElectronBinary(electronDir, { platform: "linux", env: {} }).reason,
      "MISSING_BINARY",
    );

    const binPath = path.join(distDir, "electron");
    fs.writeFileSync(binPath, "#!/bin/sh\nexit 0\n", "utf8");
    fs.chmodSync(binPath, 0o644);

    // ensurePosixExecutable should restore +x automatically when allowed by filesystem
    const okResult = checkElectronBinary(electronDir, {
      platform: "linux",
      env: {},
      probeExec: false,
    });
    assert.equal(okResult.ok, true);
    assert.equal(okResult.binaryPath, binPath);
    assert.notEqual(fs.statSync(binPath).mode & 0o100, 0);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test("resolveElectronBinary honors ELECTRON_OVERRIDE_DIST_PATH", () => {
  const resolved = resolveElectronBinary("/fake/electron", {
    platform: "linux",
    env: { ELECTRON_OVERRIDE_DIST_PATH: "/opt/electron-dist" },
  });
  assert.equal(resolved.overridden, true);
  assert.equal(resolved.binaryPath, path.join("/opt/electron-dist", "electron"));
});

test("ensureElectron repairs missing path.txt via install.js and reports EACCES cleanly", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "onx-electron-heal-"));
  const electronDir = path.join(tmpDir, "node_modules", "electron");
  const distDir = path.join(electronDir, "dist");

  try {
    fs.mkdirSync(distDir, { recursive: true });
    fs.writeFileSync(
      path.join(electronDir, "package.json"),
      JSON.stringify({ name: "electron", version: "35.7.5" }),
    );
    fs.writeFileSync(path.join(electronDir, "install.js"), "// stub");
    const binPath = path.join(distDir, "electron");
    fs.writeFileSync(binPath, "binary", "utf8");
    fs.chmodSync(binPath, 0o755);

    // Simulate install.js writing path.txt when invoked by ensureElectron
    const healResult = ensureElectron({
      desktopDir: tmpDir,
      platform: "linux",
      arch: "x64",
      env: {},
      homeDir: tmpDir,
      probeExec: false,
      log: () => {},
      warn: () => {},
      spawnFn: (cmd) => {
        if (cmd === process.execPath) {
          finalizeElectronInstall(electronDir, { platform: "linux" });
          return { status: 0 };
        }
        return { status: 1 };
      },
    });

    assert.equal(healResult.healed, true);
    assert.equal(healResult.method, "install.js");
    assert.equal(fs.readFileSync(path.join(electronDir, "path.txt"), "utf8"), "electron");

    // Simulate EACCES from noexec mount when probing binary execution
    assert.throws(
      () =>
        ensureElectron({
          desktopDir: tmpDir,
          platform: "linux",
          arch: "x64",
          env: {},
          homeDir: tmpDir,
          probeExec: true,
          log: () => {},
          warn: () => {},
          spawnFn: () => ({ error: Object.assign(new Error("EACCES"), { code: "EACCES" }) }),
        }),
      /ELECTRON_OVERRIDE_DIST_PATH/,
    );
    assert.match(formatEaccesHint(binPath), /ELECTRON_OVERRIDE_DIST_PATH/);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test("ensureElectron falls back to cached zip extraction when install.js fails", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "onx-electron-cache-heal-"));
  const electronDir = path.join(tmpDir, "node_modules", "electron");
  const cacheSubdir = path.join(tmpDir, ".cache", "electron", "abc123");

  try {
    fs.mkdirSync(electronDir, { recursive: true });
    fs.mkdirSync(cacheSubdir, { recursive: true });
    fs.writeFileSync(
      path.join(electronDir, "package.json"),
      JSON.stringify({ name: "electron", version: "35.7.5" }),
    );
    fs.writeFileSync(path.join(electronDir, "install.js"), "// stub");
    const cachedZip = path.join(cacheSubdir, "electron-v35.7.5-linux-x64.zip");
    fs.writeFileSync(cachedZip, "PK\x05\x06");

    const calls = [];
    const result = ensureElectron({
      desktopDir: tmpDir,
      platform: "linux",
      arch: "x64",
      env: {},
      homeDir: tmpDir,
      probeExec: false,
      log: () => {},
      warn: () => {},
      spawnFn: (cmd, args) => {
        calls.push([cmd, args]);
        if (cmd === process.execPath) {
          return { status: 1 };
        }
        if (cmd === "unzip") {
          const destIdx = args.indexOf("-d");
          const destDir = args[destIdx + 1];
          fs.mkdirSync(destDir, { recursive: true });
          fs.writeFileSync(path.join(destDir, "electron"), "#!/bin/sh\n", "utf8");
          return { status: 0 };
        }
        return { status: 1 };
      },
    });

    assert.equal(result.healed, true);
    assert.equal(result.method, "cache-extract");
    assert.equal(fs.readFileSync(path.join(electronDir, "path.txt"), "utf8"), "electron");
    assert.ok(fs.existsSync(path.join(electronDir, "dist", "electron")));
    assert.ok(calls.some(([cmd]) => cmd === "unzip"));
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});
