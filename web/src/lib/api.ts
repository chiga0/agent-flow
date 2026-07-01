export type RunStatus =
  "created" | "queued" | "running" | "completed" | "failed" | "cancelled";

const API_BASE = getApiBase();

export interface RunSpec {
  prompt?: string | null;
  adapter: string;
  repo?: string | null;
  workspace?: string | null;
  model?: string | null;
  sandbox?: Record<string, unknown>;
  timeout_seconds?: number | null;
  metadata?: Record<string, unknown>;
}

export interface RunState {
  run_id: string;
  status: RunStatus;
  adapter_run_id?: string | null;
  created_at: string;
  updated_at: string;
  event_count: number;
  prompt_count: number;
  spec: RunSpec;
}

export interface RuntimeEvent {
  id: string;
  run_id: string;
  sequence: number;
  type: string;
  created_at: string;
  data: Record<string, unknown>;
}

export interface ArtifactInfo {
  name: string;
  size_bytes: number;
  updated_at: string;
}

export interface PermissionRequest {
  permission_id: string;
  prompt?: string;
  options?: Array<{ id: string; label?: string; description?: string }>;
  tool?: string;
  raw?: Record<string, unknown>;
}

export interface WorkerInfo {
  worker_id: string;
  status: string;
  capacity: number;
  active_count: number;
  heartbeat_at: string;
  lease_ttl_seconds: number;
}

export interface QueueStatus {
  counts: Record<string, number>;
  jobs: Array<Record<string, unknown>>;
  workers: WorkerInfo[];
}

export interface DrillCheck {
  id: string;
  status: "pass" | "warn" | "fail" | string;
  summary: string;
  details: Record<string, unknown>;
}

export interface Capabilities {
  mode: string;
  features: string[];
  adapters: Record<
    string,
    { name: string; status?: string; features?: string[] }
  >;
  queue: QueueStatus;
  profiles: AgentProfile[];
  permission_stall_policy?: { seconds: number; action: string };
  cleanup_policy?: Record<string, unknown>;
  ops_policy?: Record<string, unknown>;
}

export interface Metrics {
  generated_at: string;
  runs: { total: number; by_status: Record<string, number> };
  missions: { total: number; by_status: Record<string, number> };
  queue: {
    counts: Record<string, number>;
    worker_count: number;
    active_workers: number;
    stale_workers: number;
  };
  permissions: { pending: number; stalled: number };
  latency_seconds: { count: number; avg: number | null; p95: number | null };
}

export interface MissionTask {
  task_id: string;
  title: string;
  profile_id: string;
  status: string;
  run_id?: string | null;
  depends_on: string[];
}

export interface MissionState {
  mission_id: string;
  status: string;
  created_at: string;
  updated_at: string;
  event_count: number;
  task_count: number;
  completed_task_count: number;
  failed_task_count: number;
  spec: { goal: string; strategy: string; adapter: string };
  tasks: MissionTask[];
}

export interface AgentProfile {
  id: string;
  display_name: string;
  description: string;
  version: number;
  source: string;
  runtime: Record<string, unknown>;
  tools: Record<string, unknown>;
  approval: Record<string, unknown>;
  limits: Record<string, unknown>;
  workspace: Record<string, unknown>;
  artifacts: Record<string, unknown>;
}

export interface BackupInfo {
  name: string;
  size_bytes: number;
  created_at: string;
}

export interface P5Evaluation {
  id: string;
  status: string;
  mode: string;
  decision: string;
  entrypoints?: string[];
  required_env?: string;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error((await response.text()) || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const runtimeApi = {
  health: () => api<{ ok: boolean; version: string }>("health"),
  capabilities: () => api<Capabilities>("capabilities"),
  metrics: () => api<Metrics>("metrics.json"),
  queue: () => api<QueueStatus>("queue"),
  runs: () => api<{ runs: RunState[] }>("runs"),
  run: (runId: string) => api<RunState>(`runs/${runId}`),
  runEvents: (runId: string) =>
    api<{ events: RuntimeEvent[] }>(`runs/${runId}/events.json`),
  runArtifacts: (runId: string) =>
    api<{ artifacts: ArtifactInfo[] }>(`runs/${runId}/artifacts`),
  runAudit: (runId: string) =>
    api<Record<string, unknown>>(`runs/${runId}/audit.json`),
  createRun: (payload: Partial<RunSpec>) =>
    api<RunState>("runs", { method: "POST", body: JSON.stringify(payload) }),
  cancelRun: (runId: string) =>
    api<{ cancelled: boolean }>(`runs/${runId}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason: "cancelled from console" }),
    }),
  resolvePermission: (
    runId: string,
    permissionId: string,
    payload: { decision: string; option_id?: string; reason?: string },
  ) =>
    api(`runs/${runId}/permissions/${permissionId}`, {
      method: "POST",
      body: JSON.stringify({ decided_by: "web-console", ...payload }),
    }),
  missions: () => api<{ missions: MissionState[] }>("missions"),
  createMission: (payload: Record<string, unknown>) =>
    api<MissionState>("missions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  profiles: () => api<{ profiles: AgentProfile[] }>("profiles"),
  opsStatus: () => api<Record<string, unknown>>("ops/status"),
  drills: () => api<Record<string, unknown>>("ops/drills"),
  runDrills: () =>
    api<Record<string, unknown>>("ops/drills", {
      method: "POST",
      body: JSON.stringify({}),
    }),
  backups: () => api<{ backups: BackupInfo[] }>("ops/backups"),
  createBackup: () =>
    api<{ backup: BackupInfo }>("ops/backups", {
      method: "POST",
      body: JSON.stringify({}),
    }),
  p5Evaluations: () => api<{ components: P5Evaluation[] }>("p5/evaluations"),
};

export function artifactHref(runId: string, artifactName: string) {
  return `${API_BASE}runs/${runId}/artifacts/${encodeURIComponent(artifactName)}`;
}

export function auditHref(runId: string) {
  return `${API_BASE}runs/${runId}/audit.json`;
}

export function backupHref(name: string) {
  return `${API_BASE}ops/backups/${encodeURIComponent(name)}`;
}

export function missionArtifactHref(missionId: string, artifactName: string) {
  return `${API_BASE}missions/${missionId}/artifacts/${encodeURIComponent(artifactName)}`;
}

export function extractPermissionRequest(
  event: RuntimeEvent,
): PermissionRequest | null {
  if (event.type !== "permission.requested") {
    return null;
  }
  const rawId =
    event.data.permission_id ??
    nestedValue(event.data.raw, "data", "requestId");
  if (typeof rawId !== "string" || !rawId.trim()) {
    return null;
  }
  const options =
    event.data.options ?? nestedValue(event.data.raw, "data", "options");
  return {
    permission_id: rawId,
    prompt: stringValue(
      event.data.prompt ?? nestedValue(event.data.raw, "data", "prompt"),
    ),
    tool: stringValue(
      event.data.tool ?? nestedValue(event.data.raw, "data", "tool"),
    ),
    options: Array.isArray(options)
      ? options
          .filter(
            (option): option is Record<string, unknown> =>
              typeof option === "object",
          )
          .map((option) => ({
            id:
              stringValue(option.id) ||
              stringValue(option.option_id) ||
              "approve",
            label: stringValue(option.label),
            description: stringValue(option.description),
          }))
      : undefined,
    raw: event.data,
  };
}

export function resolvedPermissionIds(events: RuntimeEvent[]) {
  const ids = new Set<string>();
  for (const event of events) {
    if (event.type !== "permission.resolved") {
      continue;
    }
    const id =
      event.data.permission_id ??
      nestedValue(event.data.raw, "data", "requestId");
    if (typeof id === "string") {
      ids.add(id);
    }
  }
  return ids;
}

function getApiBase() {
  const path = window.location.pathname;
  if (path === "/cloud-agents" || path.startsWith("/cloud-agents/")) {
    return "/cloud-agents/";
  }
  return "/";
}

function nestedValue(value: unknown, ...keys: string[]) {
  let current = value;
  for (const key of keys) {
    if (!current || typeof current !== "object") {
      return undefined;
    }
    current = (current as Record<string, unknown>)[key];
  }
  return current;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : undefined;
}
