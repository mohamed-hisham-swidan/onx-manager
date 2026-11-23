"use strict";

const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const { spawn, execFileSync } = require("node:child_process");

const { normalizePanelUrl } = require("./connectionsStore");

const MAX_LOG_LINES = 120;

function addAncestors(list, startPath, depth = 4) {
  if (!startPath) return;
  let current = path.resolve(startPath);
  for (let i = 0; i <= depth; i++) {
    list.push(current);
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
}

function resolveInstallDir(explicitDir, env = process.env, cwd = process.cwd(), execPath = process.execPath) {
  if (explicitDir) {
    return path.resolve(explicitDir);
  }
  const candidates = [];
  if (env.ONX_INSTALL_DIR) candidates.push(env.ONX_INSTALL_DIR);
  candidates.push(path.resolve(__dirname, "..", ".."));

  if (env.APPIMAGE) {
    addAncestors(candidates, path.dirname(env.APPIMAGE), 4);
  }
  if (execPath) {
    addAncestors(candidates, path.dirname(execPath), 4);
  }
  if (cwd) {
    addAncestors(candidates, cwd, 4);
  }

  const standardDir =
    process.platform === "win32" && env.LOCALAPPDATA
      ? path.join(env.LOCALAPPDATA, "onx-manager")
      : path.join(os.homedir(), ".local", "share", "onx-manager");
  candidates.push(standardDir);

  for (const dir of candidates) {
    if (
      dir &&
      fs.existsSync(path.join(dir, "backend", "pyproject.toml"))
    ) {
      return path.resolve(dir);
    }
  }
  return path.resolve(candidates[0]);
}

function findVenvPython(installDir) {
  const winPy = path.join(installDir, "backend", ".venv", "Scripts", "python.exe");
  const posixPy = path.join(installDir, "backend", ".venv", "bin", "python");
  if (process.platform === "win32" && fs.existsSync(winPy)) return winPy;
  if (fs.existsSync(posixPy)) return posixPy;
  if (fs.existsSync(winPy)) return winPy;
  return null;
}

function _readConfiguredBindHost(backendDir) {
  try {
    const settingsPath = path.join(backendDir, "config", "settings.yaml");
    if (!fs.existsSync(settingsPath)) return null;
    const raw = fs.readFileSync(settingsPath, "utf8");
    const match = raw.match(/^\s*panel_bind_host:\s*['"]?([^'"\s#]+)['"]?/m);
    return match && match[1] ? match[1].trim() : null;
  } catch {
    return null;
  }
}

function isPortFree(port, host = "127.0.0.1") {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, host);
  });
}

async function findAvailablePort(preferredPort = 8000, span = 50) {
  for (let offset = 0; offset < span; offset++) {
    const port = preferredPort + offset;
    if (await isPortFree(port, "127.0.0.1")) {
      return port;
    }
  }
  throw new Error(`No free loopback port found between ${preferredPort} and ${preferredPort + span - 1}.`);
}

function httpGetJson(urlString, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(urlString);
    const transport = parsed.protocol === "https:" ? https : http;
    const req = transport.request(
      parsed,
      { method: "GET", timeout: timeoutMs, headers: { Accept: "application/json" } },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const body = Buffer.concat(chunks).toString("utf8");
          try {
            const json = JSON.parse(body);
            resolve({ status: res.statusCode || 0, data: json });
          } catch {
            resolve({ status: res.statusCode || 0, data: null });
          }
        });
      },
    );
    req.on("timeout", () => {
      req.destroy(new Error(`Request timed out after ${timeoutMs}ms`));
    });
    req.on("error", reject);
    req.end();
  });
}

async function probePanelEndpoint(rawUrl, timeoutMs = 8000) {
  const baseUrl = normalizePanelUrl(rawUrl);
  try {
    const statusRes = await httpGetJson(`${baseUrl}/api/v1/setup/status`, timeoutMs);
    if (statusRes.status >= 200 && statusRes.status < 300 && statusRes.data && typeof statusRes.data.initialized === "boolean") {
      return {
        ok: true,
        url: baseUrl,
        version: statusRes.data.version || null,
        initialized: statusRes.data.initialized,
        deploymentProfile: statusRes.data.deployment_profile || "vps",
        authMode: statusRes.data.auth_mode || "jwt",
        passwordConfigured: Boolean(statusRes.data.password_configured),
        error: null,
      };
    }
    const healthRes = await httpGetJson(`${baseUrl}/health`, timeoutMs);
    if (healthRes.status >= 200 && healthRes.status < 300 && healthRes.data && healthRes.data.status === "ok") {
      return {
        ok: true,
        url: baseUrl,
        version: healthRes.data.version || null,
        initialized: null,
        deploymentProfile: healthRes.data.deployment_profile || "vps",
        authMode: null,
        passwordConfigured: null,
        error: null,
      };
    }
    return {
      ok: false,
      url: baseUrl,
      version: null,
      initialized: null,
      deploymentProfile: null,
      authMode: null,
      passwordConfigured: null,
      error: `Panel responded with HTTP ${statusRes.status || healthRes.status || "error"}.`,
    };
  } catch (err) {
    return {
      ok: false,
      url: baseUrl,
      version: null,
      initialized: null,
      deploymentProfile: null,
      authMode: null,
      passwordConfigured: null,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

class LocalBackendManager {
  constructor(options = {}) {
    this.installDir = resolveInstallDir(options.installDir);
    this.preferredPort = Number(options.preferredPort || process.env.ONX_BACKEND_PORT || 8000);
    this.healthTimeoutMs = Number(options.healthTimeoutMs || 35000);
    this.child = null;
    this.port = null;
    this.status = "stopped";
    this.lastError = null;
    this.logs = [];
    this.onStatusChange = typeof options.onStatusChange === "function" ? options.onStatusChange : () => {};
    this._startingPromise = null;
  }

  _appendLog(line) {
    if (!line) return;
    for (const part of String(line).split(/\r?\n/)) {
      if (!part) continue;
      this.logs.push(part);
      if (this.logs.length > MAX_LOG_LINES) {
        this.logs.shift();
      }
    }
  }

  _setStatus(status, error = null) {
    this.status = status;
    this.lastError = error;
    this.onStatusChange(this.getSnapshot());
  }

  getSnapshot() {
    return {
      status: this.status,
      port: this.port,
      url: this.port ? `http://127.0.0.1:${this.port}` : null,
      installDir: this.installDir,
      error: this.lastError,
    };
  }

  getLogs() {
    return [...this.logs];
  }

  async _reconcileDatabase(pyBin, backendDir, env) {
    const reconcilerEnv = {
      ...env,
      PYTHONPATH: env.PYTHONPATH ? `${backendDir}${path.delimiter}${env.PYTHONPATH}` : backendDir,
    };

    const { code, stdout, stderr } = await new Promise((resolve, reject) => {
      const child = spawn(pyBin, ["-m", "app.core.persistence.reconciler", "--json"], {
        cwd: backendDir,
        env: reconcilerEnv,
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
      });

      const outChunks = [];
      const errChunks = [];
      let timedOut = false;

      const timer = setTimeout(() => {
        timedOut = true;
        try {
          child.kill("SIGKILL");
        } catch {
          // Ignore
        }
      }, 60000);
      timer.unref();

      child.stdout.on("data", (chunk) => outChunks.push(chunk));
      child.stderr.on("data", (chunk) => errChunks.push(chunk));
      child.once("error", (err) => {
        clearTimeout(timer);
        reject(err);
      });
      child.once("exit", (exitCode) => {
        clearTimeout(timer);
        const stdoutText = Buffer.concat(outChunks).toString("utf8");
        const stderrText = Buffer.concat(errChunks).toString("utf8");
        if (timedOut) {
          reject(new Error("Database schema reconciliation timed out after 60s."));
          return;
        }
        resolve({ code: exitCode ?? 1, stdout: stdoutText, stderr: stderrText });
      });
    });

    if (stderr && stderr.trim()) {
      this._appendLog(stderr);
    }

    let parsed = null;
    const lines = stdout
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    for (let i = lines.length - 1; i >= 0; i--) {
      if (lines[i].startsWith("{") && lines[i].endsWith("}")) {
        try {
          parsed = JSON.parse(lines[i]);
          break;
        } catch {
          // Try preceding line
        }
      }
    }

    const okStatuses = new Set(["READY", "RECONCILED"]);
    if (code === 0 && (!parsed || okStatuses.has(parsed.status))) {
      if (parsed && parsed.message) {
        this._appendLog(`[Database] ${parsed.status}: ${parsed.message}`);
      } else {
        this._appendLog("[Database] Schema check passed.");
      }
      return parsed;
    }

    const detail =
      (parsed && (parsed.message || parsed.error_detail || parsed.status)) ||
      stderr.trim() ||
      stdout.trim() ||
      `reconciler exited with code ${code}`;
    const msg = `Database schema reconciliation failed: ${detail}`;
    this._appendLog(msg);
    throw new Error(msg);
  }

  async _waitForHealthy(port) {
    const deadline = Date.now() + this.healthTimeoutMs;
    const url = `http://127.0.0.1:${port}/health`;
    while (Date.now() < deadline) {
      if (!this.child || this.child.exitCode !== null) {
        throw new Error(`Local backend exited early (code ${this.child ? this.child.exitCode : "unknown"}).`);
      }
      try {
        const res = await httpGetJson(url, 1500);
        if (res.status === 200 && res.data && res.data.status === "ok") {
          return true;
        }
      } catch {
        // Not listening yet
      }
      await new Promise((r) => setTimeout(r, 350));
    }
    throw new Error(`Local backend failed health check within ${this.healthTimeoutMs}ms.`);
  }

  async start() {
    if (this.status === "running" && this.child && this.child.exitCode === null && this.port) {
      return this.getSnapshot();
    }
    if (this._startingPromise) {
      return this._startingPromise;
    }

    this._startingPromise = this._startInternal().finally(() => {
      this._startingPromise = null;
    });
    return this._startingPromise;
  }

  async _startInternal() {
    const pyBin = findVenvPython(this.installDir);
    if (!pyBin) {
      const msg = `Python 3.12 virtualenv not found in ${path.join(this.installDir, "backend", ".venv")}. Run install.sh / install.ps1 first.`;
      this._setStatus("error", msg);
      throw new Error(msg);
    }

    this._setStatus("starting", null);
    this.logs = [];

    const port = await findAvailablePort(this.preferredPort, 50);
    this.port = port;

    const backendDir = path.join(this.installDir, "backend");
    const staticDir = path.join(this.installDir, "frontend", "dist");
    const envBindHost = process.env.ONX_PANEL_BIND_HOST || process.env.MCS_PANEL_BIND_HOST;
    const configuredBindHost = _readConfiguredBindHost(backendDir);
    const bindHost = envBindHost || configuredBindHost || "127.0.0.1";
    const env = {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      ONX_DEPLOYMENT_PROFILE: "local",
      ONX_PANEL_BIND_PORT: String(port),
      ONX_STATIC_DIR: fs.existsSync(path.join(staticDir, "index.html")) ? staticDir : "off",
    };

    const reconcilerScript = path.join(backendDir, "app", "core", "persistence", "reconciler.py");
    if (fs.existsSync(reconcilerScript)) {
      try {
        await this._reconcileDatabase(pyBin, backendDir, env);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        this.port = null;
        this._setStatus("error", msg);
        throw err;
      }
    }

    const child = spawn(
      pyBin,
      ["-m", "uvicorn", "app.main:app", "--host", bindHost, "--port", String(port), "--workers", "1"],
      {
        cwd: backendDir,
        env,
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    this.child = child;

    child.stdout.on("data", (chunk) => this._appendLog(chunk.toString("utf8")));
    child.stderr.on("data", (chunk) => this._appendLog(chunk.toString("utf8")));
    child.once("exit", (code, signal) => {
      if (this.child === child) {
        this.child = null;
        if (this.status === "running") {
          this._setStatus("stopped", code ? `Exited with code ${code} (${signal || "signal"})` : null);
        }
      }
    });

    try {
      await this._waitForHealthy(port);
      this._setStatus("running", null);
      return this.getSnapshot();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      await this.stop();
      this._setStatus("error", msg);
      throw err;
    }
  }

  async stop() {
    const proc = this.child;
    this.child = null;
    this.port = null;
    if (!proc || proc.exitCode !== null) {
      this._setStatus("stopped", null);
      return;
    }

    await new Promise((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        resolve();
      };
      proc.once("exit", finish);

      if (process.platform === "win32") {
        try {
          execFileSync("taskkill", ["/PID", String(proc.pid), "/T", "/F"], {
            windowsHide: true,
            stdio: "ignore",
          });
        } catch {
          try {
            proc.kill("SIGKILL");
          } catch {
            // Already exited
          }
        }
      } else {
        try {
          proc.kill("SIGTERM");
        } catch {
          finish();
          return;
        }
      }

      const timer = setTimeout(() => {
        if (proc.exitCode === null) {
          try {
            proc.kill("SIGKILL");
          } catch {
            // Ignore
          }
        }
        finish();
      }, 4000);
      timer.unref();
    });

    this._setStatus("stopped", null);
  }

  async restart() {
    await this.stop();
    return this.start();
  }
}

module.exports = {
  LocalBackendManager,
  findAvailablePort,
  findVenvPython,
  isPortFree,
  probePanelEndpoint,
  resolveInstallDir,
};
