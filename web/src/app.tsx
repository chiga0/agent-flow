import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQueries,
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
  useNavigate,
  useParams,
} from "@tanstack/react-router";
import { useForm } from "@tanstack/react-form";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  Clock3,
  Copy,
  Cpu,
  Download,
  FileText,
  Filter,
  GitBranch,
  KeyRound,
  MessageSquare,
  PauseCircle,
  Play,
  Radio,
  RefreshCw,
  Save,
  Send,
  Server,
  ShieldCheck,
  UserCog,
  Users,
  WalletCards,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { LanguageToggle, Shell } from "./components/shell";
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
  permissionEventId,
  resolvedPermissionIds,
  runtimeApi,
  sessionEventStreamHref,
  type AccessProject,
  type ArtifactInfo,
  type ApiToken,
  type AuthUser,
  type CostStatus,
  type DaemonEvent,
  type DrillCheck,
  type AgentProfile,
  type ExecutorLease,
  type MissionEvent,
  type MissionState,
  type PermissionNotification,
  type PermissionRequest,
  type RuntimeEvent,
  type RunState,
  type TaskEvent,
  type TaskState,
  type WorkerInfo,
  type WorkerRegistration,
} from "./lib/api";
import { LanguageProvider, useI18n, type I18nKey } from "./lib/i18n";
import { downloadJson } from "./lib/utils";

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
  component: WorkspacePage,
});
const overviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/overview",
  component: OverviewPage,
});
const adminOverviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin",
  component: OverviewPage,
});
const adminOverviewAliasRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/overview",
  component: OverviewPage,
});
const runsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs",
  component: RunsPage,
});
const adminRunsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/runs",
  component: RunsPage,
});
const runDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs/$runId",
  component: RunDetailPage,
});
const adminRunDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/runs/$runId",
  component: RunDetailPage,
});
const unitsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/units",
  component: UnitsPage,
});
const adminUnitsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/units",
  component: UnitsPage,
});
const executorsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/executors",
  component: ExecutorsPage,
});
const adminExecutorsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/executors",
  component: ExecutorsPage,
});
const missionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/missions",
  component: MissionsPage,
});
const adminMissionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/missions",
  component: MissionsPage,
});
const missionDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/missions/$missionId",
  component: MissionDetailPage,
});
const adminMissionDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/missions/$missionId",
  component: MissionDetailPage,
});
const taskDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tasks/$taskId",
  component: TaskDetailPage,
});
const profilesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/profiles",
  component: ProfilesPage,
});
const adminProfilesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/profiles",
  component: ProfilesPage,
});
const accessRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/access",
  component: AccessPage,
});
const adminAccessRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/access",
  component: AccessPage,
});
const operationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/operations",
  component: OperationsPage,
});
const adminOperationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/operations",
  component: OperationsPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  taskDetailRoute,
  adminOverviewRoute,
  adminOverviewAliasRoute,
  adminRunsRoute,
  adminRunDetailRoute,
  adminUnitsRoute,
  adminExecutorsRoute,
  adminMissionsRoute,
  adminMissionDetailRoute,
  adminProfilesRoute,
  adminAccessRoute,
  adminOperationsRoute,
  overviewRoute,
  runsRoute,
  runDetailRoute,
  unitsRoute,
  executorsRoute,
  missionsRoute,
  missionDetailRoute,
  profilesRoute,
  accessRoute,
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
      <LanguageProvider>
        <AuthGate />
      </LanguageProvider>
    </QueryClientProvider>
  );
}

function AuthGate() {
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: runtimeApi.session,
    refetchInterval: false,
    retry: false,
  });

  if (session.isPending) {
    return (
      <div className="grid min-h-screen place-items-center bg-background px-4">
        <div className="h-10 w-10 animate-spin rounded-full border-2 border-border border-t-primary" />
      </div>
    );
  }

  if (!session.data?.authenticated) {
    return <LoginPage />;
  }

  return <RouterProvider router={router} />;
}

function LoginPage() {
  const { t } = useI18n();
  const client = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: runtimeApi.login,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["auth", "session"] });
    },
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    login.mutate({ email, password });
  };

  return (
    <div className="min-h-screen bg-background px-4 py-6 text-foreground sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-5xl justify-end">
        <LanguageToggle />
      </div>
      <div className="mx-auto grid min-h-[calc(100vh-3rem)] w-full max-w-5xl items-center gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
        <section className="grid gap-6">
          <div className="flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-md bg-primary text-primary-foreground">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-normal sm:text-3xl">
                {t("nav.title")}
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("nav.subtitle")}
              </p>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Metric
              label={t("login.ingress")}
              value={t("login.ingressValue")}
              detail={t("login.ingressDetail")}
            />
            <Metric
              label={t("login.scope")}
              value={t("login.scopeValue")}
              detail={t("login.scopeDetail")}
            />
            <Metric
              label={t("login.workers")}
              value={t("login.workersValue")}
              detail={t("login.workersDetail")}
            />
          </div>
        </section>

        <Card className="w-full">
          <CardHeader className="grid gap-1">
            <div className="flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-primary" />
              <CardTitle>{t("login.title")}</CardTitle>
            </div>
            <p className="text-sm text-muted-foreground">
              {t("login.subtitle")}
            </p>
          </CardHeader>
          <CardBody>
            <form className="grid gap-4" onSubmit={submit}>
              <Field label={t("login.email")}>
                <Input
                  autoComplete="email"
                  inputMode="email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </Field>
              <Field label={t("login.password")}>
                <Input
                  autoComplete="current-password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </Field>
              {login.isError ? (
                <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                  {t("login.error")}
                </div>
              ) : null}
              <Button
                className="h-11 w-full"
                disabled={login.isPending || !email || !password}
                type="submit"
                variant="primary"
              >
                <KeyRound className="h-4 w-4" />
                {login.isPending ? t("login.signingIn") : t("login.signIn")}
              </Button>
            </form>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function WorkspacePage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: runtimeApi.tasks });
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: runtimeApi.capabilities,
  });
  const adapters = Object.keys(capabilities.data?.adapters ?? { fake: {} });
  const [goal, setGoal] = useState("");
  const [promptSeed, setPromptSeed] = useState(0);
  const running = (tasks.data?.tasks ?? []).filter((task) =>
    ["queued", "running", "blocked"].includes(task.status),
  ).length;
  const attention = (tasks.data?.tasks ?? []).filter(
    (task) => task.needs_attention,
  ).length;
  const completed = (tasks.data?.tasks ?? []).filter(
    (task) => task.status === "completed",
  ).length;
  const attentionTasks = (tasks.data?.tasks ?? []).filter(
    (task) => task.needs_attention,
  );
  const activeTasks = (tasks.data?.tasks ?? []).filter((task) =>
    ["queued", "running", "blocked"].includes(task.status),
  );
  const createTask = useMutation({
    mutationFn: runtimeApi.createTask,
    onSuccess: async (task) => {
      setGoal("");
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
      await navigate({
        to: "/tasks/$taskId",
        params: { taskId: task.task_id },
      });
    },
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = goal.trim();
    if (!trimmed) {
      return;
    }
    createTask.mutate({
      goal: trimmed,
      mode: "mission",
      adapter: preferredTaskAdapter(adapters),
      strategy: "sequential",
    });
  };
  const quickPrompts = [
    t("workspace.quickResearch"),
    t("workspace.quickPlan"),
    t("workspace.quickReview"),
  ];

  return (
    <div className="mx-auto grid w-full max-w-7xl gap-5">
      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid min-h-[calc(100vh-9rem)] content-center gap-5">
          <div className="grid gap-3">
            <div className="text-sm font-medium text-primary">
              {t("workspace.userMode")}
            </div>
            <h1 className="max-w-3xl text-3xl font-semibold tracking-normal sm:text-5xl">
              {t("workspace.chatTitle")}
            </h1>
          </div>
          <form
            className="grid gap-3 rounded-lg border border-border bg-card p-3 shadow-sm"
            onSubmit={submit}
          >
            <label className="sr-only" htmlFor="consumer-task-input">
              {t("workspace.goal")}
            </label>
            <Textarea
              key={promptSeed}
              className="min-h-36 resize-y border-0 bg-transparent text-base shadow-none focus-visible:ring-0"
              id="consumer-task-input"
              placeholder={t("workspace.chatPlaceholder")}
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter" || event.shiftKey) {
                  return;
                }
                event.preventDefault();
                const form = event.currentTarget.form;
                form?.requestSubmit();
              }}
            />
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
              <div className="flex flex-wrap gap-2">
                {quickPrompts.map((prompt) => (
                  <Button
                    key={prompt}
                    size="sm"
                    type="button"
                    variant="secondary"
                    onClick={() => {
                      setGoal(prompt);
                      setPromptSeed((value) => value + 1);
                    }}
                  >
                    {prompt}
                  </Button>
                ))}
              </div>
              <Button
                className="w-full sm:w-auto"
                disabled={createTask.isPending || !goal.trim()}
                type="submit"
                variant="primary"
              >
                <Send className="h-4 w-4" />
                {createTask.isPending
                  ? t("workspace.creating")
                  : t("workspace.startTask")}
              </Button>
            </div>
          </form>
          {createTask.isError ? (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              {String(createTask.error)}
            </div>
          ) : null}
        </div>

        <aside className="grid content-start gap-4">
          <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
            <Metric
              label={t("workspace.activeTasks")}
              value={running}
              detail={t("workspace.activeTasksDetail")}
            />
            <Metric
              label={t("workspace.needsAttention")}
              value={attention}
              detail={t("workspace.needsAttentionDetail")}
            />
            <Metric
              label={t("workspace.completedTasks")}
              value={completed}
              detail={t("workspace.completedTasksDetail")}
            />
          </div>
          {attentionTasks.length ? (
            <TaskSection
              tasks={attentionTasks}
              title={t("workspace.needsAttention")}
            />
          ) : null}
          {activeTasks.length ? (
            <TaskSection tasks={activeTasks} title={t("workspace.activeTasks")} />
          ) : null}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4 text-primary" />
                <CardTitle>{t("workspace.recentTasks")}</CardTitle>
              </div>
              <Button size="sm" variant="ghost" onClick={() => tasks.refetch()}>
                <RefreshCw className="h-4 w-4" />
                {t("common.refresh")}
              </Button>
            </CardHeader>
            <CardBody>
              <TaskList tasks={(tasks.data?.tasks ?? []).slice(0, 6)} compact />
            </CardBody>
          </Card>
        </aside>
      </section>
    </div>
  );
}

function preferredTaskAdapter(adapters: string[]) {
  return adapters.includes("qwen") ? "qwen" : adapters[0] || "fake";
}

function TaskSection({ title, tasks }: { title: string; tasks: TaskState[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <Badge tone="neutral">{tasks.length}</Badge>
      </CardHeader>
      <CardBody>
        <TaskList tasks={tasks.slice(0, 4)} compact />
      </CardBody>
    </Card>
  );
}

function TaskList({
  compact = false,
  tasks,
}: {
  compact?: boolean;
  tasks: TaskState[];
}) {
  const { t } = useI18n();
  if (!tasks.length) {
    return (
      <EmptyState
        title={t("workspace.noTasks")}
        detail={t("workspace.noTasksDetail")}
      />
    );
  }
  return (
    <div className="grid gap-3">
      {tasks.map((task) => (
        <Link
          key={task.task_id}
          className="grid gap-3 rounded-md border border-border p-3 hover:bg-muted"
          to="/tasks/$taskId"
          params={{ taskId: task.task_id }}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="line-clamp-1 font-medium">{task.title}</div>
              <div className="mt-1 truncate font-mono text-xs text-muted-foreground">
                {task.task_id}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {task.needs_attention ? (
                <Badge tone="warn">{t("workspace.attention")}</Badge>
              ) : null}
              <StatusBadge status={task.status} />
            </div>
          </div>
          <div className="line-clamp-2 text-sm text-muted-foreground">
            {task.goal}
          </div>
          {compact ? null : <TaskProgressBar task={task} />}
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>{compact ? timeAgo(task.updated_at) : taskAgentLabel(task)}</span>
            {!compact ? <span>{timeAgo(task.updated_at)}</span> : null}
          </div>
        </Link>
      ))}
    </div>
  );
}

function TaskDetailPage() {
  const { taskId } = useParams({ strict: false }) as { taskId: string };
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const task = useQuery({
    queryKey: ["tasks", taskId],
    queryFn: () => runtimeApi.task(taskId),
  });
  const events = useQuery({
    queryKey: ["tasks", taskId, "events"],
    queryFn: () => runtimeApi.taskEvents(taskId),
  });
  const artifacts = useQuery({
    queryKey: ["tasks", taskId, "artifacts"],
    queryFn: () => runtimeApi.taskArtifacts(taskId),
  });
  const result = useQuery({
    queryKey: ["tasks", taskId, "result"],
    queryFn: () => runtimeApi.taskResult(taskId),
  });
  const cancelTask = useMutation({
    mutationFn: () => runtimeApi.cancelTask(taskId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
      await queryClient.invalidateQueries({ queryKey: ["tasks", taskId] });
    },
  });
  const submitMessage = useMutation({
    mutationFn: (message: string) =>
      runtimeApi.submitTaskMessage(taskId, message),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["tasks", taskId, "events"],
      });
    },
  });
  const current = task.data;
  return (
    <Page
      title={current?.title ?? t("workspace.taskDetail")}
      subtitle={current?.goal ?? t("workspace.loadingTask")}
    >
      {current ? (
        <div className="grid gap-4 md:grid-cols-3">
          <Metric
            label={t("workspace.taskStatus")}
            value={<StatusBadge status={current.status} />}
            detail={taskAgentLabel(current)}
          />
          <Metric
            label={t("common.progress")}
            value={`${current.progress.percent}%`}
            detail={`${current.progress.completed_steps}/${current.progress.total_steps}`}
          />
          <Metric
            label={t("workspace.updated")}
            value={timeAgo(current.updated_at)}
            detail={current.kind}
          />
        </div>
      ) : null}

      {current ? (
        <Card>
          <CardBody className="grid gap-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                {current.result_summary ? (
                  <div className="text-sm text-muted-foreground">
                    {current.result_summary}
                  </div>
                ) : null}
                <TaskProgressBar task={current} />
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={
                    cancelTask.isPending ||
                    ["completed", "failed", "cancelled"].includes(
                      current.status,
                    )
                  }
                  size="sm"
                  variant="danger"
                  onClick={() => cancelTask.mutate()}
                >
                  <PauseCircle className="h-4 w-4" />
                  {t("common.cancel")}
                </Button>
              </div>
            </div>
          </CardBody>
        </Card>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Radio className="h-4 w-4 text-primary" />
              <CardTitle>{t("workspace.timeline")}</CardTitle>
            </div>
            <Badge tone="neutral">{events.data?.events.length ?? 0}</Badge>
          </CardHeader>
          <CardBody>
            <TaskTimeline events={events.data?.events ?? []} />
            {current?.kind === "run" ? (
              <TaskMessageForm
                disabled={
                  submitMessage.isPending ||
                  !current ||
                  current.status !== "running"
                }
                onSubmit={(message) => submitMessage.mutate(message)}
              />
            ) : null}
          </CardBody>
        </Card>

        <div className="grid content-start gap-4">
          <TaskResultPanel result={result.data} />
          <TaskArtifactsPanel
            artifacts={artifacts.data?.artifacts ?? []}
            task={current}
          />
        </div>
      </div>
    </Page>
  );
}

function TaskProgressBar({ task }: { task: TaskState }) {
  const percent = Math.max(0, Math.min(100, task.progress.percent || 0));
  return (
    <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
      <div
        className="h-full rounded-full bg-primary transition-all"
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}

function TaskTimeline({ events }: { events: TaskEvent[] }) {
  const { t } = useI18n();
  if (!events.length) {
    return (
      <EmptyState
        title={t("workspace.noEvents")}
        detail={t("workspace.noEventsDetail")}
      />
    );
  }
  return (
    <div className="grid gap-3">
      {events.map((event) => (
        <div
          key={event.id}
          className="grid grid-cols-[28px_minmax(0,1fr)] gap-3"
        >
          <div className="grid h-7 w-7 place-items-center rounded-full border border-border bg-background">
            {taskEventIcon(event.status)}
          </div>
          <div className="min-w-0 rounded-md border border-border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-medium">{event.title}</div>
              <div className="flex items-center gap-2">
                <StatusBadge status={event.status} />
                <span className="text-xs text-muted-foreground">
                  {timeAgo(event.created_at)}
                </span>
              </div>
            </div>
            {event.body ? (
              <div className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">
                {event.body}
              </div>
            ) : null}
            <div className="mt-2 font-mono text-xs text-muted-foreground">
              {event.sequence}. {event.source_event_type}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function TaskMessageForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (message: string) => void;
}) {
  const { t } = useI18n();
  const [message, setMessage] = useState("");
  return (
    <form
      className="mt-4 grid gap-2 border-t border-border pt-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!message.trim()) {
          return;
        }
        onSubmit(message.trim());
        setMessage("");
      }}
    >
      <Field label={t("workspace.followUp")}>
        <Textarea
          className="min-h-24"
          disabled={disabled}
          placeholder={t("workspace.followUpPlaceholder")}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
      </Field>
      <Button
        disabled={disabled || !message.trim()}
        type="submit"
        variant="primary"
      >
        <Send className="h-4 w-4" />
        {t("live.send")}
      </Button>
    </form>
  );
}

function TaskResultPanel({ result }: { result?: { summary?: string | null } }) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-primary" />
          <CardTitle>{t("common.result")}</CardTitle>
        </div>
      </CardHeader>
      <CardBody>
        {result?.summary ? (
          <div className="whitespace-pre-wrap text-sm">{result.summary}</div>
        ) : (
          <EmptyState
            title={t("workspace.noResult")}
            detail={t("workspace.noResultDetail")}
          />
        )}
      </CardBody>
    </Card>
  );
}

function TaskArtifactsPanel({
  task,
  artifacts,
}: {
  task?: TaskState;
  artifacts: ArtifactInfo[];
}) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("common.artifacts")}</CardTitle>
        <Badge tone="neutral">{artifacts.length}</Badge>
      </CardHeader>
      <CardBody className="grid gap-2">
        {artifacts.map((artifact) => {
          const href = taskArtifactHref(task, artifact.name);
          return (
            <div
              key={artifact.name}
              className="grid gap-2 rounded-md border border-border p-3 text-sm"
            >
              <div className="break-words font-medium">{artifact.name}</div>
              <div className="text-xs text-muted-foreground">
                {formatBytes(artifact.size_bytes)}
              </div>
              {href ? (
                <LinkButton href={href} size="sm">
                  <Download className="h-4 w-4" />
                  {t("common.download")}
                </LinkButton>
              ) : null}
            </div>
          );
        })}
        {!artifacts.length ? (
          <EmptyState title={t("runs.noArtifacts")} />
        ) : null}
      </CardBody>
    </Card>
  );
}

function taskArtifactHref(task: TaskState | undefined, artifactName: string) {
  if (task?.source.run_id) {
    return artifactHref(task.source.run_id, artifactName);
  }
  if (task?.source.mission_id) {
    return missionArtifactHref(task.source.mission_id, artifactName);
  }
  return undefined;
}

function taskEventIcon(status: string) {
  if (status === "completed") {
    return <CheckCircle2 className="h-4 w-4 text-success" />;
  }
  if (status === "queued") {
    return <Clock3 className="h-4 w-4 text-warning" />;
  }
  if (status === "failed" || status === "cancelled" || status === "blocked") {
    return <AlertTriangle className="h-4 w-4 text-destructive" />;
  }
  return <CircleDot className="h-4 w-4 text-primary" />;
}

function taskAgentLabel(task: TaskState) {
  const adapter = stringValue(task.agent_summary.adapter);
  const activeAgent = stringValue(task.agent_summary.active_agent);
  const strategy = stringValue(task.agent_summary.strategy);
  return (
    [activeAgent, adapter, strategy].filter(Boolean).join(" · ") || task.kind
  );
}

function OverviewPage() {
  const { t } = useI18n();
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
    <Page title={t("overview.title")} subtitle={t("overview.subtitle")}>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Metric
          label={t("overview.runtime")}
          value={health.data?.ok ? t("common.healthy") : t("common.checking")}
          detail={health.data?.version}
        />
        <Metric
          label={t("overview.runs")}
          value={metrics.data?.runs.total ?? "-"}
          detail={statusLine(metrics.data?.runs.by_status)}
        />
        <Metric
          label={t("overview.missions")}
          value={metrics.data?.missions.total ?? "-"}
          detail={statusLine(metrics.data?.missions.by_status)}
        />
        <Metric
          label={t("overview.permissions")}
          value={metrics.data?.permissions.pending ?? "-"}
          detail={`${metrics.data?.permissions.stalled ?? 0} ${t("overview.stalledSuffix")}`}
        />
      </div>

      <GettingStartedPanel />

      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <Card>
          <CardHeader>
            <CardTitle>{t("overview.queue")}</CardTitle>
            <Badge tone={metrics.data?.queue.stale_workers ? "warn" : "ok"}>
              {metrics.data?.queue.active_workers ?? 0}{" "}
              {t("overview.activeSuffix")}
            </Badge>
          </CardHeader>
          <CardBody className="grid gap-3 md:grid-cols-3">
            <Metric
              label={t("overview.queued")}
              value={metrics.data?.queue.counts.queued ?? 0}
            />
            <Metric
              label={t("overview.running")}
              value={metrics.data?.queue.counts.running ?? 0}
            />
            <Metric
              label={t("overview.staleWorkers")}
              value={metrics.data?.queue.stale_workers ?? 0}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("overview.adapters")}</CardTitle>
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

function GettingStartedPanel() {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("overview.getStarted")}</CardTitle>
        <a
          className="text-sm text-primary"
          href="https://chiga0.github.io/agent-research/architecture/"
          rel="noreferrer"
          target="_blank"
        >
          {t("overview.checkDocs")}
        </a>
      </CardHeader>
      <CardBody className="grid gap-3 md:grid-cols-3">
        <Link
          className="rounded-md border border-border p-3 hover:bg-muted"
          to="/runs"
        >
          <div className="flex items-center gap-2 font-medium">
            <Play className="h-4 w-4 text-primary" />
            {t("overview.checkFake")}
          </div>
          <div className="mt-2 text-sm text-muted-foreground">
            {t("overview.checkFakeDetail")}
          </div>
        </Link>
        <Link
          className="rounded-md border border-border p-3 hover:bg-muted"
          to="/runs"
        >
          <div className="flex items-center gap-2 font-medium">
            <MessageSquare className="h-4 w-4 text-primary" />
            {t("overview.checkQwen")}
          </div>
          <div className="mt-2 text-sm text-muted-foreground">
            {t("overview.checkQwenDetail")}
          </div>
        </Link>
        <Link
          className="rounded-md border border-border p-3 hover:bg-muted"
          to="/units"
        >
          <div className="flex items-center gap-2 font-medium">
            <Server className="h-4 w-4 text-primary" />
            {t("overview.checkWorker")}
          </div>
          <div className="mt-2 text-sm text-muted-foreground">
            {t("overview.checkWorkerDetail")}
          </div>
        </Link>
      </CardBody>
    </Card>
  );
}

function RunsPage() {
  const { t } = useI18n();
  const runs = useQuery({ queryKey: ["runs"], queryFn: runtimeApi.runs });
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: runtimeApi.capabilities,
  });
  return (
    <Page title={t("runs.title")} subtitle={t("runs.subtitle")}>
      <div className="grid gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
        <CreateRunForm
          adapters={Object.keys(capabilities.data?.adapters ?? { fake: {} })}
        />
        <Card>
          <CardHeader>
            <CardTitle>{t("runs.history")}</CardTitle>
            <Button size="sm" variant="ghost" onClick={() => runs.refetch()}>
              <RefreshCw className="h-4 w-4" />
              {t("common.refresh")}
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

function UnitsPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const workers = useQuery({
    queryKey: ["workers"],
    queryFn: runtimeApi.workers,
  });
  const [registration, setRegistration] = useState<WorkerRegistration | null>(
    null,
  );
  const drain = useMutation({
    mutationFn: (workerId: string) => runtimeApi.drainWorker(workerId),
    onSuccess: async () =>
      queryClient.invalidateQueries({ queryKey: ["workers"] }),
  });
  const resume = useMutation({
    mutationFn: runtimeApi.resumeWorker,
    onSuccess: async () =>
      queryClient.invalidateQueries({ queryKey: ["workers"] }),
  });
  const retry = useMutation({
    mutationFn: runtimeApi.retryWorkerRuns,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workers"] });
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });
  const workerList = workers.data?.workers ?? [];
  const active = workerList.filter(
    (worker) => worker.status === "active",
  ).length;
  const draining = workerList.filter(
    (worker) => worker.status === "draining",
  ).length;
  const stale = workerList.filter((worker) => worker.status === "stale").length;
  return (
    <Page title={t("units.title")} subtitle={t("units.subtitle")}>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Metric
          label={t("units.title")}
          value={workerList.length}
          detail={t("units.localRemote")}
        />
        <Metric
          label={t("common.active")}
          value={active}
          detail={t("units.activeDetail")}
        />
        <Metric
          label={t("units.draining")}
          value={draining}
          detail={t("units.drainingDetail")}
        />
        <Metric
          label={t("common.stale")}
          value={stale}
          detail={t("units.staleDetail")}
        />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{t("units.howItWorks")}</CardTitle>
        </CardHeader>
        <CardBody className="grid gap-3 md:grid-cols-3">
          <div className="rounded-md bg-muted/50 p-3 text-sm">
            {t("units.helpWorker")}
          </div>
          <div className="rounded-md bg-muted/50 p-3 text-sm">
            {t("units.helpRegister")}
          </div>
          <div className="rounded-md bg-muted/50 p-3 text-sm">
            {t("units.helpToken")}
          </div>
        </CardBody>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
        <WorkerRegistrationForm onCreated={setRegistration} />
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Server className="h-4 w-4 text-primary" />
              <CardTitle>{t("units.executionUnits")}</CardTitle>
            </div>
            <Button size="sm" variant="ghost" onClick={() => workers.refetch()}>
              <RefreshCw className="h-4 w-4" />
              {t("common.refresh")}
            </Button>
          </CardHeader>
          <CardBody>
            <WorkerList
              workers={workerList}
              onDrain={(workerId) => drain.mutate(workerId)}
              onResume={(workerId) => resume.mutate(workerId)}
              onRetry={(workerId) => retry.mutate(workerId)}
            />
          </CardBody>
        </Card>
      </div>
      {registration ? (
        <WorkerRegistrationResult registration={registration} />
      ) : null}
    </Page>
  );
}

function WorkerRegistrationForm({
  onCreated,
}: {
  onCreated: (registration: WorkerRegistration) => void;
}) {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);
  const createRegistration = useMutation({
    mutationFn: runtimeApi.createWorkerRegistration,
    onSuccess: (result) => {
      setError(null);
      onCreated(result);
    },
    onError: (err) => setError(String(err)),
  });
  const form = useForm({
    defaultValues: {
      worker_id: "hk-2c2g-a",
      control_url: defaultWorkerControlUrl(),
      capacity: 1,
      region: "hk",
      cpus: 2,
      memory_gb: 2,
    },
    onSubmit: async ({ value }) => {
      await createRegistration.mutateAsync({
        worker_id: value.worker_id,
        control_url: value.control_url,
        capacity: Number(value.capacity) || 1,
        labels: { region: value.region },
        resources: {
          cpus: Number(value.cpus) || 2,
          memory_gb: Number(value.memory_gb) || 2,
        },
      });
    },
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("units.register")}</CardTitle>
        <Badge tone="info">{t("units.oneTimeToken")}</Badge>
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
          <form.Field name="worker_id">
            {(field) => (
              <Field label={t("units.unitId")}>
                <Input
                  value={field.state.value}
                  onChange={(event) => field.handleChange(event.target.value)}
                />
              </Field>
            )}
          </form.Field>
          <form.Field name="control_url">
            {(field) => (
              <Field label={t("units.workerControlUrl")}>
                <Input
                  value={field.state.value}
                  onChange={(event) => field.handleChange(event.target.value)}
                />
              </Field>
            )}
          </form.Field>
          <div className="grid gap-3 md:grid-cols-3">
            <form.Field name="capacity">
              {(field) => (
                <Field label={t("common.capacity")}>
                  <Input
                    min={1}
                    type="number"
                    value={field.state.value}
                    onChange={(event) =>
                      field.handleChange(Number(event.target.value))
                    }
                  />
                </Field>
              )}
            </form.Field>
            <form.Field name="cpus">
              {(field) => (
                <Field label={t("units.cpUs")}>
                  <Input
                    min={1}
                    type="number"
                    value={field.state.value}
                    onChange={(event) =>
                      field.handleChange(Number(event.target.value))
                    }
                  />
                </Field>
              )}
            </form.Field>
            <form.Field name="memory_gb">
              {(field) => (
                <Field label={t("units.memoryGb")}>
                  <Input
                    min={1}
                    type="number"
                    value={field.state.value}
                    onChange={(event) =>
                      field.handleChange(Number(event.target.value))
                    }
                  />
                </Field>
              )}
            </form.Field>
          </div>
          <form.Field name="region">
            {(field) => (
              <Field label={t("units.region")}>
                <Input
                  value={field.state.value}
                  onChange={(event) => field.handleChange(event.target.value)}
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
            disabled={createRegistration.isPending}
            type="submit"
            variant="primary"
          >
            <KeyRound className="h-4 w-4" />
            {t("common.generate")}
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function WorkerList({
  workers,
  onDrain,
  onResume,
  onRetry,
}: {
  workers: WorkerInfo[];
  onDrain: (workerId: string) => void;
  onResume: (workerId: string) => void;
  onRetry: (workerId: string) => void;
}) {
  const { t } = useI18n();
  if (!workers.length) {
    return (
      <EmptyState
        title={t("units.noUnits")}
        detail={t("units.noUnitsDetail")}
      />
    );
  }
  return (
    <div className="grid gap-2">
      {workers.map((worker) => (
        <div
          key={worker.worker_id}
          className="grid gap-3 rounded-md border border-border p-3 xl:grid-cols-[minmax(0,1fr)_160px_220px]"
        >
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="truncate font-mono text-sm">
                {worker.worker_id}
              </span>
              <StatusBadge status={worker.status} />
              <Badge tone="neutral">
                {stringValue(worker.metadata?.kind ?? "local")}
              </Badge>
            </div>
            <div className="mt-2 grid gap-1 text-xs text-muted-foreground md:grid-cols-2">
              <span>
                {t("units.heartbeat")} {timeAgo(worker.heartbeat_at)}
              </span>
              <span>
                {t("units.leaseTtl")} {worker.lease_ttl_seconds}s
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {workerBadges(worker).map((badge) => (
                <Badge key={badge} tone="neutral">
                  {badge}
                </Badge>
              ))}
            </div>
            <WorkerResourceWaterline worker={worker} />
          </div>
          <div className="grid content-start gap-2">
            <Metric
              label={t("common.capacity")}
              value={`${worker.active_count}/${worker.capacity}`}
            />
          </div>
          <div className="flex flex-wrap content-start justify-start gap-2 xl:justify-end">
            <Button
              disabled={worker.status === "draining"}
              size="sm"
              onClick={() => onDrain(worker.worker_id)}
            >
              <PauseCircle className="h-4 w-4" />
              {t("units.drain")}
            </Button>
            <Button
              disabled={worker.status === "active"}
              size="sm"
              onClick={() => onResume(worker.worker_id)}
            >
              <Play className="h-4 w-4" />
              {t("units.resume")}
            </Button>
            <Button
              disabled={worker.active_count === 0}
              size="sm"
              variant="danger"
              onClick={() => onRetry(worker.worker_id)}
            >
              <RefreshCw className="h-4 w-4" />
              {t("units.retry")}
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}

function WorkerResourceWaterline({ worker }: { worker: WorkerInfo }) {
  const { t } = useI18n();
  const resources = workerResourceRows(worker);
  const warnings = workerResourceWarnings(worker);
  if (!resources.length && !warnings.length) {
    return null;
  }
  return (
    <div className="mt-3 grid gap-2">
      {resources.length ? (
        <div className="grid gap-2 md:grid-cols-2">
          {resources.map((resource) => (
            <div key={resource.label} className="grid gap-1">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-muted-foreground">{resource.label}</span>
                <span className="font-mono">{resource.value}</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full rounded-full ${resource.tone === "warn" ? "bg-warning" : "bg-primary"}`}
                  style={{ width: `${resource.percent}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      ) : null}
      {warnings.map((warning) => (
        <div
          key={warning}
          className="rounded-md border border-warning/30 bg-warning/10 p-2 text-xs text-amber-800 dark:text-warning"
        >
          {t(warning)}
        </div>
      ))}
    </div>
  );
}

function WorkerRegistrationResult({
  registration,
}: {
  registration: WorkerRegistration;
}) {
  const { t } = useI18n();
  const noSourceCommand = workerNoSourceDeployCommand(registration);
  return (
    <Card className="border-warning/40">
      <CardHeader>
        <div>
          <CardTitle>{t("units.deploymentCommand")}</CardTitle>
          <div className="mt-1 text-xs text-muted-foreground">
            {t("units.tokenDetail")}
          </div>
        </div>
        <Button size="sm" onClick={() => copyText(noSourceCommand)}>
          <Copy className="h-4 w-4" />
          {t("common.copy")}
        </Button>
      </CardHeader>
      <CardBody className="grid gap-3">
        <div className="grid gap-3 md:grid-cols-3">
          <Metric label={t("units.unit")} value={registration.worker_id} />
          <Metric label={t("common.capacity")} value={registration.capacity} />
          <Metric
            label={t("common.token")}
            value={registration.token.token_prefix}
          />
        </div>
        <div className="grid gap-2">
          <div>
            <div className="text-sm font-medium">
              {t("units.deployNoSource")}
            </div>
            <div className="text-xs text-muted-foreground">
              {t("units.deployNoSourceDetail")}
            </div>
          </div>
          <pre className="max-h-[320px] overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
            {noSourceCommand}
          </pre>
        </div>
        <div className="grid gap-2">
          <div>
            <div className="text-sm font-medium">
              {t("units.deployLocalSource")}
            </div>
            <div className="text-xs text-muted-foreground">
              {t("units.deployLocalSourceDetail")}
            </div>
          </div>
          <pre className="max-h-[320px] overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
            {registration.deploy_command}
          </pre>
        </div>
      </CardBody>
    </Card>
  );
}

function ExecutorsPage() {
  const { t } = useI18n();
  const executors = useQuery({
    queryKey: ["executors"],
    queryFn: runtimeApi.executors,
  });
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: runtimeApi.capabilities,
  });
  const registry = executors.data?.executor_registry ?? {};
  const config = registryValue(registry, "config");
  const counts = registryValue(registry, "counts");
  const leases = executors.data?.executors ?? [];
  const activeCount = leases.filter((lease) =>
    ["starting", "running"].includes(lease.status),
  ).length;
  const failedCount = leases.filter((lease) =>
    ["failed", "orphaned"].includes(lease.status),
  ).length;

  return (
    <Page title={t("executors.title")} subtitle={t("executors.subtitle")}>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Metric
          label={t("common.strategy")}
          value={stringValue(config.strategy ?? "shared")}
          detail={
            config.enabled
              ? t("executors.registryEnabled")
              : t("executors.sharedEndpoint")
          }
        />
        <Metric
          label={t("common.active")}
          value={activeCount}
          detail={t("executors.activeDetail")}
        />
        <Metric
          label={t("common.failed")}
          value={failedCount}
          detail={t("executors.failedDetail")}
        />
        <Metric
          label={t("executors.container")}
          value={stringValue(config.container_image ?? "-")}
          detail={stringValue(config.container_network ?? "bridge")}
        />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{t("executors.howItWorks")}</CardTitle>
        </CardHeader>
        <CardBody className="grid gap-3 md:grid-cols-3">
          <div className="rounded-md bg-muted/50 p-3 text-sm">
            {t("executors.helpUnit")}
          </div>
          <div className="rounded-md bg-muted/50 p-3 text-sm">
            {t("executors.helpExecutor")}
          </div>
          <div className="rounded-md bg-muted/50 p-3 text-sm">
            {t("executors.helpRegistry")}
          </div>
        </CardBody>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Server className="h-4 w-4 text-primary" />
              <CardTitle>{t("executors.leases")}</CardTitle>
            </div>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => executors.refetch()}
            >
              <RefreshCw className="h-4 w-4" />
              {t("common.refresh")}
            </Button>
          </CardHeader>
          <CardBody>
            <ExecutorLeaseList leases={leases} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Cpu className="h-4 w-4 text-primary" />
              <CardTitle>{t("executors.registry")}</CardTitle>
            </div>
            <Badge
              tone={
                capabilities.data?.features.includes("executor_registry")
                  ? "ok"
                  : "neutral"
              }
            >
              {stringValue(config.strategy ?? "shared")}
            </Badge>
          </CardHeader>
          <CardBody className="grid gap-3">
            <ProfileJson label={t("common.config")} value={config} />
            <ProfileJson label={t("common.counts")} value={counts} />
          </CardBody>
        </Card>
      </div>
    </Page>
  );
}

function ExecutorLeaseList({ leases }: { leases: ExecutorLease[] }) {
  const { t } = useI18n();
  if (!leases.length) {
    return <EmptyState title={t("executors.noLeases")} />;
  }
  return (
    <div className="grid gap-2">
      {leases.map((lease) => (
        <div
          key={lease.executor_id}
          className="grid gap-3 rounded-md border border-border p-3 lg:grid-cols-[220px_120px_minmax(0,1fr)_160px]"
        >
          <div className="min-w-0">
            <div className="truncate font-mono text-xs">
              {lease.executor_id}
            </div>
            <Link
              className="mt-1 block truncate text-sm text-primary"
              to="/runs/$runId"
              params={{ runId: lease.run_id }}
            >
              {lease.run_id}
            </Link>
          </div>
          <div className="grid content-start gap-1">
            <StatusBadge status={lease.status} />
            <Badge tone="neutral">{lease.strategy}</Badge>
          </div>
          <div className="min-w-0 text-sm text-muted-foreground">
            <div className="truncate">{lease.base_url ?? "-"}</div>
            <div className="mt-1 truncate">{lease.workspace ?? "-"}</div>
            {lease.last_error ? (
              <div className="mt-1 text-destructive">{lease.last_error}</div>
            ) : null}
          </div>
          <div className="grid content-start gap-1 text-xs text-muted-foreground">
            <div>pid {lease.pid ?? "-"}</div>
            <div>port {lease.port ?? "-"}</div>
            <div>{timeAgo(lease.heartbeat_at ?? lease.started_at)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function CreateRunForm({ adapters }: { adapters: string[] }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const createRun = useMutation({
    mutationFn: runtimeApi.createRun,
    onSuccess: async (run) => {
      setError(null);
      queryClient.setQueryData<{ runs: RunState[] }>(["runs"], (current) => {
        if (!current) {
          return { runs: [run] };
        }
        const withoutCreated = current.runs.filter(
          (item) => item.run_id !== run.run_id,
        );
        return { runs: [run, ...withoutCreated] };
      });
      queryClient.setQueryData(["runs", run.run_id], run);
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
      void queryClient.invalidateQueries({ queryKey: ["metrics"] });
      await router.navigate({
        to: "/runs/$runId",
        params: { runId: run.run_id },
      });
    },
    onError: (err) => setError(String(err)),
  });
  const form = useForm({
    defaultValues: {
      adapter: adapters.includes("fake") ? "fake" : adapters[0] || "fake",
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
        <CardTitle>{t("runs.create")}</CardTitle>
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
              <div className="grid gap-1.5">
                <Field label={t("common.adapter")}>
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
                <p className="text-xs text-muted-foreground">
                  {adapterTip(field.state.value, t)}
                </p>
              </div>
            )}
          </form.Field>
          <form.Field name="prompt">
            {(field) => (
              <Field label={t("common.prompt")}>
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
                <Field label={t("common.repo")}>
                  <Input
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                  />
                </Field>
              )}
            </form.Field>
            <form.Field name="workspace">
              {(field) => (
                <Field label={t("common.workspace")}>
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
              <Field label={t("runs.timeout")}>
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
            {createRun.isPending ? t("runs.submitting") : t("common.start")}
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function adapterTip(adapter: string, t: (key: I18nKey) => string) {
  return adapter === "qwen"
    ? t("runs.adapterQwenTip")
    : t("runs.adapterFakeTip");
}

function RunDetailPage() {
  const { t } = useI18n();
  const { runId } = useParams({ strict: false }) as { runId: string };
  const queryClient = useQueryClient();
  const run = useQuery({
    queryKey: ["runs", runId],
    queryFn: () => runtimeApi.run(runId),
  });
  const events = useQuery({
    queryKey: ["runs", runId, "events"],
    queryFn: () => runtimeApi.runEvents(runId),
  });
  const sessionEvents = useQuery({
    queryKey: ["session", runId, "events"],
    queryFn: () => runtimeApi.sessionEvents(runId),
  });
  const artifacts = useQuery({
    queryKey: ["runs", runId, "artifacts"],
    queryFn: () => runtimeApi.runArtifacts(runId),
  });
  const live = useRunLiveDaemonEvents(
    runId,
    sessionEvents.data?.events ?? [],
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
    <Page title={t("runs.detail")} subtitle={runId}>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid min-w-0 gap-4">
          <LiveRunnerPanel
            connectionStatus={live.status}
            daemonEvents={live.events}
            artifacts={artifacts.data?.artifacts ?? []}
            runtimeEvents={events.data?.events ?? []}
            run={run.data}
            runId={runId}
            runStatus={run.data?.status}
          />
          <EventList events={events.data?.events ?? []} />
        </div>
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>{t("runs.state")}</CardTitle>
              <div className="flex gap-2">
                {run.data ? <StatusBadge status={run.data.status} /> : null}
                <Button
                  disabled={cancel.isPending || isTerminal(run.data?.status)}
                  size="sm"
                  onClick={() => cancel.mutate()}
                >
                  <PauseCircle className="h-4 w-4" />
                  {t("common.cancel")}
                </Button>
              </div>
            </CardHeader>
            <CardBody className="grid gap-3 md:grid-cols-4">
              <Metric
                label={t("common.adapter")}
                value={run.data?.spec.adapter ?? "-"}
              />
              <Metric
                label={t("common.events")}
                value={run.data?.event_count ?? "-"}
              />
              <Metric
                label={t("runs.inputs")}
                value={run.data?.prompt_count ?? "-"}
              />
              <Metric
                label={t("common.updated")}
                value={timeAgo(run.data?.updated_at)}
              />
            </CardBody>
          </Card>
          <ArtifactPanel
            runId={runId}
            artifacts={artifacts.data?.artifacts ?? []}
          />
          <Card>
            <CardHeader>
              <div>
                <CardTitle>{t("runs.auditDownloads")}</CardTitle>
                <div className="mt-1 text-xs text-muted-foreground">
                  {t("runs.auditDownloadsDetail")}
                </div>
              </div>
            </CardHeader>
            <CardBody className="grid gap-2">
              <LinkButton href={artifactHref(runId, "events.jsonl")}>
                <Download className="h-4 w-4" />
                {t("common.eventsJsonl")}
              </LinkButton>
              <LinkButton href={artifactHref(runId, "diagnostics.json")}>
                <Download className="h-4 w-4" />
                {t("common.diagnostics")}
              </LinkButton>
              <LinkButton href={auditHref(runId)}>
                <Download className="h-4 w-4" />
                {t("common.auditBundle")}
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

const daemonLiveEventTypes = [
  "session_update",
  "shell_output",
  "permission_request",
  "permission_resolved",
  "turn_complete",
  "turn_error",
  "prompt_cancelled",
  "stream_error",
];

function useRunLiveDaemonEvents(
  runId: string,
  initialEvents: DaemonEvent[],
  runStatus?: string,
) {
  const [events, setEvents] = useState<DaemonEvent[]>(initialEvents);
  const [status, setStatus] = useState<LiveConnectionStatus>("connecting");

  useEffect(() => {
    setEvents((current) => mergeDaemonEvents(current, initialEvents));
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
    const source = new EventSource(sessionEventStreamHref(runId));
    const handleEvent = (message: MessageEvent) => {
      try {
        const event = JSON.parse(message.data) as DaemonEvent;
        setEvents((current) => mergeDaemonEvents(current, [event]));
        if (isTerminalDaemonEvent(event.type)) {
          setStatus("closed");
          source.close();
        }
      } catch {
        setStatus("reconnecting");
      }
    };
    for (const eventType of daemonLiveEventTypes) {
      source.addEventListener(eventType, handleEvent);
    }
    source.onopen = () => setStatus("live");
    source.onerror = () =>
      setStatus(
        source.readyState === EventSource.CLOSED ? "closed" : "reconnecting",
      );

    return () => {
      for (const eventType of daemonLiveEventTypes) {
        source.removeEventListener(eventType, handleEvent);
      }
      source.close();
    };
  }, [runId, runStatus]);

  return { events, status };
}

function LiveRunnerPanel({
  artifacts,
  connectionStatus,
  daemonEvents,
  runtimeEvents,
  run,
  runId,
  runStatus,
}: {
  artifacts: ArtifactInfo[];
  connectionStatus: LiveConnectionStatus;
  daemonEvents: DaemonEvent[];
  runtimeEvents: RuntimeEvent[];
  run?: RunState;
  runId: string;
  runStatus?: string;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const transcript = useMemo(
    () => daemonRunnerTranscript(daemonEvents),
    [daemonEvents],
  );
  const processSummary = useMemo(
    () => daemonRunnerProcessSummary(daemonEvents, transcript),
    [daemonEvents, transcript],
  );
  const [filter, setFilter] = useState<RunnerFilter>("all");
  const [prompt, setPrompt] = useState("");
  const [inputError, setInputError] = useState<string | null>(null);
  const filteredTranscript = useMemo(
    () => filterTranscript(transcript, filter),
    [filter, transcript],
  );
  const latest = daemonEvents.at(-1);
  const signal = runnerSignal(latest, runStatus);
  const workers = useQuery({
    queryKey: ["workers"],
    queryFn: runtimeApi.workers,
    enabled:
      signal.tone === "warn" ||
      runStatus === "queued" ||
      runtimeEvents.at(-1)?.type === "run.queued",
  });
  const stallReason = runnerStallExplanation(
    runtimeEvents,
    runStatus,
    workers.data?.workers ?? [],
  );
  const resolvedPermissions = daemonResolvedPermissionIds(daemonEvents);
  const submittedPermissions = permissionResolveRequestedIds(runtimeEvents);
  const pendingPermissions = daemonPendingPermissionRequests(daemonEvents);
  const taskProgress = runTaskProgress(
    run,
    runtimeEvents,
    artifacts,
    workers.data?.workers ?? [],
  );
  const ended = isTerminal(runStatus);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const submitInput = useMutation({
    mutationFn: (nextPrompt: string) =>
      runtimeApi.submitSessionPrompt(runId, nextPrompt),
    onSuccess: async () => {
      setPrompt("");
      setInputError(null);
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["runs", runId] });
      await queryClient.invalidateQueries({
        queryKey: ["runs", runId, "events"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["session", runId, "events"],
      });
    },
    onError: (error) => setInputError(String(error)),
  });

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextPrompt = prompt.trim();
    if (!nextPrompt || ended || submitInput.isPending) {
      return;
    }
    submitInput.mutate(nextPrompt);
  };

  const handlePromptKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }
    event.preventDefault();
    const nextPrompt = prompt.trim();
    if (!nextPrompt || ended || submitInput.isPending) {
      return;
    }
    submitInput.mutate(nextPrompt);
  };

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
  }, [filteredTranscript.length, latest?.id]);

  return (
    <Card className="min-w-0">
      <CardHeader>
        <div className="flex min-w-0 items-center gap-2">
          <MessageSquare className="h-4 w-4 text-primary" />
          <CardTitle>{t("live.title")}</CardTitle>
        </div>
        <Badge tone={connectionTone(connectionStatus)}>
          <Radio className="h-4 w-4" />
          {connectionLabel(connectionStatus)}
        </Badge>
      </CardHeader>
      <CardBody className="grid gap-4">
        <TaskProgressPanel progress={taskProgress} />
        <InlinePermissionPanel pending={pendingPermissions} runId={runId} />
        <RunnerProcessSummaryPanel summary={processSummary} />
        <div className="grid gap-3 md:grid-cols-4">
          <Metric
            label={t("live.runStatus")}
            value={runStatus ?? t("common.loading")}
          />
          <Metric label={t("live.lastEvent")} value={latest?.type ?? "-"} />
          <Metric
            label={t("live.runnerSignal")}
            value={signal.label}
            detail={latest ? `id ${latest.id}` : undefined}
          />
          <Metric label={t("common.events")} value={daemonEvents.length} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            {(
              [
                "all",
                "agent",
                "process",
                "tools",
                "permission",
                "warning",
                "error",
              ] as const
            ).map((item) => (
              <Button
                key={item}
                size="sm"
                variant={filter === item ? "primary" : "secondary"}
                onClick={() => setFilter(item)}
              >
                <Filter className="h-4 w-4" />
                {filterLabel(item, t)}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <LinkButton
              href={artifactHref(runId, "raw_events.jsonl")}
              size="sm"
            >
              <Download className="h-4 w-4" />
              {t("live.rawEvents")}
            </LinkButton>
            <Button
              size="sm"
              onClick={() =>
                downloadText(
                  `run-${runId}-report.md`,
                  runnerReadableReport(transcript, runtimeEvents),
                )
              }
            >
              <FileText className="h-4 w-4" />
              {t("live.downloadReport")}
            </Button>
          </div>
        </div>
        {signal.tone === "warn" ? (
          <div className="grid gap-2 rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-amber-800 dark:text-warning">
            <div className="font-medium">{t("live.stallTitle")}</div>
            <div>{t(stallReason)}</div>
          </div>
        ) : null}
        <div
          ref={scrollRef}
          className="grid min-h-[420px] max-h-[min(68vh,760px)] content-start gap-3 overflow-auto rounded-md border border-border bg-muted/40 p-3"
        >
          {filteredTranscript.map((item) => (
            <RunnerBubble
              key={item.id}
              item={item}
              resolvedPermissions={resolvedPermissions}
              submittedPermissions={submittedPermissions}
              runId={runId}
            />
          ))}
          {!filteredTranscript.length ? (
            <EmptyState title={t("live.waiting")} detail={t("live.subtitle")} />
          ) : null}
        </div>
        <form
          className="grid gap-2 rounded-md border border-border bg-background p-3"
          onSubmit={handleSubmit}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label
              className="text-sm font-medium"
              htmlFor={`run-input-${runId}`}
            >
              {t("live.followUp")}
            </label>
            {ended ? (
              <span className="text-xs text-muted-foreground">
                {t("live.inputDisabled")}
              </span>
            ) : null}
          </div>
          <div className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
            <Textarea
              className="min-h-20 resize-y"
              disabled={ended || submitInput.isPending}
              id={`run-input-${runId}`}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={handlePromptKeyDown}
              placeholder={t("live.inputPlaceholder")}
              value={prompt}
            />
            <Button
              className="w-full self-end sm:w-auto"
              disabled={!prompt.trim() || ended || submitInput.isPending}
              type="submit"
              variant="primary"
            >
              <Send className="h-4 w-4" />
              {submitInput.isPending ? t("live.sending") : t("live.send")}
            </Button>
          </div>
          {inputError ? (
            <div className="text-sm text-destructive">{inputError}</div>
          ) : null}
        </form>
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
  permissionRequest?: PermissionRequest;
};

type RunnerFilter =
  "all" | "agent" | "process" | "tools" | "permission" | "warning" | "error";

type PermissionDecisionPayload = {
  decision: "approve" | "deny" | "cancel";
  option_id?: string;
  reason: string;
};

type TaskProgress = {
  goal: string;
  phase: string;
  status: string;
  nextAction: string;
  tone: "neutral" | "ok" | "warn" | "bad" | "info";
  evidence: string;
};

type RunnerProcessSummary = {
  messageChunks: number;
  progressSignals: number;
  toolCalls: number;
  permissionRequests: number;
  rawAdapterEvents: number;
  lastTool?: RunnerTranscriptItem;
};

function TaskProgressPanel({ progress }: { progress: TaskProgress }) {
  const { t } = useI18n();
  return (
    <div className="grid gap-3 rounded-md border border-border bg-background p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {t("live.taskProgress")}
          </div>
          <div className="mt-1 break-words text-base font-semibold">
            {progress.goal}
          </div>
        </div>
        <Badge tone={progress.tone}>{progress.phase}</Badge>
      </div>
      <div className="grid gap-2 md:grid-cols-3">
        <div className="rounded-md bg-muted/50 p-3">
          <div className="text-xs text-muted-foreground">
            {t("live.currentState")}
          </div>
          <div className="mt-1 font-medium">{progress.status}</div>
        </div>
        <div className="rounded-md bg-muted/50 p-3">
          <div className="text-xs text-muted-foreground">
            {t("live.nextAction")}
          </div>
          <div className="mt-1 font-medium">{progress.nextAction}</div>
        </div>
        <div className="rounded-md bg-muted/50 p-3">
          <div className="text-xs text-muted-foreground">
            {t("live.evidence")}
          </div>
          <div className="mt-1 font-medium">{progress.evidence}</div>
        </div>
      </div>
    </div>
  );
}

function RunnerProcessSummaryPanel({
  summary,
}: {
  summary: RunnerProcessSummary;
}) {
  const { t } = useI18n();
  return (
    <div className="grid gap-3 rounded-md border border-border bg-muted/30 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium">{t("live.processTitle")}</div>
          <div className="text-xs text-muted-foreground">
            {t("live.processDetail")}
          </div>
        </div>
        <Badge tone={summary.toolCalls ? "info" : "neutral"}>
          {summary.toolCalls} {t("live.toolCalls")}
        </Badge>
      </div>
      <div className="grid gap-2 md:grid-cols-4">
        <Metric label={t("live.messageChunks")} value={summary.messageChunks} />
        <Metric
          label={t("live.progressSignals")}
          value={summary.progressSignals}
        />
        <Metric label={t("live.toolCalls")} value={summary.toolCalls} />
        <Metric
          label={t("live.permissionRequests")}
          value={summary.permissionRequests}
        />
      </div>
      {summary.lastTool ? (
        <div className="rounded-md border border-border bg-background p-3 text-sm">
          <div className="mb-1 font-medium">{t("live.lastToolCall")}</div>
          <div className="whitespace-pre-wrap break-words text-muted-foreground">
            {summary.lastTool.body.length > 700
              ? `${summary.lastTool.body.slice(0, 700)}...`
              : summary.lastTool.body}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function RunnerBubble({
  item,
  resolvedPermissions,
  submittedPermissions,
  runId,
}: {
  item: RunnerTranscriptItem;
  resolvedPermissions?: Set<string>;
  submittedPermissions?: Set<string>;
  runId?: string;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [submittedPermissionId, setSubmittedPermissionId] = useState<
    string | null
  >(null);
  const permission = item.permissionRequest;
  const isPendingPermission =
    permission &&
    !resolvedPermissions?.has(permission.permission_id) &&
    !submittedPermissions?.has(permission.permission_id) &&
    submittedPermissionId !== permission.permission_id;
  const isSubmittedPermission =
    permission &&
    submittedPermissions?.has(permission.permission_id) &&
    !resolvedPermissions?.has(permission.permission_id);
  const permissionContext = permission ? permissionContextRows(permission) : [];
  const resolve = useMutation({
    mutationFn: ({
      id,
      option,
    }: {
      id: string;
      option: NonNullable<PermissionRequest["options"]>[number];
    }) => {
      if (!runId) {
        throw new Error("run id is required");
      }
      return runtimeApi.resolveSessionPermission(
        runId,
        id,
        permissionDecisionPayload(option, "resolved from Agent Chat"),
      );
    },
    onSuccess: async (_result, variables) => {
      setSubmittedPermissionId(variables.id);
      if (!runId) {
        return;
      }
      await queryClient.invalidateQueries({
        queryKey: ["runs", runId, "events"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["session", runId, "events"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["runs", runId, "permission-notifications"],
      });
    },
  });
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
        {isPendingPermission ? (
          <div className="mt-3 grid gap-2 rounded-md border border-warning/30 bg-warning/10 p-2">
            <div className="text-xs font-medium text-amber-800 dark:text-warning">
              {t("live.permissionAction")}
            </div>
            <div className="grid gap-1 text-xs opacity-80">
              <div>
                {t("common.token")}: {permission.permission_id}
              </div>
              {permission.tool ? (
                <div>
                  {t("live.permissionTool")}: {permission.tool}
                </div>
              ) : null}
              {permissionContext.map((row) => (
                <div key={row.label}>
                  {t(row.label)}: {row.value}
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {(permission.options?.length
                ? permission.options
                : [{ id: "approve" }, { id: "deny" }]
              ).map((option) => (
                <Button
                  key={option.id}
                  disabled={resolve.isPending}
                  size="sm"
                  variant={
                    permissionDecisionForOption(option) === "cancel"
                      ? "danger"
                      : option.id.toLowerCase().includes("always")
                        ? "secondary"
                        : "primary"
                  }
                  onClick={() =>
                    resolve.mutate({
                      id: permission.permission_id,
                      option,
                    })
                  }
                >
                  {permissionOptionLabel(option)}
                </Button>
              ))}
              <Button
                disabled={resolve.isPending}
                size="sm"
                variant="secondary"
                onClick={() =>
                  downloadJson(
                    `permission-${permission.permission_id}.json`,
                    permission.raw ?? {},
                  )
                }
              >
                <Download className="h-4 w-4" />
                {t("live.permissionPayload")}
              </Button>
            </div>
            {resolve.isSuccess ? (
              <div className="text-xs text-muted-foreground">
                {t("live.permissionSubmitted")}
              </div>
            ) : null}
            {resolve.isError ? (
              <div className="text-xs text-destructive">
                {String(resolve.error)}
              </div>
            ) : null}
          </div>
        ) : null}
        {isSubmittedPermission ? (
          <div className="mt-3 rounded-md border border-sky-500/30 bg-sky-500/10 p-2 text-xs text-sky-700 dark:text-sky-300">
            {t("live.permissionSubmitted")}
          </div>
        ) : null}
        <div className="mt-2 font-mono text-xs opacity-60">
          {item.event_type}
        </div>
      </div>
    </div>
  );
}

function InlinePermissionPanel({
  runId,
  pending,
}: {
  runId: string;
  pending: PermissionRequest[];
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [submittedIds, setSubmittedIds] = useState<Set<string>>(
    () => new Set(),
  );
  const visiblePending = pending.filter(
    (request) => !submittedIds.has(request.permission_id),
  );
  const resolve = useMutation({
    mutationFn: ({
      id,
      option,
    }: {
      id: string;
      option: NonNullable<PermissionRequest["options"]>[number];
    }) =>
      runtimeApi.resolveSessionPermission(
        runId,
        id,
        permissionDecisionPayload(option, "resolved from web console"),
      ),
    onSuccess: async (_result, variables) => {
      setSubmittedIds((current) => new Set(current).add(variables.id));
      await queryClient.invalidateQueries({
        queryKey: ["runs", runId, "events"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["session", runId, "events"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["runs", runId, "permission-notifications"],
      });
    },
  });
  const notifications = useQuery({
    queryKey: ["runs", runId, "permission-notifications"],
    queryFn: () => runtimeApi.permissionNotifications(runId),
    enabled: visiblePending.length > 0,
    refetchInterval: visiblePending.length > 0 ? 5000 : false,
  });
  const retryNotifications = useMutation({
    mutationFn: (permissionId: string) =>
      runtimeApi.retryPermissionNotifications(runId, permissionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["runs", runId, "permission-notifications"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["runs", runId, "events"],
      });
    },
  });
  if (!visiblePending.length) {
    return null;
  }
  const notificationsByPermission = groupPermissionNotifications(
    notifications.data?.notifications ?? [],
  );
  return (
    <Card className="border-warning/40">
      <CardHeader>
        <div>
          <CardTitle>{t("runs.permissionRequests")}</CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("live.permissionPanelDetail")}
          </p>
        </div>
        <Badge tone="warn">
          {visiblePending.length} {t("runs.permissionPending")}
        </Badge>
      </CardHeader>
      <CardBody className="grid gap-3">
        {visiblePending.map((request) => (
          <div
            key={request.permission_id}
            className="rounded-md border border-border p-3"
          >
            <div className="font-medium">
              {request.prompt || request.tool || request.permission_id}
            </div>
            <div className="mt-2 grid gap-1 text-sm text-muted-foreground">
              <div>
                {t("common.token")}: {request.permission_id}
              </div>
              {request.tool ? (
                <div>
                  {t("live.permissionTool")}: {request.tool}
                </div>
              ) : null}
              {permissionContextRows(request).map((row) => (
                <div key={row.label}>
                  {t(row.label)}: {row.value}
                </div>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {(request.options?.length
                ? request.options
                : [{ id: "approve" }, { id: "deny" }]
              ).map((option) => (
                <Button
                  key={option.id}
                  disabled={resolve.isPending}
                  size="sm"
                  variant={
                    permissionDecisionForOption(option) === "cancel"
                      ? "danger"
                      : option.id.toLowerCase().includes("always")
                        ? "secondary"
                        : "primary"
                  }
                  onClick={() =>
                    resolve.mutate({
                      id: request.permission_id,
                      option,
                    })
                  }
                >
                  {permissionOptionLabel(option)}
                </Button>
              ))}
            </div>
            {resolve.isPending ? (
              <div className="mt-2 text-sm text-muted-foreground">
                {t("live.permissionSubmitting")}
              </div>
            ) : null}
            {resolve.isError ? (
              <div className="mt-2 text-sm text-destructive">
                {String(resolve.error)}
              </div>
            ) : null}
            <PermissionNotificationStatus
              notifications={
                notificationsByPermission.get(request.permission_id) ?? []
              }
              isRetrying={retryNotifications.isPending}
              onRetry={() => retryNotifications.mutate(request.permission_id)}
            />
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

function PermissionNotificationStatus({
  notifications,
  isRetrying,
  onRetry,
}: {
  notifications: PermissionNotification[];
  isRetrying: boolean;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  const hasFailure = notifications.some(
    (notification) => notification.status === "failed",
  );
  return (
    <div className="mt-3 rounded-md bg-muted/50 p-2 text-xs">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-muted-foreground">
          {t("runs.notificationStatus")}
        </span>
        {hasFailure ? (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={onRetry}
            disabled={isRetrying}
          >
            <RefreshCw className="size-3.5" />
            {t("runs.notificationRetry")}
          </Button>
        ) : null}
      </div>
      {notifications.length ? (
        <div className="flex flex-wrap gap-2">
          {notifications.map((notification) => (
            <Badge
              key={notification.notification_id}
              tone={permissionNotificationTone(notification.status)}
            >
              {notification.channel}:{notification.status}
            </Badge>
          ))}
        </div>
      ) : (
        <div className="text-muted-foreground">
          {t("runs.notificationNone")}
        </div>
      )}
      {notifications
        .filter((notification) => notification.error)
        .map((notification) => (
          <div
            key={`${notification.notification_id}-error`}
            className="mt-2 break-words text-destructive"
          >
            {notification.error}
          </div>
        ))}
    </div>
  );
}

function MissionsPage() {
  const { t } = useI18n();
  const missions = useQuery({
    queryKey: ["missions"],
    queryFn: runtimeApi.missions,
  });
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: runtimeApi.capabilities,
  });
  return (
    <Page title={t("missions.title")} subtitle={t("missions.subtitle")}>
      <div className="grid gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
        <CreateMissionForm
          adapters={Object.keys(capabilities.data?.adapters ?? { fake: {} })}
        />
        <Card>
          <CardHeader>
            <CardTitle>{t("missions.history")}</CardTitle>
          </CardHeader>
          <CardBody>
            <MissionList missions={missions.data?.missions ?? []} />
          </CardBody>
        </Card>
      </div>
    </Page>
  );
}

function MissionDetailPage() {
  const { t } = useI18n();
  const { missionId } = useParams({ strict: false }) as { missionId: string };
  const queryClient = useQueryClient();
  const mission = useQuery({
    queryKey: ["missions", missionId],
    queryFn: () => runtimeApi.mission(missionId),
  });
  const events = useQuery({
    queryKey: ["missions", missionId, "events"],
    queryFn: () => runtimeApi.missionEvents(missionId),
  });
  const artifacts = useQuery({
    queryKey: ["missions", missionId, "artifacts"],
    queryFn: () => runtimeApi.missionArtifacts(missionId),
  });
  const cancel = useMutation({
    mutationFn: () => runtimeApi.cancelMission(missionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["missions"] });
      await queryClient.invalidateQueries({
        queryKey: ["missions", missionId],
      });
    },
  });
  const override = useMutation({
    mutationFn: (decision: "approve" | "deny") =>
      runtimeApi.overrideReviewGate(missionId, {
        decision,
        reason: `review gate ${decision} from web console`,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["missions"] });
      await queryClient.invalidateQueries({
        queryKey: ["missions", missionId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["missions", missionId, "events"],
      });
    },
  });
  const state = mission.data;
  const missionEvents = events.data?.events ?? [];
  return (
    <Page title={t("missions.detail")} subtitle={missionId}>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid gap-4">
          <Card>
            <CardHeader>
              <div className="min-w-0">
                <CardTitle>{t("missions.state")}</CardTitle>
                <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                  {state?.spec.goal ?? t("missions.loadingGoal")}
                </p>
              </div>
              <div className="flex flex-wrap justify-end gap-2">
                {state ? <StatusBadge status={state.status} /> : null}
                <Button
                  disabled={cancel.isPending || isTerminal(state?.status)}
                  size="sm"
                  onClick={() => cancel.mutate()}
                >
                  <PauseCircle className="h-4 w-4" />
                  {t("common.cancel")}
                </Button>
              </div>
            </CardHeader>
            <CardBody className="grid gap-3 md:grid-cols-4">
              <Metric
                label={t("common.strategy")}
                value={state?.spec.strategy ?? "-"}
              />
              <Metric
                label={t("common.adapter")}
                value={state?.spec.adapter ?? "-"}
              />
              <Metric
                label={t("common.progress")}
                value={`${state?.completed_task_count ?? 0}/${state?.task_count ?? 0}`}
              />
              <Metric
                label={t("common.events")}
                value={state?.event_count ?? "-"}
              />
            </CardBody>
          </Card>
          {state?.status === "blocked" ? (
            <Card className="border-warning/40">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-warning" />
                  <CardTitle>{t("missions.reviewBlocked")}</CardTitle>
                </div>
                <Badge tone="warn">{t("missions.reviewDecision")}</Badge>
              </CardHeader>
              <CardBody className="flex flex-wrap gap-2">
                <Button
                  disabled={override.isPending}
                  size="sm"
                  variant="primary"
                  onClick={() => override.mutate("approve")}
                >
                  {t("missions.approveGate")}
                </Button>
                <Button
                  disabled={override.isPending}
                  size="sm"
                  variant="danger"
                  onClick={() => override.mutate("deny")}
                >
                  {t("missions.denyGate")}
                </Button>
              </CardBody>
            </Card>
          ) : null}
          <MissionChatPanel events={missionEvents} mission={state} />
          <MissionDagPanel mission={state} />
          <MissionEventList events={missionEvents} />
        </div>
        <div className="grid content-start gap-4">
          <MissionArtifactPanel
            missionId={missionId}
            artifacts={artifacts.data?.artifacts ?? []}
          />
          <Card>
            <CardHeader>
              <CardTitle>{t("common.downloads")}</CardTitle>
            </CardHeader>
            <CardBody className="grid gap-2">
              <LinkButton
                href={missionArtifactHref(missionId, "manifest.json")}
              >
                <Download className="h-4 w-4" />
                {t("common.manifest")}
              </LinkButton>
              <LinkButton href={missionArtifactHref(missionId, "events.jsonl")}>
                <Download className="h-4 w-4" />
                {t("common.eventsJsonl")}
              </LinkButton>
              <LinkButton
                href={missionArtifactHref(missionId, "final-report.md")}
              >
                <Download className="h-4 w-4" />
                {t("common.finalReport")}
              </LinkButton>
            </CardBody>
          </Card>
        </div>
      </div>
    </Page>
  );
}

function CreateMissionForm({ adapters }: { adapters: string[] }) {
  const { t } = useI18n();
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
        <CardTitle>{t("missions.create")}</CardTitle>
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
              <Field label={t("common.goal")}>
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
                <Field label={t("common.strategy")}>
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
                <Field label={t("common.adapter")}>
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
            {t("common.start")}
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function ProfilesPage() {
  const { t } = useI18n();
  const profiles = useQuery({
    queryKey: ["profiles"],
    queryFn: runtimeApi.profiles,
  });
  const [draft, setDraft] = useState<AgentProfile | null>(null);
  return (
    <Page title={t("profiles.title")} subtitle={t("profiles.subtitle")}>
      <div className="grid gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
        <ProfileEditor
          key={
            draft ? `${draft.id}-${draft.version}-${draft.display_name}` : "new"
          }
          draft={draft}
          onSaved={() => setDraft(null)}
        />
        <div className="grid gap-4 md:grid-cols-2">
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
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    onClick={() => setDraft(copyProfile(profile))}
                  >
                    <Copy className="h-4 w-4" />
                    {t("common.copy")}
                  </Button>
                  <Button size="sm" onClick={() => setDraft(profile)}>
                    <UserCog className="h-4 w-4" />
                    {t("common.edit")}
                  </Button>
                </div>
                <ProfileJson
                  label={t("profiles.runtime")}
                  value={profile.runtime}
                />
                <ProfileJson
                  label={t("profiles.tools")}
                  value={profile.tools}
                />
                <ProfileJson
                  label={t("profiles.approval")}
                  value={profile.approval}
                />
                <ProfileJson
                  label={t("profiles.limits")}
                  value={profile.limits}
                />
                <ProfileJson
                  label={t("profiles.workspace")}
                  value={profile.workspace}
                />
                <ProfileJson
                  label={t("profiles.artifacts")}
                  value={profile.artifacts}
                />
              </CardBody>
            </Card>
          ))}
        </div>
      </div>
    </Page>
  );
}

function AccessPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [projectId, setProjectId] = useState("default");
  const [projectName, setProjectName] = useState("Default");
  const [tokenName, setTokenName] = useState("operator-token");
  const [createdToken, setCreatedToken] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState("");
  const [userDisplayName, setUserDisplayName] = useState("");
  const [userPassword, setUserPassword] = useState("");
  const [userRole, setUserRole] = useState("member");
  const [userVerified, setUserVerified] = useState(true);
  const policy = useQuery({
    queryKey: ["access", "policy"],
    queryFn: runtimeApi.accessPolicy,
  });
  const projects = useQuery({
    queryKey: ["access", "projects"],
    queryFn: runtimeApi.accessProjects,
  });
  const tokens = useQuery({
    queryKey: ["access", "tokens"],
    queryFn: runtimeApi.apiTokens,
  });
  const users = useQuery({
    queryKey: ["auth", "users"],
    queryFn: runtimeApi.authUsers,
    retry: false,
  });
  const createProject = useMutation({
    mutationFn: runtimeApi.createAccessProject,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["access"] });
    },
  });
  const createToken = useMutation({
    mutationFn: runtimeApi.createApiToken,
    onSuccess: async (token) => {
      setCreatedToken(token.token ?? null);
      await queryClient.invalidateQueries({ queryKey: ["access"] });
    },
  });
  const revokeToken = useMutation({
    mutationFn: runtimeApi.revokeApiToken,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["access"] });
    },
  });
  const createUser = useMutation({
    mutationFn: runtimeApi.createAuthUser,
    onSuccess: async () => {
      setUserEmail("");
      setUserDisplayName("");
      setUserPassword("");
      setUserRole("member");
      setUserVerified(true);
      await queryClient.invalidateQueries({ queryKey: ["auth", "users"] });
    },
  });
  const updateUserRoles = useMutation({
    mutationFn: (payload: { email: string; roles: string[] }) =>
      runtimeApi.updateAuthUserRoles(payload.email, payload.roles),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth", "users"] });
    },
  });
  const updateUserStatus = useMutation({
    mutationFn: (payload: { email: string; status: string }) =>
      runtimeApi.updateAuthUserStatus(payload.email, payload.status),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth", "users"] });
    },
  });
  const resetUserPassword = useMutation({
    mutationFn: (payload: { email: string; password: string }) =>
      runtimeApi.resetAuthUserPassword(payload.email, payload.password),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth", "users"] });
    },
  });
  const principal = policy.data?.current_principal;
  const isOwner = Boolean(principal?.roles.includes("owner"));
  return (
    <Page title={t("access.title")} subtitle={t("access.subtitle")}>
      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-primary" />
              <CardTitle>{t("access.currentPrincipal")}</CardTitle>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge tone="info">{policy.data?.mode ?? "loading"}</Badge>
              <Button
                disabled={!policy.data}
                size="sm"
                onClick={() => downloadJson("access-policy.json", policy.data)}
              >
                <Download className="h-4 w-4" />
                {t("access.export")}
              </Button>
            </div>
          </CardHeader>
          <CardBody className="grid gap-3">
            <Metric
              label={t("access.identity")}
              value={principal?.display_name ?? "-"}
            />
            <Metric
              label={t("access.roles")}
              value={principal?.roles.join(", ") || "-"}
            />
            <ProfileJson
              label={t("access.auditPosture")}
              value={policy.data?.audit ?? {}}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("access.roleMatrix")}</CardTitle>
            <Badge tone="neutral">{policy.data?.roles.length ?? 0}</Badge>
          </CardHeader>
          <CardBody className="grid gap-3">
            {(policy.data?.roles ?? []).map((role) => (
              <div
                key={role.id}
                className="rounded-md border border-border p-3"
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-medium">{role.id}</div>
                    <div className="mt-1 text-sm text-muted-foreground">
                      {role.description}
                    </div>
                  </div>
                  <Badge tone="neutral">{role.permissions.length}</Badge>
                </div>
                <div className="mt-3 flex flex-wrap gap-1">
                  {role.permissions.map((permission) => (
                    <Badge key={permission} tone="neutral">
                      {permission}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{t("access.scopes")}</CardTitle>
          <Badge tone="info">P7 foundation</Badge>
        </CardHeader>
        <CardBody className="flex flex-wrap gap-2">
          {(policy.data?.scopes ?? []).map((scope) => (
            <Badge key={scope} tone="neutral">
              {scope}
            </Badge>
          ))}
        </CardBody>
      </Card>
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <UserCog className="h-4 w-4 text-primary" />
            <CardTitle>{t("access.users")}</CardTitle>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone={isOwner ? "ok" : "warn"}>
              {isOwner ? t("access.ownerControls") : t("access.ownerOnly")}
            </Badge>
            <Badge tone="neutral">{users.data?.users.length ?? 0}</Badge>
          </div>
        </CardHeader>
        <CardBody className="grid gap-4">
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)_160px_auto]">
            <Field label={t("access.userEmail")}>
              <Input
                autoComplete="email"
                inputMode="email"
                type="email"
                value={userEmail}
                onChange={(event) => setUserEmail(event.target.value)}
              />
            </Field>
            <Field label={t("access.displayName")}>
              <Input
                value={userDisplayName}
                onChange={(event) => setUserDisplayName(event.target.value)}
              />
            </Field>
            <Field label={t("access.initialPassword")}>
              <Input
                autoComplete="new-password"
                type="password"
                value={userPassword}
                onChange={(event) => setUserPassword(event.target.value)}
              />
            </Field>
            <Field label={t("access.userRole")}>
              <Select
                value={userRole}
                onChange={(event) => setUserRole(event.target.value)}
              >
                <option value="member">member</option>
                <option value="operator">operator</option>
                <option value="auditor">auditor</option>
                <option value="owner">owner</option>
              </Select>
            </Field>
            <Button
              className="self-end"
              disabled={
                !isOwner ||
                createUser.isPending ||
                !userEmail.trim() ||
                !userPassword
              }
              onClick={() =>
                createUser.mutate({
                  email: userEmail,
                  display_name: userDisplayName || userEmail,
                  password: userPassword,
                  roles: [userRole],
                  email_verified: userVerified,
                })
              }
            >
              <UserCog className="h-4 w-4" />
              {t("common.create")}
            </Button>
          </div>
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <input
              checked={userVerified}
              disabled={!isOwner}
              type="checkbox"
              onChange={(event) => setUserVerified(event.target.checked)}
            />
            {t("access.markEmailVerified")}
          </label>
          {!isOwner ? (
            <div className="rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-amber-800 dark:text-warning">
              {t("access.ownerOnlyDetail")}
            </div>
          ) : null}
          {createUser.isError ? (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              {String(createUser.error)}
            </div>
          ) : null}
          <AccessUserList
            canManage={isOwner}
            currentPrincipalId={principal?.id}
            users={users.data?.users ?? []}
            onResetPassword={(email, password) =>
              resetUserPassword.mutate({ email, password })
            }
            onRoles={(email, roles) => updateUserRoles.mutate({ email, roles })}
            onStatus={(email, status) =>
              updateUserStatus.mutate({ email, status })
            }
          />
        </CardBody>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-primary" />
              <CardTitle>{t("access.projects")}</CardTitle>
            </div>
            <Badge tone="neutral">{projects.data?.projects.length ?? 0}</Badge>
          </CardHeader>
          <CardBody className="grid gap-4">
            <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
              <Field label={t("access.projectId")}>
                <Input
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                />
              </Field>
              <Field label={t("profiles.displayName")}>
                <Input
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                />
              </Field>
              <Button
                className="self-end"
                disabled={!isOwner || createProject.isPending}
                onClick={() =>
                  createProject.mutate({
                    project_id: projectId,
                    display_name: projectName,
                  })
                }
              >
                <Save className="h-4 w-4" />
                {t("common.create")}
              </Button>
            </div>
            <AccessProjectList
              projects={projects.data?.projects ?? policy.data?.projects ?? []}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-primary" />
              <CardTitle>{t("access.apiTokens")}</CardTitle>
            </div>
            <Badge tone="neutral">{tokens.data?.tokens.length ?? 0}</Badge>
          </CardHeader>
          <CardBody className="grid gap-4">
            <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
              <Field label={t("access.tokenName")}>
                <Input
                  value={tokenName}
                  onChange={(event) => setTokenName(event.target.value)}
                />
              </Field>
              <Field label={t("access.projectId")}>
                <Input
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                />
              </Field>
              <Button
                className="self-end"
                disabled={!isOwner || createToken.isPending}
                onClick={() =>
                  createToken.mutate({
                    name: tokenName,
                    project_id: projectId || undefined,
                  })
                }
              >
                <KeyRound className="h-4 w-4" />
                {t("common.create")}
              </Button>
            </div>
            {createdToken ? (
              <div className="rounded-md border border-warning/40 bg-warning/10 p-3">
                <div className="text-sm font-medium">
                  {t("access.newToken")}
                </div>
                <div className="mt-2 break-words font-mono text-xs">
                  {createdToken}
                </div>
              </div>
            ) : null}
            <ApiTokenList
              canManage={isOwner}
              tokens={tokens.data?.tokens ?? policy.data?.tokens ?? []}
              onRevoke={(tokenId) => revokeToken.mutate(tokenId)}
            />
          </CardBody>
        </Card>
      </div>
    </Page>
  );
}

function AccessUserList({
  canManage,
  currentPrincipalId,
  users,
  onResetPassword,
  onRoles,
  onStatus,
}: {
  canManage: boolean;
  currentPrincipalId?: string;
  users: AuthUser[];
  onResetPassword: (email: string, password: string) => void;
  onRoles: (email: string, roles: string[]) => void;
  onStatus: (email: string, status: string) => void;
}) {
  const { t } = useI18n();
  const [roleByEmail, setRoleByEmail] = useState<Record<string, string>>({});
  const [passwordByEmail, setPasswordByEmail] = useState<Record<string, string>>({});
  useEffect(() => {
    setRoleByEmail((current) => {
      const next = { ...current };
      for (const user of users) {
        if (!next[user.email]) {
          next[user.email] = user.roles[0] ?? "member";
        }
      }
      return next;
    });
  }, [users]);
  if (!users.length) {
    return <EmptyState title={t("access.noUsers")} />;
  }
  return (
    <div className="grid gap-2">
      {users.map((user) => (
        <div
          key={user.email}
          className="grid gap-3 rounded-md border border-border p-3 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.9fr)]"
        >
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="truncate font-medium">
                {user.display_name || user.email}
              </span>
              <StatusBadge status={user.status} />
              <Badge tone={user.email_verified_at ? "ok" : "warn"}>
                {user.email_verified_at
                  ? t("access.emailVerified")
                  : t("access.emailUnverified")}
              </Badge>
            </div>
            <div className="mt-1 break-words font-mono text-xs text-muted-foreground">
              {user.email}
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {user.roles.map((role) => (
                <Badge key={role} tone="neutral">
                  {role}
                </Badge>
              ))}
            </div>
            <div className="mt-2 grid gap-1 text-xs text-muted-foreground">
              <span>
                {t("access.createdAt")}: {timeAgo(user.created_at)}
              </span>
              <span>
                {t("access.lastLogin")}:{" "}
                {user.last_login_at ? timeAgo(user.last_login_at) : "-"}
              </span>
            </div>
          </div>
          <div className="grid gap-3">
            <div className="grid gap-2 sm:grid-cols-[1fr_auto_auto]">
              <Field label={t("access.userRole")}>
                <Select
                  disabled={!canManage}
                  value={roleByEmail[user.email] ?? user.roles[0] ?? "member"}
                  onChange={(event) =>
                    setRoleByEmail((current) => ({
                      ...current,
                      [user.email]: event.target.value,
                    }))
                  }
                >
                  <option value="member">member</option>
                  <option value="operator">operator</option>
                  <option value="auditor">auditor</option>
                  <option value="owner">owner</option>
                </Select>
              </Field>
              <Button
                className="self-end"
                disabled={!canManage}
                onClick={() =>
                  onRoles(user.email, [
                    roleByEmail[user.email] ?? user.roles[0] ?? "member",
                  ])
                }
              >
                <Save className="h-4 w-4" />
                {t("access.saveRole")}
              </Button>
              <Button
                className="self-end"
                disabled={!canManage || user.email === currentPrincipalId}
                onClick={() =>
                  onStatus(
                    user.email,
                    user.status === "active" ? "disabled" : "active",
                  )
                }
              >
                {user.status === "active" ? (
                  <PauseCircle className="h-4 w-4" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                {user.status === "active"
                  ? t("access.disableUser")
                  : t("access.enableUser")}
              </Button>
            </div>
            <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
              <Field label={t("access.newPassword")}>
                <Input
                  autoComplete="new-password"
                  disabled={!canManage}
                  type="password"
                  value={passwordByEmail[user.email] ?? ""}
                  onChange={(event) =>
                    setPasswordByEmail((current) => ({
                      ...current,
                      [user.email]: event.target.value,
                    }))
                  }
                />
              </Field>
              <Button
                className="self-end"
                disabled={!canManage || !passwordByEmail[user.email]}
                onClick={() => {
                  onResetPassword(user.email, passwordByEmail[user.email] ?? "");
                  setPasswordByEmail((current) => ({
                    ...current,
                    [user.email]: "",
                  }));
                }}
              >
                <KeyRound className="h-4 w-4" />
                {t("access.resetPassword")}
              </Button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function AccessProjectList({ projects }: { projects: AccessProject[] }) {
  const { t } = useI18n();
  if (!projects.length) {
    return <EmptyState title={t("access.noProjects")} />;
  }
  return (
    <div className="grid gap-2">
      {projects.map((project) => (
        <div
          key={project.project_id}
          className="rounded-md border border-border p-3"
        >
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="font-medium">{project.display_name}</div>
              <div className="mt-1 font-mono text-xs text-muted-foreground">
                {project.project_id}
              </div>
            </div>
            <StatusBadge status={project.status} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ApiTokenList({
  canManage,
  tokens,
  onRevoke,
}: {
  canManage: boolean;
  tokens: ApiToken[];
  onRevoke: (tokenId: string) => void;
}) {
  const { t } = useI18n();
  if (!tokens.length) {
    return <EmptyState title={t("access.noApiTokens")} />;
  }
  return (
    <div className="grid gap-2">
      {tokens.map((token) => (
        <div
          key={token.token_id}
          className="grid gap-3 rounded-md border border-border p-3 md:grid-cols-[minmax(0,1fr)_auto]"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="truncate font-medium">{token.name}</span>
              <StatusBadge status={token.status} />
            </div>
            <div className="mt-1 font-mono text-xs text-muted-foreground">
              {token.token_id} / {token.token_prefix}
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {token.scopes.map((scope) => (
                <Badge key={scope} tone="neutral">
                  {scope}
                </Badge>
              ))}
            </div>
          </div>
          <Button
            disabled={!canManage || token.status !== "active"}
            size="sm"
            variant="danger"
            onClick={() => onRevoke(token.token_id)}
          >
            {t("access.revoke")}
          </Button>
        </div>
      ))}
    </div>
  );
}

function ProfileEditor({
  draft,
  onSaved,
}: {
  draft: AgentProfile | null;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const createProfile = useMutation({
    mutationFn: runtimeApi.createProfile,
    onSuccess: async () => {
      setError(null);
      onSaved();
      await queryClient.invalidateQueries({ queryKey: ["profiles"] });
      await queryClient.invalidateQueries({ queryKey: ["capabilities"] });
    },
    onError: (err) => setError(String(err)),
  });
  const defaultProfile = draft ?? emptyProfile();
  const form = useForm({
    defaultValues: {
      id: defaultProfile.id,
      display_name: defaultProfile.display_name,
      description: defaultProfile.description,
      runtime: prettyJson(defaultProfile.runtime),
      tools: prettyJson(defaultProfile.tools),
      approval: prettyJson(defaultProfile.approval),
      limits: prettyJson(defaultProfile.limits),
      workspace: prettyJson(defaultProfile.workspace),
      artifacts: prettyJson(defaultProfile.artifacts),
    },
    onSubmit: async ({ value }) => {
      try {
        await createProfile.mutateAsync({
          id: value.id,
          display_name: value.display_name,
          description: value.description,
          runtime: parseJsonObject(value.runtime, "runtime"),
          tools: parseJsonObject(value.tools, "tools"),
          approval: parseJsonObject(value.approval, "approval"),
          limits: parseJsonObject(value.limits, "limits"),
          workspace: parseJsonObject(value.workspace, "workspace"),
          artifacts: parseJsonObject(value.artifacts, "artifacts"),
        });
      } catch (err) {
        setError(String(err));
      }
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("profiles.editor")}</CardTitle>
        <Badge tone="info">{t("profiles.versioned")}</Badge>
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
          <div className="grid gap-3 md:grid-cols-2">
            <form.Field name="id">
              {(field) => (
                <Field label={t("profiles.id")}>
                  <Input
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                  />
                </Field>
              )}
            </form.Field>
            <form.Field name="display_name">
              {(field) => (
                <Field label={t("profiles.displayName")}>
                  <Input
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                  />
                </Field>
              )}
            </form.Field>
          </div>
          <form.Field name="description">
            {(field) => (
              <Field label={t("profiles.description")}>
                <Textarea
                  className="min-h-20"
                  value={field.state.value}
                  onChange={(event) => field.handleChange(event.target.value)}
                />
              </Field>
            )}
          </form.Field>
          {(
            [
              "runtime",
              "tools",
              "approval",
              "limits",
              "workspace",
              "artifacts",
            ] as const
          ).map((name) => (
            <form.Field key={name} name={name}>
              {(field) => (
                <Field label={`${name} JSON`}>
                  <Textarea
                    className="min-h-24 font-mono text-xs"
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                  />
                </Field>
              )}
            </form.Field>
          ))}
          {error ? (
            <div className="rounded-md border border-destructive/30 p-3 text-sm text-destructive">
              {error}
            </div>
          ) : null}
          <Button
            disabled={createProfile.isPending}
            type="submit"
            variant="primary"
          >
            <Save className="h-4 w-4" />
            {t("profiles.save")}
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function OperationsPage() {
  const { t } = useI18n();
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
  const cost = useQuery({
    queryKey: ["cost"],
    queryFn: runtimeApi.costStatus,
  });
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
    <Page title={t("operations.title")} subtitle={t("operations.subtitle")}>
      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <Card>
          <CardHeader>
            <CardTitle>{t("operations.drills")}</CardTitle>
            <Button
              size="sm"
              variant="primary"
              onClick={() => runDrills.mutate()}
            >
              <ShieldCheck className="h-4 w-4" />
              {t("operations.runDrills")}
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
            <CardTitle>{t("operations.backups")}</CardTitle>
            <Button
              disabled={createBackup.isPending}
              size="sm"
              onClick={() => createBackup.mutate()}
            >
              <Download className="h-4 w-4" />
              {t("operations.createBackup")}
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
              <EmptyState title={t("operations.noBackups")} />
            ) : null}
          </CardBody>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <CostBudgetPanel cost={cost.data} />
        <Card>
          <CardHeader>
            <CardTitle>{t("operations.p5Evaluations")}</CardTitle>
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
            <CardTitle>{t("operations.runtimeStatus")}</CardTitle>
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

function CostBudgetPanel({ cost }: { cost?: CostStatus }) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <WalletCards className="h-4 w-4 text-primary" />
          <CardTitle>{t("operations.costBudget")}</CardTitle>
        </div>
        <StatusBadge status={cost?.status ?? "loading"} />
      </CardHeader>
      <CardBody className="grid gap-3 md:grid-cols-3">
        <Metric
          label={t("common.month")}
          value={cost?.month ?? "-"}
          detail="UTC"
        />
        <Metric
          label={t("common.estimated")}
          value={money(cost?.monthly_estimated_cost_usd)}
          detail={`${cost?.runs.length ?? 0} runs`}
        />
        <Metric
          label={t("common.budget")}
          value={money(cost?.monthly_budget_usd)}
          detail={
            cost?.warning_threshold_usd == null
              ? "unconfigured"
              : `warn at ${money(cost.warning_threshold_usd)}`
          }
        />
      </CardBody>
    </Card>
  );
}

function RunList({ runs }: { runs: RunState[] }) {
  const { t } = useI18n();
  if (!runs.length) {
    return (
      <EmptyState title={t("runs.noRuns")} detail={t("runs.noRunsDetail")} />
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
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("overview.recentRuns")}</CardTitle>
        <Link className="text-sm text-primary" to="/runs">
          {t("overview.viewAll")}
        </Link>
      </CardHeader>
      <CardBody>
        <RunList runs={runs.slice(0, 5)} />
      </CardBody>
    </Card>
  );
}

function MissionList({ missions }: { missions: MissionState[] }) {
  const { t } = useI18n();
  if (!missions.length) {
    return (
      <EmptyState
        title={t("missions.noMissions")}
        detail={t("missions.noMissionsDetail")}
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
            <Link
              className="inline-flex h-8 items-center gap-2 rounded-md border border-border px-2 text-xs font-medium text-primary hover:bg-muted"
              to="/missions/$missionId"
              params={{ missionId: mission.mission_id }}
            >
              <GitBranch className="h-4 w-4" />
              {t("missions.openDetail")}
            </Link>
            <LinkButton
              href={missionArtifactHref(mission.mission_id, "manifest.json")}
              size="sm"
            >
              <Download className="h-4 w-4" />
              {t("common.manifest")}
            </LinkButton>
            <LinkButton
              href={missionArtifactHref(mission.mission_id, "final-report.md")}
              size="sm"
            >
              <Download className="h-4 w-4" />
              {t("missions.report")}
            </LinkButton>
          </div>
        </div>
      ))}
    </div>
  );
}

type MissionChatItem = {
  id: string;
  title: string;
  body: string;
  status: string;
  time?: string;
  runId?: string | null;
  sequence: number;
};

function MissionChatPanel({
  events,
  mission,
}: {
  events: MissionEvent[];
  mission?: MissionState;
}) {
  const { t } = useI18n();
  const runIds = useMemo(
    () =>
      Array.from(
        new Set(
          (mission?.tasks ?? [])
            .map((task) => task.run_id)
            .filter((runId): runId is string => Boolean(runId)),
        ),
      ),
    [mission?.tasks],
  );
  const runEventQueries = useQueries({
    queries: runIds.map((runId) => ({
      queryKey: ["runs", runId, "events"],
      queryFn: () => runtimeApi.runEvents(runId),
      refetchInterval: 5000,
      retry: 1,
    })),
  });
  const runOutputById = useMemo(() => {
    const outputs: Record<string, string> = {};
    runIds.forEach((runId, index) => {
      const output = latestRunOutput(
        runEventQueries[index]?.data?.events ?? [],
      );
      if (output) {
        outputs[runId] = output;
      }
    });
    return outputs;
  }, [runIds, runEventQueries]);
  const items = missionChatItems(mission, events, runOutputById);
  return (
    <Card>
      <CardHeader>
        <div className="flex min-w-0 items-center gap-2">
          <MessageSquare className="h-4 w-4 text-primary" />
          <CardTitle>{t("missions.chat")}</CardTitle>
        </div>
        <Badge tone="info">{items.length}</Badge>
      </CardHeader>
      <CardBody className="grid max-h-[620px] gap-3 overflow-auto">
        {items.map((item) => (
          <div
            key={item.id}
            className="grid gap-2 rounded-md border border-border bg-muted/30 p-3 text-sm"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate font-medium">{item.title}</div>
                {item.time ? (
                  <div className="text-xs text-muted-foreground">
                    {timeAgo(item.time)}
                  </div>
                ) : null}
              </div>
              <StatusBadge status={item.status} />
            </div>
            <div className="whitespace-pre-wrap break-words leading-6">
              {item.body}
            </div>
            {item.runId ? (
              <Link
                className="inline-flex items-center gap-2 text-xs text-primary"
                to="/runs/$runId"
                params={{ runId: item.runId }}
              >
                <MessageSquare className="h-4 w-4" />
                {t("missions.openRun")}
              </Link>
            ) : null}
          </div>
        ))}
        {!items.length ? (
          <EmptyState
            title={t("missions.noMissionChat")}
            detail={t("missions.noMissionChatDetail")}
          />
        ) : null}
      </CardBody>
    </Card>
  );
}

function MissionDagPanel({ mission }: { mission?: MissionState }) {
  const { t } = useI18n();
  const tasks = mission?.tasks ?? [];
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-primary" />
          <CardTitle>{t("missions.taskDag")}</CardTitle>
        </div>
        <Badge tone="neutral">{tasks.length}</Badge>
      </CardHeader>
      <CardBody className="grid gap-3">
        {tasks.map((task) => (
          <div
            key={task.task_id}
            className="grid gap-3 rounded-md border border-border p-3 lg:grid-cols-[220px_minmax(0,1fr)_180px]"
          >
            <div className="min-w-0">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-medium">{task.title}</span>
                <StatusBadge status={task.status} />
              </div>
              <div className="mt-1 font-mono text-xs text-muted-foreground">
                {task.task_id}
              </div>
            </div>
            <div className="grid gap-2 text-sm">
              <div>
                <span className="text-muted-foreground">
                  {t("common.profile")}{" "}
                </span>
                <span className="font-medium">{task.profile_id}</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {(task.depends_on.length ? task.depends_on : ["root"]).map(
                  (dependency) => (
                    <Badge key={dependency} tone="neutral">
                      {dependency}
                    </Badge>
                  ),
                )}
              </div>
            </div>
            <div className="grid content-start gap-2">
              {task.run_id ? (
                <Link
                  className="inline-flex items-center gap-2 text-sm text-primary"
                  to="/runs/$runId"
                  params={{ runId: task.run_id }}
                >
                  <MessageSquare className="h-4 w-4" />
                  {t("missions.openRun")}
                </Link>
              ) : (
                <span className="text-sm text-muted-foreground">
                  Waiting for dependencies
                </span>
              )}
              {task.result ? (
                <details className="text-xs">
                  <summary className="cursor-pointer text-muted-foreground">
                    {t("common.result")}
                  </summary>
                  <pre className="mt-2 max-h-32 overflow-auto rounded-md bg-slate-950 p-2 text-slate-100">
                    {JSON.stringify(task.result, null, 2)}
                  </pre>
                </details>
              ) : null}
            </div>
          </div>
        ))}
        {!tasks.length ? <EmptyState title={t("missions.noTasks")} /> : null}
      </CardBody>
    </Card>
  );
}

function MissionEventList({ events }: { events: MissionEvent[] }) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("missions.events")}</CardTitle>
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
        {!events.length ? <EmptyState title={t("missions.noEvents")} /> : null}
      </CardBody>
    </Card>
  );
}

function MissionArtifactPanel({
  missionId,
  artifacts,
}: {
  missionId: string;
  artifacts: ArtifactInfo[];
}) {
  const { t } = useI18n();
  const [previewName, setPreviewName] = useState<string | null>(null);
  const selectedArtifact = artifacts.find(
    (artifact) => artifact.name === previewName,
  );
  const preview = useQuery({
    queryKey: ["missions", missionId, "artifact-preview", previewName],
    queryFn: () =>
      fetchTextArtifact(missionArtifactHref(missionId, previewName ?? "")),
    enabled: Boolean(previewName && selectedArtifact),
    retry: 1,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("common.artifacts")}</CardTitle>
        <Badge tone="neutral">{artifacts.length}</Badge>
      </CardHeader>
      <CardBody className="grid gap-2">
        {artifacts.map((artifact) => (
          <div
            key={artifact.name}
            className="grid gap-3 rounded-md border border-border p-3 text-sm"
          >
            <div className="min-w-0">
              <div className="break-words font-medium">{artifact.name}</div>
              <div className="text-xs text-muted-foreground">
                {formatBytes(artifact.size_bytes)}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={!canPreviewArtifact(artifact)}
                size="sm"
                onClick={() => setPreviewName(artifact.name)}
              >
                <FileText className="h-4 w-4" />
                {t("common.preview")}
              </Button>
              <LinkButton
                href={missionArtifactHref(missionId, artifact.name)}
                size="sm"
              >
                <Download className="h-4 w-4" />
                {t("common.download")}
              </LinkButton>
            </div>
          </div>
        ))}
        {!artifacts.length ? (
          <EmptyState title={t("missions.noArtifacts")} />
        ) : null}
        {selectedArtifact ? (
          <div className="mt-2 grid gap-2 rounded-md border border-border bg-muted/30 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="font-medium">{t("runs.artifactPreview")}</div>
                <div className="break-words text-xs text-muted-foreground">
                  {selectedArtifact.name} ·{" "}
                  {formatBytes(selectedArtifact.size_bytes)}
                </div>
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setPreviewName(null)}
              >
                {t("common.close")}
              </Button>
            </div>
            {preview.isLoading ? (
              <div className="text-sm text-muted-foreground">
                {t("common.loading")}
              </div>
            ) : preview.isError ? (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                {String(preview.error)}
              </div>
            ) : (
              <pre className="max-h-[520px] overflow-auto rounded-md bg-slate-950 p-3 text-xs leading-5 text-slate-100">
                {preview.data}
              </pre>
            )}
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function RecentMissions({ missions }: { missions: MissionState[] }) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("overview.recentMissions")}</CardTitle>
        <Link className="text-sm text-primary" to="/missions">
          {t("overview.viewAll")}
        </Link>
      </CardHeader>
      <CardBody>
        <MissionList missions={missions.slice(0, 3)} />
      </CardBody>
    </Card>
  );
}

function EventList({ events }: { events: RuntimeEvent[] }) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("common.eventStream")}</CardTitle>
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
        {!events.length ? <EmptyState title={t("runs.noEvents")} /> : null}
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
  const { t } = useI18n();
  const [previewName, setPreviewName] = useState<string | null>(null);
  const selectedArtifact = artifacts.find(
    (artifact) => artifact.name === previewName,
  );
  const preview = useQuery({
    queryKey: ["runs", runId, "artifact-preview", previewName],
    queryFn: () => fetchTextArtifact(artifactHref(runId, previewName ?? "")),
    enabled: Boolean(previewName && selectedArtifact),
    retry: 1,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("common.artifacts")}</CardTitle>
        <Badge tone="neutral">{artifacts.length}</Badge>
      </CardHeader>
      <CardBody className="grid gap-2">
        {artifacts.map((artifact) => (
          <div
            key={artifact.name}
            className="grid gap-3 rounded-md border border-border p-3 text-sm"
          >
            <div className="min-w-0">
              <div className="break-words font-medium">{artifact.name}</div>
              <div className="text-xs text-muted-foreground">
                {formatBytes(artifact.size_bytes)}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={!canPreviewArtifact(artifact)}
                size="sm"
                onClick={() => setPreviewName(artifact.name)}
              >
                <FileText className="h-4 w-4" />
                {t("common.preview")}
              </Button>
              <LinkButton href={artifactHref(runId, artifact.name)} size="sm">
                <Download className="h-4 w-4" />
                {t("common.download")}
              </LinkButton>
            </div>
          </div>
        ))}
        {!artifacts.length ? (
          <EmptyState title={t("runs.noArtifacts")} />
        ) : null}
        {selectedArtifact ? (
          <div className="mt-2 grid gap-2 rounded-md border border-border bg-muted/30 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="font-medium">{t("runs.artifactPreview")}</div>
                <div className="break-words text-xs text-muted-foreground">
                  {selectedArtifact.name} ·{" "}
                  {formatBytes(selectedArtifact.size_bytes)}
                </div>
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setPreviewName(null)}
              >
                {t("common.close")}
              </Button>
            </div>
            {preview.isLoading ? (
              <div className="text-sm text-muted-foreground">
                {t("common.loading")}
              </div>
            ) : preview.isError ? (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                {String(preview.error)}
              </div>
            ) : (
              <pre className="max-h-[520px] overflow-auto rounded-md bg-slate-950 p-3 text-xs leading-5 text-slate-100">
                {preview.data}
              </pre>
            )}
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function canPreviewArtifact(artifact: ArtifactInfo) {
  if (artifact.size_bytes > 256 * 1024) {
    return false;
  }
  return /\.(json|jsonl|md|txt|log|csv|yaml|yml)$/i.test(artifact.name);
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

function emptyProfile(): AgentProfile {
  return {
    id: "custom-profile",
    display_name: "Custom Profile",
    description: "Describe when this Agent profile should be used.",
    version: 1,
    source: "user",
    runtime: { preferred_adapter: "qwen" },
    tools: { allow: [], deny: [] },
    approval: { mode: "ask" },
    limits: { max_turns: 40, timeout_seconds: 1800 },
    workspace: { strategy: "per_run" },
    artifacts: { required: ["final-report.md"] },
    metadata: {},
  };
}

function copyProfile(profile: AgentProfile): AgentProfile {
  return {
    ...profile,
    id: `${profile.id}-copy`,
    display_name: `${profile.display_name} Copy`,
    source: "user",
    version: 1,
  };
}

function prettyJson(value: Record<string, unknown> | undefined) {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseJsonObject(value: string, label: string) {
  const parsed = JSON.parse(value || "{}") as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object`);
  }
  return parsed as Record<string, unknown>;
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

function groupPermissionNotifications(notifications: PermissionNotification[]) {
  const grouped = new Map<string, PermissionNotification[]>();
  for (const notification of notifications) {
    const current = grouped.get(notification.permission_id) ?? [];
    current.push(notification);
    grouped.set(notification.permission_id, current);
  }
  return grouped;
}

function permissionNotificationTone(status: string) {
  if (status === "sent") {
    return "ok";
  }
  if (status === "failed") {
    return "bad";
  }
  if (status === "queued") {
    return "warn";
  }
  return "neutral";
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

function mergeDaemonEvents(current: DaemonEvent[], incoming: DaemonEvent[]) {
  if (!incoming.length) {
    return current;
  }
  const byId = new Map<string, DaemonEvent>();
  for (const event of [...current, ...incoming]) {
    byId.set(String(event.id), event);
  }
  const merged = [...byId.values()].sort(
    (left, right) => daemonSequence(left) - daemonSequence(right),
  );
  if (
    merged.length === current.length &&
    merged.every(
      (event, index) => String(event.id) === String(current[index]?.id),
    )
  ) {
    return current;
  }
  return merged;
}

function pendingPermissionRequests(events: RuntimeEvent[]) {
  if (events.some((event) => isTerminalEvent(event.type))) {
    return [];
  }
  const resolved = resolvedPermissionIds(events);
  const submitted = permissionResolveRequestedIds(events);
  const seen = new Set<string>();
  return events
    .map(extractPermissionRequest)
    .filter((request): request is PermissionRequest => Boolean(request))
    .filter((request) => {
      if (
        seen.has(request.permission_id) ||
        resolved.has(request.permission_id) ||
        submitted.has(request.permission_id)
      ) {
        return false;
      }
      seen.add(request.permission_id);
      return true;
    });
}

function permissionResolveRequestedIds(events: RuntimeEvent[]) {
  const submitted = new Set<string>();
  for (const event of events) {
    if (event.type !== "permission.resolve_requested") {
      continue;
    }
    const permissionId = permissionEventId(event);
    if (permissionId) {
      submitted.add(permissionId);
    }
  }
  return submitted;
}

function permissionDecisionForOption(
  option: NonNullable<PermissionRequest["options"]>[number],
): PermissionDecisionPayload["decision"] {
  const value = `${option.id} ${option.label ?? ""}`.toLowerCase();
  if (
    value.includes("cancel") ||
    value.includes("reject") ||
    value.includes("deny")
  ) {
    return "cancel";
  }
  return "approve";
}

function permissionDecisionPayload(
  option: NonNullable<PermissionRequest["options"]>[number],
  reason: string,
): PermissionDecisionPayload {
  return {
    decision: permissionDecisionForOption(option),
    option_id: option.id,
    reason,
  };
}

function permissionOptionLabel(
  option: NonNullable<PermissionRequest["options"]>[number],
) {
  const decision = permissionDecisionForOption(option);
  if (option.label) {
    return option.label;
  }
  if (decision === "cancel") {
    return "Reject";
  }
  return option.id === "approve" ? "Approve" : option.id;
}

function runTaskProgress(
  run: RunState | undefined,
  events: RuntimeEvent[],
  artifacts: ArtifactInfo[],
  workers: WorkerInfo[] = [],
): TaskProgress {
  const latest = events.at(-1);
  const pending = pendingPermissionRequests(events);
  const submitted = permissionResolveRequestedIds(events);
  const resolved = resolvedPermissionIds(events);
  const goal =
    run?.spec.prompt?.trim() ||
    stringValue(
      events.find((event) => event.type === "input.accepted")?.data
        .prompt_preview,
    ) ||
    "Run request";
  const evidence = latest
    ? `${latest.type} #${latest.sequence}`
    : run?.status
      ? `run.${run.status}`
      : "waiting";
  const terminalStatus = effectiveTerminalStatus(run?.status, events);
  if (terminalStatus === "completed") {
    const finalArtifact =
      artifacts.find((artifact) => artifact.name.includes("final")) ??
      artifacts.at(0);
    return {
      goal,
      phase: "已完成",
      status: "Runner 已完成本次执行。",
      nextAction: finalArtifact
        ? `查看产物 ${finalArtifact.name} 或下载审计包。`
        : "下载事件和审计包完成复盘。",
      tone: "ok",
      evidence,
    };
  }
  if (terminalStatus === "failed") {
    return {
      goal,
      phase: "失败",
      status: "执行器或适配器报告失败。",
      nextAction: "查看错误事件、诊断信息和审计包后重试。",
      tone: "bad",
      evidence,
    };
  }
  if (terminalStatus === "cancelled") {
    return {
      goal,
      phase: "已取消",
      status: "Run 已停止，不会再产生新的模型输出。",
      nextAction: "如需继续，请创建新的 Run。",
      tone: "warn",
      evidence,
    };
  }
  if (pending.length) {
    return {
      goal,
      phase: "等待权限审批",
      status: "Runner 已暂停在需要人工确认的操作前。",
      nextAction: "请在上方权限卡片批准或拒绝。",
      tone: "warn",
      evidence,
    };
  }
  if (submitted.size > resolved.size) {
    return {
      goal,
      phase: "等待执行单元应用审批",
      status: "决策已写入控制面，正在等待 worker 拉取并应用。",
      nextAction: "保持页面打开，稍后查看实时输出是否继续推进。",
      tone: "info",
      evidence,
    };
  }
  if (run?.status === "queued" || latest?.type === "run.queued") {
    const activeWorkers = workers.filter(
      (worker) => worker.status === "active",
    );
    const hasCapacity = activeWorkers.some(
      (worker) => worker.active_count < worker.capacity,
    );
    return {
      goal,
      phase: "排队中",
      status: activeWorkers.length
        ? "Run 已进入队列，正在等待执行单元释放容量或认领租约。"
        : "Run 已进入队列，但当前没有 active 执行单元。",
      nextAction: hasCapacity
        ? "等待 worker 下一次轮询；如果长时间不动，请检查 worker 日志和控制地址。"
        : "到执行单元页面注册/恢复 worker，或排空高负载机器后重试。",
      tone: activeWorkers.length ? "info" : "warn",
      evidence,
    };
  }
  if (latest?.type.endsWith(".failed")) {
    return {
      goal,
      phase: "失败",
      status: "执行器或适配器报告失败。",
      nextAction: "查看错误事件、诊断信息和审计包后重试。",
      tone: "bad",
      evidence,
    };
  }
  return {
    goal,
    phase: "执行中",
    status: "Runner 正在接收模型、工具和控制面事件。",
    nextAction: "关注下方实时对话；出现权限卡片时及时处理。",
    tone: "ok",
    evidence,
  };
}

function daemonRunnerTranscript(events: DaemonEvent[]): RunnerTranscriptItem[] {
  const items: RunnerTranscriptItem[] = [];
  const agentMessages = new Map<string, RunnerTranscriptItem>();
  const progressMessages = new Map<string, RunnerTranscriptItem>();

  for (const event of events) {
    const update = daemonSessionUpdate(event);
    const sessionUpdate = stringValue(update?.sessionUpdate);
    const base = daemonBaseTranscriptItem(event);

    if (
      event.type === "session_update" &&
      sessionUpdate === "agent_message_chunk"
    ) {
      const text = daemonContentText(update) ?? "";
      if (!text.trim()) {
        continue;
      }
      const key = "daemon-agent-current";
      const existing = agentMessages.get(key);
      if (existing) {
        existing.body = `${existing.body}${text}`;
        existing.sequence = base.sequence;
        existing.created_at = base.created_at;
      } else {
        const item: RunnerTranscriptItem = {
          ...base,
          id: key,
          role: "agent",
          title: "Agent output",
          body: text,
        };
        agentMessages.set(key, item);
        items.push(item);
      }
      continue;
    }

    if (
      event.type === "session_update" &&
      sessionUpdate === "agent_thought_chunk"
    ) {
      const key = "daemon-agent-progress";
      const existing = progressMessages.get(key);
      if (existing) {
        existing.sequence = base.sequence;
        existing.created_at = base.created_at;
      } else {
        const item: RunnerTranscriptItem = {
          ...base,
          id: key,
          role: "system",
          title: "Agent progress",
          body: "Model is analyzing the request and preparing the next action.",
        };
        progressMessages.set(key, item);
        items.push(item);
      }
      continue;
    }

    const item = daemonTranscriptItemForEvent(event);
    if (item) {
      items.push(item);
    }
  }

  return items.sort((left, right) => left.sequence - right.sequence);
}

function daemonTranscriptItemForEvent(
  event: DaemonEvent,
): RunnerTranscriptItem | null {
  const base = daemonBaseTranscriptItem(event);
  const update = daemonSessionUpdate(event);
  const sessionUpdate = stringValue(update?.sessionUpdate);
  if (event.type === "session_update") {
    if (sessionUpdate === "user_message_chunk") {
      return {
        ...base,
        role: "operator",
        title: "Prompt submitted",
        body: daemonContentText(update) ?? "User input was accepted.",
      };
    }
    if (sessionUpdate === "tool_call" || sessionUpdate === "tool_call_update") {
      return {
        ...base,
        role: daemonToolRole(update),
        title: daemonToolTitle(update),
        body: daemonToolBody(update),
      };
    }
    if (sessionUpdate === "status") {
      const status = recordValue(update?.status);
      return {
        ...base,
        role: "system",
        title: stringValue(status?.eventType) ?? "Status",
        body: stringValue(status?.message) ?? compactJson(update),
      };
    }
    return null;
  }
  if (event.type === "shell_output") {
    const stdout = stringValue(event.data.stdout);
    const stderr = stringValue(event.data.stderr);
    return {
      ...base,
      role: stderr ? "warning" : "system",
      title: "Shell output",
      body:
        [stdout, stderr].filter(Boolean).join("\n") || compactJson(event.data),
    };
  }
  if (event.type === "permission_request") {
    const permission = daemonPermissionRequest(event);
    return {
      ...base,
      role: "warning",
      title: "Permission required",
      body: permission?.prompt ?? permission?.tool ?? compactJson(event.data),
      permissionRequest: permission ?? undefined,
    };
  }
  if (event.type === "permission_resolved") {
    return {
      ...base,
      role: "success",
      title: "Permission resolved",
      body: `Decision: ${stringValue(event.data.decision) ?? "recorded"}`,
    };
  }
  if (event.type === "turn_complete") {
    return {
      ...base,
      role: "success",
      title: "Runner completed",
      body: "Runner completed this turn.",
    };
  }
  if (event.type === "turn_error") {
    return {
      ...base,
      role: "error",
      title: "Runner error",
      body: stringValue(event.data.message) ?? compactJson(event.data),
    };
  }
  if (event.type === "prompt_cancelled") {
    return {
      ...base,
      role: "warning",
      title: "Prompt cancelled",
      body: stringValue(event.data.reason) ?? "Prompt was cancelled.",
    };
  }
  if (event.type === "stream_error") {
    return {
      ...base,
      role: "warning",
      title: "Stream recovered",
      body: stringValue(event.data.message) ?? compactJson(event.data),
    };
  }
  return {
    ...base,
    role: "system",
    title: event.type,
    body: compactJson(event.data),
  };
}

function daemonBaseTranscriptItem(event: DaemonEvent) {
  return {
    id: String(event.id),
    created_at: daemonCreatedAt(event),
    event_type: event.type,
    sequence: daemonSequence(event),
  };
}

function daemonSessionUpdate(event: DaemonEvent) {
  return recordValue(event.data.update) ?? recordValue(event.data);
}

function daemonContentText(update: Record<string, unknown> | null) {
  if (!update) {
    return null;
  }
  const content = update.content;
  const contentRecord = recordValue(content);
  if (contentRecord) {
    return stringValue(contentRecord.text);
  }
  if (!Array.isArray(content)) {
    return null;
  }
  return content
    .map((item) => {
      const itemRecord = recordValue(item);
      const nested = recordValue(itemRecord?.content);
      return stringValue(nested?.text) ?? stringValue(itemRecord?.text);
    })
    .filter(Boolean)
    .join("\n");
}

function daemonToolPayload(update: Record<string, unknown> | null) {
  return recordValue(update?.toolCall) ?? update;
}

function daemonToolTitle(update: Record<string, unknown> | null) {
  const tool = daemonToolPayload(update);
  const status = stringValue(tool?.status) ?? stringValue(update?.status);
  const name =
    stringValue(tool?.name) ??
    stringValue(tool?.title) ??
    stringValue(update?.title) ??
    "Tool call";
  return status ? `${name} · ${status}` : name;
}

function daemonToolBody(update: Record<string, unknown> | null) {
  const tool = daemonToolPayload(update);
  const input = tool?.input ?? tool?.rawInput;
  const output = tool?.output ?? tool?.rawOutput;
  const command =
    typeof input === "string"
      ? input
      : (stringValue(recordValue(input)?.command) ??
        stringValue(recordValue(input)?.cmd));
  return [
    stringValue(tool?.name) ?? stringValue(update?.title) ?? "tool event",
    stringValue(tool?.status)
      ? `status: ${stringValue(tool?.status)}`
      : undefined,
    command ? `command: ${command}` : undefined,
    input && !command ? `input: ${compactJson(input)}` : undefined,
    output
      ? `output: ${typeof output === "string" ? output : compactJson(output)}`
      : undefined,
    daemonContentText(update)
      ? `content: ${daemonContentText(update)}`
      : undefined,
  ]
    .filter(Boolean)
    .join("\n");
}

function daemonToolRole(update: Record<string, unknown> | null) {
  const tool = daemonToolPayload(update);
  const status = stringValue(tool?.status) ?? stringValue(update?.status);
  return status === "failed" || status === "error" ? "error" : "system";
}

function daemonPermissionRequest(event: DaemonEvent): PermissionRequest | null {
  const requestId = stringValue(event.data.requestId);
  if (!requestId) {
    return null;
  }
  const options = Array.isArray(event.data.options) ? event.data.options : [];
  return {
    permission_id: requestId,
    prompt: stringValue(event.data.prompt),
    tool: stringValue(event.data.tool),
    options: options
      .map((option) => recordValue(option))
      .filter((option): option is Record<string, unknown> => Boolean(option))
      .map((option) => ({
        id: stringValue(option.id) ?? "approve",
        label: stringValue(option.label),
        description: stringValue(option.description),
      })),
    raw: recordValue(event.data.context) ?? event.data,
  };
}

function daemonResolvedPermissionIds(events: DaemonEvent[]) {
  const resolved = new Set<string>();
  for (const event of events) {
    if (event.type !== "permission_resolved") {
      continue;
    }
    const id = stringValue(event.data.requestId);
    if (id) {
      resolved.add(id);
    }
  }
  return resolved;
}

function daemonPendingPermissionRequests(events: DaemonEvent[]) {
  const resolved = daemonResolvedPermissionIds(events);
  const seen = new Set<string>();
  return events
    .map(daemonPermissionRequest)
    .filter((request): request is PermissionRequest => Boolean(request))
    .filter((request) => {
      if (
        seen.has(request.permission_id) ||
        resolved.has(request.permission_id)
      ) {
        return false;
      }
      seen.add(request.permission_id);
      return true;
    });
}

function daemonRunnerProcessSummary(
  events: DaemonEvent[],
  transcript: RunnerTranscriptItem[],
): RunnerProcessSummary {
  const messageChunks = events.filter((event) => {
    const update = daemonSessionUpdate(event);
    return (
      event.type === "session_update" &&
      stringValue(update?.sessionUpdate) === "agent_message_chunk" &&
      Boolean(daemonContentText(update))
    );
  }).length;
  const progressSignals = events.filter((event) => {
    const update = daemonSessionUpdate(event);
    return stringValue(update?.sessionUpdate) === "agent_thought_chunk";
  }).length;
  const toolItems = transcript.filter(
    (item) =>
      item.event_type === "shell_output" ||
      item.title.toLowerCase().includes("tool") ||
      item.title.toLowerCase().includes("shell") ||
      item.body.toLowerCase().includes("command:"),
  );
  return {
    messageChunks,
    progressSignals,
    toolCalls: toolItems.length,
    permissionRequests: events.filter(
      (event) => event.type === "permission_request",
    ).length,
    rawAdapterEvents: 0,
    lastTool: toolItems.at(-1),
  };
}

function runnerTranscript(events: RuntimeEvent[]): RunnerTranscriptItem[] {
  const items: RunnerTranscriptItem[] = [];
  const agentMessages = new Map<string, RunnerTranscriptItem>();
  const progressMessages = new Map<string, RunnerTranscriptItem>();

  for (const event of events) {
    const adapterDelta = qwenMessageDeltaFromAdapterEvent(event);
    if (event.type === "message.delta" || adapterDelta) {
      const promptNumber = stringValue(event.data.prompt_number) ?? "current";
      const key = `agent-${promptNumber}`;
      const text = adapterDelta ?? stringValue(event.data.text) ?? "";
      if (!text.trim()) {
        continue;
      }
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

    if (isQwenThoughtEvent(event)) {
      const promptNumber = stringValue(event.data.prompt_number) ?? "current";
      const key = `agent-progress-${promptNumber}`;
      const existing = progressMessages.get(key);
      if (existing) {
        existing.sequence = event.sequence;
        existing.created_at = event.created_at;
      } else {
        const item: RunnerTranscriptItem = {
          id: key,
          role: "system",
          title: "Agent progress",
          body: "Model is analyzing the request and preparing the next action.",
          created_at: event.created_at,
          event_type: event.type,
          sequence: event.sequence,
        };
        progressMessages.set(key, item);
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
    case "permission.requested": {
      const request = extractPermissionRequest(event);
      return {
        ...base,
        role: "warning",
        title: "Permission required",
        body: permissionBody(event),
        permissionRequest: request ?? undefined,
      };
    }
    case "permission.resolved":
      return {
        ...base,
        role: "success",
        title: "Permission resolved",
        body: `Decision: ${stringValue(event.data.decision) ?? "recorded"}`,
      };
    case "permission.resolve_requested":
      return {
        ...base,
        role: "system",
        title: "Permission decision submitted",
        body: "Decision was recorded in the control plane and is waiting for the worker to apply it.",
      };
    case "permission.resolve_failed":
      return {
        ...base,
        role: "error",
        title: "Permission decision failed",
        body: compactJson(event.data),
      };
    case "permission.notification.queued":
    case "permission.notification.sent":
    case "permission.notification.failed":
      return {
        ...base,
        role: event.type.endsWith(".failed") ? "warning" : "system",
        title: "Permission notification",
        body: compactJson(event.data),
      };
    case "permission.stalled":
      return {
        ...base,
        role: "warning",
        title: "Permission stalled",
        body: compactJson(event.data),
      };
    case "adapter.event":
      if (isQwenThoughtEvent(event)) {
        return null;
      }
      return {
        ...base,
        role: toolEventRole(event),
        title: qwenAdapterEventTitle(event) ?? "Tool event",
        body: toolEventBody(event),
      };
    case "stream.warning":
    case "cancel.warning":
      return {
        ...base,
        role: "warning",
        title: "Runner warning",
        body: compactJson(event.data),
      };
    case "run.cancel_requested":
      return {
        ...base,
        role: "warning",
        title: "Cancel requested",
        body: "The control plane accepted the cancel request and is waiting for the runner to stop.",
      };
    case "event.gap_detected":
      return {
        ...base,
        role: "warning",
        title: "Event stream recovered",
        body: compactJson(event.data),
      };
    case "cost.quoted":
      return {
        ...base,
        role: "system",
        title: "Cost budget checked",
        body: compactJson(event.data),
      };
    case "executor.failed":
      return {
        ...base,
        role: "error",
        title: "Executor failed",
        body: failureBody(event),
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

function permissionContextRows(permission: PermissionRequest) {
  const raw = recordValue(permission.raw);
  const rawPayload = recordValue(raw?.payload) ?? recordValue(raw?.raw);
  const qwenData = recordValue(rawPayload?.data);
  const qwenToolCall = recordValue(qwenData?.toolCall);
  const qwenRawInput = recordValue(qwenToolCall?.rawInput);
  const qwenMeta = recordValue(qwenToolCall?._meta);
  const command =
    stringValue(raw?.command) ??
    stringValue(rawPayload?.command) ??
    stringValue(rawPayload?.cmd) ??
    stringValue(rawPayload?.shell) ??
    stringValue(qwenRawInput?.command);
  const cwd =
    stringValue(raw?.cwd) ??
    stringValue(rawPayload?.cwd) ??
    stringValue(rawPayload?.workspace) ??
    stringValue(qwenRawInput?.cwd);
  const risk =
    stringValue(raw?.risk) ??
    stringValue(raw?.risk_level) ??
    stringValue(rawPayload?.risk) ??
    stringValue(rawPayload?.risk_level);
  const tool =
    permission.tool ??
    stringValue(qwenMeta?.toolName) ??
    stringValue(qwenToolCall?.tool);
  return [
    risk ? { label: "live.permissionRisk" as I18nKey, value: risk } : undefined,
    tool ? { label: "live.permissionTool" as I18nKey, value: tool } : undefined,
    cwd ? { label: "live.permissionCwd" as I18nKey, value: cwd } : undefined,
    command
      ? {
          label: "live.permissionCommand" as I18nKey,
          value: command.length > 220 ? `${command.slice(0, 220)}...` : command,
        }
      : undefined,
  ].filter((row): row is { label: I18nKey; value: string } => Boolean(row));
}

function failureBody(event: RuntimeEvent) {
  return stringValue(event.data.reason) ?? compactJson(event.data);
}

function toolEventRole(event: RuntimeEvent): RunnerTranscriptItem["role"] {
  const status =
    stringValue(event.data.status) ??
    stringValue(event.data.outcome) ??
    qwenAdapterStatus(event);
  const exitCode = event.data.exit_code;
  if (status === "failed" || exitCode === 1) {
    return "error";
  }
  return "system";
}

function toolEventBody(event: RuntimeEvent) {
  const qwenBody = qwenAdapterEventBody(event);
  if (qwenBody) {
    return qwenBody;
  }
  const command =
    stringValue(event.data.command) ??
    stringValue(event.data.tool) ??
    stringValue(event.data.name) ??
    "adapter event";
  const cwd = stringValue(event.data.cwd);
  const exitCode =
    typeof event.data.exit_code === "number"
      ? `exit ${event.data.exit_code}`
      : undefined;
  const stdout = stringValue(event.data.stdout);
  const stderr = stringValue(event.data.stderr);
  return [
    command,
    cwd ? `cwd: ${cwd}` : undefined,
    exitCode,
    stdout ? `stdout: ${stdout.slice(0, 800)}` : undefined,
    stderr ? `stderr: ${stderr.slice(0, 800)}` : undefined,
  ]
    .filter(Boolean)
    .join("\n");
}

function qwenAdapterEventTitle(event: RuntimeEvent) {
  const update = qwenSessionUpdate(event);
  if (!update) {
    return null;
  }
  const sessionUpdate = stringValue(update.sessionUpdate);
  if (sessionUpdate === "tool_call" || sessionUpdate === "tool_call_update") {
    const status = stringValue(update.status);
    const meta = recordValue(update._meta);
    const title =
      stringValue(update.title) ?? stringValue(meta?.toolName) ?? "Tool call";
    return status ? `${title} · ${status}` : title;
  }
  if (sessionUpdate === "user_message_chunk") {
    return "User input streamed";
  }
  return sessionUpdate ? `Adapter event: ${sessionUpdate}` : null;
}

function qwenMessageDeltaFromAdapterEvent(event: RuntimeEvent) {
  if (event.type !== "adapter.event") {
    return null;
  }
  const update = qwenSessionUpdate(event);
  if (!update || stringValue(update.sessionUpdate) !== "agent_message_chunk") {
    return null;
  }
  return qwenContentText(update);
}

function qwenAdapterStatus(event: RuntimeEvent) {
  const update = qwenSessionUpdate(event);
  return update ? stringValue(update.status) : undefined;
}

function qwenAdapterEventBody(event: RuntimeEvent) {
  const update = qwenSessionUpdate(event);
  if (!update) {
    return null;
  }
  const sessionUpdate = stringValue(update.sessionUpdate);
  if (sessionUpdate !== "tool_call" && sessionUpdate !== "tool_call_update") {
    return null;
  }
  const meta = recordValue(update._meta);
  const title = stringValue(update.title) ?? stringValue(meta?.toolName);
  const status = stringValue(update.status);
  const rawInputRecord = recordValue(update.rawInput);
  const rawInput = rawInputRecord ? compactJson(rawInputRecord) : undefined;
  const command = rawInputRecord
    ? (stringValue(rawInputRecord.command) ?? stringValue(rawInputRecord.cmd))
    : undefined;
  const cwd = rawInputRecord ? stringValue(rawInputRecord.cwd) : undefined;
  const rawOutput =
    stringValue(update.rawOutput) ??
    (update.rawOutput ? compactJson(update.rawOutput) : undefined);
  const content = qwenContentText(update);
  return [
    title ?? "qwen tool event",
    status ? `status: ${status}` : undefined,
    command ? `command: ${command}` : undefined,
    cwd ? `cwd: ${cwd}` : undefined,
    rawInput ? `input: ${rawInput}` : undefined,
    rawOutput ? `output: ${rawOutput}` : undefined,
    content ? `content: ${content}` : undefined,
  ]
    .filter(Boolean)
    .join("\n");
}

function qwenSessionUpdate(event: RuntimeEvent) {
  const raw = recordValue(event.data.raw);
  const data = recordValue(raw?.data);
  if (!data) {
    return null;
  }
  return recordValue(data.update) ?? data;
}

function isQwenThoughtEvent(event: RuntimeEvent) {
  return (
    stringValue(qwenSessionUpdate(event)?.sessionUpdate) ===
    "agent_thought_chunk"
  );
}

function qwenContentText(update: Record<string, unknown>) {
  const content = update.content;
  const contentRecord = recordValue(content);
  if (contentRecord) {
    return stringValue(contentRecord.text);
  }
  if (!Array.isArray(content)) {
    return null;
  }
  return content
    .map((item) => {
      const itemRecord = recordValue(item);
      const nested = recordValue(itemRecord?.content);
      return stringValue(nested?.text);
    })
    .filter(Boolean)
    .join("\n");
}

function latestRunOutput(events: RuntimeEvent[]) {
  for (const event of [...events].reverse()) {
    const text =
      event.type === "message.delta"
        ? stringValue(event.data.text)
        : (qwenMessageDeltaFromAdapterEvent(event) ??
          stringValue(event.data.output) ??
          stringValue(event.data.message));
    if (text) {
      return text.length > 500 ? `${text.slice(0, 500)}...` : text;
    }
  }
  return undefined;
}

function filterTranscript(
  transcript: RunnerTranscriptItem[],
  filter: RunnerFilter,
) {
  if (filter === "all") {
    return transcript;
  }
  if (filter === "permission") {
    return transcript.filter((item) =>
      item.event_type.startsWith("permission."),
    );
  }
  if (filter === "process") {
    return transcript.filter(
      (item) => item.role !== "agent" && item.role !== "operator",
    );
  }
  if (filter === "tools") {
    return transcript.filter(
      (item) =>
        (item.event_type === "adapter.event" ||
          item.event_type === "session_update" ||
          item.event_type === "shell_output") &&
        (item.title.toLowerCase().includes("tool") ||
          item.title.toLowerCase().includes("shell") ||
          item.body.toLowerCase().includes("command:") ||
          item.body.toLowerCase().includes("exit code")),
    );
  }
  if (filter === "warning") {
    return transcript.filter((item) => item.role === "warning");
  }
  if (filter === "error") {
    return transcript.filter((item) => item.role === "error");
  }
  return transcript.filter((item) => item.role === "agent");
}

function filterLabel(
  filter: RunnerFilter,
  t?: (key: Parameters<ReturnType<typeof useI18n>["t"]>[0]) => string,
) {
  const labels: Record<RunnerFilter, string> = {
    agent: t?.("live.agent") ?? "Agent",
    all: t?.("live.all") ?? "All",
    error: t?.("live.errors") ?? "Errors",
    permission: t?.("live.permissions") ?? "Permissions",
    process: t?.("live.process") ?? "Process",
    tools: t?.("live.tools") ?? "Tools",
    warning: t?.("live.warnings") ?? "Warnings",
  };
  return labels[filter];
}

function runnerProcessSummary(
  events: RuntimeEvent[],
  transcript: RunnerTranscriptItem[],
): RunnerProcessSummary {
  const messageChunks = events.filter(
    (event) => event.type === "message.delta" && stringValue(event.data.text),
  ).length;
  const progressSignals = events.filter(isQwenThoughtEvent).length;
  const toolItems = transcript.filter(
    (item) =>
      item.event_type === "adapter.event" &&
      (item.title.toLowerCase().includes("tool") ||
        item.body.toLowerCase().includes("command:") ||
        item.body.toLowerCase().includes("exit code")),
  );
  return {
    messageChunks,
    progressSignals,
    toolCalls: toolItems.length,
    permissionRequests: events.filter(
      (event) => event.type === "permission.requested",
    ).length,
    rawAdapterEvents: events.filter((event) => event.type === "adapter.event")
      .length,
    lastTool: toolItems.at(-1),
  };
}

function runnerSignal(latest?: RuntimeEvent | DaemonEvent, runStatus?: string) {
  if (isTerminal(runStatus)) {
    return { label: "terminal", tone: "neutral" as const };
  }
  if (!latest) {
    return { label: "waiting", tone: "neutral" as const };
  }
  const createdAt =
    "created_at" in latest ? latest.created_at : daemonCreatedAt(latest);
  const ageMs = Date.now() - new Date(createdAt).getTime();
  if (Number.isFinite(ageMs) && ageMs > 120_000) {
    return { label: "stalled", tone: "warn" as const };
  }
  return { label: "active", tone: "ok" as const };
}

function runnerStallExplanation(
  events: RuntimeEvent[],
  runStatus?: string,
  workers: WorkerInfo[] = [],
): I18nKey {
  if (isTerminal(runStatus)) {
    return "live.stallTerminal";
  }
  const resolved = resolvedPermissionIds(events);
  const pendingPermission = events
    .map(extractPermissionRequest)
    .some((request) => request && !resolved.has(request.permission_id));
  if (pendingPermission) {
    return "live.stallPermission";
  }
  const latest = events.at(-1);
  if (latest?.type === "run.queued") {
    return workers.some((worker) => worker.status === "active")
      ? "live.stallQueuedCapacity"
      : "live.stallQueuedNoWorker";
  }
  const workerId = latest ? stringValue(latest.data.worker_id) : undefined;
  if (
    workerId &&
    workers.some(
      (worker) => worker.worker_id === workerId && worker.status === "stale",
    )
  ) {
    return "live.stallWorkerStale";
  }
  if (
    latest?.type === "adapter.not_configured" ||
    latest?.type === "executor.failed" ||
    latest?.type === "run.failed"
  ) {
    return "live.stallExecutorFailed";
  }
  return "live.stallNoRecentEvent";
}

function runnerReadableReport(
  transcript: RunnerTranscriptItem[],
  events: RuntimeEvent[],
) {
  const lines = [
    "# Runner Execution Report",
    "",
    `Generated: ${new Date().toISOString()}`,
    `Events: ${events.length}`,
    "",
    "## Timeline",
    "",
  ];
  for (const item of transcript) {
    lines.push(
      `### ${item.sequence}. ${item.title}`,
      "",
      `Event: ${item.event_type}`,
      `Time: ${item.created_at}`,
      "",
      item.body || "-",
      "",
    );
  }
  return lines.join("\n");
}

function missionChatItems(
  mission: MissionState | undefined,
  events: MissionEvent[],
  runOutputById: Record<string, string> = {},
): MissionChatItem[] {
  const items: MissionChatItem[] = [];
  if (mission) {
    mission.tasks.forEach((task, index) => {
      const artifacts = taskResultArtifactNames(task.result);
      const dependencyText = task.depends_on.length
        ? `Dependencies: ${task.depends_on.join(", ")}`
        : "Root task";
      const resultText = artifacts.length
        ? `Artifacts: ${artifacts.join(", ")}`
        : task.result
          ? `Result: ${compactJson(task.result).slice(0, 500)}`
          : "No result yet";
      const lastOutput = task.run_id ? runOutputById[task.run_id] : undefined;
      items.push({
        id: `task-${task.task_id}`,
        title: `${task.title} · ${task.profile_id}`,
        body: [
          dependencyText,
          resultText,
          lastOutput ? `Last output: ${lastOutput}` : undefined,
        ]
          .filter(Boolean)
          .join("\n"),
        runId: task.run_id,
        sequence: index + 1,
        status: task.status,
      });
    });
  }
  for (const event of events.slice(-8)) {
    items.push({
      id: event.id,
      title: event.type,
      body: missionEventSummary(event),
      sequence: 10_000 + event.sequence,
      status: event.type.includes("failed")
        ? "failed"
        : event.type.includes("completed")
          ? "completed"
          : "running",
      time: event.created_at,
    });
  }
  return items.sort((left, right) => left.sequence - right.sequence);
}

function missionEventSummary(event: MissionEvent) {
  const taskId = stringValue(event.data.task_id);
  const runId = stringValue(event.data.run_id);
  const status = stringValue(event.data.status);
  return [
    taskId ? `Task: ${taskId}` : undefined,
    runId ? `Run: ${runId}` : undefined,
    status ? `Status: ${status}` : undefined,
    compactJson(event.data).slice(0, 600),
  ]
    .filter(Boolean)
    .join("\n");
}

function taskResultArtifactNames(result?: Record<string, unknown>) {
  const artifacts = Array.isArray(result?.artifacts) ? result.artifacts : [];
  return artifacts
    .map((artifact) => {
      if (typeof artifact === "string") {
        return artifact;
      }
      const item = recordValue(artifact);
      return stringValue(item?.name);
    })
    .filter((name): name is string => Boolean(name));
}

function downloadText(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function fetchTextArtifact(href: string) {
  const response = await fetch(href, { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error((await response.text()) || response.statusText);
  }
  return response.text();
}

function compactJson(value: unknown) {
  if (!value || typeof value !== "object") {
    return String(value ?? "");
  }
  return JSON.stringify(value, null, 2);
}

function recordValue(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function registryValue(source: Record<string, unknown>, key: string) {
  const value = source[key];
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, unknown>;
}

function money(value?: number | null) {
  if (value == null || !Number.isFinite(value)) {
    return "$0.00";
  }
  return `$${value.toFixed(2)}`;
}

function defaultWorkerControlUrl() {
  if (window.location.pathname.startsWith("/agentflow")) {
    return `${window.location.origin}/agentflow-worker`;
  }
  if (window.location.pathname.startsWith("/cloud-agents")) {
    return `${window.location.origin}/cloud-agents-worker`;
  }
  return `${window.location.origin}/cloud-agents-worker`;
}

function workerNoSourceDeployCommand(registration: WorkerRegistration) {
  const token = registration.token.token ?? "<worker-token-shown-once>";
  return [
    `RUN_WORKER_CONTROL_URL=${shellSingleQuote(registration.control_url)}`,
    `RUN_WORKER_TOKEN=${shellSingleQuote(token)}`,
    `RUN_WORKER_ID=${shellSingleQuote(registration.worker_id)}`,
    `RUN_WORKER_CAPACITY=${registration.capacity}`,
    'bash -c \'tmp=$(mktemp); curl -fsSL https://raw.githubusercontent.com/chiga0/agent-research/main/scripts/deploy_worker_vps.sh -o "$tmp"; bash "$tmp" root@<worker-ip> /path/to/key.pem\'',
  ].join(" \\\n  ");
}

function shellSingleQuote(value: string) {
  return `'${value.replaceAll("'", "'\"'\"'")}'`;
}

function workerBadges(worker: WorkerInfo) {
  const metadata = worker.metadata ?? {};
  const labels = objectValue(metadata.labels);
  const resources = objectValue(metadata.resources);
  const capabilities = objectValue(metadata.capabilities);
  const adapters = Array.isArray(capabilities.adapters)
    ? capabilities.adapters
        .map((adapter) => stringValue(adapter))
        .filter((adapter): adapter is string => Boolean(adapter))
    : [];
  return [
    ...Object.entries(labels).map(([key, value]) => `${key}:${String(value)}`),
    ...Object.entries(resources).map(
      ([key, value]) => `${key}:${String(value)}`,
    ),
    ...adapters.map((adapter) => `adapter:${adapter}`),
  ].slice(0, 8);
}

function workerResourceRows(worker: WorkerInfo) {
  const resources = objectValue(worker.metadata?.resources);
  const metrics = objectValue(worker.metadata?.metrics);
  const cpus =
    numericValue(metrics.cpu_percent) ?? numericValue(resources.cpu_percent);
  const memoryPercent =
    numericValue(metrics.memory_percent) ??
    numericValue(resources.memory_percent);
  const diskPercent =
    numericValue(metrics.disk_percent) ?? numericValue(resources.disk_percent);
  const swapPercent =
    numericValue(metrics.swap_percent) ?? numericValue(resources.swap_percent);
  const loadAverage =
    numericValue(metrics.load_average) ?? numericValue(resources.load_average);
  const rows: Array<{
    label: string;
    percent: number;
    tone: "ok" | "warn";
    value: string;
  }> = [];
  const capacityPercent =
    worker.capacity > 0 ? (worker.active_count / worker.capacity) * 100 : 0;
  rows.push({
    label: "capacity",
    percent: clampPercent(capacityPercent),
    tone: capacityPercent >= 100 ? "warn" : "ok",
    value: `${worker.active_count}/${worker.capacity}`,
  });
  if (cpus != null) {
    rows.push({
      label: "cpu",
      percent: clampPercent(cpus),
      tone: cpus >= 85 ? "warn" : "ok",
      value: `${Math.round(cpus)}%`,
    });
  } else if (numericValue(resources.cpus) != null) {
    rows.push({
      label: "cpu",
      percent: clampPercent(
        (worker.active_count / Math.max(1, numericValue(resources.cpus) ?? 1)) *
          100,
      ),
      tone:
        worker.active_count >= (numericValue(resources.cpus) ?? 1)
          ? "warn"
          : "ok",
      value: `${resources.cpus} cores`,
    });
  }
  if (memoryPercent != null) {
    rows.push({
      label: "memory",
      percent: clampPercent(memoryPercent),
      tone: memoryPercent >= 85 ? "warn" : "ok",
      value: `${Math.round(memoryPercent)}%`,
    });
  } else if (numericValue(resources.memory_gb) != null) {
    const memoryGb = numericValue(resources.memory_gb) ?? 0;
    rows.push({
      label: "memory",
      percent: clampPercent(
        (worker.active_count / Math.max(1, memoryGb / 2)) * 100,
      ),
      tone: memoryGb <= 2 && worker.active_count > 0 ? "warn" : "ok",
      value: `${memoryGb} GB`,
    });
  }
  if (diskPercent != null) {
    rows.push({
      label: "disk",
      percent: clampPercent(diskPercent),
      tone: diskPercent >= 85 ? "warn" : "ok",
      value: `${Math.round(diskPercent)}%`,
    });
  }
  if (swapPercent != null) {
    rows.push({
      label: "swap",
      percent: clampPercent(swapPercent),
      tone: swapPercent >= 40 ? "warn" : "ok",
      value: `${Math.round(swapPercent)}%`,
    });
  }
  if (loadAverage != null) {
    const cpuCount = Math.max(1, numericValue(resources.cpus) ?? 1);
    const loadPercent = (loadAverage / cpuCount) * 100;
    rows.push({
      label: "load",
      percent: clampPercent(loadPercent),
      tone: loadPercent >= 85 ? "warn" : "ok",
      value: loadAverage.toFixed(2),
    });
  }
  return rows;
}

function workerResourceWarnings(worker: WorkerInfo): I18nKey[] {
  const resources = objectValue(worker.metadata?.resources);
  const warnings: I18nKey[] = [];
  if (
    (numericValue(resources.memory_gb) ?? 0) <= 2 &&
    worker.active_count > 0
  ) {
    warnings.push("units.lowMemoryWarning");
  }
  if (worker.capacity > 0 && worker.active_count >= worker.capacity) {
    warnings.push("units.capacityFullWarning");
  }
  if (worker.status === "stale") {
    warnings.push("units.staleWarning");
  }
  return warnings;
}

function clampPercent(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(value)));
}

function numericValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function objectValue(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, unknown>;
}

function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    void navigator.clipboard.writeText(value);
    return;
  }
  const element = document.createElement("textarea");
  element.value = value;
  document.body.appendChild(element);
  element.select();
  document.execCommand("copy");
  element.remove();
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

function effectiveTerminalStatus(status: string | undefined, events: RuntimeEvent[]) {
  if (isTerminal(status)) {
    return status;
  }
  for (const event of [...events].reverse()) {
    if (event.type === "run.completed") {
      return "completed";
    }
    if (event.type === "run.failed") {
      return "failed";
    }
    if (event.type === "run.cancelled") {
      return "cancelled";
    }
  }
  return undefined;
}

function isTerminalDaemonEvent(eventType: string) {
  return ["turn_complete", "turn_error", "prompt_cancelled"].includes(
    eventType,
  );
}

function daemonSequence(event: DaemonEvent) {
  if (typeof event.id === "number") {
    return event.id;
  }
  const parsed = Number(event.id);
  if (Number.isFinite(parsed)) {
    return parsed;
  }
  const metaSequence = Number(recordValue(event._meta)?.runtimeSequence);
  return Number.isFinite(metaSequence) ? metaSequence : 0;
}

function daemonCreatedAt(event: DaemonEvent) {
  const timestamp = Number(recordValue(event._meta)?.serverTimestamp);
  if (Number.isFinite(timestamp) && timestamp > 0) {
    return new Date(timestamp).toISOString();
  }
  return new Date().toISOString();
}

function isTerminal(status?: string) {
  return Boolean(
    status && ["completed", "failed", "cancelled"].includes(status),
  );
}

export const __testUtils = {
  bubbleClass,
  canPreviewArtifact,
  connectionLabel,
  connectionTone,
  compactJson,
  copyText,
  copyProfile,
  defaultWorkerControlUrl,
  downloadText,
  emptyProfile,
  emptyToNull,
  effectiveTerminalStatus,
  filterLabel,
  filterTranscript,
  formatBytes,
  fetchTextArtifact,
  isTerminalEvent,
  isTerminalDaemonEvent,
  mergeEvents,
  mergeDaemonEvents,
  money,
  objectValue,
  parseJsonObject,
  prettyJson,
  registryValue,
  runnerStallExplanation,
  runnerReadableReport,
  runnerProcessSummary,
  runnerSignal,
  runnerTranscript,
  daemonRunnerTranscript,
  daemonRunnerProcessSummary,
  daemonPendingPermissionRequests,
  daemonResolvedPermissionIds,
  daemonCreatedAt,
  daemonSequence,
  runTaskProgress,
  shellSingleQuote,
  stringValue,
  toolEventBody,
  toolEventRole,
  transcriptItemForEvent,
  workerBadges,
  workerNoSourceDeployCommand,
  workerResourceRows,
  workerResourceWarnings,
  latestRunOutput,
  missionChatItems,
  pendingPermissionRequests,
  permissionDecisionForOption,
  permissionDecisionPayload,
  permissionContextRows,
  permissionResolveRequestedIds,
  isTerminal,
  statusLine,
  timeAgo,
};
