import { describe, expect, it, vi } from "vitest";

import {
  artifactHref,
  auditHref,
  backupHref,
  extractPermissionRequest,
  missionArtifactHref,
  permissionEventId,
  resolvedPermissionIds,
  runEventStreamHref,
  runtimeApi,
  sessionEventStreamHref,
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
    const fallbackOption = event("permission.requested", {
      permission_id: "perm_fallback",
      options: [{}],
    });
    const qwenShape = event("permission.requested", {
      raw: {
        data: {
          requestId: "perm_qwen",
          options: [{ optionId: "proceed_once", name: "Allow" }],
          toolCall: {
            title: "/var/lib/cloud-agents-runtime",
            _meta: { toolName: "list_directory" },
          },
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
    expect(extractPermissionRequest(fallbackOption)).toMatchObject({
      permission_id: "perm_fallback",
      options: [{ id: "approve" }],
    });
    expect(extractPermissionRequest(qwenShape)).toMatchObject({
      permission_id: "perm_qwen",
      prompt: "/var/lib/cloud-agents-runtime",
      tool: "list_directory",
      options: [{ id: "proceed_once", label: "Allow" }],
    });
    expect(extractPermissionRequest(event("run.running", {}))).toBeNull();
    expect(
      extractPermissionRequest(event("permission.requested", {})),
    ).toBeNull();
  });

  it("collects resolved permission ids", () => {
    const ids = resolvedPermissionIds([
      event("permission.resolved", { permission_id: "perm_1" }),
      event("permission.resolved", { raw: { data: { requestId: "perm_2" } } }),
      event("permission.resolved", { requestId: "perm_3" }),
      event("permission.requested", { permission_id: "perm_3" }),
    ]);

    expect([...ids]).toEqual(["perm_1", "perm_2", "perm_3"]);
  });

  it("normalizes permission ids across runtime and qwen event shapes", () => {
    expect(
      permissionEventId(event("permission.requested", { permission_id: "a" })),
    ).toBe("a");
    expect(
      permissionEventId(event("permission.requested", { permissionId: "b" })),
    ).toBe("b");
    expect(
      permissionEventId(event("permission.requested", { request_id: "c" })),
    ).toBe("c");
    expect(
      permissionEventId(event("permission.requested", { requestId: "d" })),
    ).toBe("d");
    expect(
      permissionEventId(
        event("permission.requested", { raw: { data: { requestId: "e" } } }),
      ),
    ).toBe("e");
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

    await runtimeApi.session();
    await runtimeApi.login({ email: "owner@example.com", password: "secret" });
    await runtimeApi.logout();
    await runtimeApi.workerControl("worker 1");
    await runtimeApi.drainWorker("worker 1");
    await runtimeApi.resumeWorker("worker 1");
    await runtimeApi.retryWorkerRuns("worker 1");
    await runtimeApi.queue();
    await runtimeApi.executors();
    await runtimeApi.costStatus();
    await runtimeApi.tasks();
    await runtimeApi.task("run 1");
    await runtimeApi.taskEvents("run 1");
    await runtimeApi.taskArtifacts("run 1");
    await runtimeApi.taskResult("run 1");
    await runtimeApi.createTask({ goal: "ship", adapter: "fake" });
    await runtimeApi.submitTaskMessage("run 1", "continue");
    await runtimeApi.cancelTask("run 1");
    await runtimeApi.runAudit("run_1");
    await runtimeApi.submitRunInput("run_1", "legacy continue");
    await runtimeApi.resolvePermission("run_1", "perm_legacy", {
      decision: "deny",
    });
    await runtimeApi.sessionEvents("run_1");
    await runtimeApi.submitSessionPrompt("run_1", "continue");
    await runtimeApi.resolveSessionPermission("run_1", "perm_1", {
      decision: "approve",
      option_id: "proceed_once",
    });
    await runtimeApi.permissionNotifications("run_1");
    await runtimeApi.retryPermissionNotifications("run_1", "perm_1");
    await runtimeApi.cancelRun("run_1");
    await runtimeApi.mission("mission_1");
    await runtimeApi.missionEvents("mission_1");
    await runtimeApi.missionArtifacts("mission_1");
    await runtimeApi.cancelMission("mission_1");
    await runtimeApi.overrideReviewGate("mission_1", {
      decision: "approve",
      reason: "reviewed",
    });
    await runtimeApi.profile("planner");
    await runtimeApi.createProfile({ id: "planner-copy" });
    await runtimeApi.accessPolicy();
    await runtimeApi.accessProjects();
    await runtimeApi.createAccessProject({ project_id: "default" });
    await runtimeApi.apiTokens();
    await runtimeApi.createApiToken({ name: "operator" });
    await runtimeApi.revokeApiToken("token_1");
    await runtimeApi.authUsers();
    await runtimeApi.createAuthUser({
      email: "new@example.com",
      password: "secret-12345",
      roles: ["operator"],
    });
    await runtimeApi.updateAuthUserRoles("new@example.com", ["member"]);
    await runtimeApi.updateAuthUserStatus("new@example.com", "disabled");
    await runtimeApi.resetAuthUserPassword("new@example.com", "secret-67890");
    await runtimeApi.createMission({ goal: "ship", strategy: "sequential" });
    await runtimeApi.v2Capabilities();
    await runtimeApi.v2Tasks();
    await runtimeApi.v2Task("task 1");
    await runtimeApi.v2TaskEvents("task 1");
    await runtimeApi.v2TaskWorkflow("task 1");
    await runtimeApi.v2TaskArtifacts("task 1");
    await runtimeApi.v2TaskEvaluations("task 1");
    await runtimeApi.v2TaskReplays("task 1");
    await runtimeApi.v2CreateTask({ goal: "ship v2" });
    await runtimeApi.v2SubmitMessage("task 1", "continue");
    await runtimeApi.v2RetryTask("task 1");
    await runtimeApi.v2ReplayTask("task 1");
    await runtimeApi.v2AdminOverview();
    await runtimeApi.v2ExecutionUnits();
    await runtimeApi.v2Channels();
    await runtimeApi.v2RegisterExecutionUnit({ unit_id: "docker-a" });

    expect(calls.map(([path]) => path)).toEqual([
      "/auth/session",
      "/auth/login",
      "/auth/logout",
      "/workers/worker%201/control",
      "/workers/worker%201/drain",
      "/workers/worker%201/resume",
      "/workers/worker%201/retry",
      "/queue",
      "/executors",
      "/cost/status",
      "/tasks",
      "/tasks/run%201",
      "/tasks/run%201/events.json",
      "/tasks/run%201/artifacts",
      "/tasks/run%201/result",
      "/tasks",
      "/tasks/run%201/messages",
      "/tasks/run%201/cancel",
      "/runs/run_1/audit.json",
      "/runs/run_1/input",
      "/runs/run_1/permissions/perm_legacy",
      "/session/run_1/events.json",
      "/session/run_1/prompt",
      "/session/run_1/permission/perm_1",
      "/runs/run_1/permission-notifications",
      "/runs/run_1/permissions/perm_1/notifications/retry",
      "/runs/run_1/cancel",
      "/missions/mission_1",
      "/missions/mission_1/events.json",
      "/missions/mission_1/artifacts",
      "/missions/mission_1/cancel",
      "/missions/mission_1/review-gate/override",
      "/profiles/planner",
      "/profiles",
      "/access/policy",
      "/access/projects",
      "/access/projects",
      "/access/tokens",
      "/access/tokens",
      "/access/tokens/token_1/revoke",
      "/auth/users",
      "/auth/users",
      "/auth/users/new%40example.com/roles",
      "/auth/users/new%40example.com/status",
      "/auth/users/new%40example.com/password",
      "/missions",
      "/v2/capabilities",
      "/v2/tasks",
      "/v2/tasks/task%201",
      "/v2/tasks/task%201/events.json",
      "/v2/tasks/task%201/workflow",
      "/v2/tasks/task%201/artifacts",
      "/v2/tasks/task%201/evaluations",
      "/v2/tasks/task%201/replays",
      "/v2/tasks",
      "/v2/tasks/task%201/messages",
      "/v2/tasks/task%201/retry",
      "/v2/tasks/task%201/replay",
      "/v2/admin/overview",
      "/v2/admin/execution-units",
      "/v2/admin/channels",
      "/v2/admin/execution-units",
    ]);
    const methods = new Map(calls.map(([path, init]) => [path, init?.method]));
    expect(methods.get("/auth/login")).toBe("POST");
    expect(methods.get("/auth/logout")).toBe("POST");
    expect(methods.get("/workers/worker%201/drain")).toBe("POST");
    expect(methods.get("/workers/worker%201/resume")).toBe("POST");
    expect(methods.get("/workers/worker%201/retry")).toBe("POST");
    expect(methods.get("/tasks")).toBe("POST");
    expect(methods.get("/tasks/run%201/messages")).toBe("POST");
    expect(methods.get("/tasks/run%201/cancel")).toBe("POST");
    expect(methods.get("/runs/run_1/input")).toBe("POST");
    expect(methods.get("/runs/run_1/permissions/perm_legacy")).toBe("POST");
    expect(methods.get("/session/run_1/prompt")).toBe("POST");
    expect(methods.get("/session/run_1/permission/perm_1")).toBe("POST");
    expect(
      methods.get("/runs/run_1/permissions/perm_1/notifications/retry"),
    ).toBe("POST");
    expect(methods.get("/runs/run_1/cancel")).toBe("POST");
    expect(methods.get("/missions/mission_1/cancel")).toBe("POST");
    expect(methods.get("/missions/mission_1/review-gate/override")).toBe(
      "POST",
    );
    expect(methods.get("/profiles")).toBe("POST");
    expect(methods.get("/access/projects")).toBe("POST");
    expect(methods.get("/access/tokens")).toBe("POST");
    expect(methods.get("/access/tokens/token_1/revoke")).toBe("POST");
    expect(methods.get("/auth/users")).toBe("POST");
    expect(methods.get("/auth/users/new%40example.com/roles")).toBe("POST");
    expect(methods.get("/auth/users/new%40example.com/status")).toBe("POST");
    expect(methods.get("/auth/users/new%40example.com/password")).toBe("POST");
    expect(methods.get("/missions")).toBe("POST");
    expect(methods.get("/v2/tasks")).toBe("POST");
    expect(methods.get("/v2/tasks/task%201/messages")).toBe("POST");
    expect(methods.get("/v2/tasks/task%201/retry")).toBe("POST");
    expect(methods.get("/v2/tasks/task%201/replay")).toBe("POST");
    expect(methods.get("/v2/admin/execution-units")).toBe("POST");
  });

  it("surfaces API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response("not allowed", {
            status: 403,
            statusText: "Forbidden",
          }),
        ),
      ),
    );

    await expect(runtimeApi.health()).rejects.toThrow("not allowed");
  });

  it("builds hrefs from the current app base", async () => {
    window.history.pushState({}, "", "/cloud-agents/");
    vi.resetModules();
    const fresh = await import("./api");

    expect(fresh.artifactHref("run_1", "a b.json")).toBe(
      "/cloud-agents/runs/run_1/artifacts/a%20b.json",
    );
    expect(fresh.auditHref("run_1")).toBe(
      "/cloud-agents/runs/run_1/audit.json",
    );
    expect(fresh.runEventStreamHref("run_1")).toBe(
      "/cloud-agents/runs/run_1/events",
    );
    expect(fresh.sessionEventStreamHref("run_1")).toBe(
      "/cloud-agents/session/run_1/events",
    );
    expect(fresh.backupHref("backup.tgz")).toBe(
      "/cloud-agents/ops/backups/backup.tgz",
    );
    expect(fresh.missionArtifactHref("mission_1", "final report.md")).toBe(
      "/cloud-agents/missions/mission_1/artifacts/final%20report.md",
    );

    window.history.pushState({}, "", "/agentflow/");
    vi.resetModules();
    const agentflowBase = await import("./api");
    expect(agentflowBase.artifactHref("run_1", "a b.json")).toBe(
      "/agentflow/runs/run_1/artifacts/a%20b.json",
    );

    window.history.pushState({}, "", "/");
    expect(artifactHref("run_1", "events.jsonl")).toBe(
      "/runs/run_1/artifacts/events.jsonl",
    );
    expect(auditHref("run_1")).toBe("/runs/run_1/audit.json");
    expect(runEventStreamHref("run_1")).toBe("/runs/run_1/events");
    expect(sessionEventStreamHref("run_1")).toBe("/session/run_1/events");
    expect(backupHref("backup.tgz")).toBe("/ops/backups/backup.tgz");
    expect(missionArtifactHref("mission_1", "manifest.json")).toBe(
      "/missions/mission_1/artifacts/manifest.json",
    );
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
