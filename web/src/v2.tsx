import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Boxes,
  CheckCircle2,
  Clock3,
  GitBranch,
  MessageSquare,
  Network,
  RefreshCw,
  Send,
  ShieldCheck,
  Smartphone,
  TerminalSquare,
} from "lucide-react";
import { useState, type FormEvent } from "react";

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
  Select,
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

export function V2ClientPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [goal, setGoal] = useState("");
  const [mode, setMode] = useState("auto");
  const [channel, setChannel] = useState("web");
  const tasks = useQuery({
    queryKey: ["v2", "tasks"],
    queryFn: runtimeApi.v2Tasks,
    refetchInterval: 2000,
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

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!goal.trim()) {
      return;
    }
    createTask.mutate({
      goal: goal.trim(),
      mode,
      channel,
      adapter: "fake",
      metadata: { product_surface: "v2-client" },
    });
  };

  return (
    <div className="mx-auto grid w-full max-w-7xl gap-5">
      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium text-primary">AgentFlow V2</div>
              <h1 className="mt-1 text-3xl font-semibold tracking-normal">
                Client Workspace
              </h1>
            </div>
            <Link
              className="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm font-medium hover:bg-muted"
              to="/v2/admin"
            >
              <ShieldCheck className="h-4 w-4" />
              Admin
            </Link>
          </div>

          <form
            className="grid gap-3 rounded-lg border border-border bg-card p-3"
            onSubmit={submit}
          >
            <Textarea
              className="min-h-40 resize-y border-0 bg-transparent text-base focus:ring-0"
              placeholder="Describe the outcome you want. The platform will choose a plan, agents, runtime, and artifacts."
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
            />
            <div className="grid gap-2 border-t border-border pt-3 md:grid-cols-[1fr_1fr_auto]">
              <Field label="Mode">
                <Select value={mode} onChange={(event) => setMode(event.target.value)}>
                  <option value="auto">Auto</option>
                  <option value="workflow">Workflow</option>
                  <option value="multi-agent">Multi-agent</option>
                </Select>
              </Field>
              <Field label="Channel">
                <Select
                  value={channel}
                  onChange={(event) => setChannel(event.target.value)}
                >
                  <option value="web">Web</option>
                  <option value="mobile">Mobile</option>
                  <option value="dingtalk">DingTalk</option>
                  <option value="feishu">Feishu</option>
                  <option value="wecom">WeCom</option>
                </Select>
              </Field>
              <Button
                className="self-end"
                disabled={createTask.isPending || !goal.trim()}
                type="submit"
                variant="primary"
              >
                <Send className="h-4 w-4" />
                {createTask.isPending ? "Starting" : "Start"}
              </Button>
            </div>
          </form>

          <div className="grid gap-3 md:grid-cols-3">
            <Metric label="Active" value={active.length} detail="queued/running" />
            <Metric label="Completed" value={completed.length} detail="accepted results" />
            <Metric
              label="Channels"
              value="5"
              detail="web, mobile, DingTalk, Feishu, WeCom"
            />
          </div>

          <TaskGrid tasks={taskItems} />
        </div>

        <aside className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-primary" />
                <CardTitle>Live Work</CardTitle>
              </div>
              <Button size="icon" variant="ghost" onClick={() => tasks.refetch()}>
                <RefreshCw className="h-4 w-4" />
              </Button>
            </CardHeader>
            <CardBody>
              <TaskList tasks={active.slice(0, 4)} />
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Smartphone className="h-4 w-4 text-primary" />
                <CardTitle>Channel Ready</CardTitle>
              </div>
            </CardHeader>
            <CardBody className="grid gap-2">
              {["Web", "Mobile", "DingTalk", "Feishu", "WeCom"].map((item) => (
                <div
                  key={item}
                  className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm"
                >
                  <span>{item}</span>
                  <Badge tone={item === "Web" ? "ok" : "info"}>
                    {item === "Web" ? "live" : "reserved"}
                  </Badge>
                </div>
              ))}
            </CardBody>
          </Card>
        </aside>
      </section>
    </div>
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
    <div className="grid gap-3 md:grid-cols-2">
      {tasks.map((task) => (
        <Link
          key={task.task_id}
          className="grid gap-3 rounded-md border border-border p-3 hover:bg-muted"
          to="/v2/tasks/$taskId"
          params={{ taskId: task.task_id }}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="line-clamp-1 font-medium">{task.title}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                {task.plan?.strategy ?? task.mode}
              </div>
            </div>
            <StatusBadge status={task.status} />
          </div>
          <p className="line-clamp-2 text-sm text-muted-foreground">{task.goal}</p>
          <ProgressBar percent={task.progress.percent} />
        </Link>
      ))}
    </div>
  );
}

function TaskList({ tasks }: { tasks: V2Task[] }) {
  if (!tasks.length) {
    return <EmptyState title="No active work" />;
  }
  return (
    <div className="grid gap-2">
      {tasks.map((task) => (
        <Link
          key={task.task_id}
          className="grid gap-2 rounded-md border border-border p-3 hover:bg-muted"
          to="/v2/tasks/$taskId"
          params={{ taskId: task.task_id }}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="line-clamp-1 text-sm font-medium">{task.title}</span>
            <StatusBadge status={task.status} />
          </div>
          <ProgressBar percent={task.progress.percent} />
        </Link>
      ))}
    </div>
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
