import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("api client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns parsed JSON for successful responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    await expect(api<{ status: string }>("/healthz")).resolves.toEqual({ status: "ok" });
  });

  it("surfaces FastAPI detail messages", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Case not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    await expect(api("/cases/missing")).rejects.toThrow("Case not found");
  });
});
