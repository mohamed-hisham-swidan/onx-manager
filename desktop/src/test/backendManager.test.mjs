import assert from "node:assert/strict";
import http from "node:http";
import { createRequire } from "node:module";
import net from "node:net";
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
          initialized: false,
          access_mode: "LOCAL",
          user_count: 0,
          version: "0.1.0",
          deployment_profile: "vps",
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
    assert.equal(okResult.deploymentProfile, "vps");
    assert.equal(okResult.initialized, false);

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
