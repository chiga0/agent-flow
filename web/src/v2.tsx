import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  Bot,
  Boxes,
  Brain,
  CheckCircle2,
  Clock3,
  GitBranch,
  Layers3,
  ListChecks,
  MessageSquare,
  Network,
  RadioTower,
  RefreshCw,
  Route,
  Send,
  ShieldCheck,
  Smartphone,
  TerminalSquare,
  Zap,
} from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

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
  Metric,
  StatusBadge,
  Textarea,
} from "./components/ui";
import {
  runtimeApi,
  type V2AdminOverview,
  type V2AgentTask,
  type V2Event,
  type V2Task,
} from "./lib/api";

const modeOptions = [
  {
    value: "auto",
    label: "Auto",
    detail: "balanced",
    icon: <Zap className="h-4 w-4" />,
  },
  {
    value: "workflow",
    label: "Workflow",
    detail: "DAG",
    icon: <Route className="h-4 w-4" />,
  },
  {
    value: "multi-agent",
    label: "Multi-agent",
    detail: "brain + workers",
    icon: <Layers3 className="h-4 w-4" />,
  },
];

const channelOptions = [
  { value: "web", label: "Web", icon: <MessageSquare className="h-4 w-4" /> },
  { value: "mobile", label: "Mobile", icon: <Smartphone className="h-4 w-4" /> },
  { value: "dingtalk", label: "DingTalk", icon: <RadioTower className="h-4 w-4" /> },
  { value: "feishu", label: "Feishu", icon: <RadioTower className="h-4 w-4" /> },
  { value: "wecom", label: "WeCom", icon: <RadioTower className="h-4 w-4" /> },
];

const adapterOptions = [
  { value: "auto", label: "Auto", icon: <Bot className="h-4 w-4" /> },
  { value: "qwen", label: "qwen-code", icon: <TerminalSquare className="h-4 w-4" /> },
  { value: "codex", label: "codex cli", icon: <TerminalSquare className="h-4 w-4" /> },
  { value: "claude", label: "claude code", icon: <TerminalSquare className="h-4 w-4" /> },
  { value: "opencode", label: "opencode", icon: <TerminalSquare className="h-4 w-4" /> },
  { value: "fake", label: "fake", icon: <CheckCircle2 className="h-4 w-4" /> },
];

export function V2ClientPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [goal, setGoal] = useState("");
  const [mode, setMode] = useState("auto");
  const [channel, setChannel] = useState("web");
  const [adapter, setAdapter] = useState("auto");
  const tasks = useQuery({
    queryKey: ["v2", "tasks"],
    queryFn: runtimeApi.v2Tasks,
    refetchInterval: 2000,
  });
  const overview = useQuery({
    queryKey: ["v2", "admin", "overview"],
    queryFn: runtimeApi.v2AdminOverview,
    refetchInterval: 5000,
  });
  const createTask = useMutation({
    mutationFn: runtimeApi.v2CreateTask,
    onSuccess: async (task) => {
      setGoal("");
      await queryClient.invalidateQueries({ queryKey: ["v2", "tasks"] });
      await navigate({
        to: "/v2/tasks/$taskId",
        params: { taskId: task.task_id },
      });
    },
  });
  const taskItems = tasks.data?.tasks ?? [];
  const active = taskItems.filter((task) =>
    ["queued", "running"].includes(task.status),
  );
  const completed = taskItems.filter((task) => task.status === "completed");
  const recent = taskItems.slice(0, 6);
  const channels = overview.data?.channels ?? [];
  const units = overview.data?.execution_units ?? [];
  const availableAdapters = Array.from(
    new Set(units.flatMap((unit) => unit.adapters)),
  );

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!goal.trim()) {
      return;
    }
    createTask.mutate({
      goal: goal.trim(),
      mode,
      channel,
      adapter,
      metadata: { product_surface: "v2-client" },
    });
  };

  return (
    <div className="mx-auto grid w-full max-w-7xl gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-primary">AgentFlow V2</div>
          <h1 className="mt-1 text-3xl font-semibold tracking-normal">
            Client Workspace
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={active.length ? "warn" : "ok"}>
            {active.length ? `${active.length} active` : "ready"}
          </Badge>
          <Link
            className="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm font-medium hover:bg-muted"
            to="/v2/admin"
          >
            <ShieldCheck className="h-4 w-4" />
            Admin
          </Link>
        </div>
      </div>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <form
          aria-label="New Task"
          className="grid gap-4 rounded-lg border border-border bg-card p-4"
          onSubmit={submit}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <div className="grid h-9 w-9 place-items-center rounded-md border border-border bg-background">
                <Brain className="h-4 w-4 text-primary" />
              </div>
              <div>
                <div className="text-sm font-semibold">New Task</div>
                <div className="text-xs text-muted-foreground">
                  {modeLabel(mode)} · {channelLabel(channel)} · {adapterLabel(adapter)}
                </div>
              </div>
            </div>
            <Button
              disabled={createTask.isPending || !goal.trim()}
              type="submit"
              variant="primary"
            >
              <Send className="h-4 w-4" />
              {createTask.isPending ? "Starting" : "Start"}
            </Button>
          </div>

          <Field label="Goal">
            <Textarea
              className="min-h-44 resize-y text-base"
              placeholder="Describe the outcome you want. The platform will choose a plan, agents, runtime, and artifacts."
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
            />
          </Field>

          <div className="grid gap-3 border-t border-border pt-4">
            <fieldset className="grid gap-2">
              <legend className="text-sm font-medium">Mode</legend>
              <div className="grid gap-2 md:grid-cols-3">
                {modeOptions.map((option) => (
                  <OptionButton
                    key={option.value}
                    active={mode === option.value}
                    detail={option.detail}
                    icon={option.icon}
                    label={option.label}
                    onClick={() => setMode(option.value)}
                  />
                ))}
              </div>
            </fieldset>

            <fieldset className="grid gap-2">
              <legend className="text-sm font-medium">Channel</legend>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                {channelOptions.map((option) => (
                  <OptionButton
                    key={option.value}
                    active={channel === option.value}
                    compact
                    detail={channelStatus(channels, option.value)}
                    icon={option.icon}
                    label={option.label}
                    onClick={() => setChannel(option.value)}
                  />
                ))}
              </div>
            </fieldset>

            <fieldset className="grid gap-2">
              <legend className="text-sm font-medium">Agent CLI</legend>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {adapterOptions.map((option) => (
                  <OptionButton
                    key={option.value}
                    active={adapter === option.value}
                    detail={
                      option.value === "auto"
                        ? "scheduler"
                        : availableAdapters.includes(option.value)
                          ? "registered"
                          : "not discovered"
                    }
                    icon={option.icon}
                    label={option.label}
                    onClick={() => setAdapter(option.value)}
                  />
                ))}
              </div>
            </fieldset>
          </div>
        </form>

        <aside className="grid content-start gap-4">
          <div className="grid gap-3 rounded-lg border border-border bg-card p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-primary" />
                <div className="text-sm font-semibold">Workload</div>
              </div>
              <Button size="icon" variant="ghost" onClick={() => tasks.refetch()}>
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <Metric label="Active" value={active.length} detail="queued/running" />
              <Metric label="Done" value={completed.length} detail="completed" />
              <Metric label="Units" value={units.length} detail="registered" />
            </div>
          </div>

          <ChannelReadiness channels={channels} />

          <div className="grid gap-3 rounded-lg border border-border bg-card p-4">
            <div className="flex items-center gap-2">
              <RadioTower className="h-4 w-4 text-primary" />
              <div className="text-sm font-semibold">Dispatch Trust</div>
            </div>
            <div className="grid gap-2 text-sm">
              <TrustRow label="Idempotency" value="enabled" />
              <TrustRow label="Events" value="canonical" />
              <TrustRow label="Recovery" value="background runner" />
            </div>
          </div>
        </aside>
      </section>

      <section className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ListChecks className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold">Task Track</h2>
          </div>
          <Badge tone="neutral">{taskItems.length} total</Badge>
        </div>
        <TaskGrid tasks={recent} />
      </section>
    </div>
  );
}

function OptionButton({
  active,
  compact,
  detail,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  compact?: boolean;
  detail: ReactNode;
  icon: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={[
        "flex min-h-14 items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors",
        active
          ? "border-primary bg-primary/10 text-foreground"
          : "border-border bg-background hover:bg-muted",
        compact ? "min-h-12" : "",
      ].join(" ")}
      type="button"
      onClick={onClick}
    >
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-border bg-card text-primary">
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium">{label}</span>
        <span className="block truncate text-xs text-muted-foreground">{detail}</span>
      </span>
    </button>
  );
}

function ChannelReadiness({ channels }: { channels: V2AdminOverview["channels"] }) {
  return (
    <div className="grid gap-3 rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <Smartphone className="h-4 w-4 text-primary" />
        <div className="text-sm font-semibold">Channel Ready</div>
      </div>
      <div className="grid gap-2">
        {channelOptions.map((option) => (
          <div
            key={option.value}
            className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm"
          >
            <span className="flex items-center gap-2">
              {option.icon}
              {option.label}
            </span>
            <StatusBadge status={channelStatus(channels, option.value)} />
          </div>
        ))}
      </div>
    </div>
  );
}

function TrustRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function modeLabel(value: string) {
  return modeOptions.find((option) => option.value === value)?.label ?? value;
}

function channelLabel(value: string) {
  return channelOptions.find((option) => option.value === value)?.label ?? value;
}

function adapterLabel(value: string) {
  return adapterOptions.find((option) => option.value === value)?.label ?? value;
}

function channelStatus(channels: V2AdminOverview["channels"], platform: string) {
  return (
    channels.find((channel) => channel.platform === platform)?.status ??
    (platform === "web" ? "configured" : "reserved")
  );
}

export function V2TaskPage() {
  const { taskId } = useParams({ strict: false }) as { taskId: string };
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const task = useQuery({
    queryKey: ["v2", "tasks", taskId],
    queryFn: () => runtimeApi.v2Task(taskId),
    refetchInterval: 1500,
  });
  const events = useQuery({
    queryKey: ["v2", "tasks", taskId, "events"],
    queryFn: () => runtimeApi.v2TaskEvents(taskId),
    refetchInterval: 1500,
  });
  const sendMessage = useMutation({
    mutationFn: () => runtimeApi.v2SubmitMessage(taskId, message),
    onSuccess: async () => {
      setMessage("");
      await queryClient.invalidateQueries({
        queryKey: ["v2", "tasks", taskId, "events"],
      });
    },
  });
  const current = task.data;

  return (
    <div className="mx-auto grid w-full max-w-7xl gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Link className="text-primary hover:underline" to="/v2">
              Client Workspace
            </Link>
            <Link className="text-primary hover:underline" to="/v2/admin">
              Admin
            </Link>
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-normal">
            {current?.title ?? "Task"}
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            {current?.goal ?? "Loading"}
          </p>
        </div>
        {current ? <StatusBadge status={current.status} /> : null}
      </div>

      {current ? (
        <div className="grid gap-3 md:grid-cols-4">
          <Metric label="Progress" value={`${current.progress.percent}%`} />
          <Metric label="Mode" value={current.mode} />
          <Metric label="Channel" value={current.channel} />
          <Metric label="Adapter" value={current.adapter} />
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-primary" />
              <CardTitle>Plan DAG</CardTitle>
            </div>
            {current?.plan ? <Badge tone="info">{current.plan.strategy}</Badge> : null}
          </CardHeader>
          <CardBody>
            <AgentDag agents={current?.plan?.agent_tasks ?? []} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-primary" />
              <CardTitle>Result</CardTitle>
            </div>
          </CardHeader>
          <CardBody>
            {current?.result ? (
              <div className="grid gap-3 text-sm">
                <p className="text-muted-foreground">{current.result.summary}</p>
                <StatusBadge
                  status={String(current.result.evaluation.status ?? "passed")}
                />
              </div>
            ) : (
              <EmptyState title="No result yet" detail="The task is still running." />
            )}
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-primary" />
              <CardTitle>Canonical Events</CardTitle>
            </div>
            <Badge tone="neutral">{events.data?.events.length ?? 0}</Badge>
          </CardHeader>
          <CardBody className="grid gap-3">
            <EventTimeline events={events.data?.events ?? []} />
            <form
              className="grid gap-2 border-t border-border pt-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (message.trim()) {
                  sendMessage.mutate();
                }
              }}
            >
              <Input
                placeholder="Add context or a follow-up instruction"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
              />
              <Button disabled={!message.trim() || sendMessage.isPending} type="submit">
                <Send className="h-4 w-4" />
                Send
              </Button>
            </form>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <TerminalSquare className="h-4 w-4 text-primary" />
              <CardTitle>Agent Contracts</CardTitle>
            </div>
          </CardHeader>
          <CardBody>
            <div className="grid gap-3">
              {(current?.plan?.agent_tasks ?? []).map((agent) => (
                <div
                  key={agent.agent_task_id}
                  className="grid gap-2 rounded-md border border-border p-3 text-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{agent.role}</span>
                    <StatusBadge status={agent.status} />
                  </div>
                  <p className="text-muted-foreground">{agent.goal}</p>
                  <div className="text-xs text-muted-foreground">
                    {String(agent.artifact_contract.evaluation)}
                  </div>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

export function V2AdminPage() {
  const overview = useQuery({
    queryKey: ["v2", "admin", "overview"],
    queryFn: runtimeApi.v2AdminOverview,
    refetchInterval: 3000,
  });
  const data = overview.data;
  return (
    <div className="mx-auto grid w-full max-w-7xl gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-primary">AgentFlow V2</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-normal">
            Admin Control Plane
          </h1>
        </div>
        <Link
          className="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm font-medium hover:bg-muted"
          to="/v2"
        >
          Client
        </Link>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Tasks" value={data?.tasks.total ?? 0} />
        <Metric label="Agent Tasks" value={data?.agent_tasks.total ?? 0} />
        <Metric label="Execution Units" value={data?.execution_units.length ?? 0} />
        <Metric label="Channels" value={data?.channels.length ?? 0} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <AdminStatusCard overview={data} />
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Network className="h-4 w-4 text-primary" />
              <CardTitle>Execution Units</CardTitle>
            </div>
          </CardHeader>
          <CardBody className="grid gap-3">
            {(data?.execution_units ?? []).map((unit) => (
              <div
                key={unit.unit_id}
                className="grid gap-2 rounded-md border border-border p-3 text-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{unit.unit_id}</span>
                  <StatusBadge status={unit.status} />
                </div>
                <div className="text-muted-foreground">
                  {unit.kind} · {unit.adapters.join(", ")}
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Smartphone className="h-4 w-4 text-primary" />
            <CardTitle>Channels</CardTitle>
          </div>
        </CardHeader>
        <CardBody className="grid gap-3 md:grid-cols-5">
          {(data?.channels ?? []).map((channel) => (
            <div
              key={channel.channel_id}
              className="grid gap-2 rounded-md border border-border p-3 text-sm"
            >
              <div className="font-medium">{channel.platform}</div>
              <StatusBadge status={channel.status} />
            </div>
          ))}
        </CardBody>
      </Card>
    </div>
  );
}

function TaskGrid({ tasks }: { tasks: V2Task[] }) {
  if (!tasks.length) {
    return (
      <EmptyState
        title="No tasks yet"
        detail="Create a task to see the V2 control plane run end to end."
      />
    );
  }
  return (
    <div className="grid gap-3">
      {tasks.map((task) => (
        <TaskTrackItem key={task.task_id} task={task} />
      ))}
    </div>
  );
}

function TaskTrackItem({ task }: { task: V2Task }) {
  const dispatch = task.metadata?.dispatch as Record<string, unknown> | undefined;
  const adapter = String(dispatch?.adapter ?? task.adapter);
  const unit = String(dispatch?.execution_unit_id ?? "unassigned");
  const reason = String(dispatch?.reason ?? task.plan?.strategy ?? task.mode);
  return (
    <Link
      className="grid gap-3 rounded-md border border-border bg-card p-3 hover:bg-muted md:grid-cols-[minmax(0,1fr)_220px]"
      to="/v2/tasks/$taskId"
      params={{ taskId: task.task_id }}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={task.status} />
          <Badge tone="info">{task.plan?.strategy ?? task.mode}</Badge>
          <Badge tone="neutral">{channelLabel(task.channel)}</Badge>
        </div>
        <div className="mt-2 line-clamp-1 font-medium">{task.title}</div>
        <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{task.goal}</p>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{adapterLabel(adapter)}</span>
          <ArrowRight className="h-3 w-3" />
          <span>{unit}</span>
          <span className="hidden sm:inline">·</span>
          <span className="line-clamp-1">{reason}</span>
        </div>
      </div>
      <div className="grid content-center gap-2">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Progress</span>
          <span>{task.progress.percent}%</span>
        </div>
        <ProgressBar percent={task.progress.percent} />
      </div>
    </Link>
  );
}

function AgentDag({ agents }: { agents: V2AgentTask[] }) {
  if (!agents.length) {
    return <EmptyState title="No plan yet" />;
  }
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {agents.map((agent) => (
        <div
          key={agent.agent_task_id}
          className="grid gap-2 rounded-md border border-border p-3"
        >
          <div className="flex items-center justify-between gap-2">
            <Badge tone="info">{agent.role}</Badge>
            <StatusBadge status={agent.status} />
          </div>
          <div className="font-medium">{agent.title}</div>
          <div className="text-sm text-muted-foreground">{agent.goal}</div>
          <div className="text-xs text-muted-foreground">
            Depends on: {agent.depends_on.length ? agent.depends_on.join(", ") : "none"}
          </div>
        </div>
      ))}
    </div>
  );
}

function EventTimeline({ events }: { events: V2Event[] }) {
  if (!events.length) {
    return <EmptyState title="No events yet" />;
  }
  return (
    <div className="grid gap-3">
      {events.map((event) => (
        <div
          key={event.event_id}
          className="grid grid-cols-[28px_minmax(0,1fr)] gap-3"
        >
          <div className="grid h-7 w-7 place-items-center rounded-full border border-border">
            <Clock3 className="h-3.5 w-3.5 text-primary" />
          </div>
          <div className="rounded-md border border-border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-medium">{event.type}</div>
              <Badge tone="neutral">{event.actor}</Badge>
            </div>
            <pre className="mt-2 max-h-28 overflow-auto whitespace-pre-wrap text-xs text-muted-foreground">
              {JSON.stringify(event.payload, null, 2)}
            </pre>
          </div>
        </div>
      ))}
    </div>
  );
}

function AdminStatusCard({ overview }: { overview?: V2AdminOverview }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Boxes className="h-4 w-4 text-primary" />
          <CardTitle>Reliability Spine</CardTitle>
        </div>
      </CardHeader>
      <CardBody className="grid gap-3">
        {Object.entries(overview?.reliability ?? {}).map(([key, value]) => (
          <div
            key={key}
            className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm"
          >
            <span className="text-muted-foreground">{key}</span>
            <span className="font-medium">{value}</span>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

function ProgressBar({ percent }: { percent: number }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-muted">
      <div
        className="h-full rounded-full bg-primary transition-all"
        style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
      />
    </div>
  );
}
