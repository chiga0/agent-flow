import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App, __testUtils, queryClient, router } from "./app";
import { __shellTestUtils } from "./components/shell";

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
      result: { artifacts: [{ name: "plan.md" }] },
    },
    {
      task_id: "review",
      title: "Review mission",
      profile_id: "reviewer",
      status: "pending",
      run_id: null,
      depends_on: ["plan"],
    },
  ],
};

const missionEvents = [
  {
    id: "mevt_1",
    mission_id: "mission_1",
    sequence: 1,
    type: "task.created",
    created_at: new Date().toISOString(),
    data: { task_id: "plan" },
  },
  {
    id: "mevt_2",
    mission_id: "mission_1",
    sequence: 2,
    type: "mission.started",
    created_at: new Date().toISOString(),
    data: { strategy: "sequential" },
  },
];

const task = {
  task_id: "run_1",
  kind: "run",
  title: "Inspect runtime",
  goal: "Inspect runtime",
  status: "running",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  progress: { completed_steps: 0, total_steps: 1, percent: 50 },
  agent_summary: { adapter: "fake", active_agent: "Smoke Test Agent" },
  needs_attention: true,
  pending_permission_count: 1,
  source: { run_id: "run_1", mission_id: null },
  result_summary: "Inspecting live runner state.",
  links: { detail: "/tasks/run_1", source: "/runs/run_1" },
};

const taskEvents = [
  {
    id: "tevt_1",
    task_id: "run_1",
    sequence: 1,
    type: "task.accepted",
    title: "Task accepted",
    body: "Inspect runtime",
    status: "queued",
    created_at: new Date().toISOString(),
    source_event_type: "run.created",
    source: { kind: "run" },
  },
  {
    id: "tevt_2",
    task_id: "run_1",
    sequence: 2,
    type: "permission.required",
    title: "Action needs approval",
    body: "Allow shell command?",
    status: "blocked",
    created_at: new Date().toISOString(),
    source_event_type: "permission.requested",
    source: { kind: "run" },
  },
  {
    id: "tevt_3",
    task_id: "run_1",
    sequence: 3,
    type: "agent.message",
    title: "Agent update",
    body: "Inspecting live runner state.",
    status: "running",
    created_at: new Date().toISOString(),
    source_event_type: "message.delta",
    source: { kind: "run" },
  },
];

const v2Task = {
  task_id: "task_v2_1",
  tenant_id: "tenant_default",
  project_id: "project_default",
  created_by: "owner@example.com",
  title: "Ship the control plane",
  goal: "Ship the control plane",
  mode: "auto",
  status: "completed",
  priority: "normal",
  channel: "web",
  adapter: "fake",
  execution_mode: "fake",
  metadata: {
    dispatch: {
      adapter: "fake",
      execution_unit_id: "local-dev",
      reason: "auto selected fake on local-dev for web",
    },
  },
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  progress: {
    completed_steps: 3,
    running_steps: 0,
    total_steps: 3,
    percent: 100,
  },
  plan: {
    plan_id: "plan_v2_1",
    task_id: "task_v2_1",
    version: 1,
    status: "active",
    strategy: "orchestrator-workers",
    graph: {
      strategy: "orchestrator-workers",
      nodes: [
        { id: "brain", title: "Plan the work", depends_on: [] },
        { id: "builder", title: "Execute the work", depends_on: ["brain"] },
        { id: "reviewer", title: "Review and package", depends_on: ["builder"] },
      ],
    },
    artifact_contract: { required: ["final_summary"] },
    agent_tasks: [
      {
        agent_task_id: "at_brain",
        task_id: "task_v2_1",
        plan_id: "plan_v2_1",
        role: "brain",
        title: "Plan the work",
        goal: "Clarify scope, risks, and execution order",
        status: "completed",
        adapter: "fake",
        order_index: 0,
        depends_on: [],
        artifact_contract: { evaluation: "must produce non-empty result summary" },
        result: { final_summary: "Plan complete." },
        started_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      {
        agent_task_id: "at_builder",
        task_id: "task_v2_1",
        plan_id: "plan_v2_1",
        role: "builder",
        title: "Execute the work",
        goal: "Produce the requested deliverable",
        status: "completed",
        adapter: "fake",
        order_index: 1,
        depends_on: ["brain"],
        artifact_contract: { evaluation: "must produce non-empty result summary" },
        result: { final_summary: "Build complete." },
        started_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      {
        agent_task_id: "at_reviewer",
        task_id: "task_v2_1",
        plan_id: "plan_v2_1",
        role: "reviewer",
        title: "Review and package",
        goal: "Evaluate output and prepare summary",
        status: "completed",
        adapter: "fake",
        order_index: 2,
        depends_on: ["builder"],
        artifact_contract: { evaluation: "must produce non-empty result summary" },
        result: { final_summary: "Review complete." },
        started_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  result: {
    summary: "Plan complete. Build complete. Review complete.",
    artifacts: [{ name: "final_summary", kind: "summary", status: "available" }],
    evaluation: { status: "passed", checks: ["contract"] },
  },
};

const v2FallbackTask = {
  ...v2Task,
  task_id: "task_v2_legacy",
  title: "Legacy recovered task",
  goal: "Continue a recovered task",
  status: "queued",
  channel: "email",
  adapter: "custom-cli",
  metadata: {},
  progress: {
    completed_steps: 0,
    running_steps: 0,
    total_steps: 1,
    percent: 0,
  },
  plan: null,
  result: null,
};

const v2Events = [
  {
    event_id: "v2evt_1",
    task_id: "task_v2_1",
    sequence: 1,
    type: "task.created",
    actor: "system",
    payload: { title: "Ship the control plane" },
    created_at: new Date().toISOString(),
  },
  {
    event_id: "v2evt_2",
    task_id: "task_v2_1",
    sequence: 2,
    type: "plan.created",
    actor: "brain",
    payload: { strategy: "orchestrator-workers" },
    created_at: new Date().toISOString(),
  },
];

const v2Workflow = {
  run: {
    workflow_run_id: "wfr_1",
    task_id: "task_v2_1",
    status: "completed",
    engine: "local-sqlite-dag",
    config: { strategy: "orchestrator-workers" },
    attempt: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  steps: v2Task.plan.agent_tasks.map((agent) => ({
    step_id: `wfs_${agent.role}`,
    workflow_run_id: "wfr_1",
    task_id: "task_v2_1",
    agent_task_id: agent.agent_task_id,
    role: agent.role,
    status: agent.status,
    adapter: agent.adapter,
    order_index: agent.order_index,
    input: { goal: agent.goal },
    output: { artifact_id: `artifact_${agent.role}` },
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
  })),
};

const v2Artifacts = {
  artifacts: v2Task.plan.agent_tasks.map((agent) => ({
    artifact_id: `artifact_${agent.role}`,
    task_id: "task_v2_1",
    agent_task_id: agent.agent_task_id,
    name: "final_summary",
    kind: "summary",
    status: "available",
    content: { final_summary: agent.result.final_summary },
    ref: `v2/task_v2_1/artifact_${agent.role}.json`,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  })),
};

const v2Evaluations = {
  evaluations: v2Task.plan.agent_tasks.map((agent) => ({
    evaluation_id: `eval_${agent.role}`,
    task_id: "task_v2_1",
    agent_task_id: agent.agent_task_id,
    kind: "contract",
    status: "passed",
    details: { checks: ["non_empty_summary"] },
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  })),
};

const v2Replay = {
  replay_id: "replay_1",
  task_id: "task_v2_1",
  requested_by: "owner@example.com",
  status: "created",
  snapshot: { task: v2Task, workflow: v2Workflow },
  created_at: new Date().toISOString(),
};

const v2Overview = {
  generated_at: new Date().toISOString(),
  tasks: { total: 1, by_status: { completed: 1 } },
  agent_tasks: { total: 3, by_status: { completed: 3 } },
  execution_units: [
    {
      unit_id: "local-dev",
      kind: "local-workspace",
      status: "active",
      labels: { region: "local" },
      resources: { cpu: 2 },
      adapters: ["fake", "qwen"],
      features: ["workspace", "artifacts", "events"],
      heartbeat_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ],
  channels: [
    {
      channel_id: "channel_web",
      platform: "web",
      status: "configured",
      config: { signed_callbacks: false },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    {
      channel_id: "channel_feishu",
      platform: "feishu",
      status: "reserved",
      config: { signed_callbacks: true },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ],
  tenants: [
    {
      tenant_id: "tenant_default",
      name: "Default Tenant",
      status: "active",
      settings: { plan: "local" },
      created_by: "system",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ],
  ha: {
    profile: "local-2c2g",
    database: { driver: "sqlite", configured: false },
    queue: { driver: "sqlite-lease", configured: false },
    workers: { horizontal_scale: false, concurrency: 1 },
    workflow: {
      active_engine: "local-sqlite-dag",
      engines: [
        { engine: "local-sqlite-dag", status: "available" },
        { engine: "temporal", status: "available" },
      ],
    },
    backup: { enabled: true, target: "local-artifacts" },
    resource_fit: { two_c_two_g: true },
  },
  reliability: {
    idempotency: "enabled",
    event_source: "sqlite:v2_events",
    runner: "local background worker",
    production_runner: "Temporal",
  },
};

const events = [
  {
    id: "evt_0",
    run_id: "run_1",
    sequence: 1,
    type: "run.created",
    created_at: new Date().toISOString(),
    data: { spec: run.spec },
  },
  {
    id: "evt_1",
    run_id: "run_1",
    sequence: 2,
    type: "permission.requested",
    created_at: new Date().toISOString(),
    data: {
      permission_id: "perm_1",
      prompt: "Allow shell command?",
      tool: "shell",
      options: [
        { id: "proceed_once", label: "Approve" },
        { id: "cancel", label: "Reject" },
      ],
    },
  },
  {
    id: "evt_2",
    run_id: "run_1",
    sequence: 3,
    type: "step.started",
    created_at: new Date().toISOString(),
    data: { prompt_number: 1 },
  },
  {
    id: "evt_3",
    run_id: "run_1",
    sequence: 4,
    type: "message.delta",
    created_at: new Date().toISOString(),
    data: { prompt_number: 1, text: "Inspecting live runner state." },
  },
];

const daemonEvents = [
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
      runtimeEventType: "input.accepted",
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
      options: [
        { id: "proceed_once", label: "Approve" },
        { id: "cancel", label: "Reject" },
      ],
      context: { command: "uname -a", cwd: "/workspace" },
    },
    _meta: {
      serverTimestamp: Date.now(),
      runtimeRunId: "run_1",
      runtimeSequence: 2,
      runtimeEventType: "permission.requested",
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
          text: "Inspecting live runner state.",
        },
      },
    },
    _meta: {
      serverTimestamp: Date.now(),
      runtimeRunId: "run_1",
      runtimeSequence: 3,
      runtimeEventType: "message.delta",
      agentTaskId: "at_brain",
      agentRole: "brain",
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
          id: "tool_1",
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
      runtimeEventType: "tool.completed",
    },
  },
] as const;

let authSessionAuthenticated = true;

const fixtures: Record<string, unknown> = {
  "auth/session": {
    authenticated: true,
    principal: { id: "operator", display_name: "operator", roles: ["owner"] },
  },
  health: { ok: true, version: "0.1-test" },
  capabilities: {
    mode: "saeu-runtime",
    features: ["metrics", "backup", "executor_registry", "cost_budget"],
    adapters: {
      fake: { name: "Fake", status: "available" },
      qwen: { name: "Qwen", status: "available" },
    },
    queue: { counts: {}, jobs: [], workers: [] },
    executor_registry: {
      config: {
        strategy: "per_run_process",
        enabled: true,
        container_image: "qwen-code:latest",
        container_network: "bridge",
      },
      counts: { running: 1 },
    },
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
  executors: {
    executor_registry: {
      config: {
        strategy: "per_run_process",
        enabled: true,
        container_image: "qwen-code:latest",
        container_network: "bridge",
      },
      counts: { running: 1 },
    },
    executors: [
      {
        executor_id: "exec_1",
        run_id: "run_1",
        adapter: "qwen",
        strategy: "per_run_process",
        status: "running",
        base_url: "http://127.0.0.1:4210",
        workspace: "/tmp/workspace/run_1",
        port: 4210,
        pid: 1234,
        started_at: new Date().toISOString(),
        heartbeat_at: new Date().toISOString(),
        released_at: null,
        exit_code: null,
        last_error: null,
        metadata: {},
      },
    ],
  },
  "cost/status": {
    generated_at: new Date().toISOString(),
    status: "ok",
    config: {
      monthly_budget_usd: 10,
      per_run_budget_usd: 1,
      estimated_cost_per_run_usd: 0.05,
    },
    month: "2026-07",
    monthly_estimated_cost_usd: 0.1,
    monthly_budget_usd: 10,
    warning_threshold_usd: 8,
    runs: [{ run_id: "run_1", estimated_cost_usd: 0.1 }],
  },
  workers: {
    workers: [
      {
        worker_id: "hk-2c2g-a",
        status: "active",
        capacity: 1,
        active_count: 1,
        heartbeat_at: new Date().toISOString(),
        lease_ttl_seconds: 60,
        metadata: {
          kind: "remote",
          labels: { region: "hk" },
          resources: { cpus: 2, memory_gb: 2 },
          capabilities: { adapters: ["fake", "qwen"] },
        },
      },
      {
        worker_id: "local",
        status: "draining",
        capacity: 1,
        active_count: 0,
        heartbeat_at: new Date().toISOString(),
        lease_ttl_seconds: 60,
        metadata: { kind: "local" },
      },
    ],
  },
  tasks: { tasks: [task] },
  "tasks/run_1": task,
  "tasks/run_1/events.json": { events: taskEvents },
  "tasks/run_1/artifacts": {
    artifacts: [
      {
        name: "final-report.md",
        size_bytes: 42,
        updated_at: new Date().toISOString(),
      },
    ],
  },
  "tasks/run_1/result": {
    task_id: "run_1",
    status: "running",
    summary: "Inspecting live runner state.",
    artifacts: [
      {
        name: "final-report.md",
        size_bytes: 42,
        updated_at: new Date().toISOString(),
      },
    ],
    completed: false,
    generated_at: new Date().toISOString(),
  },
  "v2/tasks": { tasks: [v2Task, v2FallbackTask] },
  "v2/tasks/task_v2_1": v2Task,
  "v2/tasks/task_v2_1/events.json": { events: v2Events },
  "v2/tasks/task_v2_1/webshell/events.json": { events: daemonEvents },
  "v2/tasks/task_v2_1/workflow": v2Workflow,
  "v2/tasks/task_v2_1/artifacts": v2Artifacts,
  "v2/tasks/task_v2_1/evaluations": v2Evaluations,
  "v2/tasks/task_v2_1/replays": { replays: [v2Replay] },
  "v2/admin/overview": v2Overview,
  "v2/admin/projects": {
    projects: [
      {
        project_id: "project_default",
        tenant_id: "tenant_default",
        name: "Default Project",
        status: "active",
        created_by: "owner@example.com",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ],
  },
  "v2/admin/projects/project_default/members": {
    members: [
      {
        project_id: "project_default",
        user_id: "owner@example.com",
        role: "owner",
        status: "active",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ],
  },
  "v2/admin/execution-units": { units: v2Overview.execution_units },
  "v2/admin/channels": { channels: v2Overview.channels },
  "v2/admin/channel-messages": {
    messages: [
      {
        message_id: "chmsg_1",
        channel_id: "channel_feishu",
        platform: "feishu",
        direction: "inbound",
        status: "accepted",
        external_message_id: "msg_1",
        sender: { open_id: "ou_1" },
        content: { text: "Ship control plane" },
        raw: {},
        task_id: "task_v2_1",
        error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ],
  },
  "v2/admin/tenants": { tenants: v2Overview.tenants },
  "v2/admin/tenants/tenant_default/users": {
    users: [
      {
        tenant_id: "tenant_default",
        user_id: "owner@example.com",
        email: "owner@example.com",
        roles: ["owner"],
        status: "active",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ],
  },
  "v2/admin/tenants/tenant_default/rbac": {
    policies: [
      {
        tenant_id: "tenant_default",
        role: "owner",
        permissions: ["*"],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ],
  },
  "v2/admin/ha": v2Overview.ha,
  "v2/admin/workflow-engines": v2Overview.ha.workflow,
  "v2/admin/execution-units/discover": {
    units: v2Overview.execution_units,
    discovered: [],
  },
  "v2/admin/channels/feishu/config": v2Overview.channels[1],
  "v2/admin/channels/feishu/send": {
    message_id: "chmsg_2",
    channel_id: "channel_feishu",
    platform: "feishu",
    direction: "outbound",
    status: "queued",
    external_message_id: "",
    sender: { system: "agentflow" },
    content: { msg_type: "text", content: { text: "aflow channel test" } },
    raw: {},
    task_id: null,
    error: "webhook_url is not configured",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  "v2/admin/tenants/tenant_acme": v2Overview.tenants[0],
  runs: { runs: [run] },
  "runs/run_1": run,
  "runs/run_1/events.json": { events },
  "session/run_1/events.json": { events: daemonEvents },
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
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        sent_at: new Date().toISOString(),
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
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        sent_at: null,
        metadata: {},
      },
    ],
  },
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
  "missions/mission_1": mission,
  "missions/mission_1/events.json": { events: missionEvents },
  "missions/mission_1/artifacts": {
    artifacts: [
      {
        name: "final_report.md",
        size_bytes: 88,
        updated_at: new Date().toISOString(),
      },
    ],
  },
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
    projects: [
      {
        project_id: "default",
        display_name: "Default",
        description: "Default project",
        status: "active",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        metadata: {},
      },
    ],
    tokens: [
      {
        token_id: "token_1",
        name: "operator-token",
        principal_id: "operator",
        project_id: "default",
        scopes: ["runs:*"],
        status: "active",
        token_prefix: "cat_test",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        revoked_at: null,
        last_used_at: null,
        metadata: {},
      },
    ],
    audit: { auth_boundary: "runtime session cookie plus bearer" },
  },
  "access/projects": {
    projects: [
      {
        project_id: "default",
        display_name: "Default",
        description: "Default project",
        status: "active",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        metadata: {},
      },
    ],
  },
  "access/tokens": {
    tokens: [
      {
        token_id: "token_1",
        name: "operator-token",
        principal_id: "operator",
        project_id: "default",
        scopes: ["runs:*"],
        status: "active",
        token_prefix: "cat_test",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        revoked_at: null,
        last_used_at: null,
        metadata: {},
      },
    ],
  },
  "auth/users": {
    users: [
      {
        email: "owner@example.com",
        display_name: "Owner",
        roles: ["owner"],
        status: "active",
        email_verified_at: new Date().toISOString(),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        last_login_at: null,
        metadata: {},
      },
      {
        email: "auditor@example.com",
        display_name: "",
        roles: ["auditor"],
        status: "active",
        email_verified_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        last_login_at: new Date().toISOString(),
        metadata: {},
      },
    ],
  },
};

describe("aflow console", () => {
  beforeEach(async () => {
    queryClient.clear();
    authSessionAuthenticated = true;
    localStorage.clear();
    window.location.hash = "";
    document.documentElement.classList.remove("dark");
    vi.stubGlobal("fetch", vi.fn(fetchMock));
    await act(async () => {
      await router.navigate({ to: "/" });
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("renders the client workspace and keeps the admin control plane reachable", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Client Workspace" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Channel Ready")).toBeInTheDocument();
    expect(screen.getByText("Live Agent Chats")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "管理后台" }));
    expect(
      await screen.findByRole("heading", { name: "Admin Control Plane" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Reliability Spine")).toBeInTheDocument();

    await user.click(screen.getByLabelText("切换语言"));
    expect(
      await screen.findByRole("heading", { name: "Admin Control Plane" }),
    ).toBeInTheDocument();
    expect(localStorage.getItem("agentflow-locale")).toBe("en");
  });

  it("shows login page and signs in with session credentials", async () => {
    const user = userEvent.setup();
    authSessionAuthenticated = false;
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "登录" }),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText("邮箱"), "owner@example.com");
    await user.type(screen.getByLabelText("密码"), "wrong");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByText("邮箱或密码无效。")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("密码"));
    await user.type(screen.getByLabelText("密码"), "secret");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(
      await screen.findByRole("heading", { name: "Client Workspace" }),
    ).toBeInTheDocument();
  });

  it("creates and inspects a task from the client workspace", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Client Workspace" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Channel Ready")).toBeInTheDocument();

    await user.type(
      screen.getByPlaceholderText(
        "Describe the outcome you want. The platform will choose a plan, agents, runtime, and artifacts.",
      ),
      "Ship the control plane",
    );
    await user.click(screen.getByRole("button", { name: /Multi-agent/ }));
    await user.click(screen.getByRole("button", { name: /Feishu/ }));
    await user.click(screen.getByRole("button", { name: /codex cli/ }));
    await user.click(screen.getByRole("button", { name: "Start" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/v2/tasks",
        expect.objectContaining({
          method: "POST",
          body: expect.stringMatching(
            /Ship the control plane.*multi-agent.*feishu.*codex/s,
          ),
        }),
      ),
    );
    expect(
      await screen.findByRole("heading", { name: "Ship the control plane" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Plan DAG")).toBeInTheDocument();
    expect(screen.getByText("Agent Chat")).toBeInTheDocument();
    expect(screen.getByLabelText("Agent switcher")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /All output/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /brain/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /builder/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reviewer/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /brain/ }));
    expect(screen.getByText("brain output")).toBeInTheDocument();
    expect(
      within(screen.getByLabelText("Real-time Agent output")).getByText(
        "Inspecting live runner state.",
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /builder/ }));
    expect(screen.getByText("Waiting for builder to emit output.")).toBeInTheDocument();
    expect(screen.getByText("Stream complete")).toBeInTheDocument();
    expect(screen.getByText("Execution")).toBeInTheDocument();
    expect(screen.getByText("Durable Workflow")).toBeInTheDocument();
    expect(screen.getByText("Artifacts")).toBeInTheDocument();
    expect(screen.getByText("Evaluations")).toBeInTheDocument();
    expect(screen.getByText("Replay Snapshots")).toBeInTheDocument();
    expect(screen.getByText("Canonical Events")).toBeInTheDocument();
    expect(screen.getByText("Agent Contracts")).toBeInTheDocument();
    expect(screen.getByText("Download audit bundle")).toHaveAttribute(
      "href",
      "/v2/tasks/task_v2_1/audit.json",
    );
    expect(screen.getAllByText("Preview").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Download artifact").length).toBeGreaterThan(0);
    expect(screen.getByText("orchestrator-workers")).toBeInTheDocument();
    expect(screen.getByText("task.created")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Replay" }));
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/v2/tasks/task_v2_1/replay",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(fetch).toHaveBeenCalledWith(
      "/v2/tasks/task_v2_1/retry",
      expect.objectContaining({ method: "POST" }),
    );

    await user.type(
      screen.getByPlaceholderText("Add context or a follow-up instruction"),
      "Include audit notes",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/v2/tasks/task_v2_1/messages",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("Include audit notes"),
        }),
      ),
    );
  });

  it("does not submit an empty task", async () => {
    render(<App />);

    fireEvent.submit(await screen.findByRole("form", { name: "New Task" }));

    expect(fetch).not.toHaveBeenCalledWith(
      "/v2/tasks",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows the admin control plane overview", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(
      await screen.findByRole("link", { name: /Admin|管理后台/ }),
    );

    expect(
      await screen.findByRole("heading", { name: "Admin Control Plane" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Reliability Spine")).toBeInTheDocument();
    expect(screen.getByText("local-dev")).toBeInTheDocument();
    expect(screen.getByText("Feishu")).toBeInTheDocument();
    expect(screen.getByText("sqlite:v2_events")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Discover" }));
    await user.type(screen.getByLabelText("Webhook URL"), "https://bot.example");
    await user.type(screen.getByLabelText("Callback token"), "token");
    await user.click(screen.getByRole("button", { name: "Configure" }));
    await user.clear(screen.getByLabelText("Outbound test"));
    await user.type(screen.getByLabelText("Outbound test"), "hello channel");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await user.type(screen.getByLabelText("Tenant name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Create" }));
    await user.type(screen.getByLabelText("Default tenant user"), "new@example.com");
    await user.click(screen.getByRole("button", { name: "Add" }));
  });

  it("creates a run from the Runs page", async () => {
    const user = userEvent.setup();
    render(<App />);
    await switchToEnglish(user);
    await user.click(
      await screen.findByRole("link", { name: /Admin|管理后台/ }),
    );
    await user.click(await screen.findByRole("link", { name: "Runs" }));

    expect(
      await screen.findByRole("heading", { name: "Runs" }),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("Adapter")).toHaveValue("fake");
    expect(
      screen.getByText(
        "fake is a low-cost smoke test. Run it first when validating a new deployment.",
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /refresh/i }));
    await user.selectOptions(screen.getByLabelText("Adapter"), "qwen");
    expect(
      screen.getByText(
        "qwen consumes more CPU/memory and may require approvals. Use it after fake passes.",
      ),
    ).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Adapter"), "fake");
    await user.clear(await screen.findByLabelText("Prompt"));
    await user.type(screen.getByLabelText("Prompt"), "Run a smoke validation");
    await user.type(screen.getByLabelText("Repo"), "/tmp/repo");
    await user.type(screen.getByLabelText("Workspace"), "/tmp/workspace");
    await user.clear(screen.getByLabelText("Timeout seconds"));
    await user.type(screen.getByLabelText("Timeout seconds"), "900");
    await user.click(screen.getByRole("button", { name: /start/i }));
    expect(screen.getByRole("button", { name: /submitting/i })).toBeDisabled();

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/runs",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("Run a smoke validation"),
        }),
      ),
    );
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/admin/runs/run_created"),
    );
    expect(
      await screen.findByRole("heading", { name: "Run Detail" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Agent Chat")).toBeInTheDocument();
  });

  it("resolves a run permission and exposes artifact downloads", async () => {
    const user = userEvent.setup();
    const createObjectURL = vi.fn(() => "blob:runner-report");
    const revokeObjectURL = vi.fn();
    const click = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    vi.spyOn(document, "createElement").mockImplementation((tagName) => {
      const element = document.createElementNS(
        "http://www.w3.org/1999/xhtml",
        tagName,
      ) as HTMLAnchorElement;
      if (tagName === "a") {
        element.click = click;
      }
      return element;
    });
    await act(async () => {
      await router.navigate({
        to: "/admin/runs/$runId",
        params: { runId: "run_1" },
      });
    });
    render(<App />);
    await switchToEnglish(user);

    expect(await screen.findByText("Permission Requests")).toBeInTheDocument();
    expect(await screen.findByText("log:sent")).toBeInTheDocument();
    expect(screen.getByText("webhook:failed")).toBeInTheDocument();
    expect(screen.getByText("webhook unreachable")).toBeInTheDocument();
    expect(await screen.findByText("Agent Chat")).toBeInTheDocument();
    expect(screen.getByText("Run workspace")).toBeInTheDocument();
    expect(screen.getByText("Current state")).toBeInTheDocument();
    expect(screen.getByText("Next action")).toBeInTheDocument();
    expect(screen.getByText("Human approval required")).toBeInTheDocument();
    expect(screen.getAllByText(/Tool: shell/).length).toBeGreaterThan(0);
    expect(
      within(screen.getByRole("main")).getByText(
        "Inspecting live runner state.",
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Agent" }));
    await user.click(screen.getByRole("button", { name: "Permissions" }));
    await user.click(screen.getByRole("button", { name: "Warnings" }));
    await user.click(screen.getByRole("button", { name: "Errors" }));
    await user.click(screen.getByRole("button", { name: "All" }));
    await user.click(screen.getByRole("button", { name: "Download Report" }));
    expect(click).toHaveBeenCalled();
    expect(screen.getByText("final-report.md")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeVisible();
    await user.type(screen.getByLabelText("Continue chat"), "Please continue");
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/session/run_1/prompt",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("Please continue"),
        }),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(
      screen.getByRole("button", { name: "Retry notification" }),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/runs/run_1/permissions/perm_1/notifications/retry",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await user.click(screen.getAllByRole("button", { name: "Approve" })[0]);

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/session/run_1/permission/perm_1",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("approve"),
        }),
      ),
    );
    expect(fetch).toHaveBeenCalledWith(
      "/session/run_1/permission/perm_1",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining("proceed_once"),
      }),
    );
  });

  it("shows mission detail and profile policy editor", async () => {
    const user = userEvent.setup();
    await act(async () => {
      await router.navigate({ to: "/admin/missions" });
    });
    render(<App />);
    await switchToEnglish(user);

    expect(await screen.findByText("Ship beta")).toBeInTheDocument();
    expect(screen.getByText("Plan mission")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: /open detail/i }));
    expect(await screen.findByText("Mission Stream")).toBeInTheDocument();
    expect(screen.getByText(/Artifacts: plan.md/)).toBeInTheDocument();
    expect(await screen.findByText("Task DAG")).toBeInTheDocument();
    expect(screen.getByText("Mission Events")).toBeInTheDocument();
    expect(screen.getByText("final_report.md")).toBeInTheDocument();

    await act(async () => {
      await router.navigate({ to: "/admin/missions" });
    });
    await user.clear(screen.getByLabelText("Goal"));
    await user.type(
      screen.getByLabelText("Goal"),
      "Create a beta validation report",
    );
    await user.selectOptions(screen.getByLabelText("Strategy"), "fanout");
    await user.selectOptions(screen.getByLabelText("Adapter"), "fake");
    await user.click(screen.getByRole("button", { name: "Start" }));
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
      await router.navigate({ to: "/admin/profiles" });
    });
    await screen.findByText("Planner");
    expect(screen.getByText("Runtime")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy" }));
    await user.clear(screen.getByLabelText("Profile ID"));
    await user.type(screen.getByLabelText("Profile ID"), "planner-copy");
    await user.clear(screen.getByLabelText("Display name"));
    await user.type(screen.getByLabelText("Display name"), "Planner Copy");
    await user.type(screen.getByLabelText("Description"), " copied");
    await user.click(screen.getByRole("button", { name: "Save Profile" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/profiles",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("Planner Copy"),
        }),
      ),
    );
  });

  it("shows access policy foundations", async () => {
    const user = userEvent.setup();
    const createObjectURL = vi.fn(() => "blob:access-policy");
    const revokeObjectURL = vi.fn();
    const click = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    vi.spyOn(document, "createElement").mockImplementation((tagName) => {
      const element = document.createElementNS(
        "http://www.w3.org/1999/xhtml",
        tagName,
      ) as HTMLAnchorElement;
      if (tagName === "a") {
        element.click = click;
      }
      return element;
    });
    await act(async () => {
      await router.navigate({ to: "/admin/access" });
    });
    render(<App />);
    await switchToEnglish(user);

    expect(await screen.findByText("Current Principal")).toBeInTheDocument();
    expect(screen.getByText("Role Matrix")).toBeInTheDocument();
    expect(screen.getByText("Users")).toBeInTheDocument();
    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.getByText("API Tokens")).toBeInTheDocument();
    expect((await screen.findAllByText("runs:*")).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Export" }));
    expect(click).toHaveBeenCalled();
    await user.clear(screen.getAllByLabelText("Project ID")[0]);
    await user.type(screen.getAllByLabelText("Project ID")[0], "team1");
    await user.clear(screen.getAllByLabelText("Display name")[1]);
    await user.type(screen.getAllByLabelText("Display name")[1], "Team One");
    await user.type(screen.getByLabelText("User email"), "new@example.com");
    await user.type(screen.getByLabelText("Initial password"), "secret-12345");
    await user.clear(screen.getByLabelText("Token name"));
    await user.type(screen.getByLabelText("Token name"), "team-token");
    await user.click(screen.getAllByRole("button", { name: "Create" })[1]);
    await user.click(screen.getAllByRole("button", { name: "Create" })[0]);
    await user.click(screen.getAllByRole("button", { name: "Create" })[2]);
    expect(
      (await screen.findAllByText("new@example.com")).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("member").length).toBeGreaterThan(0);
    await user.selectOptions(screen.getAllByLabelText("Role")[1], "auditor");
    await user.click(screen.getAllByRole("button", { name: "Save role" })[0]);
    await user.type(screen.getAllByLabelText("New password")[0], "reset-12345");
    await user.click(screen.getAllByRole("button", { name: "Reset password" })[0]);
    await user.click(screen.getAllByRole("button", { name: "Disable" })[0]);
    expect(await screen.findByText("cat_created_secret")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/access/tokens",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/auth/users",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("new@example.com"),
        }),
      ),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/auth/users/owner%40example.com/roles",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("auditor"),
        }),
      ),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/auth/users/owner%40example.com/password",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("reset-12345"),
        }),
      ),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/auth/users/owner%40example.com/status",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("disabled"),
        }),
      ),
    );
  });

  it("disables access write controls for non-owner roles", async () => {
    const policy = fixtures["access/policy"] as {
      current_principal: { roles: string[]; display_name: string; id: string };
    };
    policy.current_principal = {
      id: "auditor@example.com",
      display_name: "Auditor",
      roles: ["auditor"],
    };
    const user = userEvent.setup();
    await act(async () => {
      await router.navigate({ to: "/admin/access" });
    });
    render(<App />);
    await switchToEnglish(user);

    expect(await screen.findByText("Owner only")).toBeInTheDocument();
    for (const button of screen.getAllByRole("button", { name: "Create" })) {
      expect(button).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "Revoke" })).toBeDisabled();

    policy.current_principal = {
      id: "operator",
      display_name: "operator",
      roles: ["owner"],
    };
  });

  it("shows executor isolation registry", async () => {
    const user = userEvent.setup();
    await act(async () => {
      await router.navigate({ to: "/admin/executors" });
    });
    render(<App />);
    await switchToEnglish(user);

    expect(await screen.findByText("Executor Leases")).toBeInTheDocument();
    expect(screen.getByText("Registry")).toBeInTheDocument();
    expect(await screen.findByText("exec_1")).toBeInTheDocument();
    expect(screen.getAllByText("per_run_process").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
  });

  it("registers and controls execution units", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    await act(async () => {
      await router.navigate({ to: "/admin/units" });
    });
    render(<App />);
    await switchToEnglish(user);

    expect(
      await screen.findByRole("heading", { name: "Units" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("hk-2c2g-a")).toBeInTheDocument();
    expect(screen.getByText("adapter:qwen")).toBeInTheDocument();
    expect(
      screen.getByText(
        "2 GB memory is already running work. Keep this worker at capacity=1.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "This execution unit is at capacity; new work will remain queued.",
      ),
    ).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Unit ID"));
    await user.type(screen.getByLabelText("Unit ID"), "hk-2c2g-b");
    await user.clear(screen.getByLabelText("Worker control URL"));
    await user.type(
      screen.getByLabelText("Worker control URL"),
      "https://doubaofans.site/cloud-agents-worker",
    );
    await user.clear(screen.getByLabelText("Capacity"));
    await user.type(screen.getByLabelText("Capacity"), "1");
    await user.clear(screen.getByLabelText("CPUs"));
    await user.type(screen.getByLabelText("CPUs"), "2");
    await user.clear(screen.getByLabelText("Memory GB"));
    await user.type(screen.getByLabelText("Memory GB"), "2");
    await user.clear(screen.getByLabelText("Region label"));
    await user.type(screen.getByLabelText("Region label"), "hk");
    await user.click(screen.getByRole("button", { name: "Generate" }));
    expect(await screen.findByText("Deployment Command")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining("deploy_worker_vps.sh"),
    );
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await user.click(screen.getAllByRole("button", { name: "Drain" })[0]);
    await user.click(screen.getAllByRole("button", { name: "Resume" })[1]);
    await user.click(screen.getAllByRole("button", { name: "Retry" })[0]);
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/workers/hk-2c2g-a/retry",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("runs operations drills and creates backups", async () => {
    const user = userEvent.setup();
    await act(async () => {
      await router.navigate({ to: "/admin/operations" });
    });
    render(<App />);
    await switchToEnglish(user);

    expect(await screen.findByText("Failure Drills")).toBeInTheDocument();
    expect(await screen.findByText("Cost Budget")).toBeInTheDocument();
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

    await user.click(await screen.findByLabelText("打开导航"));
    expect(screen.getByText("导航")).toBeInTheDocument();
    await user.click(screen.getAllByRole("link", { name: /任务编排/ }).at(-1)!);
    expect(
      await screen.findByRole("heading", { name: "任务编排" }),
    ).toBeInTheDocument();
    await user.click(screen.getByLabelText("打开导航"));
    await user.click(screen.getByLabelText("关闭导航"));
    await waitFor(() =>
      expect(screen.queryByText("导航")).not.toBeInTheDocument(),
    );

    await user.click(screen.getByLabelText("切换主题"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    await user.click(screen.getByLabelText("退出登录"));
    expect(
      await screen.findByRole("heading", { name: "登录" }),
    ).toBeInTheDocument();
  });

  it("summarizes runner events for the live chat timeline", () => {
    const now = new Date().toISOString();
    const liveEvents = [
      event("run.created", 1, { spec: run.spec }, now),
      event(
        "workspace.prepared",
        2,
        {
          strategy: "qwen_serve_shared",
          path: "/workspace",
        },
        now,
      ),
      event("resources.resolved", 3, { cpus: 1 }, now),
      event("run.queued", 4, {}, now),
      event("lease.claimed", 5, { worker_id: "worker_1" }, now),
      event(
        "run.started",
        6,
        { adapter: "qwen", workspace: "/workspace" },
        now,
      ),
      event(
        "input.accepted",
        7,
        { prompt_number: 1, prompt_preview: "Hello" },
        now,
      ),
      event("step.started", 8, { prompt_number: 1 }, now),
      event("step.submitted", 9, { prompt_number: 1 }, now),
      event("message.delta", 9.5, { prompt_number: 1, text: "" }, now),
      event("message.delta", 10, { prompt_number: 1, text: "Hel" }, now),
      event("message.delta", 11, { prompt_number: 1, text: "lo" }, now),
      event(
        "permission.requested",
        12,
        { permission_id: "perm_2", prompt: "Approve?" },
        now,
      ),
      event("permission.resolved", 13, { decision: "approve" }, now),
      event(
        "permission.resolve_requested",
        13.5,
        { permission_id: "perm_2", decision: "approve" },
        now,
      ),
      event("permission.stalled", 14, { permission_id: "perm_3" }, now),
      event("permission.notification.sent", 14.5, { channel: "log" }, now),
      event(
        "permission.notification.failed",
        14.55,
        { channel: "webhook" },
        now,
      ),
      event(
        "permission.resolve_failed",
        14.56,
        { reason: "worker stale" },
        now,
      ),
      event("cost.quoted", 14.6, { estimated_cost_usd: 0.01 }, now),
      event("event.gap_detected", 14.7, { missed: 2 }, now),
      event("stream.warning", 15, { reason: "reconnect" }, now),
      event("step.completed", 16, { prompt_number: 1 }, now),
      event("run.completed", 17, { final_artifact: "final_1.json" }, now),
      event("run.failed", 18, { reason: "boom" }, now),
      event("run.cancel_requested", 18.5, { reason: "user" }, now),
      event("run.cancelled", 19, { reason: "user" }, now),
      event("executor.failed", 19.5, { reason: "executor boom" }, now),
      event("turn_error", 20, { raw: true }, now),
      event(
        "adapter.event",
        21,
        { command: "npm test", cwd: "/workspace", exit_code: 0 },
        now,
      ),
      event(
        "adapter.event",
        22,
        { command: "npm lint", exit_code: 1, stderr: "lint failed" },
        now,
      ),
      event(
        "adapter.event",
        23,
        {
          adapter: "qwen",
          raw: {
            type: "session_update",
            data: {
              sessionId: "session_1",
              update: {
                sessionUpdate: "agent_message_chunk",
                content: { type: "text", text: "Qwen streamed output." },
              },
            },
          },
        },
        now,
      ),
      event(
        "adapter.event",
        24,
        {
          adapter: "qwen",
          raw: {
            type: "session_update",
            data: {
              sessionId: "session_1",
              update: {
                sessionUpdate: "tool_call_update",
                status: "completed",
                title: "ListFiles: .",
                rawInput: { path: "/workspace" },
                rawOutput: "Directory is empty.",
              },
            },
          },
        },
        now,
      ),
      event(
        "adapter.event",
        25,
        {
          adapter: "qwen",
          raw: {
            type: "session_update",
            data: {
              sessionId: "session_1",
              update: {
                sessionUpdate: "agent_thought_chunk",
                content: { type: "text", text: "hidden internal text" },
              },
            },
          },
        },
        now,
      ),
      event(
        "adapter.event",
        25.1,
        {
          adapter: "qwen",
          raw: {
            type: "session_update",
            data: {
              sessionId: "session_1",
              update: {
                sessionUpdate: "agent_thought_chunk",
                content: { type: "text", text: "another hidden chunk" },
              },
            },
          },
        },
        now,
      ),
    ];

    const transcript = __testUtils.runnerTranscript(liveEvents);
    const plannerProfile = (
      fixtures.profiles as {
        profiles: Array<Parameters<typeof __testUtils.copyProfile>[0]>;
      }
    ).profiles[0];

    expect(transcript.map((item) => item.title)).toContain("Agent output #1");
    expect(
      transcript.find((item) => item.title === "Agent output #1")?.body,
    ).toBe("Hello");
    expect(transcript.find((item) => item.title === "Agent output")?.body).toBe(
      "Qwen streamed output.",
    );
    expect(transcript.map((item) => item.body)).toContain(
      [
        "ListFiles: .",
        "status: completed",
        'input: {\n  "path": "/workspace"\n}',
        "output: Directory is empty.",
      ].join("\n"),
    );
    expect(transcript.map((item) => item.title)).toContain(
      "Permission required",
    );
    expect(transcript.map((item) => item.title)).toContain(
      "Permission decision submitted",
    );
    expect(transcript.map((item) => item.title)).toContain(
      "Permission decision failed",
    );
    expect(transcript.map((item) => item.title)).toContain(
      "Permission notification",
    );
    expect(transcript.map((item) => item.title)).toContain("Agent progress");
    expect(transcript.map((item) => item.body).join("\n")).not.toContain(
      "hidden internal text",
    );
    expect(transcript.map((item) => item.title)).toContain("Run failed");
    expect(transcript.map((item) => item.title)).toContain("Cancel requested");
    expect(transcript.map((item) => item.title)).toContain("Executor failed");
    expect(transcript.map((item) => item.title)).toContain(
      "Cost budget checked",
    );
    expect(transcript.map((item) => item.title)).toContain(
      "Event stream recovered",
    );
    expect(transcript.map((item) => item.title)).toContain("turn_error");
    expect(__testUtils.mergeEvents(liveEvents, [])).toBe(liveEvents);
    expect(__testUtils.mergeEvents(liveEvents, [liveEvents[0]])).toBe(
      liveEvents,
    );
    expect(__testUtils.isTerminalEvent("run.completed")).toBe(true);
    expect(__testUtils.isTerminalEvent("step.completed")).toBe(false);
    expect(__testUtils.connectionLabel("fallback")).toBe("polling");
    expect(__testUtils.connectionTone("live")).toBe("ok");
    expect(__testUtils.connectionTone("reconnecting")).toBe("warn");
    expect(__testUtils.connectionTone("closed")).toBe("neutral");
    expect(__testUtils.bubbleClass("error")).toContain("destructive");
    expect(__testUtils.filterLabel("warning")).toBe("Warnings");
    expect(__testUtils.filterTranscript(transcript, "all")).toBe(transcript);
    expect(__testUtils.filterTranscript(transcript, "agent")).toHaveLength(2);
    expect(
      __testUtils.filterTranscript(transcript, "process").length,
    ).toBeGreaterThan(5);
    expect(
      __testUtils.filterTranscript(transcript, "tools").length,
    ).toBeGreaterThan(0);
    expect(
      __testUtils.filterTranscript(transcript, "permission").length,
    ).toBeGreaterThan(1);
    expect(
      __testUtils.filterTranscript(transcript, "warning").length,
    ).toBeGreaterThan(1);
    expect(
      __testUtils.filterTranscript(transcript, "error").length,
    ).toBeGreaterThan(1);
    expect(__testUtils.runnerSignal(liveEvents.at(-1), "running").label).toBe(
      "active",
    );
    expect(__testUtils.runnerSignal(undefined, "running").label).toBe(
      "waiting",
    );
    expect(__testUtils.runnerSignal(liveEvents[0], "completed").label).toBe(
      "terminal",
    );
    expect(
      __testUtils.runnerSignal(
        event(
          "run.started",
          30,
          {},
          new Date(Date.now() - 180_000).toISOString(),
        ),
        "running",
      ).label,
    ).toBe("stalled");
    expect(__testUtils.runnerReadableReport(transcript, liveEvents)).toContain(
      "Runner Execution Report",
    );
    expect(__testUtils.runnerProcessSummary(liveEvents, transcript)).toEqual(
      expect.objectContaining({
        messageChunks: 2,
        permissionRequests: 1,
        progressSignals: 2,
        rawAdapterEvents: 6,
        toolCalls: 2,
      }),
    );
    const daemon = [
      {
        id: 1,
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "user_message_chunk",
            content: { text: "hello agent" },
          },
        },
        _meta: { serverTimestamp: Date.now(), runtimeSequence: 1 },
      },
      {
        id: "2",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "agent_message_chunk",
            content: { type: "text", text: "Hel" },
          },
        },
        _meta: { serverTimestamp: Date.now(), runtimeSequence: 2 },
      },
      {
        id: "3",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "agent_message_chunk",
            content: { type: "text", text: "lo" },
          },
        },
        _meta: { serverTimestamp: Date.now(), runtimeSequence: 3 },
      },
      {
        id: "seq-tool",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "tool_call_update",
            toolCall: {
              name: "shell",
              status: "completed",
              input: { command: "npm test" },
              output: { ok: true },
            },
          },
        },
        _meta: { serverTimestamp: Date.now(), runtimeSequence: 4 },
      },
      {
        id: 5,
        v: 1,
        type: "shell_output",
        data: { stdout: "stdout text", stderr: "" },
        _meta: { serverTimestamp: Date.now(), runtimeSequence: 5 },
      },
      {
        id: 6,
        v: 1,
        type: "permission_request",
        data: {
          requestId: "perm_daemon",
          prompt: "Approve command?",
          tool: "shell",
          options: [{ id: "proceed_once", label: "Approve" }],
        },
        _meta: { serverTimestamp: Date.now(), runtimeSequence: 6 },
      },
      {
        id: 7,
        v: 1,
        type: "permission_resolved",
        data: { requestId: "perm_daemon", decision: "approve" },
        _meta: { serverTimestamp: Date.now(), runtimeSequence: 7 },
      },
      {
        id: 8,
        v: 1,
        type: "turn_complete",
        data: {},
        _meta: { serverTimestamp: Date.now(), runtimeSequence: 8 },
      },
    ] as const;
    const daemonTranscript = __testUtils.daemonRunnerTranscript([...daemon]);
    expect(daemonTranscript).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ role: "operator", body: "hello agent" }),
        expect.objectContaining({ role: "agent", body: "Hello" }),
        expect.objectContaining({
          title: "shell · completed",
          body: expect.stringContaining("command: npm test"),
        }),
        expect.objectContaining({ title: "Shell output", body: "stdout text" }),
        expect.objectContaining({ title: "Permission required" }),
        expect.objectContaining({ title: "Permission resolved" }),
        expect.objectContaining({ title: "Runner completed" }),
      ]),
    );
    expect(
      __testUtils.daemonRunnerProcessSummary([...daemon], daemonTranscript),
    ).toEqual(
      expect.objectContaining({
        messageChunks: 2,
        permissionRequests: 1,
        toolCalls: 2,
      }),
    );
    expect(__testUtils.daemonResolvedPermissionIds([...daemon])).toEqual(
      new Set(["perm_daemon"]),
    );
    expect(__testUtils.daemonPendingPermissionRequests([...daemon])).toEqual(
      [],
    );
    expect(__testUtils.mergeDaemonEvents([], [...daemon])).toHaveLength(8);
    expect(__testUtils.daemonSequence(daemon[3])).toBe(4);
    expect(__testUtils.daemonCreatedAt(daemon[0])).toContain("T");
    expect(__testUtils.isTerminalDaemonEvent("turn_complete")).toBe(true);
    const daemonEdges = [
      {
        id: "thought",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "agent_thought_chunk",
            content: [{ content: { text: "hidden" } }],
          },
        },
      },
      {
        id: "thought-2",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "agent_thought_chunk",
            content: [{ content: { text: "still hidden" } }],
          },
        },
      },
      {
        id: "empty",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "agent_message_chunk",
            content: { text: "" },
          },
        },
      },
      {
        id: "empty-user",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "user_message_chunk",
          },
        },
      },
      {
        id: "array-user",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "user_message_chunk",
            content: [{ content: { text: "array prompt" } }],
          },
        },
      },
      {
        id: "status",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "status",
            status: { eventType: "custom.event", message: "custom status" },
          },
        },
      },
      {
        id: "unknown-session-update",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "unknown_update",
            message: "ignored update",
          },
        },
      },
      {
        id: "failed-tool",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "tool_call_update",
            status: "failed",
            title: "Run shell",
            rawInput: "npm lint",
            rawOutput: "lint failed",
          },
        },
      },
      {
        id: "title-tool",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "tool_call",
            status: "running",
            title: "Custom title",
            content: [{ text: "content array text" }],
          },
        },
      },
      {
        id: "fallback-tool",
        v: 1,
        type: "session_update",
        data: {
          update: {
            sessionUpdate: "tool_call",
            rawInput: { path: "/tmp" },
          },
        },
      },
      {
        id: "stderr",
        v: 1,
        type: "shell_output",
        data: { stderr: "permission denied" },
      },
      {
        id: "pending-permission",
        v: 1,
        type: "permission_request",
        data: { requestId: "perm_pending", options: [{}] },
      },
      {
        id: "error",
        v: 1,
        type: "turn_error",
        data: {},
      },
      {
        id: "cancel",
        v: 1,
        type: "prompt_cancelled",
        data: {},
      },
      {
        id: "stream",
        v: 1,
        type: "stream_error",
        data: {},
      },
      {
        id: "unknown",
        v: 1,
        type: "unknown_event",
        data: { ok: true },
      },
    ] as const;
    const edgeTranscript = __testUtils.daemonRunnerTranscript([...daemonEdges]);
    expect(edgeTranscript).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ title: "Agent progress" }),
        expect.objectContaining({
          title: "Prompt submitted",
          body: "User input was accepted.",
        }),
        expect.objectContaining({
          title: "Prompt submitted",
          body: "array prompt",
        }),
        expect.objectContaining({
          title: "custom.event",
          body: "custom status",
        }),
        expect.objectContaining({ role: "error", title: "Run shell · failed" }),
        expect.objectContaining({
          title: "Custom title · running",
          body: expect.stringContaining("content: content array text"),
        }),
        expect.objectContaining({ title: "Tool call" }),
        expect.objectContaining({
          role: "warning",
          title: "Shell output",
          body: "permission denied",
        }),
        expect.objectContaining({ title: "Runner error" }),
        expect.objectContaining({ title: "Prompt cancelled" }),
        expect.objectContaining({ title: "Stream recovered" }),
        expect.objectContaining({ title: "unknown_event" }),
      ]),
    );
    expect(
      edgeTranscript.find((item) => item.role === "agent" && !item.body.trim()),
    ).toBeUndefined();
    expect(
      __testUtils.daemonPendingPermissionRequests([...daemonEdges]),
    ).toEqual([
      expect.objectContaining({
        permission_id: "perm_pending",
        options: [{ id: "approve" }],
      }),
    ]);
    expect(__testUtils.daemonSequence(daemonEdges[0])).toBe(0);
    expect(__testUtils.daemonCreatedAt(daemonEdges[0])).toContain("T");
    expect(__testUtils.copyProfile(plannerProfile).id).toBe("planner-copy");
    expect(
      __testUtils.pendingPermissionRequests([
        event(
          "permission.requested",
          40,
          { permission_id: "perm_pending" },
          now,
        ),
      ]),
    ).toHaveLength(1);
    expect(
      __testUtils.pendingPermissionRequests([
        event(
          "permission.requested",
          41,
          { permission_id: "perm_submitted" },
          now,
        ),
        event(
          "permission.resolve_requested",
          42,
          { permission_id: "perm_submitted" },
          now,
        ),
      ]),
    ).toHaveLength(0);
    expect(
      __testUtils.pendingPermissionRequests([
        event(
          "permission.requested",
          43,
          { raw: { data: { requestId: "perm_qwen" } } },
          now,
        ),
        event(
          "permission.resolve_requested",
          44,
          { requestId: "perm_qwen" },
          now,
        ),
      ]),
    ).toHaveLength(0);
    expect(
      __testUtils.pendingPermissionRequests([
        event(
          "permission.requested",
          45,
          { permission_id: "perm_completed" },
          now,
        ),
        event("run.completed", 46, {}, now),
      ]),
    ).toHaveLength(0);
    expect(
      __testUtils.permissionDecisionPayload(
        { id: "proceed_once", label: "Allow" },
        "reason",
      ),
    ).toEqual({
      decision: "approve",
      option_id: "proceed_once",
      reason: "reason",
    });
    expect(
      __testUtils.permissionDecisionForOption({
        id: "cancel",
        label: "Reject",
      }),
    ).toBe("cancel");
    expect(__testUtils.compactJson(null)).toBe("");
    expect(__testUtils.compactJson({ ok: true })).toContain("ok");
    expect(__testUtils.emptyProfile().id).toBe("custom-profile");
    expect(__testUtils.emptyToNull("  ")).toBeNull();
    expect(__testUtils.formatBytes(1024)).toBe("1.0 KB");
    expect(__testUtils.prettyJson({ ok: true })).toContain("ok");
    expect(__testUtils.parseJsonObject("{}", "test")).toEqual({});
    expect(() => __testUtils.parseJsonObject("[]", "test")).toThrow(
      "test must be a JSON object",
    );
    expect(
      __testUtils.toolEventBody(
        event("adapter.event", 31, { tool: "shell", stdout: "ok" }, now),
      ),
    ).toContain("shell");
    expect(
      __testUtils.toolEventRole(
        event("adapter.event", 32, { status: "failed" }, now),
      ),
    ).toBe("error");
    expect(
      __testUtils.toolEventRole(
        event(
          "adapter.event",
          32.1,
          {
            adapter: "qwen",
            raw: {
              type: "session_update",
              data: {
                update: {
                  sessionUpdate: "tool_call_update",
                  status: "failed",
                },
              },
            },
          },
          now,
        ),
      ),
    ).toBe("error");
    expect(
      __testUtils.runnerTranscript([event("run.completed", 33, {}, now)])[0]
        .body,
    ).toBe("The runner reached a terminal success state.");
    expect(
      __testUtils.runnerTranscript([
        event("run.started", 34, { adapter: "qwen" }, now),
      ])[0].body,
    ).toBe("qwen");
    expect(
      __testUtils.runnerTranscript([event("run.started", 34, {}, now)])[0].body,
    ).toBe("Session is active.");
    expect(
      __testUtils.runnerTranscript([
        event("input.accepted", 35, { prompt_number: 3 }, now),
      ])[0].body,
    ).toBe("Prompt #3");
    expect(
      __testUtils.runnerTranscript([
        event(
          "adapter.event",
          36,
          {
            raw: {
              data: {
                update: {
                  sessionUpdate: "agent_thought_chunk",
                  content: { text: "private reasoning chunk" },
                },
              },
            },
          },
          now,
        ),
      ])[0].body,
    ).toBe("Model is analyzing the request and preparing the next action.");
    expect(
      __testUtils.transcriptItemForEvent(
        event(
          "adapter.event",
          37,
          {
            raw: {
              data: {
                update: {
                  sessionUpdate: "agent_thought_chunk",
                  content: { text: "private reasoning chunk" },
                },
              },
            },
          },
          now,
        ),
      ),
    ).toBeNull();
    expect(
      __testUtils.runnerTranscript([event("unmapped.event", 34, {}, now)]),
    ).toHaveLength(0);
    expect(
      __testUtils.toolEventBody(
        event("adapter.event", 35, { name: "named-tool" }, now),
      ),
    ).toContain("named-tool");
    expect(
      __testUtils.toolEventBody(
        event(
          "adapter.event",
          35.1,
          {
            adapter: "qwen",
            raw: {
              type: "session_update",
              data: {
                update: {
                  sessionUpdate: "tool_call",
                  status: "running",
                  _meta: { toolName: "run_shell_command" },
                  rawInput: {
                    command: "pwd",
                    cwd: "/workspace",
                  },
                  rawOutput: { stdout: "/workspace" },
                  content: [
                    { content: { text: "tool content" } },
                    { content: { text: "" } },
                  ],
                },
              },
            },
          },
          now,
        ),
      ),
    ).toContain("command: pwd");
    expect(
      __testUtils.toolEventBody(
        event(
          "adapter.event",
          35.2,
          {
            adapter: "qwen",
            raw: {
              type: "session_update",
              data: {
                update: {
                  sessionUpdate: "tool_call_update",
                  rawInput: { cmd: "echo ok" },
                  rawOutput: { stdout: "ok" },
                },
              },
            },
          },
          now,
        ),
      ),
    ).toContain("command: echo ok");
    expect(
      __testUtils.toolEventBody(
        event(
          "adapter.event",
          35.3,
          {
            adapter: "qwen",
            raw: {
              type: "session_update",
              data: {
                update: {
                  sessionUpdate: "agent_message_chunk",
                  content: { text: "not a tool" },
                },
              },
            },
          },
          now,
        ),
      ),
    ).toBe("adapter event");
    expect(
      __testUtils.toolEventBody(
        event(
          "adapter.event",
          35.4,
          {
            adapter: "qwen",
            raw: {
              type: "session_update",
              data: {
                update: {
                  sessionUpdate: "tool_call_update",
                  title: "No input tool",
                },
              },
            },
          },
          now,
        ),
      ),
    ).toContain("No input tool");
    expect(
      __testUtils.runnerTranscript([
        event(
          "adapter.event",
          35.5,
          {
            adapter: "qwen",
            raw: {
              type: "session_update",
              data: {
                update: {
                  sessionUpdate: "user_message_chunk",
                  content: { text: "hello" },
                },
              },
            },
          },
          now,
        ),
      ])[0].title,
    ).toBe("User input streamed");
    expect(__testUtils.toolEventBody(event("adapter.event", 36, {}, now))).toBe(
      "adapter event",
    );
    expect(
      __testUtils.runTaskProgress(
        { ...run, status: "queued" },
        [event("run.queued", 37, {}, now)],
        [],
      ).phase,
    ).toBe("排队中");
    expect(
      __testUtils.runTaskProgress(
        { ...run, status: "completed" },
        [event("run.completed", 38, {}, now)],
        [
          {
            name: "final-report.md",
            size_bytes: 12,
            updated_at: now,
          },
        ],
      ).phase,
    ).toBe("已完成");
    expect(
      __testUtils.runTaskProgress(
        { ...run, status: "completed" },
        [event("run.completed", 38.1, {}, now)],
        [],
      ).nextAction,
    ).toBe("下载事件和审计包完成复盘。");
    expect(
      __testUtils.runTaskProgress(
        { ...run, status: "failed" },
        [event("executor.failed", 39, {}, now)],
        [],
      ).tone,
    ).toBe("bad");
    expect(
      __testUtils.runTaskProgress(
        { ...run, status: "running" },
        [
          event(
            "permission.requested",
            39.1,
            { permission_id: "perm_wait" },
            now,
          ),
        ],
        [],
      ).phase,
    ).toBe("等待权限审批");
    expect(
      __testUtils.runTaskProgress(
        { ...run, status: "running" },
        [
          event("permission.requested", 39.15, { requestId: "perm_done" }, now),
          event("run.completed", 39.16, {}, now),
        ],
        [],
      ).phase,
    ).toBe("已完成");
    expect(
      __testUtils.runTaskProgress(
        { ...run, status: "running" },
        [
          event(
            "permission.resolve_requested",
            39.2,
            { permission_id: "perm_wait" },
            now,
          ),
        ],
        [],
      ).phase,
    ).toBe("等待执行单元应用审批");
    expect(
      __testUtils.runTaskProgress(
        { ...run, status: "cancelled" },
        [event("run.cancelled", 39.3, {}, now)],
        [],
      ).phase,
    ).toBe("已取消");
    expect(
      __testUtils.runTaskProgress(
        undefined,
        [
          event(
            "input.accepted",
            39.4,
            { prompt_preview: "fallback prompt" },
            now,
          ),
        ],
        [],
      ).goal,
    ).toBe("fallback prompt");
    expect(
      __testUtils.permissionDecisionForOption({
        id: "deny_once",
        label: "Deny",
      }),
    ).toBe("cancel");
    expect(__testUtils.statusLine({ running: 2 })).toBe("running 2");
    expect(__testUtils.stringValue(123)).toBe("123");
    expect(__testUtils.timeAgo(undefined)).toBe("-");
    expect(__testUtils.money(1.25)).toBe("$1.25");
    expect(__testUtils.money(null)).toBe("$0.00");
    expect(
      __testUtils.registryValue({ config: { ok: true } }, "config"),
    ).toEqual({
      ok: true,
    });
    expect(__testUtils.registryValue({ config: [] }, "config")).toEqual({});
    expect(__testUtils.objectValue({ ok: true })).toEqual({ ok: true });
    expect(__testUtils.objectValue(null)).toEqual({});
    expect(__testUtils.defaultWorkerControlUrl()).toContain(
      "/cloud-agents-worker",
    );
    window.history.pushState({}, "", "/cloud-agents/");
    expect(__testUtils.defaultWorkerControlUrl()).toContain(
      "/cloud-agents-worker",
    );
    window.history.pushState({}, "", "/agentflow/");
    expect(__testUtils.defaultWorkerControlUrl()).toContain(
      "/agentflow-worker",
    );
    window.history.pushState({}, "", "/");
    expect(
      __testUtils.canPreviewArtifact({
        name: "diagnostics.json",
        size_bytes: 512,
        updated_at: now,
      }),
    ).toBe(true);
    expect(
      __testUtils.canPreviewArtifact({
        name: "video.bin",
        size_bytes: 512,
        updated_at: now,
      }),
    ).toBe(false);
    expect(
      __testUtils.canPreviewArtifact({
        name: "large.jsonl",
        size_bytes: 300 * 1024,
        updated_at: now,
      }),
    ).toBe(false);
    expect(__testUtils.shellSingleQuote("worker's token")).toBe(
      "'worker'\"'\"'s token'",
    );
    expect(
      __testUtils.workerNoSourceDeployCommand({
        worker_id: "hk-worker",
        capacity: 1,
        control_url: "https://doubaofans.site/cloud-agents-worker",
        token: {
          token_id: "token_worker",
          name: "worker-hk-worker",
          principal_id: "operator",
          scopes: ["workers:*"],
          status: "active",
          token_prefix: "cat_worker",
          token: "worker-token-placeholder",
          created_at: now,
          updated_at: now,
          metadata: {},
        },
        metadata: {},
        deploy_command: "local-source-command",
      }),
    ).toContain("raw.githubusercontent.com/chiga0/aflow");
    expect(
      __testUtils.workerBadges({
        worker_id: "worker",
        status: "active",
        capacity: 1,
        active_count: 0,
        heartbeat_at: now,
        lease_ttl_seconds: 60,
        metadata: {
          labels: { region: "hk" },
          resources: { cpus: 2 },
          capabilities: { adapters: ["fake"] },
        },
      }),
    ).toEqual(["region:hk", "cpus:2", "adapter:fake"]);
    expect(
      __testUtils.workerResourceRows({
        worker_id: "metrics-worker",
        status: "active",
        capacity: 2,
        active_count: 1,
        heartbeat_at: now,
        lease_ttl_seconds: 60,
        metadata: {
          resources: { cpus: 2 },
          metrics: {
            cpu_percent: 90,
            memory_percent: "70",
            disk_percent: 86,
            swap_percent: 41,
            load_average: 1.5,
          },
        },
      }),
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ label: "cpu", tone: "warn", value: "90%" }),
        expect.objectContaining({ label: "memory", value: "70%" }),
        expect.objectContaining({ label: "disk", tone: "warn" }),
        expect.objectContaining({ label: "swap", tone: "warn" }),
        expect.objectContaining({ label: "load", value: "1.50" }),
      ]),
    );
    expect(
      __testUtils.workerResourceRows({
        worker_id: "declared-worker",
        status: "active",
        capacity: 1,
        active_count: 1,
        heartbeat_at: now,
        lease_ttl_seconds: 60,
        metadata: { resources: { cpus: 1, memory_gb: 2 } },
      }),
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ label: "capacity", tone: "warn" }),
        expect.objectContaining({ label: "memory", tone: "warn" }),
      ]),
    );
    expect(
      __testUtils.workerResourceRows({
        worker_id: "zero-capacity",
        status: "active",
        capacity: 0,
        active_count: 0,
        heartbeat_at: now,
        lease_ttl_seconds: 60,
        metadata: { resources: { cpu_percent: "bad", memory_percent: 0 / 0 } },
      }),
    ).toEqual([expect.objectContaining({ label: "capacity", percent: 0 })]);
    expect(
      __testUtils.workerResourceRows({
        worker_id: "nan-capacity",
        status: "active",
        capacity: 1,
        active_count: Number.NaN,
        heartbeat_at: now,
        lease_ttl_seconds: 60,
        metadata: {},
      })[0],
    ).toEqual(expect.objectContaining({ label: "capacity", percent: 0 }));
    expect(
      __testUtils.workerResourceWarnings({
        worker_id: "stale-worker",
        status: "stale",
        capacity: 1,
        active_count: 1,
        heartbeat_at: now,
        lease_ttl_seconds: 60,
        metadata: { resources: { memory_gb: 2 } },
      }),
    ).toEqual([
      "units.lowMemoryWarning",
      "units.capacityFullWarning",
      "units.staleWarning",
    ]);
    expect(
      __testUtils.runnerStallExplanation(
        [event("permission.requested", 40, { permission_id: "perm_x" }, now)],
        "running",
      ),
    ).toBe("live.stallPermission");
    expect(
      __testUtils.runnerStallExplanation(
        [event("run.queued", 41, {}, now)],
        "running",
        [],
      ),
    ).toBe("live.stallQueuedNoWorker");
    expect(
      __testUtils.runnerStallExplanation(
        [event("run.queued", 42, {}, now)],
        "running",
        [
          {
            worker_id: "worker",
            status: "active",
            capacity: 1,
            active_count: 1,
            heartbeat_at: now,
            lease_ttl_seconds: 60,
            metadata: {},
          },
        ],
      ),
    ).toBe("live.stallQueuedCapacity");
    expect(
      __testUtils.runnerStallExplanation(
        [event("lease.claimed", 43, { worker_id: "worker" }, now)],
        "running",
        [
          {
            worker_id: "worker",
            status: "stale",
            capacity: 1,
            active_count: 1,
            heartbeat_at: now,
            lease_ttl_seconds: 60,
            metadata: {},
          },
        ],
      ),
    ).toBe("live.stallWorkerStale");
    expect(
      __testUtils.runnerStallExplanation(
        [event("executor.failed", 44, {}, now)],
        "running",
      ),
    ).toBe("live.stallExecutorFailed");
    expect(__testUtils.runnerStallExplanation([], "completed")).toBe(
      "live.stallTerminal",
    );
    expect(__testUtils.runnerStallExplanation([], "running")).toBe(
      "live.stallNoRecentEvent",
    );
    expect(__testUtils.missionChatItems(mission, missionEvents)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          title: "Plan mission · planner",
          body: expect.stringContaining("Artifacts: plan.md"),
          runId: "run_1",
        }),
        expect.objectContaining({
          title: "task.created",
          body: expect.stringContaining("Task: plan"),
        }),
      ]),
    );
    expect(
      __testUtils.missionChatItems(mission, missionEvents, {
        run_1: "planner is producing a concrete plan",
      }),
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          body: expect.stringContaining(
            "Last output: planner is producing a concrete plan",
          ),
        }),
      ]),
    );
    expect(
      __testUtils.latestRunOutput([
        event("run.started", 1, {}, now),
        event("message.delta", 2, { text: "streaming output" }, now),
      ]),
    ).toBe("streaming output");
    expect(
      __testUtils.permissionContextRows({
        permission_id: "perm_1",
        raw: {
          risk: "high",
          cwd: "/workspace",
          payload: { command: "rm -rf build-cache" },
        },
      }),
    ).toEqual([
      { label: "live.permissionRisk", value: "high" },
      { label: "live.permissionCwd", value: "/workspace" },
      { label: "live.permissionCommand", value: "rm -rf build-cache" },
    ]);
    expect(
      __testUtils.permissionContextRows({
        permission_id: "perm_2",
        raw: {
          raw: {
            risk_level: "medium",
            workspace: "/repo",
            cmd: "npm test",
          },
        },
      }),
    ).toEqual([
      { label: "live.permissionRisk", value: "medium" },
      { label: "live.permissionCwd", value: "/repo" },
      { label: "live.permissionCommand", value: "npm test" },
    ]);
    expect(
      __testUtils.permissionContextRows({ permission_id: "empty" }),
    ).toEqual([]);
    expect(
      __testUtils.latestRunOutput([
        event(
          "adapter.event",
          3,
          {
            raw: {
              data: {
                update: {
                  sessionUpdate: "agent_message_chunk",
                  content: { text: "nested qwen chunk" },
                },
              },
            },
          },
          now,
        ),
      ]),
    ).toBe("nested qwen chunk");
    expect(
      __testUtils.latestRunOutput([event("run.started", 1, {}, now)]),
    ).toBe(undefined);
    expect(
      __shellTestUtils.dockPendingPermission([
        event("permission.requested", 1, { permission_id: "perm_1" }, now),
      ]),
    ).toEqual(expect.objectContaining({ permission_id: "perm_1" }));
    expect(
      __shellTestUtils.dockPendingPermission([
        event("permission.requested", 1, { permission_id: "perm_1" }, now),
        event("permission.resolved", 2, { permission_id: "perm_1" }, now),
      ]),
    ).toBeUndefined();
    expect(
      __shellTestUtils.dockPendingPermission([
        event("permission.requested", 1, { raw: { data: { requestId: "perm_2" } } }, now),
        event("permission.resolve_requested", 2, { requestId: "perm_2" }, now),
      ]),
    ).toBeUndefined();
    expect(
      __shellTestUtils.dockPendingPermission([
        event("permission.requested", 1, { permission_id: "perm_3" }, now),
        event("run.completed", 2, {}, now),
      ]),
    ).toBeUndefined();
    expect(
      __shellTestUtils.dockRunStatus("running", [
        event("run.completed", 2, {}, now),
      ]),
    ).toBe("completed");
    expect(
      __shellTestUtils.dockRunPreview([
        event("input.accepted", 1, { prompt_preview: "operator prompt" }, now),
      ]),
    ).toBe("operator prompt");
    expect(
      __shellTestUtils.dockRunPreview([
        event(
          "adapter.event",
          2,
          {
            raw: {
              data: {
                update: {
                  content: { text: "dock nested output" },
                },
              },
            },
          },
          now,
        ),
      ]),
    ).toBe("dock nested output");
    expect(
      __shellTestUtils.dockRunPreview([event("run.started", 1, {}, now)]),
    ).toBe(undefined);
    expect(__testUtils.missionChatItems(undefined, [])).toHaveLength(0);
    expect(
      __testUtils.missionChatItems(
        {
          ...mission,
          tasks: [
            {
              task_id: "write",
              title: "Write report",
              profile_id: "doc-writer",
              status: "running",
              run_id: null,
              depends_on: ["plan"],
              result: { summary: "drafting" },
            },
            {
              task_id: "ship",
              title: "Ship report",
              profile_id: "operator",
              status: "pending",
              run_id: null,
              depends_on: ["write"],
            },
            {
              task_id: "archive",
              title: "Archive",
              profile_id: "doc-writer",
              status: "completed",
              run_id: null,
              depends_on: [],
              result: { artifacts: ["archive.md", { name: "manifest.json" }] },
            },
          ],
        },
        [
          event("mission.completed", 50, { status: "completed" }, now),
          event("task.failed", 51, { run_id: "run_failed" }, now),
        ].map((item) => ({
          ...item,
          mission_id: "mission_1",
        })),
      ),
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ body: expect.stringContaining("Result:") }),
        expect.objectContaining({ body: "Dependencies: write\nNo result yet" }),
        expect.objectContaining({
          body: expect.stringContaining("Artifacts: archive.md, manifest.json"),
        }),
        expect.objectContaining({ status: "completed" }),
        expect.objectContaining({ status: "failed" }),
      ]),
    );
  });

  it("downloads a readable runner report", () => {
    const createObjectURL = vi.fn(() => "blob:report");
    const revokeObjectURL = vi.fn();
    const click = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    vi.spyOn(document, "createElement").mockImplementation((tagName) => {
      const element = document.createElementNS(
        "http://www.w3.org/1999/xhtml",
        tagName,
      ) as HTMLAnchorElement;
      if (tagName === "a") {
        element.click = click;
      }
      return element;
    });

    __testUtils.downloadText("report.md", "# report");

    expect(createObjectURL).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:report");
  });

  it("fetches text artifacts and surfaces preview errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response("preview body", { status: 200 }))
        .mockResolvedValueOnce(
          new Response("missing artifact", { status: 404 }),
        ),
    );

    await expect(__testUtils.fetchTextArtifact("/artifact.txt")).resolves.toBe(
      "preview body",
    );
    await expect(__testUtils.fetchTextArtifact("/missing.txt")).rejects.toThrow(
      "missing artifact",
    );
  });

  it("copies text with the textarea fallback", () => {
    const execCommand = vi.fn();
    const select = vi.fn();
    vi.stubGlobal("navigator", {});
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });
    vi.spyOn(document, "execCommand").mockImplementation(execCommand);
    vi.spyOn(document, "createElement").mockImplementation((tagName) => {
      const element = document.createElementNS(
        "http://www.w3.org/1999/xhtml",
        tagName,
      ) as HTMLTextAreaElement;
      if (tagName === "textarea") {
        element.select = select;
      }
      return element;
    });

    __testUtils.copyText("worker token");

    expect(select).toHaveBeenCalled();
    expect(execCommand).toHaveBeenCalledWith("copy");
  });
});

function event(
  type: string,
  sequence: number,
  data: Record<string, unknown>,
  createdAt: string,
) {
  return {
    id: `evt_${sequence}`,
    run_id: "run_1",
    sequence,
    type,
    created_at: createdAt,
    data,
  };
}

async function switchToEnglish(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByLabelText("切换语言"));
}

async function fetchMock(input: RequestInfo | URL, init?: RequestInit) {
  const url = typeof input === "string" ? input : input.toString();
  const path = url.replace(/^https?:\/\/[^/]+\//, "").replace(/^\//, "");
  if (path === "auth/session") {
    return jsonResponse({
      authenticated: authSessionAuthenticated,
      login_required: true,
      principal: authSessionAuthenticated
        ? {
            id: "owner@example.com",
            email: "owner@example.com",
            display_name: "Owner",
            roles: ["owner"],
          }
        : null,
    });
  }
  if (init?.method === "POST" && path === "auth/login") {
    const body = JSON.parse(String(init.body ?? "{}")) as {
      email?: string;
      password?: string;
    };
    if (body.email !== "owner@example.com" || body.password !== "secret") {
      return jsonResponse({ error: "invalid credentials" }, 401);
    }
    authSessionAuthenticated = true;
    return jsonResponse({
      authenticated: true,
      principal: {
        id: "owner@example.com",
        email: "owner@example.com",
        display_name: "Owner",
        roles: ["owner"],
      },
    });
  }
  if (init?.method === "POST" && path === "auth/logout") {
    authSessionAuthenticated = false;
    return jsonResponse({ authenticated: false });
  }
  if (init?.method === "POST" && path === "runs") {
    await new Promise((resolve) => setTimeout(resolve, 10));
    return jsonResponse({ ...run, run_id: "run_created", status: "queued" });
  }
  if (init?.method === "POST" && path === "tasks") {
    await new Promise((resolve) => setTimeout(resolve, 10));
    return jsonResponse({
      ...task,
      task_id: "run_created",
      title: "Prepare a customer report",
      goal: "Prepare a customer report",
      status: "queued",
      needs_attention: false,
      source: { run_id: "run_created", mission_id: null },
    });
  }
  if (path === "tasks/run_created") {
    return jsonResponse({
      ...task,
      task_id: "run_created",
      title: "Prepare a customer report",
      goal: "Prepare a customer report",
      status: "queued",
      needs_attention: false,
      source: { run_id: "run_created", mission_id: null },
    });
  }
  if (path === "tasks/run_created/events.json") {
    return jsonResponse({
      events: taskEvents.map((item) => ({ ...item, task_id: "run_created" })),
    });
  }
  if (path === "tasks/run_created/artifacts") {
    return jsonResponse({ artifacts: [] });
  }
  if (path === "tasks/run_created/result") {
    return jsonResponse({
      task_id: "run_created",
      status: "queued",
      summary: null,
      artifacts: [],
      completed: false,
      generated_at: new Date().toISOString(),
    });
  }
  if (init?.method === "POST" && path === "tasks/run_1/messages") {
    return jsonResponse({ accepted: true, task_id: "run_1", run_id: "run_1" });
  }
  if (init?.method === "POST" && path === "tasks/run_1/cancel") {
    return jsonResponse({ ...task, status: "cancelled" });
  }
  if (init?.method === "POST" && path === "v2/tasks") {
    return jsonResponse(v2Task);
  }
  if (init?.method === "POST" && path === "v2/tasks/task_v2_1/messages") {
    return jsonResponse({
      event: {
        event_id: "v2evt_message",
        task_id: "task_v2_1",
        sequence: 3,
        type: "user.message",
        actor: "owner@example.com",
        payload: { message: "Include audit notes" },
        created_at: new Date().toISOString(),
      },
    });
  }
  if (init?.method === "POST" && path === "v2/tasks/task_v2_1/retry") {
    return jsonResponse({ ...v2Task, status: "queued" });
  }
  if (init?.method === "POST" && path === "v2/tasks/task_v2_1/replay") {
    return jsonResponse(v2Replay);
  }
  if (path === "runs/run_created") {
    return jsonResponse({ ...run, run_id: "run_created", status: "queued" });
  }
  if (path === "runs/run_created/events.json") {
    return jsonResponse({
      events: events.map((item) => ({ ...item, run_id: "run_created" })),
    });
  }
  if (path === "runs/run_created/artifacts") {
    return jsonResponse({ artifacts: [] });
  }
  if (init?.method === "POST" && path === "missions") {
    return jsonResponse({ ...mission, mission_id: "mission_created" });
  }
  if (init?.method === "POST" && path === "profiles") {
    return jsonResponse({
      ...(fixtures.profiles as { profiles: Array<Record<string, unknown>> })
        .profiles[0],
      display_name: "Planner Copy",
      source: "user",
      version: 2,
    });
  }
  if (init?.method === "POST" && path === "access/projects") {
    return jsonResponse({
      project_id: "created",
      display_name: "Created",
      description: "",
      status: "active",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      metadata: {},
    });
  }
  if (init?.method === "POST" && path === "access/tokens") {
    return jsonResponse({
      token_id: "token_created",
      name: "operator-token",
      principal_id: "operator",
      project_id: "default",
      scopes: ["runs:*"],
      status: "active",
      token_prefix: "cat_created",
      token: "cat_created_secret",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      metadata: {},
    });
  }
  if (init?.method === "POST" && path === "access/tokens/token_1/revoke") {
    return jsonResponse({
      token_id: "token_1",
      name: "operator-token",
      principal_id: "operator",
      scopes: ["runs:*"],
      status: "revoked",
      token_prefix: "cat_test",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      revoked_at: new Date().toISOString(),
      metadata: {},
    });
  }
  if (init?.method === "POST" && path === "auth/users") {
    const body = JSON.parse(String(init.body ?? "{}")) as {
      roles?: string[];
    };
    const created = {
      email: "new@example.com",
      display_name: "new@example.com",
      roles: body.roles ?? ["member"],
      status: "active",
      email_verified_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      last_login_at: null,
      metadata: {},
    };
    (
      fixtures["auth/users"] as { users: Array<Record<string, unknown>> }
    ).users.push(created);
    return jsonResponse(created);
  }
  const authUserMatch = path.match(/^auth\/users\/([^/]+)\/(roles|status|password)$/);
  if (init?.method === "POST" && authUserMatch) {
    const email = decodeURIComponent(authUserMatch[1]);
    const action = authUserMatch[2];
    const body = JSON.parse(String(init.body ?? "{}")) as {
      roles?: string[];
      status?: string;
    };
    const usersFixture = fixtures["auth/users"] as {
      users: Array<Record<string, unknown>>;
    };
    const existing = usersFixture.users.find((item) => item.email === email);
    const updated = {
      ...(existing ?? usersFixture.users[0]),
      email,
      roles: action === "roles" ? body.roles : existing?.roles,
      status: action === "status" ? body.status : existing?.status,
      updated_at: new Date().toISOString(),
    };
    return jsonResponse(updated);
  }
  if (init?.method === "POST" && path === "auth/login") {
    return jsonResponse(fixtures["auth/session"]);
  }
  if (init?.method === "POST" && path === "auth/logout") {
    return jsonResponse({ authenticated: false });
  }
  if (init?.method === "POST" && path === "workers/registrations") {
    return jsonResponse({
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
        token: "worker-token-placeholder",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        metadata: {},
      },
      metadata: {},
      deploy_command: [
        "RUN_WORKER_TOKEN",
        "='<worker-token>' bash scripts/deploy_worker_vps.sh root@<worker-ip> /path/to/key.pem",
      ].join(""),
    });
  }
  if (init?.method === "POST" && path.endsWith("/drain")) {
    const workerFixtures = fixtures.workers as {
      workers: Array<Record<string, unknown>>;
    };
    return jsonResponse({
      worker: { ...workerFixtures.workers[0], status: "draining" },
      control: {},
    });
  }
  if (init?.method === "POST" && path.endsWith("/resume")) {
    const workerFixtures = fixtures.workers as {
      workers: Array<Record<string, unknown>>;
    };
    return jsonResponse({
      worker: { ...workerFixtures.workers[0], status: "active" },
      control: {},
    });
  }
  if (
    init?.method === "POST" &&
    path.includes("/permissions/") &&
    path.endsWith("/notifications/retry")
  ) {
    return jsonResponse(fixtures["runs/run_1/permission-notifications"]);
  }
  if (init?.method === "POST" && path.endsWith("/retry")) {
    return jsonResponse({
      worker_id: "hk-2c2g-a",
      requeued_run_ids: ["run_1"],
      control: {},
    });
  }
  if (init?.method === "POST" && path.endsWith("/input")) {
    return jsonResponse({ accepted: true, run_id: path.split("/")[1] }, 202);
  }
  if (init?.method === "POST" && path.endsWith("/prompt")) {
    const sessionId = path.split("/")[1];
    return jsonResponse(
      { accepted: true, session_id: sessionId, run_id: sessionId },
      202,
    );
  }
  if (init?.method === "POST" && path.includes("/permission/")) {
    return jsonResponse({ accepted: true });
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

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}
