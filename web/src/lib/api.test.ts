import { describe, expect, it, vi } from "vitest";

import {
  extractPermissionRequest,
  resolvedPermissionIds,
  runtimeApi,
  type RuntimeEvent,
} from "./api";

describe("api helpers", () => {
  it("extracts permission requests from direct and nested event shapes", () => {
    const direct = event("permission.requested", {
      permission_id: "perm_direct",
      prompt: "Approve write?",
      options: [{ option_id: "allow", label: "Allow" }],
    });
    const nested = event("permission.requested", {
      raw: {
        data: {
          requestId: "perm_nested",
          prompt: "Approve shell?",
          tool: "shell",
        },
      },
    });

    expect(extractPermissionRequest(direct)).toMatchObject({
      permission_id: "perm_direct",
      options: [{ id: "allow", label: "Allow" }],
    });
    expect(extractPermissionRequest(nested)).toMatchObject({
      permission_id: "perm_nested",
      tool: "shell",
    });
    expect(extractPermissionRequest(event("run.running", {}))).toBeNull();
  });

  it("collects resolved permission ids", () => {
    const ids = resolvedPermissionIds([
      event("permission.resolved", { permission_id: "perm_1" }),
      event("permission.resolved", { raw: { data: { requestId: "perm_2" } } }),
      event("permission.requested", { permission_id: "perm_3" }),
    ]);

    expect([...ids]).toEqual(["perm_1", "perm_2"]);
  });

  it("wraps runtime endpoints", async () => {
    const calls: Array<[string, RequestInit | undefined]> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init?: RequestInit) => {
        calls.push([path, init]);
        return Promise.resolve(
          new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        );
      }),
    );

    await runtimeApi.queue();
    await runtimeApi.runAudit("run_1");
    await runtimeApi.cancelRun("run_1");
    await runtimeApi.createMission({ goal: "ship", strategy: "sequential" });

    expect(calls.map(([path]) => path)).toEqual([
      "/queue",
      "/runs/run_1/audit.json",
      "/runs/run_1/cancel",
      "/missions",
    ]);
    expect(calls[2][1]?.method).toBe("POST");
    expect(calls[3][1]?.method).toBe("POST");
  });
});

function event(type: string, data: Record<string, unknown>): RuntimeEvent {
  return {
    id: `evt_${type}`,
    run_id: "run_1",
    sequence: 1,
    type,
    created_at: new Date().toISOString(),
    data,
  };
}
