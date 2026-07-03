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
  await expect(page.getByRole("heading", { name: "概览" })).toBeVisible();
});

test("manages runs, permissions, profiles, and operations", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "概览" })).toBeVisible();
  await page.getByLabel("切换语言").click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
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
  await expect(page.getByText("Permission Requests")).toBeVisible();
  await expect(page.getByText("log:sent")).toBeVisible();
  await expect(page.getByText("webhook:failed")).toBeVisible();
  await expect(page.getByText("Agent Chat")).toBeVisible();
  await expect(page.getByText("Human approval required")).toBeVisible();
  await expect(page.getByText("Agent output #1")).toBeVisible();
  await expect(
    page
      .locator("main")
      .getByText("Live runner output from the mocked SSE stream.", {
        exact: true,
      }),
  ).toBeVisible();
  await page.getByLabel("Continue chat").fill("Please continue");
  await page.getByRole("button", { name: "Send" }).click();
  await page.getByRole("button", { name: "Retry notification" }).click();
  await page.getByRole("button", { name: "Approve" }).first().click();
  await expect(page.getByText("final-report.md")).toBeVisible();

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
  options: { authenticated?: boolean } = {},
) {
  const now = new Date().toISOString();
  let authenticated = options.authenticated ?? true;
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
            roles: ["owner"],
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
          roles: ["owner"],
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
          token_id: "token_worker",
          token: "secret-token",
          capacity: 1,
          control_url: "https://doubaofans.site/cloud-agents-worker",
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
