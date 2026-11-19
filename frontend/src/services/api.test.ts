import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createApiClient, ApiError, createAuthenticatedApi } from "./api";

function mockFetch(data: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    status,
    ok: status >= 200 && status < 300,
    json: vi.fn().mockResolvedValue(data),
  });
}

function mockFetchNetworkError() {
  return vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
}

describe("createApiClient", () => {
  let api: ReturnType<typeof createApiClient>;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    api = createApiClient("http://localhost:8000", () => null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("health returns status", async () => {
    const data = { status: "ok", version: "1.0", database: "connected", uptime_seconds: 1234 };
    vi.mocked(fetch).mockImplementationOnce(mockFetch(data));
    const result = await api.health();
    expect(result.status).toBe("ok");
    expect(result.version).toBe("1.0");
  });

  it("login sends POST with body", async () => {
    const resp = { access_token: "tok", refresh_token: "rtok", token_type: "bearer", expires_in: 3600 };
    vi.mocked(fetch).mockImplementationOnce(mockFetch(resp));
    const result = await api.login({ email: "a@b.com", password: "secret" });

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/auth/login",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ email: "a@b.com", password: "secret" }),
      }),
    );
    expect(result.access_token).toBe("tok");
  });

  it("injects authorization header when token available", async () => {
    api = createApiClient("http://localhost:8000", () => "my-token");
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ status: "ok", version: "", database: "", uptime_seconds: null }));
    await api.health();

    expect(fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer my-token" }),
      }),
    );
  });

  it("listServers sends GET with no body", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch([{ server_id: "s1", name: "Test" }]));
    const result = await api.listServers();
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/servers"),
      expect.objectContaining({ method: "GET" }),
    );
    expect(result).toHaveLength(1);
    expect(result[0].server_id).toBe("s1");
  });

  it("listServers passes params as query string", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch([]));
    await api.listServers({ status: "running" });
    const url = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(url).toContain("status=running");
  });

  it("searchMarketplaceGlobal hits global endpoint with query params", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({
      items: [{ project_id: "p1", title: "Test" }],
      total_hits: 1,
      offset: 20,
      limit: 10,
    }));
    const result = await api.searchMarketplaceGlobal("essentials", "mod", 10, 20);

    const url = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(url).toContain("/api/v1/marketplace/search");
    expect(url).toContain("query=essentials");
    expect(url).toContain("project_type=mod");
    expect(url).toContain("limit=10");
    expect(url).toContain("offset=20");
    expect(result.items).toHaveLength(1);
    expect(result.items[0].project_id).toBe("p1");
    expect(result.total_hits).toBe(1);
  });

  it("searchMarketplaceGlobal appends the loader platform filter", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ items: [], total_hits: 0, offset: 0, limit: 20 }));
    await api.searchMarketplaceGlobal("sodium", "mod", 20, 0, "neoforge");

    const url = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(url).toContain("loader=neoforge");

    vi.mocked(fetch).mockImplementationOnce(mockFetch({ items: [], total_hits: 0, offset: 0, limit: 20 }));
    await api.searchMarketplaceGlobal("sodium", "mod");
    const urlNoLoader = vi.mocked(fetch).mock.calls[1][0] as string;
    expect(urlNoLoader).not.toContain("loader=");
  });

  it("throws ApiError on 4xx", async () => {
    const errBody = { error: "Not found", error_code: "NOT_FOUND", detail: null, timestamp: null };
    vi.mocked(fetch).mockImplementation(mockFetch(errBody, 404));
    await expect(api.getServer("bad-id")).rejects.toThrow(ApiError);
    await expect(api.getServer("bad-id")).rejects.toThrow("Not found");
  });

  it("ApiError has status and code", async () => {
    const errBody = { error: "Unauthorized", error_code: "UNAUTHORIZED", detail: null, timestamp: null };
    vi.mocked(fetch).mockImplementation(mockFetch(errBody, 401));
    try {
      await api.getMe();
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const ae = e as ApiError;
      expect(ae.status).toBe(401);
      expect(ae.code).toBe("UNAUTHORIZED");
      expect(ae.message).toBe("Unauthorized");
    }
  });

  it("returns undefined on 204", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch(null, 204));
    const result = await api.deleteServer("s1");
    expect(result).toBeUndefined();
  });

  it("throws NETWORK_ERROR on fetch failure", async () => {
    vi.mocked(fetch).mockImplementation(mockFetchNetworkError());
    await expect(api.health()).rejects.toThrow(ApiError);
    await expect(api.health()).rejects.toThrow("Unable to reach server");
  });

  it("throws PARSE_ERROR on invalid JSON", async () => {
    vi.mocked(fetch).mockImplementation(
      vi.fn().mockResolvedValue({
        status: 200,
        ok: true,
        json: vi.fn().mockRejectedValue(new SyntaxError("Unexpected token")),
      }),
    );
    await expect(api.health()).rejects.toThrow(ApiError);
    await expect(api.health()).rejects.toThrow("Invalid response from server");
  });

  it("deleteServer sends DELETE", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch(null, 204));
    await api.deleteServer("s1");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/servers/s1"),
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("retryProvisioning sends POST to /api/v1/servers/{id}/retry-provisioning", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", status: "provisioning" }));
    const result = await api.retryProvisioning("s1");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/retry-provisioning",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result).toEqual({ server_id: "s1", status: "provisioning" });
  });

  it("ISS-062: listServerFiles and deleteServerFile call /files endpoint without trailing slash", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch([]));
    await api.listServerFiles("s1");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/files",
      expect.objectContaining({ method: "GET" }),
    );

    vi.mocked(fetch).mockImplementationOnce(mockFetch(null, 204));
    await api.deleteServerFile("s1", "world/level.dat");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/files?path=world%2Flevel.dat",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("readServerFileContent makes JSON request to /files/content with path param", async () => {
    const fileData = { path: "server.properties", content: "motd=Minecraft Server\nmax-players=20" };
    vi.mocked(fetch).mockImplementationOnce(mockFetch(fileData));
    const result = await api.readServerFileContent("s1", "server.properties");

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/files/content?path=server.properties",
      expect.objectContaining({ method: "GET" }),
    );
    expect(result).toEqual(fileData);
  });

  it("writeServerFileContent sends PUT to /files/content with path and content body", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ path: "server.properties", content: "motd=Updated" }));
    const result = await api.writeServerFileContent("s1", "server.properties", "motd=Updated");

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/files/content?path=server.properties",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ content: "motd=Updated" }),
      }),
    );
    expect(result).toEqual({ path: "server.properties", content: "motd=Updated" });
  });

  it("passes the selected branch to Files and Save & Commit requests", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch([]));
    await api.listServerFiles("s1", "config", "dev");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/files?path=config&branch=dev",
      expect.objectContaining({ method: "GET" }),
    );

    vi.mocked(fetch).mockImplementationOnce(mockFetch({ path: "config/app.yml", content: "a: 1" }));
    await api.readServerFileContent("s1", "config/app.yml", "dev");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/files/content?path=config%2Fapp.yml&branch=dev",
      expect.objectContaining({ method: "GET" }),
    );

    vi.mocked(fetch).mockImplementationOnce(mockFetch({ commit_id: "abc" }));
    await api.createServerCommit("s1", { message: "Save branch", branch_name: "dev" });
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/commits",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ message: "Save branch", branch_name: "dev" }),
      }),
    );
  });

  it("mkdirServerDirectory sends POST with joined full path query param and no body", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ name: "logs", path: "logs", is_dir: true, size: 0 }));
    await api.mkdirServerDirectory("s1", "", "logs");

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/files/mkdir?path=logs",
      expect.objectContaining({
        method: "POST",
        body: undefined,
      }),
    );

    vi.mocked(fetch).mockImplementationOnce(mockFetch({ name: "region", path: "world/region", is_dir: true, size: 0 }));
    await api.mkdirServerDirectory("s1", "world", "region");

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/files/mkdir?path=world%2Fregion",
      expect.objectContaining({
        method: "POST",
        body: undefined,
      }),
    );
  });

  it("ISS-043: createAuthenticatedApi returns a shared singleton instance across callers", () => {
    const client1 = createAuthenticatedApi();
    const client2 = createAuthenticatedApi();
    expect(client1).toBe(client2);
  });

  it("ISS-043: concurrent 401s on shared client execute only ONE refresh call and all succeed", async () => {
    let token = "expired-token";
    const onRefresh = vi.fn(async () => {
      token = "fresh-token";
      return { accessToken: "fresh-token", refreshToken: "fresh-refresh", expiresIn: 3600 };
    });

    const client = createApiClient(
      "http://localhost:8000",
      () => token,
      onRefresh,
      () => false, // disable proactive to specifically test concurrent 401 reactive refresh
    );

    // Mock responses: initial calls return 401, retry calls return 200
    vi.mocked(fetch).mockImplementation(async (_url, init) => {
      const auth = (init?.headers as Record<string, string>)?.Authorization;
      if (auth === "Bearer fresh-token") {
        return {
          status: 200,
          ok: true,
          json: async () => ({ status: "ok" }),
        } as Response;
      }
      return {
        status: 401,
        ok: false,
        json: async () => ({ detail: "Unauthorized" }),
      } as Response;
    });

    const [res1, res2] = await Promise.all([
      client.health(),
      client.health(),
    ]);

    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(res1).toEqual({ status: "ok" });
    expect(res2).toEqual({ status: "ok" });
  });

  it("ISS-055: proactive refresh triggers before request when token is expired/near-expiry", async () => {
    let token: string | null = "stale-token";
    const onRefresh = vi.fn(async () => {
      token = "fresh-proactive-token";
      return { accessToken: "fresh-proactive-token", refreshToken: "new-rt", expiresIn: 3600 };
    });

    // Custom isTokenExpiring returns true to simulate expired/near-expiry token
    const client = createApiClient(
      "http://localhost:8000",
      () => token,
      onRefresh,
      () => true,
    );

    vi.mocked(fetch).mockImplementation(async (_url, init) => {
      const auth = (init?.headers as Record<string, string>)?.Authorization;
      expect(auth).toBe("Bearer fresh-proactive-token");
      return {
        status: 200,
        ok: true,
        json: async () => ({ status: "ok" }),
      } as Response;
    });

    const res = await client.health();
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(res).toEqual({ status: "ok" });
  });

  it("ISS-054: formats FastAPI 422 validation error array into a readable message", async () => {
    const errorBody = {
      detail: [
        { loc: ["body", "name"], msg: "Field required", type: "missing" },
        { loc: ["body", "port"], msg: "Input should be greater than 0", type: "greater_than" },
      ],
    };
    vi.mocked(fetch).mockImplementationOnce(mockFetch(errorBody, 422));

    await expect(api.health()).rejects.toThrowError(
      "name: Field required; port: Input should be greater than 0",
    );

    try {
      vi.mocked(fetch).mockImplementationOnce(mockFetch(errorBody, 422));
      await api.health();
    } catch (e: unknown) {
      expect(e).toBeInstanceOf(ApiError);
      if (e instanceof ApiError) {
        expect(e.status).toBe(422);
        expect(e.code).toBe("VALIDATION_ERROR");
        expect(e.message).toBe("name: Field required; port: Input should be greater than 0");
        expect(e.detail).toEqual(errorBody.detail);
      }
    }
  });

  it("uploadImportZip uses fetch fallback when XMLHttpRequest is undefined", async () => {
    const mockScan = { path: "/staging/123", name: "test", server_type: "vanilla", properties: { port: 25565 } };
    vi.mocked(fetch).mockImplementationOnce(mockFetch(mockScan));

    // Ensure XMLHttpRequest is undefined
    const origXhr = globalThis.XMLHttpRequest;
    // @ts-expect-error override for test
    delete globalThis.XMLHttpRequest;

    try {
      const file = new File(["dummy content"], "server.zip", { type: "application/zip" });
      const result = await api.uploadImportZip(file);

      expect(fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/servers/import/upload",
        expect.objectContaining({
          method: "POST",
          body: expect.any(FormData),
        }),
      );
      expect(result).toEqual(mockScan);
    } finally {
      globalThis.XMLHttpRequest = origXhr;
    }
  });

  it("uploadImportZip uses XMLHttpRequest with progress reporting", async () => {
    const mockScan = { path: "/staging/456", name: "test-progress", server_type: "paper", properties: { port: 25565 } };
    const progressSpy = vi.fn();

    const mockXhr = {
      open: vi.fn(),
      setRequestHeader: vi.fn(),
      send: vi.fn(),
      upload: { onprogress: null as ((e: unknown) => void) | null },
      onload: null as (() => void) | null,
      onerror: null as (() => void) | null,
      status: 200,
      responseText: JSON.stringify(mockScan),
    };

    vi.stubGlobal("XMLHttpRequest", vi.fn(function () {
      return mockXhr;
    }));

    const file = new File(["dummy content"], "server.zip", { type: "application/zip" });
    const uploadPromise = api.uploadImportZip(file, progressSpy);

    expect(mockXhr.open).toHaveBeenCalledWith("POST", "http://localhost:8000/api/v1/servers/import/upload");

    if (mockXhr.upload.onprogress) {
      mockXhr.upload.onprogress({ lengthComputable: true, loaded: 50, total: 100 });
      expect(progressSpy).toHaveBeenCalledWith(50);
    }

    mockXhr.onload?.();
    const result = await uploadPromise;
    expect(result).toEqual(mockScan);
  });

  it("uploadImportZip handles XMLHttpRequest errors", async () => {
    const mockXhr = {
      open: vi.fn(),
      setRequestHeader: vi.fn(),
      send: vi.fn(),
      upload: { onprogress: null },
      onload: null as (() => void) | null,
      onerror: null as (() => void) | null,
      status: 413,
      responseText: JSON.stringify({ detail: "Archive too large" }),
    };

    vi.stubGlobal("XMLHttpRequest", vi.fn(function () {
      return mockXhr;
    }));

    const file = new File(["dummy content"], "big.zip", { type: "application/zip" });
    const uploadPromise = api.uploadImportZip(file);

    mockXhr.onload?.();
    await expect(uploadPromise).rejects.toThrow("Archive too large");
  });

  it("mergeServerCommits sends POST to commits/merge", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ commit_id: "m1", server_id: "s1", branch_name: "main", parent_commit_ids: [] }));
    const res = await api.mergeServerCommits("s1", { target_branch_name: "main", source_branch_name: "feat", message: "merge" });
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/commits/merge",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ target_branch_name: "main", source_branch_name: "feat", message: "merge" }) }),
    );
    expect(res.commit_id).toBe("m1");
  });

  it("getRefreshState sends GET to /versioning/refresh", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", active_journal: null, latest_journal: null, can_confirm_upgrade: false, can_rollback: false, previous_tree_retention: "until_health_gate" }));
    const res = await api.getRefreshState("s1");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/refresh",
      expect.objectContaining({ method: "GET" }),
    );
    expect(res.server_id).toBe("s1");
  });

  it("refreshServer sends POST to /versioning/refresh", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", journal_id: "j1", phase: "done", status: "ok" }));
    await api.refreshServer("s1", { retention_policy: "until_health_gate" });
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/refresh",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ retention_policy: "until_health_gate" }) }),
    );
  });

  it("rollbackRefresh sends POST to /versioning/rollback", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", journal_id: "j1", phase: "rolled_back", status: "ok" }));
    await api.rollbackRefresh("s1", { journal_id: "j1", reason: "operator_requested" });
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/rollback",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("confirmUpgrade sends POST to /versioning/upgrade/confirm", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", journal_id: "j1", phase: "confirmed", status: "ok" }));
    await api.confirmUpgrade("s1", { journal_id: "j1" });
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/upgrade/confirm",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("listClassCSnapshots sends GET", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch([{ snapshot_id: "snap1", server_id: "s1", created_at: null, manifest_sha256: null, pinned: false, entry_count: 1, archive_size_bytes: 10 }]));
    const res = await api.listClassCSnapshots("s1");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/class-c/snapshots",
      expect.objectContaining({ method: "GET" }),
    );
    expect(res).toHaveLength(1);
  });

  it("extractSecret sends POST and returns placeholder", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", branch: "dev", path: "config.yml", key_name: "DB_PASSWORD", placeholder: "${ONX_SECRET_DB_PASSWORD}", replaced_occurrences: 1, remaining_findings: [] }));
    const res = await api.extractSecret("s1", { branch: "dev", path: "config.yml", key_name: "DB_PASSWORD", secret_value: "secret" });
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/secrets/extract",
      expect.objectContaining({ method: "POST" }),
    );
    expect(res.placeholder).toBe("${ONX_SECRET_DB_PASSWORD}");
  });

  it("listLiveStateFiles sends GET to /files/live-state", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ items: [{ name: "whitelist.json", path: "/whitelist.json", is_dir: false, size: 10, modified_at: 1, file_class: "C", is_dynamic_class_c: false, writable: true }] }));
    const res = await api.listLiveStateFiles("s1", "/");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/files/live-state?path=%2F",
      expect.objectContaining({ method: "GET" }),
    );
    expect(res.items).toHaveLength(1);
  });

  it("writeLiveStateFileContent sends PUT to /files/live-state/content", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ status: "ok", server_id: "s1", path: "/whitelist.json", rcon_flushed: true, rcon_reloaded: true, reload_command: "whitelist reload" }));
    await api.writeLiveStateFileContent("s1", { path: "/whitelist.json", content: "{}", reload_command: "whitelist reload" });
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/files/live-state/content",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ path: "/whitelist.json", content: "{}", reload_command: "whitelist reload" }) }),
    );
  });

  // P4-3 / P4-4 Branch Runs, Port Sets & Data Templates
  it("listDataTemplates sends GET to /versioning/data-templates", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch([{ id: "tpl-1", name: "seed-1" }]));
    const result = await api.listDataTemplates("s1");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/data-templates",
      expect.objectContaining({ method: "GET" }),
    );
    expect(result).toHaveLength(1);
  });

  it("createDataTemplate sends POST with the template body", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ id: "tpl-1", name: "seed-1", status: "ready" }));
    const body = { name: "seed-1", source: "live" as const, async_mode: false };
    await api.createDataTemplate("s1", body);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/data-templates",
      expect.objectContaining({ method: "POST", body: JSON.stringify(body) }),
    );
  });

  it("deleteDataTemplate sends DELETE to the encoded template path", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ status: "deleted", server_id: "s1", template_id: "tpl-1" }));
    await api.deleteDataTemplate("s1", "tpl-1");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/data-templates/tpl-1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("allocateBranchPortSet encodes the branch name and sends include_query", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", branch_name: "feat/ui", port_set: { game_port: 25610, rcon_port: 25611 } }));
    await api.allocateBranchPortSet("s1", "feat/ui", { include_query: true });
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/branches/feat%2Fui/port-set/allocate",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ include_query: true }) }),
    );
  });

  it("setBranchPortSet sends PUT without forbidden container port fields", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", branch_name: "feat/ui", port_set: { game_port: 25610, rcon_port: 25611 } }));
    const body = { game_port: 25610, rcon_port: 25611 };
    await api.setBranchPortSet("s1", "feat/ui", body);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/branches/feat%2Fui/port-set",
      expect.objectContaining({ method: "PUT", body: JSON.stringify(body) }),
    );
  });

  it("getBranchRuntime sends GET to the encoded branch runtime path", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", branch_name: "feat/ui", runtime_status: "stopped" }));
    await api.getBranchRuntime("s1", "feat/ui");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/branches/feat%2Fui/runtime",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("startBranchRun sends POST to the encoded branch run path", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ runtime_id: "rt-1", branch_name: "feat/ui" }));
    const body = { data_template_id: "tpl-1", allow_public_test_join: false };
    await api.startBranchRun("s1", "feat/ui", body);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/branches/feat%2Fui/run",
      expect.objectContaining({ method: "POST", body: JSON.stringify(body) }),
    );
  });

  it("stopBranchRun sends POST to the encoded branch stop path", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ runtime_id: "rt-1", branch_name: "feat/ui", status: "stopped" }));
    const body = { keep_port_assignment: true, save_template_name: "after-test" };
    await api.stopBranchRun("s1", "feat/ui", body);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/branches/feat%2Fui/stop",
      expect.objectContaining({ method: "POST", body: JSON.stringify(body) }),
    );
  });

  it("saveBranchDataTemplate sends POST to the encoded save-data-template path", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ id: "tpl-2", name: "snap-1" }));
    const body = { name: "snap-1" };
    await api.saveBranchDataTemplate("s1", "feat/ui", body);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/branches/feat%2Fui/save-data-template",
      expect.objectContaining({ method: "POST", body: JSON.stringify(body) }),
    );
  });

  it("getBranchConsole sends GET with tail query param and encoded branch", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", branch_name: "feat/ui", runtime_id: "rt-1", container_name: "c1", lines: [] }));
    await api.getBranchConsole("s1", "feat/ui", 100);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/branches/feat%2Fui/console?tail=100",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("sendBranchConsoleCommand sends POST with the command body", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", branch_name: "feat/ui", runtime_id: "rt-1", command: "list", output: "players" }));
    const body = { command: "list" };
    await api.sendBranchConsoleCommand("s1", "feat/ui", body);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/branches/feat%2Fui/console/command",
      expect.objectContaining({ method: "POST", body: JSON.stringify(body) }),
    );
  });

  it("getServerActivity forwards the branch query param", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ items: [], total: 0, limit: 25, offset: 0 }));
    await api.getServerActivity("s1", { limit: 25, branch: "feat-trial" });
    const url = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(url).toContain("/api/v1/servers/s1/activity");
    expect(url).toContain("limit=25");
    expect(url).toContain("branch=feat-trial");
  });

  // P5-3 / P5-4 GitHub Sync
  it("getGitHubStatus sends GET to the encoded server github path", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "srv/1", connected: false }));
    await api.getGitHubStatus("srv/1");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/srv%2F1/versioning/github",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("generateGitHubDeployKey sends an optional trimmed comment and omits a blank one", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ public_key_openssh: "ssh-ed25519 AAAA" }));
    await api.generateGitHubDeployKey("s1", { comment: "  onx-key  " });
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/github/deploy-key/generate",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ comment: "onx-key" }),
      }),
    );

    vi.mocked(fetch).mockImplementationOnce(mockFetch({ public_key_openssh: "ssh-ed25519 BBBB" }));
    await api.generateGitHubDeployKey("s1", { comment: "   " });
    const init = vi.mocked(fetch).mock.calls[1][1] as RequestInit | undefined;
    expect(init?.body).toBeUndefined();
  });

  it("connectGitHub sends a clean payload and omits blank optional secrets", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", connected: true }));
    await api.connectGitHub("s1", {
      remote_url: "https://github.com/owner/repo.git",
      auth_method: "pat",
      credential_secret: "ghp_token",
      enable_webhook: false,
      deploy_public_key: "",
      webhook_secret: "",
    });
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit | undefined;
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/github/connect",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(String(init?.body))).toEqual({
      remote_url: "https://github.com/owner/repo.git",
      auth_method: "pat",
      credential_secret: "ghp_token",
      enable_webhook: false,
    });
  });

  it("rotateGitHubCredentials sends only populated rotation fields", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", connected: true }));
    await api.rotateGitHubCredentials("s1", {
      credential_secret: "new-token",
      auth_method: "pat",
      regenerate_webhook_secret: true,
      disable_webhook: false,
      enable_webhook: null,
      webhook_secret: "",
      deploy_public_key: "",
    });
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit | undefined;
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/github/credentials/rotate",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(String(init?.body))).toEqual({
      credential_secret: "new-token",
      auth_method: "pat",
      regenerate_webhook_secret: true,
    });
  });

  it("disconnectGitHub sends purge_deliveries=false by default and true when requested", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", disconnected: true }));
    await api.disconnectGitHub("s1");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/github?purge_deliveries=false",
      expect.objectContaining({ method: "DELETE" }),
    );

    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", disconnected: true }));
    await api.disconnectGitHub("s1", true);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/github?purge_deliveries=true",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("fetchGitHubSync sends POST with no body", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", sync_status: "synced" }));
    await api.fetchGitHubSync("s1");
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit | undefined;
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/github/fetch",
      expect.objectContaining({ method: "POST" }),
    );
    expect(init?.body).toBeUndefined();
  });

  it("pushGitHubBranch sends strictly branch_name and never force", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", branch_name: "feat/ui" }));
    const forgedBody = { branch_name: "feat/ui", force: true } as { branch_name: string };
    await api.pushGitHubBranch("s1", forgedBody);
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit | undefined;
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/github/push",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(String(init?.body))).toEqual({ branch_name: "feat/ui" });
    expect(String(init?.body)).not.toContain("force");
  });

  it("listGitHubWebhookDeliveries sends GET with limit=50 by default and custom limits", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch([]));
    await api.listGitHubWebhookDeliveries("s1");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/github/webhooks/deliveries?limit=50",
      expect.objectContaining({ method: "GET" }),
    );

    vi.mocked(fetch).mockImplementationOnce(mockFetch([]));
    await api.listGitHubWebhookDeliveries("s1", 10);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/github/webhooks/deliveries?limit=10",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("redeliverGitHubWebhook URL-encodes the delivery id and sends POST", async () => {
    vi.mocked(fetch).mockImplementationOnce(mockFetch({ server_id: "s1", delivery_id: "del/123+abc" }));
    await api.redeliverGitHubWebhook("s1", "del/123+abc");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/servers/s1/versioning/github/webhooks/deliveries/del%2F123%2Babc/redeliver",
      expect.objectContaining({ method: "POST" }),
    );
  });

});
