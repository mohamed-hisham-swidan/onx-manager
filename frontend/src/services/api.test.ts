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
});
