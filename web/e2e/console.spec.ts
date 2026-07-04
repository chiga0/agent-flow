import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await mockRuntime(page);
});

test("signs in from the responsive login page", async ({ page, isMobile }) => {
  test.skip(!isMobile, "mobile project only");
  await mockRuntime(page, { authenticated: false });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "登录" })).toBeVisible();
  await page.getByLabel("邮箱").fill("owner@example.com");
  await page.getByLabel("密码").fill("secret");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { name: "工作台" })).toBeVisible();
});

test("creates a task from the user workspace", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel("你想完成什么？").fill("整理 V2 交付审计清单");
  await page.getByRole("button", { name: "开始任务" }).click();

  await expect(
    page.getByRole("heading", { name: "整理 V2 交付审计清单" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "实时进展" })).toBeVisible();
  await expect(page.getByText("Task accepted")).toBeVisible();
  await expect(page.getByText("V2 checklist started").first()).toBeVisible();
  await expect(page.getByText("workspace-result.md")).toBeVisible();
});

test("hides backend navigation for a member user", async ({ page, isMobile }) => {
  await mockRuntime(page, { roles: ["member"] });
  await page.goto("/");

  if (isMobile) {
    await page.getByLabel("打开导航").click();
  }
  await expect(page.getByRole("link", { name: /工作台/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /运行/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /执行器/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /访问控制/ })).toHaveCount(0);
});

test("manages runs, permissions, profiles, and operations", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "工作台" })).toBeVisible();
  await expect(page.getByText("发起任务")).toBeVisible();
  await page.getByLabel("切换语言").click();
  await expect(page.getByRole("heading", { name: "Workspace" })).toBeVisible();
  await navigate(page, /Runs/);
  await page.getByLabel("Prompt").fill("Browser smoke run");
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByRole("heading", { name: "Run Detail" })).toBeVisible();
  await expect(page.getByText("Active Runs")).toBeVisible();

  await navigate(page, /Runs/);
  await page
    .locator("main")
    .getByRole("link", { name: "run_1 running Inspect runtime", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Permission Requests" }),
  ).toBeVisible();
  await expect(page.getByText("Execution process")).toBeVisible();
  await expect(page.getByText("log:sent")).toBeVisible();
  await expect(page.getByText("webhook:failed")).toBeVisible();
  await expect(page.getByText("Agent Chat")).toBeVisible();
  await expect(page.getByText("Human approval required")).toBeVisible();
  await expect(page.getByText("Agent output")).toBeVisible();
  await expect(
    page.getByText(
      "Live runner output from the mocked SSE stream. SSE daemon chunk.",
    ),
  ).toBeVisible();
  await page.getByLabel("Continue chat").fill("Please continue");
  await page.getByRole("button", { name: "Send" }).click();
  await page.getByRole("button", { name: "Retry notification" }).click();
  await page.getByRole("button", { name: "Approve" }).first().click();
  await expect(page.getByText("final-report.md")).toBeVisible();
  await page.getByRole("button", { name: "Preview" }).first().click();
  await expect(page.getByText("mock final report")).toBeVisible();

  await navigate(page, /Missions/);
  await page.getByRole("link", { name: /Open detail/ }).click();
  await expect(
    page.getByRole("heading", { name: "Mission Stream" }),
  ).toBeVisible();
  await expect(page.getByText("Artifacts: plan.md")).toBeVisible();
  await expect(page.getByText("Task DAG")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Mission Events" }),
  ).toBeVisible();

  await navigate(page, /Profiles/);
  await expect(page.getByRole("heading", { name: "Planner" })).toBeVisible();
  await page.getByRole("button", { name: "Copy" }).click();
  await page.getByLabel("Display name").fill("Planner Copy");
  await page.getByRole("button", { name: "Save Profile" }).click();
  await expect(page.getByText("Planner Copy")).toBeVisible();

  await navigate(page, /Access/);
  await expect(page.getByText("Role Matrix")).toBeVisible();
  await expect(page.getByText("runs:*").first()).toBeVisible();

  await navigate(page, /Units/);
  await expect(
    page.getByRole("heading", { name: "Execution Units" }),
  ).toBeVisible();
  await expect(page.getByText("How Units Work")).toBeVisible();
  await expect(
    page.getByText(
      "2 GB memory is already running work. Keep this worker at capacity=1.",
    ),
  ).toBeVisible();
  await page.getByLabel("Unit ID").fill("hk-2c2g-b");
  await page
    .getByLabel("Worker control URL")
    .fill("https://doubaofans.site/cloud-agents-worker");
  await page.getByRole("button", { name: "Generate" }).click();
  await expect(
    page.getByRole("heading", { name: "Deployment Command" }),
  ).toBeVisible();
  await expect(page.getByText("No local source required")).toBeVisible();
  await page.getByRole("button", { name: "Copy" }).click();
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("button", { name: "Drain" }).first().click();
  await page.getByRole("button", { name: "Resume" }).first().click();
  await page.getByRole("button", { name: "Retry" }).first().click();

  await navigate(page, /Operations/);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByText("cloud-agents-backup-test.tar.gz")).toBeVisible();
});

test("keeps navigation usable on mobile", async ({ page, isMobile }) => {
  test.skip(!isMobile, "mobile project only");
  await page.goto("/");
  await page.getByLabel("打开导航").click();
  await page.getByRole("link", { name: /任务编排/ }).click();
  await expect(page.getByRole("heading", { name: "任务编排" })).toBeVisible();
});

async function mockRuntime(
  page: Page,
  options: { authenticated?: boolean; roles?: string[] } = {},
) {
  const now = new Date().toISOString();
  let authenticated = options.authenticated ?? true;
  const principalRoles = options.roles ?? ["owner"];
  const run = {
    run_id: "run_1",
    status: "running",
    created_at: now,
    updated_at: now,
    event_count: 2,
    prompt_count: 1,
    spec: { adapter: "fake", prompt: "Inspect runtime" },
  };
  const mission = {
    mission_id: "mission_1",
    status: "running",
    created_at: now,
    updated_at: now,
    event_count: 1,
    task_count: 1,
    completed_task_count: 0,
    failed_task_count: 0,
    spec: { goal: "Ship beta", strategy: "sequential", adapter: "fake" },
    tasks: [
      {
        task_id: "plan",
        title: "Plan mission",
        profile_id: "planner",
        status: "running",
        run_id: "run_1",
        depends_on: [],
        result: { artifacts: [{ name: "plan.md" }] },
      },
    ],
  };
  const missionEvents = [
    {
      id: "mevt_1",
      mission_id: "mission_1",
      sequence: 1,
      type: "task.created",
      created_at: now,
      data: { task_id: "plan" },
    },
  ];
  const runs = [run];
  const createdWorkspaceTask = {
    task_id: "run_workspace_created",
    kind: "run",
    title: "整理 V2 交付审计清单",
    goal: "整理 V2 交付审计清单",
    status: "running",
    created_at: now,
    updated_at: now,
    progress: { completed_steps: 0, total_steps: 1, percent: 50 },
    agent_summary: { adapter: "fake", active_agent: "Smoke Test Agent" },
    needs_attention: false,
    pending_permission_count: 0,
    access: {
      created_by: "owner@example.com",
      project_id: "default",
      visibility: "project",
    },
    source: { run_id: "run_workspace_created", mission_id: null },
    result_summary: "V2 checklist started",
    links: {
      detail: "/tasks/run_workspace_created",
      source: "/runs/run_workspace_created",
    },
  };
  const task = {
    task_id: "run_1",
    kind: "run",
    title: "Inspect runtime",
    goal: "Inspect runtime",
    status: "running",
    created_at: now,
    updated_at: now,
    progress: { completed_steps: 0, total_steps: 1, percent: 50 },
    agent_summary: { adapter: "fake", active_agent: "Smoke Test Agent" },
    needs_attention: true,
    pending_permission_count: 1,
    source: { run_id: "run_1", mission_id: null },
    result_summary: "Live runner output from the mocked SSE stream.",
    links: { detail: "/tasks/run_1", source: "/runs/run_1" },
  };
  const workers = [
    {
      worker_id: "hk-2c2g-a",
      status: "active",
      capacity: 1,
      active_count: 1,
      lease_ttl_seconds: 60,
      heartbeat_at: now,
      created_at: now,
      updated_at: now,
      metadata: {
        labels: { region: "hk" },
        resources: { cpus: 2, memory_gb: 2 },
        capabilities: { adapters: ["qwen"] },
      },
    },
  ];
  const profiles = [
    {
      id: "planner",
      display_name: "Planner",
      description: "Plan work",
      version: 1,
      source: "system",
      runtime: {},
      tools: {},
      approval: {},
      limits: {},
      workspace: {},
      artifacts: {},
    },
  ];
  const fixtures: Record<string, unknown> = {
    "auth/session": {
      authenticated,
      login_enabled: true,
      principal: authenticated
        ? {
            id: "owner@example.com",
            email: "owner@example.com",
            display_name: "Owner",
            roles: principalRoles,
          }
        : null,
    },
    health: { ok: true, version: "0.1-e2e" },
    capabilities: {
      mode: "saeu-runtime",
      features: ["metrics", "backup"],
      adapters: {
        fake: { name: "Fake", status: "available" },
        qwen: { name: "Qwen", status: "available" },
      },
      queue: { counts: {}, jobs: [], workers },
      profiles: [],
    },
    "metrics.json": {
      generated_at: now,
      runs: { total: 1, by_status: { running: 1 } },
      missions: { total: 1, by_status: { running: 1 } },
      queue: {
        counts: { queued: 0, running: 1 },
        worker_count: 1,
        active_workers: 1,
        stale_workers: 0,
      },
      permissions: { pending: 1, stalled: 0 },
      latency_seconds: { count: 0, avg: null, p95: null },
    },
    tasks: { tasks: [task] },
    "tasks/run_workspace_created": createdWorkspaceTask,
    "tasks/run_workspace_created/events.json": {
      events: [
        {
          id: "tevt_workspace_1",
          task_id: "run_workspace_created",
          sequence: 1,
          type: "task.accepted",
          title: "Task accepted",
          body: "V2 checklist started",
          status: "queued",
          created_at: now,
          source_event_type: "run.created",
          source: { kind: "run" },
        },
      ],
    },
    "tasks/run_workspace_created/artifacts": {
      artifacts: [
        { name: "workspace-result.md", size_bytes: 64, updated_at: now },
      ],
    },
    "tasks/run_workspace_created/result": {
      task_id: "run_workspace_created",
      status: "running",
      summary: "V2 checklist started",
      artifacts: [
        { name: "workspace-result.md", size_bytes: 64, updated_at: now },
      ],
      completed: false,
      generated_at: now,
    },
    "tasks/run_1": task,
    "tasks/run_1/events.json": {
      events: [
        {
          id: "tevt_1",
          task_id: "run_1",
          sequence: 1,
          type: "task.accepted",
          title: "Task accepted",
          body: "Inspect runtime",
          status: "queued",
          created_at: now,
          source_event_type: "run.created",
          source: { kind: "run" },
        },
      ],
    },
    "tasks/run_1/artifacts": {
      artifacts: [{ name: "final-report.md", size_bytes: 42, updated_at: now }],
    },
    "tasks/run_1/result": {
      task_id: "run_1",
      status: "running",
      summary: "Live runner output from the mocked SSE stream.",
      artifacts: [{ name: "final-report.md", size_bytes: 42, updated_at: now }],
      completed: false,
      generated_at: now,
    },
    runs: { runs },
    "runs/run_1": run,
    "runs/run_1/events.json": {
      events: [
        {
          id: "evt_0",
          run_id: "run_1",
          sequence: 1,
          type: "run.created",
          created_at: now,
          data: { spec: run.spec },
        },
        {
          id: "evt_1",
          run_id: "run_1",
          sequence: 2,
          type: "permission.requested",
          created_at: now,
          data: {
            permission_id: "perm_1",
            prompt: "Allow shell command?",
            tool: "shell",
            options: [{ id: "approve", label: "Approve" }],
          },
        },
        {
          id: "evt_2",
          run_id: "run_1",
          sequence: 3,
          type: "message.delta",
          created_at: now,
          data: {
            prompt_number: 1,
            text: "Live runner output from the mocked SSE stream.",
          },
        },
      ],
    },
    "session/run_1/events.json": {
      events: [
        {
          id: 1,
          v: 1,
          type: "session_update",
          data: {
            update: {
              sessionUpdate: "user_message_chunk",
              content: { type: "text", text: "Inspect runtime" },
            },
          },
          _meta: {
            serverTimestamp: Date.now(),
            runtimeRunId: "run_1",
            runtimeSequence: 1,
          },
        },
        {
          id: 2,
          v: 1,
          type: "permission_request",
          data: {
            requestId: "perm_1",
            prompt: "Allow shell command?",
            tool: "shell",
            options: [{ id: "approve", label: "Approve" }],
            context: { command: "uname -a", cwd: "/workspace" },
          },
          _meta: {
            serverTimestamp: Date.now(),
            runtimeRunId: "run_1",
            runtimeSequence: 2,
          },
        },
        {
          id: 3,
          v: 1,
          type: "session_update",
          data: {
            update: {
              sessionUpdate: "agent_message_chunk",
              content: {
                type: "text",
                text: "Live runner output from the mocked SSE stream.",
              },
            },
          },
          _meta: {
            serverTimestamp: Date.now(),
            runtimeRunId: "run_1",
            runtimeSequence: 3,
          },
        },
        {
          id: 4,
          v: 1,
          type: "session_update",
          data: {
            update: {
              sessionUpdate: "tool_call_update",
              toolCall: {
                name: "shell",
                status: "completed",
                input: "uname -a",
                output: "Linux test-host",
              },
            },
          },
          _meta: {
            serverTimestamp: Date.now(),
            runtimeRunId: "run_1",
            runtimeSequence: 4,
          },
        },
      ],
    },
    "runs/run_1/permission-notifications": {
      notifications: [
        {
          notification_id: "notif_log",
          run_id: "run_1",
          permission_id: "perm_1",
          channel: "log",
          target: "operator",
          status: "sent",
          attempts: 1,
          message: "Permission requested",
          action_url: "/#/runs/run_1",
          delivery_ref: "event-log",
          error: null,
          created_at: now,
          updated_at: now,
          sent_at: now,
          metadata: {},
        },
        {
          notification_id: "notif_webhook",
          run_id: "run_1",
          permission_id: "perm_1",
          channel: "webhook",
          target: "operator",
          status: "failed",
          attempts: 1,
          message: "Permission requested",
          action_url: "/#/runs/run_1",
          delivery_ref: null,
          error: "webhook unreachable",
          created_at: now,
          updated_at: now,
          sent_at: null,
          metadata: {},
        },
      ],
    },
    "runs/run_1/artifacts": {
      artifacts: [{ name: "final-report.md", size_bytes: 42, updated_at: now }],
    },
    missions: { missions: [mission] },
    "missions/mission_1": mission,
    "missions/mission_1/events.json": { events: missionEvents },
    "missions/mission_1/artifacts": {
      artifacts: [
        {
          name: "final_report.md",
          size_bytes: 88,
          updated_at: now,
        },
      ],
    },
    profiles: { profiles },
    workers: { workers },
    "access/policy": {
      mode: "single-tenant-rbac-foundation",
      current_principal: {
        id: "operator",
        display_name: "operator",
        roles: ["owner"],
      },
      roles: [
        {
          id: "owner",
          description: "Can administer runtime",
          permissions: ["runs:*", "missions:*", "profiles:*"],
        },
      ],
      scopes: ["runs:*", "missions:*", "profiles:*"],
      audit: {
        auth_boundary: "runtime session cookie plus bearer token or API token",
      },
    },
    "ops/status": { database: { exists: true } },
    "ops/drills": {
      status: "pass",
      checks: [
        {
          id: "runtime-db",
          status: "pass",
          summary: "runtime.db is present",
          details: {},
        },
      ],
    },
    "ops/backups": {
      backups: [
        {
          name: "cloud-agents-backup-test.tar.gz",
          size_bytes: 128,
          created_at: now,
        },
      ],
    },
    "p5/evaluations": {
      components: [
        {
          id: "acp-streamable-http",
          status: "implemented",
          mode: "json-rpc",
          decision: "keep",
        },
      ],
    },
  };

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\//, "");
    if (request.method() === "POST" && path === "auth/login") {
      const body = request.postDataJSON() as {
        email?: string;
        password?: string;
      };
      if (body.email !== "owner@example.com" || body.password !== "secret") {
        await route.fulfill({
          json: { error: "invalid credentials" },
          status: 401,
        });
        return;
      }
      authenticated = true;
      fixtures["auth/session"] = {
        authenticated: true,
        login_enabled: true,
        principal: {
          id: "owner@example.com",
          email: "owner@example.com",
          display_name: "Owner",
          roles: principalRoles,
        },
      };
      await route.fulfill({ json: fixtures["auth/session"] });
      return;
    }
    if (request.method() === "POST" && path === "auth/logout") {
      authenticated = false;
      fixtures["auth/session"] = {
        authenticated: false,
        login_enabled: true,
        principal: null,
      };
      await route.fulfill({ json: fixtures["auth/session"] });
      return;
    }
    if (request.method() === "POST" && path === "runs") {
      const created = { ...run, run_id: "run_created", status: "queued" };
      runs.unshift(created);
      await route.fulfill({ json: created });
      return;
    }
    if (request.method() === "POST" && path === "tasks") {
      fixtures.tasks = { tasks: [createdWorkspaceTask, task] };
      await route.fulfill({
        status: 201,
        json: createdWorkspaceTask,
      });
      return;
    }
    if (request.method() === "POST" && path === "profiles") {
      const created = {
        ...profiles[0],
        display_name: "Planner Copy",
        id: "planner-copy",
        source: "user",
        version: 2,
      };
      profiles.unshift(created);
      await route.fulfill({ json: created });
      return;
    }
    if (request.method() === "POST" && path === "workers/registrations") {
      await route.fulfill({
        json: {
          worker_id: "hk-2c2g-b",
          capacity: 1,
          control_url: "https://doubaofans.site/cloud-agents-worker",
          token: {
            token_id: "token_worker",
            name: "worker-hk-2c2g-b",
            principal_id: "operator",
            scopes: ["workers:*"],
            status: "active",
            token_prefix: "cat_worker",
            token: "secret-token",
            created_at: now,
            updated_at: now,
            metadata: {},
          },
          deploy_command:
            "RUN_WORKER_ID=hk-2c2g-b bash scripts/deploy_worker_vps.sh root@host /path/key.pem",
          metadata: { resources: { cpus: 2, memory_gb: 2 } },
        },
      });
      return;
    }
    if (request.method() === "POST" && path.includes("/drain")) {
      workers[0] = { ...workers[0], status: "draining" };
      await route.fulfill({ json: { worker: workers[0], control: {} } });
      return;
    }
    if (request.method() === "POST" && path.includes("/resume")) {
      workers[0] = { ...workers[0], status: "active" };
      await route.fulfill({ json: { worker: workers[0], control: {} } });
      return;
    }
    if (
      request.method() === "POST" &&
      path.includes("/permissions/") &&
      path.endsWith("/notifications/retry")
    ) {
      await route.fulfill({
        json: fixtures["runs/run_1/permission-notifications"],
      });
      return;
    }
    if (request.method() === "POST" && path.includes("/retry")) {
      await route.fulfill({
        json: { worker_id: workers[0].worker_id, requeued_run_ids: ["run_1"] },
      });
      return;
    }
    if (request.method() === "POST" && path.includes("/permission/")) {
      await route.fulfill({ json: { accepted: true } });
      return;
    }
    if (request.method() === "POST" && path.endsWith("/prompt")) {
      await route.fulfill({
        status: 202,
        json: {
          accepted: true,
          session_id: path.split("/")[1],
          run_id: path.split("/")[1],
        },
      });
      return;
    }
    if (path === "session/run_1/events") {
      await route.fulfill({
        body: 'event: session_update\nid: 5\ndata: {"id":5,"v":1,"type":"session_update","data":{"update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":" SSE daemon chunk."}}},"_meta":{"serverTimestamp":1780000000000,"runtimeRunId":"run_1","runtimeSequence":5}}\n\n',
        contentType: "text/event-stream",
        status: 200,
      });
      return;
    }
    if (request.method() === "POST" && path.includes("/permissions/")) {
      await route.fulfill({ json: { accepted: true } });
      return;
    }
    if (request.method() === "POST" && path.endsWith("/input")) {
      await route.fulfill({
        status: 202,
        json: { accepted: true, run_id: path.split("/")[1] },
      });
      return;
    }
    if (request.method() === "POST" && path === "ops/backups") {
      await route.fulfill({
        json: {
          backup: {
            name: "cloud-agents-backup-new.tar.gz",
            size_bytes: 256,
            created_at: now,
          },
        },
      });
      return;
    }
    if (request.method() === "POST" && path === "ops/drills") {
      await route.fulfill({ json: fixtures["ops/drills"] });
      return;
    }
    if (path in fixtures) {
      await route.fulfill({ json: fixtures[path] });
      return;
    }
    if (path === "runs/run_1/artifacts/final-report.md") {
      await route.fulfill({
        body: "# mock final report",
        headers: { "content-type": "text/markdown" },
      });
      return;
    }
    await route.continue();
  });
}

async function navigate(page: Page, name: RegExp) {
  const direct = page.getByRole("link", { name }).first();
  if (await direct.isVisible()) {
    await direct.click();
    return;
  }
  await page.getByLabel("Open navigation").click();
  await page.getByRole("link", { name }).last().click();
}
