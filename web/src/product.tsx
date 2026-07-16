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
  Database,
  GitBranch,
  KeyRound,
  Layers3,
  MessageSquare,
  Network,
  RadioTower,
  RefreshCw,
  Route,
  Send,
  ShieldCheck,
  Smartphone,
  TerminalSquare,
  Users,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

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
  v2TaskArtifactHref,
  v2TaskAuditHref,
  v2TaskWebshellEventStreamHref,
  type DaemonEvent,
  type V2AdminOverview,
  type V2AgentTask,
  type V2Artifact,
  type V2Channel,
  type V2ChannelMessage,
  type V2Evaluation,
  type V2Event,
  type V2Replay,
  type V2Project,
  type V2ProjectMember,
  type V2Tenant,
  type V2Task,
  type V2WorkflowStep,
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

const taskTemplates = [
  "把这个需求拆成可执行计划，并输出风险清单和验收标准。",
  "生成一份本周运维巡检报告，标出异常、影响和下一步动作。",
  "审计当前项目的部署链路，给出可以直接执行的修复顺序。",
];

export function ProductClientPage() {
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
        to: "/tasks/$taskId",
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
      metadata: { product_surface: "client" },
    });
  };

  return (
    <div className="mx-auto grid w-full max-w-7xl gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-primary">aflow</div>
          <h1 className="mt-1 text-3xl font-semibold tracking-normal">
            Client Workspace
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={active.length ? "warn" : "ok"}>
            {active.length ? `${active.length} active` : "ready"}
          </Badge>
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

          <div className="flex flex-wrap gap-2">
            {taskTemplates.map((template) => (
              <button
                key={template}
                className="rounded-md border border-border px-2.5 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                type="button"
                onClick={() => setGoal(template)}
              >
                {template}
              </button>
            ))}
          </div>

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
            <TerminalSquare className="h-4 w-4 text-primary" />
            <div>
              <h2 className="text-sm font-semibold">Live Agent Chats</h2>
              <p className="text-xs text-muted-foreground">
                Open a task to follow its real-time Agent output.
              </p>
            </div>
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

type V2StreamStatus = "connecting" | "live" | "fallback" | "closed";

function useV2WebshellEvents(
  taskId: string,
  initialEvents: DaemonEvent[],
  taskStatus?: string,
) {
  const [events, setEvents] = useState<DaemonEvent[]>(initialEvents);
  const [status, setStatus] = useState<V2StreamStatus>("connecting");

  useEffect(() => {
    setEvents((current) => mergeDaemonEvents(current, initialEvents));
  }, [initialEvents]);

  useEffect(() => {
    if (taskStatus && ["completed", "failed", "cancelled"].includes(taskStatus)) {
      setStatus("closed");
      return;
    }
    if (typeof EventSource === "undefined") {
      setStatus("fallback");
      return;
    }

    setStatus("connecting");
    const source = new EventSource(v2TaskWebshellEventStreamHref(taskId));
    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as DaemonEvent;
        setEvents((current) => mergeDaemonEvents(current, [event]));
        if (event._meta?.runtimeEventType === "task.completed") {
          setStatus("closed");
          source.close();
        }
      } catch {
        setStatus("fallback");
      }
    };
    source.onopen = () => setStatus("live");
    source.onerror = () =>
      setStatus(source.readyState === EventSource.CLOSED ? "fallback" : "connecting");

    return () => source.close();
  }, [taskId, taskStatus]);

  return { events, status };
}

function mergeDaemonEvents(current: DaemonEvent[], incoming: DaemonEvent[]) {
  const merged = new Map(current.map((event) => [String(event.id), event]));
  for (const event of incoming) {
    merged.set(String(event.id), event);
  }
  return Array.from(merged.values()).sort(
    (left, right) => Number(left.id) - Number(right.id),
  );
}

export function ProductTaskPage() {
  const { taskId } = useParams({ strict: false }) as { taskId: string };
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState("all");
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
  const webshellEvents = useQuery({
    queryKey: ["v2", "tasks", taskId, "webshell-events"],
    queryFn: () => runtimeApi.v2TaskWebshellEvents(taskId),
    refetchInterval: 15000,
  });
  const workflow = useQuery({
    queryKey: ["v2", "tasks", taskId, "workflow"],
    queryFn: () => runtimeApi.v2TaskWorkflow(taskId),
    refetchInterval: 1500,
  });
  const artifacts = useQuery({
    queryKey: ["v2", "tasks", taskId, "artifacts"],
    queryFn: () => runtimeApi.v2TaskArtifacts(taskId),
    refetchInterval: 3000,
  });
  const evaluations = useQuery({
    queryKey: ["v2", "tasks", taskId, "evaluations"],
    queryFn: () => runtimeApi.v2TaskEvaluations(taskId),
    refetchInterval: 3000,
  });
  const replays = useQuery({
    queryKey: ["v2", "tasks", taskId, "replays"],
    queryFn: () => runtimeApi.v2TaskReplays(taskId),
    refetchInterval: 5000,
  });
  const liveWebshell = useV2WebshellEvents(
    taskId,
    webshellEvents.data?.events ?? [],
    task.data?.status,
  );
  const refreshTaskDetail = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["v2", "tasks"] }),
      queryClient.invalidateQueries({ queryKey: ["v2", "tasks", taskId] }),
      queryClient.invalidateQueries({ queryKey: ["v2", "tasks", taskId, "events"] }),
      queryClient.invalidateQueries({
        queryKey: ["v2", "tasks", taskId, "webshell-events"],
      }),
      queryClient.invalidateQueries({ queryKey: ["v2", "tasks", taskId, "workflow"] }),
      queryClient.invalidateQueries({ queryKey: ["v2", "tasks", taskId, "artifacts"] }),
      queryClient.invalidateQueries({
        queryKey: ["v2", "tasks", taskId, "evaluations"],
      }),
      queryClient.invalidateQueries({ queryKey: ["v2", "tasks", taskId, "replays"] }),
    ]);
  };
  const sendMessage = useMutation({
    mutationFn: () => runtimeApi.v2SubmitMessage(taskId, message),
    onSuccess: async () => {
      setMessage("");
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["v2", "tasks", taskId, "events"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["v2", "tasks", taskId, "webshell-events"],
        }),
      ]);
    },
  });
  const retryTask = useMutation({
    mutationFn: () => runtimeApi.v2RetryTask(taskId),
    onSuccess: refreshTaskDetail,
  });
  const replayTask = useMutation({
    mutationFn: () => runtimeApi.v2ReplayTask(taskId),
    onSuccess: refreshTaskDetail,
  });
  const current = task.data;
  const agents = current?.plan?.agent_tasks ?? [];
  const visibleWebshellEvents =
    selectedAgentId === "all"
      ? liveWebshell.events
      : liveWebshell.events.filter(
          (event) => String(event._meta?.agentTaskId ?? "") === selectedAgentId,
        );
  const selectedAgent = agents.find(
    (agent) => agent.agent_task_id === selectedAgentId,
  );
  const submitFollowUp = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (message.trim()) {
      sendMessage.mutate();
    }
  };

  return (
    <div className="mx-auto grid w-full max-w-7xl gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Link className="text-primary hover:underline" to="/">
              Client Workspace
            </Link>
            <Link className="text-primary hover:underline" to="/admin">
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
        <div className="flex flex-wrap items-center gap-2">
          {current ? <StatusBadge status={current.status} /> : null}
          <Button
            disabled={replayTask.isPending || !current}
            size="sm"
            variant="secondary"
            onClick={() => replayTask.mutate()}
          >
            <Clock3 className="h-4 w-4" />
            Replay
          </Button>
          <Button
            disabled={retryTask.isPending || current?.status === "running" || !current}
            size="sm"
            variant="secondary"
            onClick={() => retryTask.mutate()}
          >
            <RefreshCw className="h-4 w-4" />
            Retry
          </Button>
        </div>
      </div>

      {current ? (
        <div className="grid gap-3 md:grid-cols-5">
          <Metric label="Progress" value={`${current.progress.percent}%`} />
          <Metric label="Mode" value={current.mode} />
          <Metric label="Channel" value={current.channel} />
          <Metric label="Adapter" value={current.adapter} />
          <Metric label="Execution" value={current.execution_mode} />
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <div>
            <div className="flex items-center gap-2">
              <TerminalSquare className="h-4 w-4 text-primary" />
              <CardTitle>Agent Chat</CardTitle>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Real-time output is the primary task view. Switch Agent when the plan
              contains multiple workers.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone="info">Qwen WebShell</Badge>
            <Badge tone="neutral">DaemonEvent</Badge>
            <Badge tone={liveWebshell.status === "live" ? "ok" : "neutral"}>
              {liveWebshell.status === "live"
                ? "Live"
                : liveWebshell.status === "fallback"
                  ? "Polling fallback"
                  : liveWebshell.status === "closed"
                    ? "Stream complete"
                    : "Connecting"}
            </Badge>
          </div>
        </CardHeader>
        <CardBody className="grid gap-3">
          <AgentSwitcher
            agents={agents}
            selectedAgentId={selectedAgentId}
            onSelect={setSelectedAgentId}
          />
          <div className="flex flex-wrap items-center justify-between gap-2 px-1">
            <div className="text-sm font-medium">
              {selectedAgent ? `${selectedAgent.role} output` : "All real-time output"}
            </div>
            <span className="text-xs text-muted-foreground">
              {visibleWebshellEvents.length} events
            </span>
          </div>
          <QwenWebshellPanel
            events={visibleWebshellEvents}
            emptyDetail={
              selectedAgent
                ? `Waiting for ${selectedAgent.role} to emit output.`
                : undefined
            }
          />
          <form className="grid gap-2 border-t border-border pt-3" onSubmit={submitFollowUp}>
            <Input
              placeholder="Add context or a follow-up instruction"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">
                Sent to the task runner and mirrored into the WebShell event stream.
              </span>
              <Button disabled={!message.trim() || sendMessage.isPending} type="submit">
                <Send className="h-4 w-4" />
                Send
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>

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
                {current.result.failure ? (
                  <div className="grid gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3">
                    <div className="font-medium text-destructive">
                      {current.result.failure.reason}
                    </div>
                    <div>
                      <span className="font-medium">Impact: </span>
                      {current.result.failure.impact}
                    </div>
                    <div>
                      <span className="font-medium">Next action: </span>
                      {current.result.failure.next_action}
                    </div>
                  </div>
                ) : (
                  <p className="text-muted-foreground">{current.result.summary}</p>
                )}
                <StatusBadge
                  status={String(current.result.evaluation.status ?? "passed")}
                />
                <a
                  className="text-primary hover:underline"
                  download={`${current.task_id}-audit.json`}
                  href={v2TaskAuditHref(current.task_id)}
                >
                  Download audit bundle
                </a>
              </div>
            ) : (
              <EmptyState title="No result yet" detail="The task is still running." />
            )}
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Route className="h-4 w-4 text-primary" />
              <CardTitle>Durable Workflow</CardTitle>
            </div>
            {workflow.data?.run ? (
              <Badge tone="info">attempt {workflow.data.run.attempt}</Badge>
            ) : null}
          </CardHeader>
          <CardBody>
            <WorkflowSteps steps={workflow.data?.steps ?? []} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Boxes className="h-4 w-4 text-primary" />
              <CardTitle>Artifacts</CardTitle>
            </div>
            <Badge tone="neutral">{artifacts.data?.artifacts.length ?? 0}</Badge>
          </CardHeader>
          <CardBody>
            <ArtifactList
              artifacts={artifacts.data?.artifacts ?? []}
              taskId={taskId}
            />
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-primary" />
              <CardTitle>Evaluations</CardTitle>
            </div>
            <Badge tone="neutral">{evaluations.data?.evaluations.length ?? 0}</Badge>
          </CardHeader>
          <CardBody>
            <EvaluationList evaluations={evaluations.data?.evaluations ?? []} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <RefreshCw className="h-4 w-4 text-primary" />
              <CardTitle>Replay Snapshots</CardTitle>
            </div>
            <Badge tone="neutral">{replays.data?.replays.length ?? 0}</Badge>
          </CardHeader>
          <CardBody>
            <ReplayList replays={replays.data?.replays ?? []} />
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

function WorkflowSteps({ steps }: { steps: V2WorkflowStep[] }) {
  if (!steps.length) {
    return <EmptyState title="No workflow steps yet" />;
  }
  return (
    <div className="grid gap-3">
      {steps.map((step) => (
        <div
          key={step.step_id}
          className="grid gap-2 rounded-md border border-border p-3 text-sm"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">
              {step.order_index + 1}. {step.role}
            </span>
            <StatusBadge status={step.status} />
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span>{adapterLabel(step.adapter)}</span>
            <span>{step.agent_task_id}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function ArtifactList({ artifacts, taskId }: { artifacts: V2Artifact[]; taskId: string }) {
  if (!artifacts.length) {
    return <EmptyState title="No artifacts yet" />;
  }
  return (
    <div className="grid gap-3">
      {artifacts.map((artifact) => (
        <div
          key={artifact.artifact_id}
          className="grid gap-2 rounded-md border border-border p-3 text-sm"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">{artifact.name}</span>
            <StatusBadge status={artifact.status} />
          </div>
          <div className="break-all text-xs text-muted-foreground">
            {artifact.kind} · {artifact.ref}
          </div>
          <details className="rounded-md bg-muted p-2 text-xs">
            <summary className="cursor-pointer font-medium">Preview</summary>
            <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap">
              {JSON.stringify(artifact.content, null, 2)}
            </pre>
          </details>
          <a
            className="text-xs font-medium text-primary hover:underline"
            download={`${artifact.name}.json`}
            href={v2TaskArtifactHref(taskId, artifact.artifact_id)}
          >
            Download artifact
          </a>
        </div>
      ))}
    </div>
  );
}

function EvaluationList({ evaluations }: { evaluations: V2Evaluation[] }) {
  if (!evaluations.length) {
    return <EmptyState title="No evaluations yet" />;
  }
  return (
    <div className="grid gap-3">
      {evaluations.map((evaluation) => (
        <div
          key={evaluation.evaluation_id}
          className="grid gap-2 rounded-md border border-border p-3 text-sm"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">{evaluation.kind}</span>
            <StatusBadge status={evaluation.status} />
          </div>
          <pre className="max-h-24 overflow-auto whitespace-pre-wrap text-xs text-muted-foreground">
            {JSON.stringify(evaluation.details, null, 2)}
          </pre>
        </div>
      ))}
    </div>
  );
}

function ReplayList({ replays }: { replays: V2Replay[] }) {
  if (!replays.length) {
    return <EmptyState title="No replay snapshots yet" />;
  }
  return (
    <div className="grid gap-3">
      {replays.map((replay) => (
        <div
          key={replay.replay_id}
          className="grid gap-2 rounded-md border border-border p-3 text-sm"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">{replay.replay_id}</span>
            <StatusBadge status={replay.status} />
          </div>
          <div className="text-xs text-muted-foreground">
            {replay.requested_by} · {new Date(replay.created_at).toLocaleString()}
          </div>
        </div>
      ))}
    </div>
  );
}

export function ProductAdminPage() {
  const queryClient = useQueryClient();
  const [channelPlatform, setChannelPlatform] = useState("feishu");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [callbackToken, setCallbackToken] = useState("");
  const [outboundText, setOutboundText] = useState("aflow channel test");
  const [tenantName, setTenantName] = useState("");
  const [tenantUserEmail, setTenantUserEmail] = useState("");
  const [projectName, setProjectName] = useState("");
  const [projectMemberEmail, setProjectMemberEmail] = useState("");
  const overview = useQuery({
    queryKey: ["v2", "admin", "overview"],
    queryFn: runtimeApi.v2AdminOverview,
    refetchInterval: 3000,
  });
  const channelMessages = useQuery({
    queryKey: ["v2", "admin", "channel-messages"],
    queryFn: runtimeApi.v2ChannelMessages,
    refetchInterval: 5000,
  });
  const projects = useQuery({
    queryKey: ["v2", "admin", "projects"],
    queryFn: runtimeApi.v2Projects,
  });
  const defaultProjectMembers = useQuery({
    queryKey: ["v2", "admin", "projects", "project_default", "members"],
    queryFn: () => runtimeApi.v2ProjectMembers("project_default"),
  });
  const configureChannel = useMutation({
    mutationFn: () =>
      runtimeApi.v2ConfigureChannel(channelPlatform, {
        webhook_url: webhookUrl,
        callback_token: callbackToken,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["v2", "admin"] });
    },
  });
  const sendChannel = useMutation({
    mutationFn: () =>
      runtimeApi.v2SendChannelMessage(channelPlatform, { message: outboundText }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["v2", "admin", "channel-messages"],
      });
    },
  });
  const createTenant = useMutation({
    mutationFn: () =>
      runtimeApi.v2UpsertTenant({
        tenant_id: tenantSlug(tenantName),
        name: tenantName,
      }),
    onSuccess: async () => {
      setTenantName("");
      await queryClient.invalidateQueries({ queryKey: ["v2", "admin"] });
    },
  });
  const addTenantUser = useMutation({
    mutationFn: () =>
      runtimeApi.v2UpsertTenantUser("tenant_default", {
        email: tenantUserEmail,
        roles: ["member"],
      }),
    onSuccess: async () => {
      setTenantUserEmail("");
      await queryClient.invalidateQueries({ queryKey: ["v2", "admin"] });
    },
  });
  const createProject = useMutation({
    mutationFn: () =>
      runtimeApi.v2UpsertProject({
        project_id: tenantSlug(projectName).replace(/^tenant_/, "project_"),
        tenant_id: "tenant_default",
        name: projectName,
      }),
    onSuccess: async () => {
      setProjectName("");
      await queryClient.invalidateQueries({ queryKey: ["v2", "admin", "projects"] });
    },
  });
  const addProjectMember = useMutation({
    mutationFn: () =>
      runtimeApi.v2UpsertProjectMember("project_default", {
        email: projectMemberEmail,
        role: "member",
      }),
    onSuccess: async () => {
      setProjectMemberEmail("");
      await queryClient.invalidateQueries({
        queryKey: ["v2", "admin", "projects", "project_default", "members"],
      });
    },
  });
  const discoverUnits = useMutation({
    mutationFn: runtimeApi.v2DiscoverExecutionUnits,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["v2", "admin"] });
    },
  });
  const data = overview.data;
  return (
    <div className="mx-auto grid w-full max-w-7xl gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-primary">aflow</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-normal">
            Admin Control Plane
          </h1>
        </div>
        <Link
          className="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm font-medium hover:bg-muted"
          to="/"
        >
          Client
        </Link>
      </div>

        <div className="grid gap-3 md:grid-cols-5">
        <Metric label="Tasks" value={data?.tasks.total ?? 0} />
        <Metric label="Agent Tasks" value={data?.agent_tasks.total ?? 0} />
        <Metric label="Execution Units" value={data?.execution_units.length ?? 0} />
        <Metric label="Tenants" value={data?.tenants.length ?? 0} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <AdminStatusCard overview={data} />
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Network className="h-4 w-4 text-primary" />
                <CardTitle>Execution Units</CardTitle>
              </div>
              <Button
                className="h-8 px-3 text-xs"
                onClick={() => discoverUnits.mutate()}
                disabled={discoverUnits.isPending}
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Discover
              </Button>
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

      <ProjectMembershipCard
        projects={projects.data?.projects ?? []}
        members={defaultProjectMembers.data?.members ?? []}
        projectName={projectName}
        memberEmail={projectMemberEmail}
        busy={createProject.isPending || addProjectMember.isPending}
        onProjectName={setProjectName}
        onMemberEmail={setProjectMemberEmail}
        onCreateProject={() => createProject.mutate()}
        onAddMember={() => addProjectMember.mutate()}
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <HaStatusCard overview={data} />
        <TenantAdminCard
          tenants={data?.tenants ?? []}
          tenantName={tenantName}
          tenantUserEmail={tenantUserEmail}
          onTenantName={setTenantName}
          onTenantUserEmail={setTenantUserEmail}
          onCreateTenant={() => createTenant.mutate()}
          onAddTenantUser={() => addTenantUser.mutate()}
          busy={createTenant.isPending || addTenantUser.isPending}
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Smartphone className="h-4 w-4 text-primary" />
            <CardTitle>Channels</CardTitle>
          </div>
        </CardHeader>
        <CardBody className="grid gap-4">
          <ChannelConfigPanel
            channels={data?.channels ?? []}
            messages={channelMessages.data?.messages ?? []}
            platform={channelPlatform}
            webhookUrl={webhookUrl}
            callbackToken={callbackToken}
            outboundText={outboundText}
            onPlatform={setChannelPlatform}
            onWebhookUrl={setWebhookUrl}
            onCallbackToken={setCallbackToken}
            onOutboundText={setOutboundText}
            onConfigure={() => configureChannel.mutate()}
            onSend={() => sendChannel.mutate()}
            busy={configureChannel.isPending || sendChannel.isPending}
          />
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
        detail="Create a task to see the control plane run end to end."
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
      to="/tasks/$taskId"
      params={{ taskId: task.task_id }}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={task.status} />
          <Badge tone="info">{task.plan?.strategy ?? task.mode}</Badge>
          <Badge tone="neutral">{channelLabel(task.channel)}</Badge>
          <Badge tone={task.execution_mode === "real-cli" ? "ok" : "neutral"}>
            {task.execution_mode}
          </Badge>
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
        <div className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary">
          <TerminalSquare className="h-3.5 w-3.5" />
          Open live chat
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

function AgentSwitcher({
  agents,
  selectedAgentId,
  onSelect,
}: {
  agents: V2AgentTask[];
  selectedAgentId: string;
  onSelect: (agentId: string) => void;
}) {
  if (!agents.length) {
    return null;
  }
  return (
    <div aria-label="Agent switcher" className="flex gap-2 overflow-x-auto pb-1">
      <button
        className={`flex shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-sm ${
          selectedAgentId === "all"
            ? "border-primary bg-primary/10"
            : "border-border bg-background hover:bg-muted"
        }`}
        type="button"
        onClick={() => onSelect("all")}
      >
        <Layers3 className="h-4 w-4 text-primary" />
        All output
      </button>
      {agents.map((agent) => (
        <button
          key={agent.agent_task_id}
          className={`flex shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-sm ${
            selectedAgentId === agent.agent_task_id
              ? "border-primary bg-primary/10"
              : "border-border bg-background hover:bg-muted"
          }`}
          type="button"
          onClick={() => onSelect(agent.agent_task_id)}
        >
          <Bot className="h-4 w-4 text-primary" />
          <span className="font-medium">{agent.role}</span>
          <StatusBadge status={agent.status} />
        </button>
      ))}
    </div>
  );
}

function QwenWebshellPanel({
  events,
  emptyDetail,
}: {
  events: DaemonEvent[];
  emptyDetail?: string;
}) {
  const outputRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const output = outputRef.current;
    if (output) {
      output.scrollTop = output.scrollHeight;
    }
  }, [events]);
  if (!events.length) {
    return (
      <div
        aria-label="Real-time Agent output"
        className="grid min-h-[55vh] place-items-center rounded-md border border-border bg-muted/20 p-4"
      >
        <EmptyState
          title="No WebShell events yet"
          detail={
            emptyDetail ??
            "The agent transcript will appear here as soon as the task runner emits user, agent, tool, or status events."
          }
        />
      </div>
    );
  }
  return (
    <div
      ref={outputRef}
      aria-label="Real-time Agent output"
      className="grid max-h-[68vh] min-h-[55vh] content-start gap-3 overflow-auto rounded-md border border-border bg-muted/20 p-3"
    >
      {events.map((event) => {
        const update = event.data?.update as
          | {
              sessionUpdate?: string;
              content?: { text?: string };
            }
          | undefined;
        const kind = String(update?.sessionUpdate ?? "session_update");
        const text = String(update?.content?.text ?? "");
        const isUser = kind.includes("user");
        const agentRole = String(event._meta?.agentRole ?? "agent");
        return (
          <div
            key={String(event.id)}
            className={`flex ${isUser ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[78%] rounded-md border px-3 py-2 text-sm ${
                isUser ? "border-primary bg-primary text-primary-foreground" : "bg-card"
              }`}
            >
              <div className="mb-1 text-[11px] opacity-75">
                {isUser ? "you" : agentRole} · {kind}
              </div>
              <div className="whitespace-pre-wrap">{text || "..."}</div>
            </div>
          </div>
        );
      })}
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

function HaStatusCard({ overview }: { overview?: V2AdminOverview }) {
  const ha = overview?.ha;
  const workflow = ha?.workflow;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-primary" />
          <CardTitle>HA Runtime</CardTitle>
        </div>
      </CardHeader>
      <CardBody className="grid gap-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <Metric label="Profile" value={String(ha?.profile ?? "local")} />
          <Metric
            label="Database"
            value={String(ha?.database?.driver ?? "sqlite")}
            detail={ha?.database?.configured ? "configured" : "local"}
          />
          <Metric
            label="Queue"
            value={String(ha?.queue?.driver ?? "sqlite")}
            detail={ha?.queue?.configured ? "configured" : "local"}
          />
        </div>
        <div className="rounded-md border border-border p-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="font-medium">Workflow Engine</span>
            <Badge tone="info">{String(workflow?.active_engine ?? "local")}</Badge>
          </div>
          <div className="mt-2 grid gap-2">
            {(workflow?.engines ?? []).map((engine) => (
              <div
                key={String(engine.engine)}
                className="flex items-center justify-between gap-3 text-xs text-muted-foreground"
              >
                <span>{String(engine.engine)}</span>
                <StatusBadge status={String(engine.status)} />
              </div>
            ))}
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

function TenantAdminCard({
  tenants,
  tenantName,
  tenantUserEmail,
  onTenantName,
  onTenantUserEmail,
  onCreateTenant,
  onAddTenantUser,
  busy,
}: {
  tenants: V2Tenant[];
  tenantName: string;
  tenantUserEmail: string;
  onTenantName: (value: string) => void;
  onTenantUserEmail: (value: string) => void;
  onCreateTenant: () => void;
  onAddTenantUser: () => void;
  busy: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-primary" />
          <CardTitle>Tenant Admin</CardTitle>
        </div>
      </CardHeader>
      <CardBody className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <Field label="Tenant name">
            <Input
              value={tenantName}
              onChange={(event) => onTenantName(event.target.value)}
              placeholder="Acme"
            />
          </Field>
          <Button
            className="self-end"
            onClick={onCreateTenant}
            disabled={busy || !tenantName.trim()}
          >
            <KeyRound className="h-4 w-4" />
            Create
          </Button>
        </div>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <Field label="Default tenant user">
            <Input
              value={tenantUserEmail}
              onChange={(event) => onTenantUserEmail(event.target.value)}
              placeholder="member@example.com"
            />
          </Field>
          <Button
            className="self-end"
            onClick={onAddTenantUser}
            disabled={busy || !tenantUserEmail.trim()}
          >
            <Users className="h-4 w-4" />
            Add
          </Button>
        </div>
        <div className="grid gap-2">
          {tenants.map((tenant) => (
            <div
              key={tenant.tenant_id}
              className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm"
            >
              <span className="font-medium">{tenant.name}</span>
              <StatusBadge status={tenant.status} />
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

function ProjectMembershipCard({
  projects,
  members,
  projectName,
  memberEmail,
  busy,
  onProjectName,
  onMemberEmail,
  onCreateProject,
  onAddMember,
}: {
  projects: V2Project[];
  members: V2ProjectMember[];
  projectName: string;
  memberEmail: string;
  busy: boolean;
  onProjectName: (value: string) => void;
  onMemberEmail: (value: string) => void;
  onCreateProject: () => void;
  onAddMember: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-primary" />
          <CardTitle>Project Membership</CardTitle>
        </div>
        <Badge tone="neutral">{projects.length} projects</Badge>
      </CardHeader>
      <CardBody className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <Field label="Project name">
            <Input
              value={projectName}
              onChange={(event) => onProjectName(event.target.value)}
              placeholder="Platform Team"
            />
          </Field>
          <Button
            className="self-end"
            disabled={busy || !projectName.trim()}
            onClick={onCreateProject}
          >
            Create project
          </Button>
        </div>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <Field label="Default project member">
            <Input
              value={memberEmail}
              onChange={(event) => onMemberEmail(event.target.value)}
              placeholder="teammate@example.com"
            />
          </Field>
          <Button
            className="self-end"
            disabled={busy || !memberEmail.trim()}
            onClick={onAddMember}
          >
            Share project
          </Button>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {members.map((member) => (
            <div
              className="flex items-center justify-between rounded-md border border-border p-3 text-sm"
              key={member.user_id}
            >
              <span>{member.user_id}</span>
              <Badge tone="info">{member.role}</Badge>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

function ChannelConfigPanel({
  channels,
  messages,
  platform,
  webhookUrl,
  callbackToken,
  outboundText,
  onPlatform,
  onWebhookUrl,
  onCallbackToken,
  onOutboundText,
  onConfigure,
  onSend,
  busy,
}: {
  channels: V2Channel[];
  messages: V2ChannelMessage[];
  platform: string;
  webhookUrl: string;
  callbackToken: string;
  outboundText: string;
  onPlatform: (value: string) => void;
  onWebhookUrl: (value: string) => void;
  onCallbackToken: (value: string) => void;
  onOutboundText: (value: string) => void;
  onConfigure: () => void;
  onSend: () => void;
  busy: boolean;
}) {
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-5">
        {channelOptions.map((option) => (
          <button
            key={option.value}
            className={`grid gap-2 rounded-md border p-3 text-left text-sm ${
              platform === option.value
                ? "border-primary bg-primary/5"
                : "border-border hover:bg-muted"
            }`}
            onClick={() => onPlatform(option.value)}
          >
            <span className="font-medium">{option.label}</span>
            <StatusBadge status={channelStatus(channels, option.value)} />
          </button>
        ))}
      </div>
      <div className="grid gap-3 lg:grid-cols-[1fr_1fr_auto]">
        <Field label="Webhook URL">
          <Input
            value={webhookUrl}
            onChange={(event) => onWebhookUrl(event.target.value)}
            placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
          />
        </Field>
        <Field label="Callback token">
          <Input
            value={callbackToken}
            onChange={(event) => onCallbackToken(event.target.value)}
            placeholder="shared callback token"
          />
        </Field>
        <Button className="self-end" onClick={onConfigure} disabled={busy}>
          <ShieldCheck className="h-4 w-4" />
          Configure
        </Button>
      </div>
      <div className="grid gap-3 lg:grid-cols-[1fr_auto]">
        <Field label="Outbound test">
          <Input
            value={outboundText}
            onChange={(event) => onOutboundText(event.target.value)}
          />
        </Field>
        <Button className="self-end" onClick={onSend} disabled={busy}>
          <Send className="h-4 w-4" />
          Send
        </Button>
      </div>
      <div className="grid gap-2">
        {messages.slice(0, 6).map((message) => (
          <div
            key={message.message_id}
            className="grid gap-1 rounded-md border border-border px-3 py-2 text-sm"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">
                {message.platform} · {message.direction}
              </span>
              <StatusBadge status={message.status} />
            </div>
            <div className="text-xs text-muted-foreground">
              {message.task_id ?? message.external_message_id}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function tenantSlug(name: string) {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return slug ? `tenant_${slug}` : "tenant_new";
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
