import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App, queryClient, router } from "./app";

const run = {
  run_id: "run_1",
  status: "running",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  event_count: 2,
  prompt_count: 1,
  spec: {
    adapter: "fake",
    prompt: "Inspect runtime",
  },
};

const mission = {
  mission_id: "mission_1",
  status: "running",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  event_count: 1,
  task_count: 2,
  completed_task_count: 1,
  failed_task_count: 0,
  spec: { goal: "Ship beta", strategy: "sequential", adapter: "fake" },
  tasks: [
    {
      task_id: "plan",
      title: "Plan mission",
      profile_id: "planner",
      status: "completed",
      run_id: "run_1",
      depends_on: [],
    },
  ],
};

const events = [
  {
    id: "evt_1",
    run_id: "run_1",
    sequence: 1,
    type: "permission.requested",
    created_at: new Date().toISOString(),
    data: {
      permission_id: "perm_1",
      prompt: "Allow shell command?",
      options: [
        { id: "approve", label: "Approve" },
        { id: "deny", label: "Deny" },
      ],
    },
  },
  {
    id: "evt_2",
    run_id: "run_1",
    sequence: 2,
    type: "run.running",
    created_at: new Date().toISOString(),
    data: { worker_id: "worker_1" },
  },
];

const fixtures: Record<string, unknown> = {
  health: { ok: true, version: "0.1-test" },
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
    generated_at: new Date().toISOString(),
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
  runs: { runs: [run] },
  "runs/run_1": run,
  "runs/run_1/events.json": { events },
  "runs/run_1/artifacts": {
    artifacts: [
      {
        name: "final-report.md",
        size_bytes: 42,
        updated_at: new Date().toISOString(),
      },
    ],
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
        runtime: { preferred_adapter: "qwen" },
        tools: { allow: ["read_file"] },
        approval: { mode: "ask" },
        limits: {},
        workspace: {},
        artifacts: {},
      },
    ],
  },
  "ops/status": {
    database: { exists: true },
    security: { docker_socket: false },
  },
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
        created_at: new Date().toISOString(),
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

describe("Cloud Agents console", () => {
  beforeEach(async () => {
    queryClient.clear();
    window.location.hash = "";
    document.documentElement.classList.remove("dark");
    vi.stubGlobal("fetch", vi.fn(fetchMock));
    await act(async () => {
      await router.navigate({ to: "/" });
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the runtime overview", async () => {
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Overview" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("Recent Runs")).toBeInTheDocument();
    expect(screen.getByText("Recent Missions")).toBeInTheDocument();
  });

  it("creates a run from the Runs page", async () => {
    const user = userEvent.setup();
    await act(async () => {
      await router.navigate({ to: "/runs" });
    });
    render(<App />);

    await user.click(screen.getByRole("button", { name: /refresh/i }));
    await user.clear(await screen.findByLabelText("Prompt"));
    await user.type(screen.getByLabelText("Prompt"), "Run a smoke validation");
    await user.type(screen.getByLabelText("Repo"), "/tmp/repo");
    await user.type(screen.getByLabelText("Workspace"), "/tmp/workspace");
    await user.clear(screen.getByLabelText("Timeout seconds"));
    await user.type(screen.getByLabelText("Timeout seconds"), "900");
    await user.click(screen.getByRole("button", { name: /start/i }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/runs",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("Run a smoke validation"),
        }),
      ),
    );
  });

  it("resolves a run permission and exposes artifact downloads", async () => {
    const user = userEvent.setup();
    await act(async () => {
      await router.navigate({ to: "/runs/$runId", params: { runId: "run_1" } });
    });
    render(<App />);

    expect(await screen.findByText("Permission Requests")).toBeInTheDocument();
    expect(screen.getByText("final-report.md")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/runs/run_1/permissions/perm_1",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("approve"),
        }),
      ),
    );
  });

  it("shows missions and profile policy details", async () => {
    await act(async () => {
      await router.navigate({ to: "/missions" });
    });
    render(<App />);

    expect(await screen.findByText("Ship beta")).toBeInTheDocument();
    expect(screen.getByText("Plan mission")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Goal"));
    await userEvent.type(
      screen.getByLabelText("Goal"),
      "Create a beta validation report",
    );
    await userEvent.selectOptions(screen.getByLabelText("Strategy"), "fanout");
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/missions",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("Create a beta validation report"),
        }),
      ),
    );

    await act(async () => {
      await router.navigate({ to: "/profiles" });
    });
    await screen.findByText("Planner");
    expect(screen.getByText("Runtime")).toBeInTheDocument();
  });

  it("runs operations drills and creates backups", async () => {
    const user = userEvent.setup();
    await act(async () => {
      await router.navigate({ to: "/operations" });
    });
    render(<App />);

    expect(await screen.findByText("Failure Drills")).toBeInTheDocument();
    expect(await screen.findByText("acp-streamable-http")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run" }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/ops/backups",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("opens mobile navigation and toggles theme", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByLabelText("Open navigation"));
    expect(screen.getByText("Navigation")).toBeInTheDocument();
    await user.click(screen.getAllByRole("link", { name: /Missions/ }).at(-1)!);
    expect(
      await screen.findByRole("heading", { name: "Missions" }),
    ).toBeInTheDocument();
    await user.click(screen.getByLabelText("Open navigation"));
    await user.click(screen.getByLabelText("Close navigation"));
    await waitFor(() =>
      expect(screen.queryByText("Navigation")).not.toBeInTheDocument(),
    );

    await user.click(screen.getByLabelText("Toggle theme"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});

async function fetchMock(input: RequestInfo | URL, init?: RequestInit) {
  const url = typeof input === "string" ? input : input.toString();
  const path = url.replace(/^https?:\/\/[^/]+\//, "").replace(/^\//, "");
  if (init?.method === "POST" && path === "runs") {
    return jsonResponse({ ...run, run_id: "run_created", status: "queued" });
  }
  if (init?.method === "POST" && path === "missions") {
    return jsonResponse({ ...mission, mission_id: "mission_created" });
  }
  if (init?.method === "POST" && path.includes("/permissions/")) {
    return jsonResponse({ accepted: true });
  }
  if (init?.method === "POST" && path === "ops/backups") {
    return jsonResponse({
      backup: {
        name: "cloud-agents-backup-new.tar.gz",
        size_bytes: 256,
        created_at: new Date().toISOString(),
      },
    });
  }
  if (init?.method === "POST" && path === "ops/drills") {
    return jsonResponse(fixtures["ops/drills"]);
  }
  return jsonResponse(fixtures[path] ?? {});
}

function jsonResponse(payload: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
}
