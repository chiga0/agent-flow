import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await mockRuntime(page);
});

test("manages runs, permissions, profiles, and operations", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await navigate(page, /Runs/);
  await page.getByLabel("Prompt").fill("Browser smoke run");
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByText("run_created")).toBeVisible();

  await page.getByText("run_1").click();
  await expect(page.getByText("Permission Requests")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("final-report.md")).toBeVisible();

  await navigate(page, /Profiles/);
  await expect(page.getByRole("heading", { name: "Planner" })).toBeVisible();

  await navigate(page, /Operations/);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByText("cloud-agents-backup-test.tar.gz")).toBeVisible();
});

test("keeps navigation usable on mobile", async ({ page, isMobile }) => {
  test.skip(!isMobile, "mobile project only");
  await page.goto("/");
  await page.getByLabel("Open navigation").click();
  await page.getByRole("link", { name: /Missions/ }).click();
  await expect(page.getByRole("heading", { name: "Missions" })).toBeVisible();
});

async function mockRuntime(page: Page) {
  const now = new Date().toISOString();
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
      },
    ],
  };
  const runs = [run];
  const fixtures: Record<string, unknown> = {
    health: { ok: true, version: "0.1-e2e" },
    capabilities: {
      mode: "saeu-runtime",
      features: ["metrics", "backup"],
      adapters: {
        fake: { name: "Fake", status: "available" },
        qwen: { name: "Qwen", status: "available" },
      },
      queue: { counts: {}, jobs: [], workers: [] },
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
          id: "evt_1",
          run_id: "run_1",
          sequence: 1,
          type: "permission.requested",
          created_at: now,
          data: {
            permission_id: "perm_1",
            prompt: "Allow shell command?",
            options: [{ id: "approve", label: "Approve" }],
          },
        },
      ],
    },
    "runs/run_1/artifacts": {
      artifacts: [{ name: "final-report.md", size_bytes: 42, updated_at: now }],
    },
    missions: { missions: [mission] },
    profiles: {
      profiles: [
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
      ],
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
    if (request.method() === "POST" && path === "runs") {
      const created = { ...run, run_id: "run_created", status: "queued" };
      runs.unshift(created);
      await route.fulfill({ json: created });
      return;
    }
    if (request.method() === "POST" && path.includes("/permissions/")) {
      await route.fulfill({ json: { accepted: true } });
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
