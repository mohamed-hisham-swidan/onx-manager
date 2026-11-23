import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import { createRequire } from "node:module";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const require = createRequire(import.meta.url);
const {
  LocalBackendManager,
  findAvailablePort,
  probePanelEndpoint,
  resolveInstallDir,
} = require("../backendManager");

test("resolveInstallDir finds repository checkout root automatically", () => {
  const dir = resolveInstallDir();
  assert.equal(path.basename(dir), "onx-manager");
});

test("resolveInstallDir honors ONX_INSTALL_DIR and APPIMAGE ancestor paths", () => {
  const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..", "..");
  const appImagePath = path.join(repoRoot, "desktop", "dist", "ONX-Manager-0.1.0-x86_64.AppImage");
  assert.equal(
    resolveInstallDir(null, { APPIMAGE: appImagePath }, "/tmp", "/tmp/mount/app"),
    repoRoot,
  );

  const customDir = fs.mkdtempSync(path.join(os.tmpdir(), "onx-install-"));
  try {
    fs.mkdirSync(path.join(customDir, "backend"), { recursive: true });
    fs.writeFileSync(path.join(customDir, "backend", "pyproject.toml"), "[project]\nname='onx'\n");
    assert.equal(
      resolveInstallDir(null, { ONX_INSTALL_DIR: customDir }, "/tmp", "/tmp/mount/app"),
      path.resolve(customDir),
    );
  } finally {
    fs.rmSync(customDir, { recursive: true, force: true });
  }
});

test("findAvailablePort skips busy loopback port", async () => {
  const blocker = net.createServer();
  await new Promise((resolve) => blocker.listen(0, "127.0.0.1", resolve));
  const busyPort = blocker.address().port;
  try {
    const picked = await findAvailablePort(busyPort, 10);
    assert.notEqual(picked, busyPort);
    assert.ok(picked > busyPort);
  } finally {
    await new Promise((resolve) => blocker.close(resolve));
  }
});

test("probePanelEndpoint validates live ONX status and reports offline errors", async () => {
  const server = http.createServer((req, res) => {
    if (req.url === "/api/v1/setup/status") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          initialized: true,
          access_mode: "LOCAL",
          user_count: 1,
          version: "0.1.0",
          deployment_profile: "local",
          password_configured: false,
          auth_mode: "local_zero_login",
        }),
      );
      return;
    }
    res.writeHead(404);
    res.end();
  });

  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  try {
    const okResult = await probePanelEndpoint(`http://127.0.0.1:${port}`);
    assert.equal(okResult.ok, true);
    assert.equal(okResult.version, "0.1.0");
    assert.equal(okResult.deploymentProfile, "local");
    assert.equal(okResult.initialized, true);
    assert.equal(okResult.authMode, "local_zero_login");
    assert.equal(okResult.passwordConfigured, false);

    const failResult = await probePanelEndpoint("http://127.0.0.1:1");
    assert.equal(failResult.ok, false);
    assert.ok(failResult.error);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("LocalBackendManager fails cleanly when virtualenv is missing", async () => {
  const mgr = new LocalBackendManager({ installDir: "/tmp/nonexistent-onx-dir-xyz" });
  await assert.rejects(() => mgr.start(), /virtualenv not found/i);
  assert.equal(mgr.getSnapshot().status, "error");
});

function createFakeInstallDir({ reconcileExit = 0, reconcileJson = null } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "onx-desktop-mgr-"));
  const backendDir = path.join(dir, "backend");
  const venvBinDir = path.join(backendDir, ".venv", "bin");
  const reconcilerDir = path.join(backendDir, "app", "core", "persistence");
  fs.mkdirSync(venvBinDir, { recursive: true });
  fs.mkdirSync(reconcilerDir, { recursive: true });
  fs.writeFileSync(path.join(backendDir, "pyproject.toml"), "[project]\nname='onx-manager'\n");
  fs.writeFileSync(path.join(reconcilerDir, "reconciler.py"), "# stub\n");

  const orderLog = path.join(dir, "invocations.log");
  const fakeScript = path.join(dir, "fake_python.mjs");
  const payloadJson = JSON.stringify(
    reconcileJson || {
      status: "RECONCILED",
      action_taken: "UPGRADE",
      target_revision: "b1e2100000034",
      message: "Database successfully upgraded to head revision 'b1e2100000034'.",
    },
  );

  fs.writeFileSync(
    fakeScript,
    `import fs from "node:fs";
import http from "node:http";

const args = process.argv.slice(2);
const orderLog = ${JSON.stringify(orderLog)};
if (args[0] === "-m" && args[1] === "app.core.persistence.reconciler") {
  fs.appendFileSync(orderLog, "reconciler\\n");
  process.stdout.write("Alembic target DB: stub\\n");
  process.stdout.write(${JSON.stringify(payloadJson)} + "\\n");
  process.exit(${Number(reconcileExit)});
}
if (args[0] === "-m" && args[1] === "uvicorn") {
  fs.appendFileSync(orderLog, "uvicorn\\n");
  const portIdx = args.indexOf("--port");
  const hostIdx = args.indexOf("--host");
  const port = Number(portIdx >= 0 ? args[portIdx + 1] : 8000);
  const host = hostIdx >= 0 ? args[hostIdx + 1] : "127.0.0.1";
  const server = http.createServer((req, res) => {
    if (req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "ok" }));
      return;
    }
    res.writeHead(404);
    res.end();
  });
  server.listen(port, host);
  process.on("SIGTERM", () => server.close(() => process.exit(0)));
}
`,
  );

  const wrapperPath = path.join(venvBinDir, "python");
  fs.writeFileSync(wrapperPath, `#!/bin/sh\nexec ${JSON.stringify(process.execPath)} ${JSON.stringify(fakeScript)} "$@"\n`);
  fs.chmodSync(wrapperPath, 0o755);

  return { dir, orderLog };
}

test(
  "LocalBackendManager runs database reconciler before starting uvicorn",
  { skip: process.platform === "win32" },
  async () => {
    const { dir, orderLog } = createFakeInstallDir();
    const mgr = new LocalBackendManager({ installDir: dir, preferredPort: 48120 });
    try {
      const snap = await mgr.start();
      assert.equal(snap.status, "running");
      const invocations = fs.readFileSync(orderLog, "utf8").trim().split(/\r?\n/);
      assert.deepEqual(invocations, ["reconciler", "uvicorn"]);
      assert.ok(mgr.getLogs().some((line) => line.includes("RECONCILED")));
    } finally {
      await mgr.stop();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  },
);

test(
  "LocalBackendManager aborts startup when database reconciliation fails",
  { skip: process.platform === "win32" },
  async () => {
    const { dir, orderLog } = createFakeInstallDir({
      reconcileExit: 1,
      reconcileJson: {
        status: "BLOCKED_UNSAFE",
        message: "Unknown schema revision detected",
      },
    });
    const mgr = new LocalBackendManager({ installDir: dir, preferredPort: 48140 });
    try {
      await assert.rejects(
        () => mgr.start(),
        /Database schema reconciliation failed: Unknown schema revision detected/,
      );
      assert.equal(mgr.getSnapshot().status, "error");
      const invocations = fs.readFileSync(orderLog, "utf8").trim().split(/\r?\n/);
      assert.deepEqual(invocations, ["reconciler"]);
    } finally {
      await mgr.stop();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  },
);
