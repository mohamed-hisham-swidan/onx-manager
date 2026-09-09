import { describe, it, expect, beforeEach } from "vitest";
import { useMarketplaceSourceStore } from "./marketplaceSourceStore";

describe("useMarketplaceSourceStore", () => {
  beforeEach(() => {
    localStorage.removeItem("onx_marketplace_source");
    useMarketplaceSourceStore.setState({ source: "modrinth" });
  });

  it("defaults to modrinth source", () => {
    expect(useMarketplaceSourceStore.getState().source).toBe("modrinth");
  });

  it("updates source and persists to localStorage", () => {
    useMarketplaceSourceStore.getState().setSource("curseforge");
    expect(useMarketplaceSourceStore.getState().source).toBe("curseforge");
    expect(localStorage.getItem("onx_marketplace_source")).toBe("curseforge");
  });

  it("switches back to modrinth source", () => {
    useMarketplaceSourceStore.getState().setSource("curseforge");
    useMarketplaceSourceStore.getState().setSource("modrinth");
    expect(useMarketplaceSourceStore.getState().source).toBe("modrinth");
    expect(localStorage.getItem("onx_marketplace_source")).toBe("modrinth");
  });
});
