import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  createHashHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  RouterProvider,
  useParams,
} from "@tanstack/react-router";
import { useForm } from "@tanstack/react-form";
import {
  Download,
  MessageSquare,
  PauseCircle,
  Play,
  Radio,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Shell } from "./components/shell";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
  Field,
  Input,
  LinkButton,
  Metric,
  Select,
  StatusBadge,
  Textarea,
} from "./components/ui";
import {
  artifactHref,
  auditHref,
  backupHref,
  extractPermissionRequest,
  missionArtifactHref,
  resolvedPermissionIds,
  runEventStreamHref,
  runtimeApi,
  type ArtifactInfo,
  type DrillCheck,
  type MissionState,
  type RuntimeEvent,
  type RunState,
} from "./lib/api";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: 5000,
      retry: 1,
    },
  },
});

const rootRoute = createRootRoute({ component: Shell });
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: OverviewPage,
});
const runsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs",
  component: RunsPage,
});
const runDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs/$runId",
  component: RunDetailPage,
});
const missionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/missions",
  component: MissionsPage,
});
const profilesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/profiles",
  component: ProfilesPage,
});
const operationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/operations",
  component: OperationsPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  runsRoute,
  runDetailRoute,
  missionsRoute,
  profilesRoute,
  operationsRoute,
]);

export const router = createRouter({ routeTree, history: createHashHistory() });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}

function OverviewPage() {
  const health = useQuery({ queryKey: ["health"], queryFn: runtimeApi.health });
  const metrics = useQuery({
    queryKey: ["metrics"],
    queryFn: runtimeApi.metrics,
  });
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: runtimeApi.capabilities,
  });
  const runs = useQuery({ queryKey: ["runs"], queryFn: runtimeApi.runs });
  const missions = useQuery({
    queryKey: ["missions"],
    queryFn: runtimeApi.missions,
  });

  return (
    <Page
      title="Overview"
      subtitle="Runtime health, queue pressure, and latest work."
    >
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Metric
          label="Runtime"
          value={health.data?.ok ? "Healthy" : "Checking"}
          detail={health.data?.version}
        />
        <Metric
          label="Runs"
          value={metrics.data?.runs.total ?? "-"}
          detail={statusLine(metrics.data?.runs.by_status)}
        />
        <Metric
          label="Missions"
          value={metrics.data?.missions.total ?? "-"}
          detail={statusLine(metrics.data?.missions.by_status)}
        />
        <Metric
          label="Permissions"
          value={metrics.data?.permissions.pending ?? "-"}
          detail={`${metrics.data?.permissions.stalled ?? 0} stalled`}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <Card>
          <CardHeader>
            <CardTitle>Queue</CardTitle>
            <Badge tone={metrics.data?.queue.stale_workers ? "warn" : "ok"}>
              {metrics.data?.queue.active_workers ?? 0} active
            </Badge>
          </CardHeader>
          <CardBody className="grid gap-3 md:grid-cols-3">
            <Metric
              label="Queued"
              value={metrics.data?.queue.counts.queued ?? 0}
            />
            <Metric
              label="Running"
              value={metrics.data?.queue.counts.running ?? 0}
            />
            <Metric
              label="Stale workers"
              value={metrics.data?.queue.stale_workers ?? 0}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Adapters</CardTitle>
            <Badge tone="info">
              {Object.keys(capabilities.data?.adapters ?? {}).length}
            </Badge>
          </CardHeader>
          <CardBody className="grid gap-2">
            {Object.entries(capabilities.data?.adapters ?? {}).map(
              ([id, adapter]) => (
                <div
                  key={id}
                  className="flex items-center justify-between gap-3 rounded-md border border-border p-2"
                >
                  <span className="font-medium">{adapter.name || id}</span>
                  <StatusBadge status={adapter.status ?? "available"} />
                </div>
              ),
            )}
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <RecentRuns runs={runs.data?.runs ?? []} />
        <RecentMissions missions={missions.data?.missions ?? []} />
      </div>
    </Page>
  );
}

function RunsPage() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: runtimeApi.runs });
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: runtimeApi.capabilities,
  });
  return (
    <Page
      title="Runs"
      subtitle="Create and inspect isolated Agent execution units."
    >
      <div className="grid gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
        <CreateRunForm
          adapters={Object.keys(capabilities.data?.adapters ?? { fake: {} })}
        />
        <Card>
          <CardHeader>
            <CardTitle>Run History</CardTitle>
            <Button size="sm" variant="ghost" onClick={() => runs.refetch()}>
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
          </CardHeader>
          <CardBody>
            <RunList runs={runs.data?.runs ?? []} />
          </CardBody>
        </Card>
      </div>
    </Page>
  );
}

function CreateRunForm({ adapters }: { adapters: string[] }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const createRun = useMutation({
    mutationFn: runtimeApi.createRun,
    onSuccess: async () => {
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["metrics"] });
    },
    onError: (err) => setError(String(err)),
  });
  const form = useForm({
    defaultValues: {
      adapter: adapters.includes("qwen") ? "qwen" : adapters[0] || "fake",
      prompt:
        "Summarize the current runtime status and produce a short final report.",
      repo: "",
      workspace: "",
      timeout_seconds: 1800,
    },
    onSubmit: async ({ value }) => {
      await createRun.mutateAsync({
        adapter: value.adapter,
        prompt: value.prompt,
        repo: emptyToNull(value.repo),
        workspace: emptyToNull(value.workspace),
        timeout_seconds: Number(value.timeout_seconds) || 1800,
      });
    },
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Create Run</CardTitle>
        <Badge tone="info">SAEU</Badge>
      </CardHeader>
      <CardBody>
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            event.stopPropagation();
            void form.handleSubmit();
          }}
        >
          <form.Field name="adapter">
            {(field) => (
              <Field label="Adapter">
                <Select
                  value={field.state.value}
                  onChange={(event) => field.handleChange(event.target.value)}
                >
                  {adapters.map((adapter) => (
                    <option key={adapter} value={adapter}>
                      {adapter}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
          </form.Field>
          <form.Field name="prompt">
            {(field) => (
              <Field label="Prompt">
                <Textarea
                  value={field.state.value}
                  onChange={(event) => field.handleChange(event.target.value)}
                />
              </Field>
            )}
          </form.Field>
          <div className="grid gap-3 md:grid-cols-2">
            <form.Field name="repo">
              {(field) => (
                <Field label="Repo">
                  <Input
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                  />
                </Field>
              )}
            </form.Field>
            <form.Field name="workspace">
              {(field) => (
                <Field label="Workspace">
                  <Input
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                  />
                </Field>
              )}
            </form.Field>
          </div>
          <form.Field name="timeout_seconds">
            {(field) => (
              <Field label="Timeout seconds">
                <Input
                  min={60}
                  type="number"
                  value={field.state.value}
                  onChange={(event) =>
                    field.handleChange(Number(event.target.value))
                  }
                />
              </Field>
            )}
          </form.Field>
          {error ? (
            <div className="rounded-md border border-destructive/30 p-3 text-sm text-destructive">
              {error}
            </div>
          ) : null}
          <Button
            disabled={createRun.isPending}
            type="submit"
            variant="primary"
          >
            <Play className="h-4 w-4" />
            Start
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function RunDetailPage() {
  const { runId } = useParams({ from: "/runs/$runId" });
  const queryClient = useQueryClient();
  const run = useQuery({
    queryKey: ["runs", runId],
    queryFn: () => runtimeApi.run(runId),
  });
  const events = useQuery({
    queryKey: ["runs", runId, "events"],
    queryFn: () => runtimeApi.runEvents(runId),
  });
  const artifacts = useQuery({
    queryKey: ["runs", runId, "artifacts"],
    queryFn: () => runtimeApi.runArtifacts(runId),
  });
  const live = useRunLiveEvents(
    runId,
    events.data?.events ?? [],
    run.data?.status,
  );
  const cancel = useMutation({
    mutationFn: () => runtimeApi.cancelRun(runId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["runs", runId] });
    },
  });
  return (
    <Page title="Run Detail" subtitle={runId}>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid gap-4">
          <Card>
            <CardHeader>
              <CardTitle>State</CardTitle>
              <div className="flex gap-2">
                {run.data ? <StatusBadge status={run.data.status} /> : null}
                <Button
                  disabled={cancel.isPending || isTerminal(run.data?.status)}
                  size="sm"
                  onClick={() => cancel.mutate()}
                >
                  <PauseCircle className="h-4 w-4" />
                  Cancel
                </Button>
              </div>
            </CardHeader>
            <CardBody className="grid gap-3 md:grid-cols-4">
              <Metric label="Adapter" value={run.data?.spec.adapter ?? "-"} />
              <Metric label="Events" value={run.data?.event_count ?? "-"} />
              <Metric label="Inputs" value={run.data?.prompt_count ?? "-"} />
              <Metric label="Updated" value={timeAgo(run.data?.updated_at)} />
            </CardBody>
          </Card>
          <PermissionPanel runId={runId} events={live.events} />
          <LiveRunnerPanel
            connectionStatus={live.status}
            events={live.events}
            runStatus={run.data?.status}
          />
          <EventList events={live.events} />
        </div>
        <div className="grid content-start gap-4">
          <ArtifactPanel
            runId={runId}
            artifacts={artifacts.data?.artifacts ?? []}
          />
          <Card>
            <CardHeader>
              <CardTitle>Downloads</CardTitle>
            </CardHeader>
            <CardBody className="grid gap-2">
              <LinkButton href={artifactHref(runId, "events.jsonl")}>
                <Download className="h-4 w-4" />
                Events JSONL
              </LinkButton>
              <LinkButton href={artifactHref(runId, "diagnostics.json")}>
                <Download className="h-4 w-4" />
                Diagnostics
              </LinkButton>
              <LinkButton href={auditHref(runId)}>
                <Download className="h-4 w-4" />
                Audit Bundle
              </LinkButton>
            </CardBody>
          </Card>
        </div>
      </div>
    </Page>
  );
}

type LiveConnectionStatus =
  "connecting" | "live" | "reconnecting" | "closed" | "fallback";

const liveEventTypes = [
  "run.created",
  "workspace.prepared",
  "resources.resolved",
  "run.queued",
  "lease.claimed",
  "run.started",
  "input.accepted",
  "step.started",
  "step.submitted",
  "message.delta",
  "adapter.event",
  "stream.warning",
  "permission.requested",
  "permission.resolved",
  "permission.stalled",
  "step.completed",
  "run.completed",
  "run.failed",
  "run.cancelled",
  "cancel.warning",
  "input.rejected",
  "adapter.not_configured",
];

function useRunLiveEvents(
  runId: string,
  initialEvents: RuntimeEvent[],
  runStatus?: string,
) {
  const [events, setEvents] = useState<RuntimeEvent[]>(initialEvents);
  const [status, setStatus] = useState<LiveConnectionStatus>("connecting");

  useEffect(() => {
    setEvents((current) => mergeEvents(current, initialEvents));
  }, [initialEvents]);

  useEffect(() => {
    if (typeof EventSource === "undefined") {
      setStatus("fallback");
      return;
    }
    if (isTerminal(runStatus)) {
      setStatus("closed");
      return;
    }

    setStatus("connecting");
    const source = new EventSource(runEventStreamHref(runId));
    const handleEvent = (message: MessageEvent) => {
      try {
        const event = JSON.parse(message.data) as RuntimeEvent;
        setEvents((current) => mergeEvents(current, [event]));
        if (isTerminalEvent(event.type)) {
          setStatus("closed");
          source.close();
        }
      } catch {
        setStatus("reconnecting");
      }
    };
    for (const eventType of liveEventTypes) {
      source.addEventListener(eventType, handleEvent);
    }
    source.onopen = () => setStatus("live");
    source.onerror = () =>
      setStatus(
        source.readyState === EventSource.CLOSED ? "closed" : "reconnecting",
      );

    return () => {
      for (const eventType of liveEventTypes) {
        source.removeEventListener(eventType, handleEvent);
      }
      source.close();
    };
  }, [runId, runStatus]);

  return { events, status };
}

function LiveRunnerPanel({
  connectionStatus,
  events,
  runStatus,
}: {
  connectionStatus: LiveConnectionStatus;
  events: RuntimeEvent[];
  runStatus?: string;
}) {
  const transcript = useMemo(() => runnerTranscript(events), [events]);
  const latest = events.at(-1);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!scrollRef.current) {
      return;
    }
    if (typeof scrollRef.current.scrollTo === "function") {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
      return;
    }
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [transcript.length, latest?.sequence]);

  return (
    <Card>
      <CardHeader>
        <div className="flex min-w-0 items-center gap-2">
          <MessageSquare className="h-4 w-4 text-primary" />
          <CardTitle>Live Runner Chat</CardTitle>
        </div>
        <Badge tone={connectionTone(connectionStatus)}>
          <Radio className="h-4 w-4" />
          {connectionLabel(connectionStatus)}
        </Badge>
      </CardHeader>
      <CardBody className="grid gap-4">
        <div className="grid gap-3 md:grid-cols-3">
          <Metric label="Run status" value={runStatus ?? "loading"} />
          <Metric label="Last event" value={latest?.type ?? "-"} />
          <Metric label="Sequence" value={latest?.sequence ?? "-"} />
        </div>
        <div
          ref={scrollRef}
          className="grid max-h-[520px] gap-3 overflow-auto rounded-md border border-border bg-muted/40 p-3"
        >
          {transcript.map((item) => (
            <RunnerBubble key={item.id} item={item} />
          ))}
          {!transcript.length ? (
            <EmptyState
              title="Waiting for runner output"
              detail="The live stream will append steps, messages, permission requests, and terminal state here."
            />
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

type RunnerTranscriptItem = {
  id: string;
  role: "system" | "agent" | "operator" | "warning" | "success" | "error";
  title: string;
  body: string;
  created_at: string;
  event_type: string;
  sequence: number;
};

function RunnerBubble({ item }: { item: RunnerTranscriptItem }) {
  return (
    <div
      className={`flex ${item.role === "agent" ? "justify-start" : "justify-end"}`}
    >
      <div
        className={`max-w-[860px] rounded-lg border p-3 text-sm ${bubbleClass(item.role)}`}
      >
        <div className="flex items-center justify-between gap-3">
          <span className="font-medium">{item.title}</span>
          <span className="shrink-0 text-xs opacity-70">
            {item.sequence} · {timeAgo(item.created_at)}
          </span>
        </div>
        <div className="mt-2 whitespace-pre-wrap break-words leading-6">
          {item.body}
        </div>
        <div className="mt-2 font-mono text-xs opacity-60">
          {item.event_type}
        </div>
      </div>
    </div>
  );
}

function PermissionPanel({
  runId,
  events,
}: {
  runId: string;
  events: RuntimeEvent[];
}) {
  const queryClient = useQueryClient();
  const resolved = resolvedPermissionIds(events);
  const pending = events
    .map(extractPermissionRequest)
    .filter((request): request is NonNullable<typeof request> =>
      Boolean(request),
    )
    .filter((request) => !resolved.has(request.permission_id));
  const resolve = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: string }) =>
      runtimeApi.resolvePermission(runId, id, {
        decision,
        option_id: decision,
        reason: "resolved from web console",
      }),
    onSuccess: async () =>
      queryClient.invalidateQueries({ queryKey: ["runs", runId, "events"] }),
  });
  if (!pending.length) {
    return null;
  }
  return (
    <Card className="border-warning/40">
      <CardHeader>
        <CardTitle>Permission Requests</CardTitle>
        <Badge tone="warn">{pending.length} pending</Badge>
      </CardHeader>
      <CardBody className="grid gap-3">
        {pending.map((request) => (
          <div
            key={request.permission_id}
            className="rounded-md border border-border p-3"
          >
            <div className="font-medium">
              {request.prompt || request.tool || request.permission_id}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {(request.options?.length
                ? request.options
                : [{ id: "approve" }, { id: "deny" }]
              ).map((option) => (
                <Button
                  key={option.id}
                  size="sm"
                  variant={option.id === "deny" ? "danger" : "primary"}
                  onClick={() =>
                    resolve.mutate({
                      id: request.permission_id,
                      decision: option.id,
                    })
                  }
                >
                  {option.label || option.id}
                </Button>
              ))}
            </div>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

function MissionsPage() {
  const missions = useQuery({
    queryKey: ["missions"],
    queryFn: runtimeApi.missions,
  });
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: runtimeApi.capabilities,
  });
  return (
    <Page
      title="Missions"
      subtitle="Profile-based multi-agent task orchestration."
    >
      <div className="grid gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
        <CreateMissionForm
          adapters={Object.keys(capabilities.data?.adapters ?? { fake: {} })}
        />
        <Card>
          <CardHeader>
            <CardTitle>Mission History</CardTitle>
          </CardHeader>
          <CardBody>
            <MissionList missions={missions.data?.missions ?? []} />
          </CardBody>
        </Card>
      </div>
    </Page>
  );
}

function CreateMissionForm({ adapters }: { adapters: string[] }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const createMission = useMutation({
    mutationFn: runtimeApi.createMission,
    onSuccess: async () => {
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["missions"] });
    },
    onError: (err) => setError(String(err)),
  });
  const form = useForm({
    defaultValues: {
      adapter: adapters.includes("qwen") ? "qwen" : adapters[0] || "fake",
      strategy: "sequential",
      goal: "Inspect the runtime, run validation, review risks, and produce a final report.",
    },
    onSubmit: async ({ value }) => createMission.mutateAsync(value),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Create Mission</CardTitle>
        <Badge tone="info">DAG</Badge>
      </CardHeader>
      <CardBody>
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            event.stopPropagation();
            void form.handleSubmit();
          }}
        >
          <form.Field name="goal">
            {(field) => (
              <Field label="Goal">
                <Textarea
                  value={field.state.value}
                  onChange={(event) => field.handleChange(event.target.value)}
                />
              </Field>
            )}
          </form.Field>
          <div className="grid gap-3 md:grid-cols-2">
            <form.Field name="strategy">
              {(field) => (
                <Field label="Strategy">
                  <Select
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                  >
                    <option value="sequential">sequential</option>
                    <option value="fanout">fanout</option>
                  </Select>
                </Field>
              )}
            </form.Field>
            <form.Field name="adapter">
              {(field) => (
                <Field label="Adapter">
                  <Select
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                  >
                    {adapters.map((adapter) => (
                      <option key={adapter} value={adapter}>
                        {adapter}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
            </form.Field>
          </div>
          {error ? (
            <div className="rounded-md border border-destructive/30 p-3 text-sm text-destructive">
              {error}
            </div>
          ) : null}
          <Button
            disabled={createMission.isPending}
            type="submit"
            variant="primary"
          >
            <Play className="h-4 w-4" />
            Start
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function ProfilesPage() {
  const profiles = useQuery({
    queryKey: ["profiles"],
    queryFn: runtimeApi.profiles,
  });
  return (
    <Page
      title="Profiles"
      subtitle="Reusable Agent roles and execution policies."
    >
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(profiles.data?.profiles ?? []).map((profile) => (
          <Card key={`${profile.id}-${profile.version}`}>
            <CardHeader>
              <div>
                <CardTitle>{profile.display_name}</CardTitle>
                <div className="mt-1 font-mono text-xs text-muted-foreground">
                  {profile.id}
                </div>
              </div>
              <Badge tone={profile.source === "system" ? "info" : "neutral"}>
                v{profile.version}
              </Badge>
            </CardHeader>
            <CardBody className="grid gap-3">
              <p className="text-sm text-muted-foreground">
                {profile.description}
              </p>
              <ProfileJson label="Runtime" value={profile.runtime} />
              <ProfileJson label="Tools" value={profile.tools} />
              <ProfileJson label="Approval" value={profile.approval} />
            </CardBody>
          </Card>
        ))}
      </div>
    </Page>
  );
}

function OperationsPage() {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["ops", "status"],
    queryFn: runtimeApi.opsStatus,
  });
  const drills = useQuery({
    queryKey: ["ops", "drills"],
    queryFn: runtimeApi.drills,
  });
  const backups = useQuery({
    queryKey: ["ops", "backups"],
    queryFn: runtimeApi.backups,
  });
  const p5 = useQuery({ queryKey: ["p5"], queryFn: runtimeApi.p5Evaluations });
  const createBackup = useMutation({
    mutationFn: runtimeApi.createBackup,
    onSuccess: async () =>
      queryClient.invalidateQueries({ queryKey: ["ops", "backups"] }),
  });
  const runDrills = useMutation({
    mutationFn: runtimeApi.runDrills,
    onSuccess: async () =>
      queryClient.invalidateQueries({ queryKey: ["ops", "drills"] }),
  });
  const checks = (drills.data?.checks ?? []) as DrillCheck[];
  return (
    <Page
      title="Operations"
      subtitle="P5 protocol decisions and P6 beta readiness controls."
    >
      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <Card>
          <CardHeader>
            <CardTitle>Failure Drills</CardTitle>
            <Button
              size="sm"
              variant="primary"
              onClick={() => runDrills.mutate()}
            >
              <ShieldCheck className="h-4 w-4" />
              Run
            </Button>
          </CardHeader>
          <CardBody className="grid gap-2">
            {checks.map((check) => (
              <div
                key={check.id}
                className="grid gap-2 rounded-md border border-border p-3 md:grid-cols-[160px_100px_1fr]"
              >
                <span className="font-mono text-xs">{check.id}</span>
                <StatusBadge status={check.status} />
                <span className="text-sm text-muted-foreground">
                  {check.summary}
                </span>
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Backups</CardTitle>
            <Button
              disabled={createBackup.isPending}
              size="sm"
              onClick={() => createBackup.mutate()}
            >
              <Download className="h-4 w-4" />
              Create
            </Button>
          </CardHeader>
          <CardBody className="grid gap-2">
            {(backups.data?.backups ?? []).map((backup) => (
              <a
                key={backup.name}
                className="rounded-md border border-border p-3 text-sm hover:bg-muted"
                href={backupHref(backup.name)}
              >
                <div className="font-medium">{backup.name}</div>
                <div className="text-xs text-muted-foreground">
                  {formatBytes(backup.size_bytes)}
                </div>
              </a>
            ))}
            {!backups.data?.backups.length ? (
              <EmptyState title="No backups yet" />
            ) : null}
          </CardBody>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>P5 Evaluations</CardTitle>
          </CardHeader>
          <CardBody className="grid gap-2">
            {(p5.data?.components ?? []).map((component) => (
              <div
                key={component.id}
                className="rounded-md border border-border p-3"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">{component.id}</span>
                  <StatusBadge status={component.status} />
                </div>
                <div className="mt-2 text-sm text-muted-foreground">
                  {component.decision}
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Runtime Status</CardTitle>
          </CardHeader>
          <CardBody>
            <pre className="max-h-[420px] overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
              {JSON.stringify(status.data ?? {}, null, 2)}
            </pre>
          </CardBody>
        </Card>
      </div>
    </Page>
  );
}

function RunList({ runs }: { runs: RunState[] }) {
  if (!runs.length) {
    return (
      <EmptyState
        title="No runs"
        detail="Create the first SAEU run from the form."
      />
    );
  }
  return (
    <div className="grid gap-2">
      {runs.map((run) => (
        <Link
          key={run.run_id}
          className="grid gap-2 rounded-md border border-border p-3 hover:bg-muted"
          to="/runs/$runId"
          params={{ runId: run.run_id }}
        >
          <div className="flex items-center justify-between gap-3">
            <span className="truncate font-mono text-xs">{run.run_id}</span>
            <StatusBadge status={run.status} />
          </div>
          <div className="line-clamp-2 text-sm text-muted-foreground">
            {run.spec.prompt || run.spec.adapter}
          </div>
        </Link>
      ))}
    </div>
  );
}

function RecentRuns({ runs }: { runs: RunState[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent Runs</CardTitle>
        <Link className="text-sm text-primary" to="/runs">
          View all
        </Link>
      </CardHeader>
      <CardBody>
        <RunList runs={runs.slice(0, 5)} />
      </CardBody>
    </Card>
  );
}

function MissionList({ missions }: { missions: MissionState[] }) {
  if (!missions.length) {
    return (
      <EmptyState
        title="No missions"
        detail="Create a mission to fan out work across profiles."
      />
    );
  }
  return (
    <div className="grid gap-3">
      {missions.map((mission) => (
        <div
          key={mission.mission_id}
          className="rounded-md border border-border p-3"
        >
          <div className="flex items-center justify-between gap-3">
            <span className="truncate font-mono text-xs">
              {mission.mission_id}
            </span>
            <StatusBadge status={mission.status} />
          </div>
          <div className="mt-2 text-sm">{mission.spec.goal}</div>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {mission.tasks.map((task) => (
              <div
                key={task.task_id}
                className="rounded-md bg-muted p-2 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{task.title}</span>
                  <StatusBadge status={task.status} />
                </div>
                <div className="mt-1 text-muted-foreground">
                  {task.profile_id}
                </div>
                {task.run_id ? (
                  <Link
                    className="mt-1 block text-primary"
                    to="/runs/$runId"
                    params={{ runId: task.run_id }}
                  >
                    {task.run_id}
                  </Link>
                ) : null}
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <LinkButton
              href={missionArtifactHref(mission.mission_id, "manifest.json")}
              size="sm"
            >
              <Download className="h-4 w-4" />
              Manifest
            </LinkButton>
            <LinkButton
              href={missionArtifactHref(mission.mission_id, "final-report.md")}
              size="sm"
            >
              <Download className="h-4 w-4" />
              Report
            </LinkButton>
          </div>
        </div>
      ))}
    </div>
  );
}

function RecentMissions({ missions }: { missions: MissionState[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent Missions</CardTitle>
        <Link className="text-sm text-primary" to="/missions">
          View all
        </Link>
      </CardHeader>
      <CardBody>
        <MissionList missions={missions.slice(0, 3)} />
      </CardBody>
    </Card>
  );
}

function EventList({ events }: { events: RuntimeEvent[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Event Stream</CardTitle>
        <Badge tone="neutral">{events.length}</Badge>
      </CardHeader>
      <CardBody className="grid max-h-[560px] gap-2 overflow-auto">
        {events.map((event) => (
          <div key={event.id} className="rounded-md border border-border p-3">
            <div className="flex items-center justify-between gap-3">
              <span className="font-mono text-xs">
                {event.sequence}. {event.type}
              </span>
              <span className="text-xs text-muted-foreground">
                {timeAgo(event.created_at)}
              </span>
            </div>
            <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-slate-950 p-2 text-xs text-slate-100">
              {JSON.stringify(event.data, null, 2)}
            </pre>
          </div>
        ))}
        {!events.length ? <EmptyState title="No events" /> : null}
      </CardBody>
    </Card>
  );
}

function ArtifactPanel({
  runId,
  artifacts,
}: {
  runId: string;
  artifacts: ArtifactInfo[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Artifacts</CardTitle>
        <Badge tone="neutral">{artifacts.length}</Badge>
      </CardHeader>
      <CardBody className="grid gap-2">
        {artifacts.map((artifact) => (
          <a
            key={artifact.name}
            className="rounded-md border border-border p-3 text-sm hover:bg-muted"
            href={artifactHref(runId, artifact.name)}
          >
            <div className="font-medium">{artifact.name}</div>
            <div className="text-xs text-muted-foreground">
              {formatBytes(artifact.size_bytes)}
            </div>
          </a>
        ))}
        {!artifacts.length ? <EmptyState title="No artifacts yet" /> : null}
      </CardBody>
    </Card>
  );
}

function ProfileJson({
  label,
  value,
}: {
  label: string;
  value: Record<string, unknown>;
}) {
  return (
    <details className="rounded-md border border-border p-2">
      <summary className="cursor-pointer text-sm font-medium">{label}</summary>
      <pre className="mt-2 max-h-44 overflow-auto rounded-md bg-slate-950 p-2 text-xs text-slate-100">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function Page({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">{title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
      </div>
      {children}
    </div>
  );
}

function statusLine(statuses?: Record<string, number>) {
  if (!statuses) {
    return "-";
  }
  const text = Object.entries(statuses)
    .map(([status, count]) => `${status} ${count}`)
    .join(" / ");
  return text || "none";
}

function formatBytes(value: number) {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function timeAgo(value?: string) {
  if (!value) {
    return "-";
  }
  const delta = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(delta)) {
    return value;
  }
  const seconds = Math.max(0, Math.round(delta / 1000));
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  return `${Math.round(minutes / 60)}h ago`;
}

function emptyToNull(value: string) {
  return value.trim() ? value.trim() : null;
}

function mergeEvents(current: RuntimeEvent[], incoming: RuntimeEvent[]) {
  if (!incoming.length) {
    return current;
  }
  const bySequence = new Map<number, RuntimeEvent>();
  for (const event of [...current, ...incoming]) {
    bySequence.set(event.sequence, event);
  }
  const merged = [...bySequence.values()].sort(
    (left, right) => left.sequence - right.sequence,
  );
  if (
    merged.length === current.length &&
    merged.every((event, index) => event.id === current[index]?.id)
  ) {
    return current;
  }
  return merged;
}

function runnerTranscript(events: RuntimeEvent[]): RunnerTranscriptItem[] {
  const items: RunnerTranscriptItem[] = [];
  const agentMessages = new Map<string, RunnerTranscriptItem>();

  for (const event of events) {
    if (event.type === "message.delta") {
      const promptNumber = stringValue(event.data.prompt_number) ?? "current";
      const key = `agent-${promptNumber}`;
      const text = stringValue(event.data.text) ?? "";
      const existing = agentMessages.get(key);
      if (existing) {
        existing.body = `${existing.body}${text}`;
        existing.sequence = event.sequence;
        existing.created_at = event.created_at;
      } else {
        const item: RunnerTranscriptItem = {
          id: key,
          role: "agent",
          title:
            `Agent output ${promptNumber === "current" ? "" : `#${promptNumber}`}`.trim(),
          body: text,
          created_at: event.created_at,
          event_type: event.type,
          sequence: event.sequence,
        };
        agentMessages.set(key, item);
        items.push(item);
      }
      continue;
    }

    const item = transcriptItemForEvent(event);
    if (item) {
      items.push(item);
    }
  }

  return items.sort((left, right) => left.sequence - right.sequence);
}

function transcriptItemForEvent(
  event: RuntimeEvent,
): RunnerTranscriptItem | null {
  const base = {
    id: event.id,
    created_at: event.created_at,
    event_type: event.type,
    sequence: event.sequence,
  };
  switch (event.type) {
    case "run.created":
      return {
        ...base,
        role: "system",
        title: "Run accepted",
        body: "The control plane created the run and stored its request.",
      };
    case "workspace.prepared":
      return {
        ...base,
        role: "system",
        title: "Workspace ready",
        body: `${stringValue(event.data.strategy) ?? "workspace"} · ${stringValue(event.data.path) ?? "prepared"}`,
      };
    case "resources.resolved":
      return {
        ...base,
        role: "system",
        title: "Resources assigned",
        body: compactJson(event.data),
      };
    case "run.queued":
      return {
        ...base,
        role: "system",
        title: "Queued",
        body: "Waiting for an available runner.",
      };
    case "lease.claimed":
      return {
        ...base,
        role: "system",
        title: "Runner claimed",
        body: `Worker ${stringValue(event.data.worker_id) ?? "unknown"} started the lease.`,
      };
    case "run.started":
      return {
        ...base,
        role: "success",
        title: "Runner started",
        body:
          stringValue(event.data.workspace) ??
          stringValue(event.data.adapter) ??
          "Session is active.",
      };
    case "input.accepted":
      return {
        ...base,
        role: "operator",
        title: "Prompt submitted",
        body:
          stringValue(event.data.prompt_preview) ??
          `Prompt #${event.data.prompt_number ?? 1}`,
      };
    case "step.started":
      return {
        ...base,
        role: "system",
        title: "Step started",
        body: stepBody(event),
      };
    case "step.submitted":
      return {
        ...base,
        role: "system",
        title: "Prompt accepted by runner",
        body: stepBody(event),
      };
    case "step.completed":
      return {
        ...base,
        role: "success",
        title: "Step completed",
        body: stepBody(event),
      };
    case "permission.requested":
      return {
        ...base,
        role: "warning",
        title: "Permission required",
        body: permissionBody(event),
      };
    case "permission.resolved":
      return {
        ...base,
        role: "success",
        title: "Permission resolved",
        body: `Decision: ${stringValue(event.data.decision) ?? "recorded"}`,
      };
    case "permission.stalled":
      return {
        ...base,
        role: "warning",
        title: "Permission stalled",
        body: compactJson(event.data),
      };
    case "stream.warning":
    case "cancel.warning":
      return {
        ...base,
        role: "warning",
        title: "Runner warning",
        body: compactJson(event.data),
      };
    case "run.completed":
      return {
        ...base,
        role: "success",
        title: "Run completed",
        body:
          stringValue(event.data.final_artifact) ??
          "The runner reached a terminal success state.",
      };
    case "run.failed":
      return {
        ...base,
        role: "error",
        title: "Run failed",
        body: failureBody(event),
      };
    case "run.cancelled":
      return {
        ...base,
        role: "warning",
        title: "Run cancelled",
        body: compactJson(event.data),
      };
    default:
      if (event.type.endsWith(".failed") || event.type.includes("error")) {
        return {
          ...base,
          role: "error",
          title: event.type,
          body: compactJson(event.data),
        };
      }
      return null;
  }
}

function stepBody(event: RuntimeEvent) {
  return `Prompt #${event.data.prompt_number ?? "current"}`;
}

function permissionBody(event: RuntimeEvent) {
  const request = extractPermissionRequest(event);
  return request?.prompt ?? request?.tool ?? compactJson(event.data);
}

function failureBody(event: RuntimeEvent) {
  return stringValue(event.data.reason) ?? compactJson(event.data);
}

function compactJson(value: unknown) {
  if (!value || typeof value !== "object") {
    return String(value ?? "");
  }
  return JSON.stringify(value, null, 2);
}

function stringValue(value: unknown) {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number") {
    return String(value);
  }
  return undefined;
}

function connectionTone(status: LiveConnectionStatus) {
  if (status === "live") {
    return "ok";
  }
  if (status === "reconnecting" || status === "fallback") {
    return "warn";
  }
  return "neutral";
}

function connectionLabel(status: LiveConnectionStatus) {
  const labels: Record<LiveConnectionStatus, string> = {
    closed: "closed",
    connecting: "connecting",
    fallback: "polling",
    live: "live",
    reconnecting: "reconnecting",
  };
  return labels[status];
}

function bubbleClass(role: RunnerTranscriptItem["role"]) {
  const classes: Record<RunnerTranscriptItem["role"], string> = {
    agent: "border-primary/30 bg-background",
    error: "border-destructive/30 bg-destructive/10 text-destructive",
    operator: "border-sky-500/30 bg-sky-500/10",
    success: "border-success/30 bg-success/10",
    system: "border-border bg-card",
    warning: "border-warning/30 bg-warning/10",
  };
  return classes[role];
}

function isTerminalEvent(eventType: string) {
  return ["run.completed", "run.failed", "run.cancelled"].includes(eventType);
}

function isTerminal(status?: string) {
  return Boolean(
    status && ["completed", "failed", "cancelled"].includes(status),
  );
}

export const __testUtils = {
  bubbleClass,
  connectionLabel,
  connectionTone,
  emptyToNull,
  formatBytes,
  isTerminalEvent,
  mergeEvents,
  runnerTranscript,
  isTerminal,
  statusLine,
  timeAgo,
};
