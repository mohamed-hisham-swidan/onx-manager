#!/usr/bin/env node
"use strict";

const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const PLATFORM_BINARY_PATHS = {
  darwin: "Electron.app/Contents/MacOS/Electron",
  mas: "Electron.app/Contents/MacOS/Electron",
  win32: "electron.exe",
  linux: "electron",
  freebsd: "electron",
  openbsd: "electron",
};

const POSIX_HELPER_BINARIES = [
  "chrome-sandbox",
  "chrome_crashpad_handler",
];

function getPlatformBinaryRelativePath(platform = process.platform) {
  const rel = PLATFORM_BINARY_PATHS[platform];
  if (!rel) {
    throw new Error(`Unsupported platform for Electron binary: ${platform}`);
  }
  return rel;
}

function getCacheDirectories({
  platform = process.platform,
  env = process.env,
  homeDir = os.homedir(),
} = {}) {
  const dirs = [];
  const customCache = env.electron_config_cache || env.ELECTRON_CACHE || env.npm_config_electron_cache;
  if (customCache) {
    dirs.push(customCache);
  }

  if (platform === "win32") {
    const localAppData = env.LOCALAPPDATA || path.join(homeDir, "AppData", "Local");
    dirs.push(path.join(localAppData, "electron", "Cache"));
  } else if (platform === "darwin") {
    dirs.push(path.join(homeDir, "Library", "Caches", "electron"));
  } else {
    const xdgCache = env.XDG_CACHE_HOME || path.join(homeDir, ".cache");
    dirs.push(path.join(xdgCache, "electron"));
  }

  return Array.from(new Set(dirs.filter(Boolean)));
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function compareVersionsDesc(a, b) {
  const partsA = a.split(".").map((n) => Number.parseInt(n, 10) || 0);
  const partsB = b.split(".").map((n) => Number.parseInt(n, 10) || 0);
  const len = Math.max(partsA.length, partsB.length);
  for (let i = 0; i < len; i += 1) {
    const diff = (partsB[i] || 0) - (partsA[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

function collectZipCandidatesInDir(dirPath, matcher, results, depth = 0) {
  if (!fs.existsSync(dirPath)) return;
  let entries;
  try {
    entries = fs.readdirSync(dirPath, { withFileTypes: true });
  } catch {
    return;
  }

  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name);
    if (entry.isFile()) {
      const match = matcher.exec(entry.name);
      if (match) {
        let mtimeMs = 0;
        try {
          mtimeMs = fs.statSync(fullPath).mtimeMs;
        } catch {
          mtimeMs = 0;
        }
        results.push({ path: fullPath, version: match[1], mtimeMs });
      }
    } else if (entry.isDirectory() && depth < 1) {
      collectZipCandidatesInDir(fullPath, matcher, results, depth + 1);
    }
  }
}

function findCachedElectronZip({
  version = null,
  platform = process.platform,
  arch = process.arch,
  env = process.env,
  homeDir = os.homedir(),
} = {}) {
  const matcher = new RegExp(
    `^electron-v(.+)-${escapeRegExp(platform)}-${escapeRegExp(arch)}\\.zip$`,
  );
  const candidates = [];

  for (const cacheDir of getCacheDirectories({ platform, env, homeDir })) {
    collectZipCandidatesInDir(cacheDir, matcher, candidates, 0);
  }

  if (candidates.length === 0) {
    return null;
  }

  if (version) {
    const cleanVersion = String(version).replace(/^v/, "");
    const exact = candidates.find((item) => item.version === cleanVersion);
    if (exact) {
      return exact.path;
    }
  }

  candidates.sort((a, b) => {
    const verDiff = compareVersionsDesc(a.version, b.version);
    if (verDiff !== 0) return verDiff;
    return b.mtimeMs - a.mtimeMs;
  });

  return candidates[0].path;
}

function resolveElectronBinary(
  electronDir,
  { platform = process.platform, env = process.env } = {},
) {
  const expectedRel = getPlatformBinaryRelativePath(platform);
  const pathFile = path.join(electronDir, "path.txt");

  let pathTxtContent = null;
  if (fs.existsSync(pathFile)) {
    const raw = fs.readFileSync(pathFile, "utf8").trim();
    if (raw) {
      pathTxtContent = raw;
    }
  }

  if (env.ELECTRON_OVERRIDE_DIST_PATH) {
    const rel = pathTxtContent || expectedRel;
    return {
      binaryPath: path.join(env.ELECTRON_OVERRIDE_DIST_PATH, rel),
      pathTxtContent,
      expectedRel,
      overridden: true,
    };
  }

  if (!pathTxtContent) {
    return {
      binaryPath: null,
      pathTxtContent: null,
      expectedRel,
      overridden: false,
    };
  }

  return {
    binaryPath: path.join(electronDir, "dist", pathTxtContent),
    pathTxtContent,
    expectedRel,
    overridden: false,
  };
}

function ensurePosixExecutable(binaryPath, { platform = process.platform } = {}) {
  if (platform === "win32") return { ok: true };

  try {
    fs.accessSync(binaryPath, fs.constants.X_OK);
    return { ok: true };
  } catch (err) {
    if (err && err.code !== "EACCES") {
      return { ok: false, reason: err.code || "ERR", error: err };
    }
  }

  try {
    fs.chmodSync(binaryPath, 0o755);
    fs.accessSync(binaryPath, fs.constants.X_OK);
    return { ok: true };
  } catch (err) {
    return {
      ok: false,
      reason: err && err.code ? err.code : "EACCES",
      error: err,
    };
  }
}

function checkElectronBinary(
  electronDir,
  {
    platform = process.platform,
    env = process.env,
    probeExec = false,
    spawnFn = spawnSync,
  } = {},
) {
  const resolution = resolveElectronBinary(electronDir, { platform, env });

  if (!resolution.overridden && !resolution.pathTxtContent) {
    return {
      ok: false,
      reason: "MISSING_PATH_TXT",
      binaryPath: path.join(electronDir, "dist", resolution.expectedRel),
    };
  }

  const { binaryPath } = resolution;
  if (!binaryPath || !fs.existsSync(binaryPath)) {
    return {
      ok: false,
      reason: "MISSING_BINARY",
      binaryPath,
    };
  }

  let stat;
  try {
    stat = fs.statSync(binaryPath);
  } catch (err) {
    return { ok: false, reason: "STAT_FAILED", binaryPath, error: err };
  }

  if (!stat.isFile()) {
    return { ok: false, reason: "NOT_A_FILE", binaryPath };
  }

  const permCheck = ensurePosixExecutable(binaryPath, { platform });
  if (!permCheck.ok) {
    return {
      ok: false,
      reason: permCheck.reason,
      binaryPath,
      error: permCheck.error,
    };
  }

  if (probeExec) {
    const result = spawnFn(binaryPath, ["--version"], {
      stdio: "ignore",
      timeout: 5000,
    });
    if (result && result.error && result.error.code === "EACCES") {
      return {
        ok: false,
        reason: "EACCES",
        binaryPath,
        error: result.error,
      };
    }
  }

  return { ok: true, reason: "OK", binaryPath };
}

function getZipExtractors(zipPath, destDir, platform = process.platform) {
  if (platform === "darwin") {
    return [
      { cmd: "ditto", args: ["-xk", zipPath, destDir] },
      { cmd: "unzip", args: ["-oq", zipPath, "-d", destDir] },
      { cmd: "tar", args: ["-xf", zipPath, "-C", destDir] },
      { cmd: "python3", args: ["-m", "zipfile", "-e", zipPath, destDir] },
    ];
  }
  if (platform === "win32") {
    const escapedZip = zipPath.replace(/'/g, "''");
    const escapedDest = destDir.replace(/'/g, "''");
    return [
      { cmd: "tar", args: ["-xf", zipPath, "-C", destDir] },
      {
        cmd: "powershell",
        args: [
          "-NoProfile",
          "-NonInteractive",
          "-Command",
          `Expand-Archive -LiteralPath '${escapedZip}' -DestinationPath '${escapedDest}' -Force`,
        ],
      },
      { cmd: "python", args: ["-m", "zipfile", "-e", zipPath, destDir] },
    ];
  }
  return [
    { cmd: "unzip", args: ["-oq", zipPath, "-d", destDir] },
    { cmd: "bsdtar", args: ["-xf", zipPath, "-C", destDir] },
    { cmd: "tar", args: ["-xf", zipPath, "-C", destDir] },
    { cmd: "python3", args: ["-m", "zipfile", "-e", zipPath, destDir] },
  ];
}

function extractZip(zipPath, destDir, { platform = process.platform, spawnFn = spawnSync } = {}) {
  fs.mkdirSync(destDir, { recursive: true });
  const attempts = [];

  for (const extractor of getZipExtractors(zipPath, destDir, platform)) {
    const res = spawnFn(extractor.cmd, extractor.args, { stdio: "pipe" });
    if (!res.error && res.status === 0) {
      return { ok: true, tool: extractor.cmd };
    }
    attempts.push(`${extractor.cmd}: ${res.error ? res.error.message : `exit ${res.status}`}`);
  }

  throw new Error(`Failed to extract ${zipPath} into ${destDir} (${attempts.join("; ")})`);
}

function finalizeElectronInstall(electronDir, { platform = process.platform } = {}) {
  const distDir = path.join(electronDir, "dist");
  const expectedRel = getPlatformBinaryRelativePath(platform);
  const srcTypeDefPath = path.join(distDir, "electron.d.ts");
  const targetTypeDefPath = path.join(electronDir, "electron.d.ts");

  if (fs.existsSync(srcTypeDefPath)) {
    fs.renameSync(srcTypeDefPath, targetTypeDefPath);
  }

  fs.writeFileSync(path.join(electronDir, "path.txt"), expectedRel, "utf8");

  if (platform !== "win32") {
    const binaryPath = path.join(distDir, expectedRel);
    if (fs.existsSync(binaryPath)) {
      fs.chmodSync(binaryPath, 0o755);
    }
    if (platform === "linux") {
      for (const helper of POSIX_HELPER_BINARIES) {
        const helperPath = path.join(distDir, helper);
        if (fs.existsSync(helperPath)) {
          try {
            fs.chmodSync(helperPath, 0o755);
          } catch {
            // Non-fatal for optional helper binaries.
          }
        }
      }
    }
  }
}

function formatEaccesHint(binaryPath) {
  const distDir = path.dirname(binaryPath);
  return [
    `[ensure-electron] Execution blocked with EACCES for: ${binaryPath}`,
    `This usually happens when node_modules is on a filesystem mounted with 'noexec' or restricted permissions.`,
    `Fix: copy "${distDir}" to an executable directory (for example "~/.local/share/onx-electron-dist") and launch with:`,
    `  ELECTRON_OVERRIDE_DIST_PATH="$HOME/.local/share/onx-electron-dist" npm start`,
  ].join("\n");
}

function readInstalledElectronVersion(electronDir) {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(electronDir, "package.json"), "utf8"));
    return pkg.version || null;
  } catch {
    return null;
  }
}

function ensureElectron({
  desktopDir = path.resolve(__dirname, ".."),
  platform = process.platform,
  arch = process.arch,
  env = process.env,
  homeDir = os.homedir(),
  probeExec = true,
  spawnFn = spawnSync,
  log = console.log,
  warn = console.warn,
} = {}) {
  const electronDir = path.join(desktopDir, "node_modules", "electron");
  if (!fs.existsSync(path.join(electronDir, "package.json"))) {
    throw new Error(
      `Electron package not found in "${electronDir}". Run "npm install" in "${desktopDir}" first.`,
    );
  }

  const initial = checkElectronBinary(electronDir, { platform, env, probeExec, spawnFn });
  if (initial.ok) {
    return { healed: false, method: "already-installed", binaryPath: initial.binaryPath };
  }

  if (initial.reason === "EACCES") {
    const hint = formatEaccesHint(initial.binaryPath);
    throw new Error(hint);
  }

  log(`[ensure-electron] Electron binary check failed (${initial.reason}); repairing installation...`);

  // Step 1: Run electron's own install.js first.
  const installScript = path.join(electronDir, "install.js");
  if (fs.existsSync(installScript)) {
    const installRes = spawnFn(process.execPath, [installScript], {
      cwd: desktopDir,
      env,
      stdio: "inherit",
    });
    if (installRes.error) {
      warn(`[ensure-electron] install.js spawn failed: ${installRes.error.message}`);
    }
  }

  const afterInstallJs = checkElectronBinary(electronDir, { platform, env, probeExec, spawnFn });
  if (afterInstallJs.ok) {
    log("[ensure-electron] Electron installation restored via install.js.");
    return { healed: true, method: "install.js", binaryPath: afterInstallJs.binaryPath };
  }

  if (afterInstallJs.reason === "EACCES") {
    throw new Error(formatEaccesHint(afterInstallJs.binaryPath));
  }

  // Step 2: Fallback to cached archive extraction if install.js left dist/ or path.txt incomplete.
  const version = readInstalledElectronVersion(electronDir);
  const cachedZip = findCachedElectronZip({ version, platform, arch, env, homeDir });
  if (!cachedZip) {
    throw new Error(
      `Electron binary still missing (${afterInstallJs.reason}) and no cached electron-v*-${platform}-${arch}.zip archive was found.`,
    );
  }

  log(`[ensure-electron] Extracting cached Electron archive: ${cachedZip}`);
  extractZip(cachedZip, path.join(electronDir, "dist"), { platform, spawnFn });
  finalizeElectronInstall(electronDir, { platform });

  const afterCache = checkElectronBinary(electronDir, { platform, env, probeExec, spawnFn });
  if (afterCache.ok) {
    log("[ensure-electron] Electron installation restored from cache.");
    return { healed: true, method: "cache-extract", binaryPath: afterCache.binaryPath };
  }

  if (afterCache.reason === "EACCES") {
    throw new Error(formatEaccesHint(afterCache.binaryPath));
  }

  throw new Error(
    `Electron self-healing failed (${afterCache.reason}) for binary at ${afterCache.binaryPath}.`,
  );
}

if (require.main === module) {
  try {
    ensureElectron();
  } catch (err) {
    console.error(err instanceof Error ? err.message : String(err));
    process.exit(1);
  }
}

module.exports = {
  checkElectronBinary,
  ensureElectron,
  extractZip,
  finalizeElectronInstall,
  findCachedElectronZip,
  formatEaccesHint,
  getCacheDirectories,
  getPlatformBinaryRelativePath,
  resolveElectronBinary,
};
