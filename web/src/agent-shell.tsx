import { RestSseTransport } from "@qwen-code/sdk/daemon/transports";
import { WebShell } from "@qwen-code/web-shell";
import {
  DaemonSessionProvider,
  DaemonWorkspaceProvider,
} from "@qwen-code/webui/daemon-react-sdk";
import { ChevronRight, PanelRightClose, PanelRightOpen } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge, Button, StatusBadge } from "./components/ui";
import {
  authenticatedFetch,
  v2TaskArtifactHref,
  v2TaskDaemonBaseHref,
  type V2AgentTask,
  type V2Artifact,
  type V2Task,
} from "./lib/api";

interface AflowAgentShellProps {
  task: V2Task;
  artifacts: V2Artifact[];
  onCancel: () => void;
  onRetry: () => void;
  busy?: boolean;
}

export function AflowAgentShell({
  task,
  artifacts,
  onCancel,
  onRetry,
  busy = false,
}: AflowAgentShellProps) {
  const agents = useMemo(
    () => task.plan?.agent_tasks ?? [],
    [task.plan?.agent_tasks],
  );
  const defaultAgent =
    agents.find((agent) => agent.status === "waiting_approval") ??
    agents.find((agent) => agent.status === "running") ??
    agents[0];
  const [selectedAgentId, setSelectedAgentId] = useState(
    defaultAgent?.agent_task_id ?? task.task_id,
  );
  const [processesOpen, setProcessesOpen] = useState(true);
  const baseUrl = v2TaskDaemonBaseHref(task.task_id);
  const workspaceCwd = taskWorkspace(task);
  const transport = useMemo(
    () => new RestSseTransport(baseUrl, undefined, authenticatedFetch),
    [baseUrl],
  );

  useEffect(() => () => transport.dispose(), [transport]);

  useEffect(() => {
    if (
      agents.length &&
      !agents.some((agent) => agent.agent_task_id === selectedAgentId)
    ) {
      setSelectedAgentId(
        defaultAgent?.agent_task_id ?? agents[0].agent_task_id,
      );
    }
  }, [agents, defaultAgent?.agent_task_id, selectedAgentId]);

  const selectedAgent =
    agents.find((agent) => agent.agent_task_id === selectedAgentId) ??
    defaultAgent;
  const runningCount = agents.filter((agent) =>
    ["queued", "running"].includes(agent.status),
  ).length;

  return (
    <div className="flex h-[calc(100vh-3.5rem)] min-h-[620px] overflow-hidden bg-background">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex min-h-14 items-center gap-2 border-b border-border bg-card px-3">
          <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto py-2">
            {agents.map((agent) => (
              <button
                key={agent.agent_task_id}
                className={`flex shrink-0 items-center gap-2 rounded-md border px-3 py-1.5 text-sm transition-colors ${
                  agent.agent_task_id === selectedAgentId
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
                type="button"
                onClick={() => setSelectedAgentId(agent.agent_task_id)}
              >
                <AgentStatusDot status={agent.status} />
                <span>{agent.role}</span>
                <span className="hidden max-w-44 truncate text-xs opacity-70 sm:inline">
                  {agent.title}
                </span>
              </button>
            ))}
          </div>
          <Badge tone={runningCount ? "info" : "neutral"}>
            {runningCount} active
          </Badge>
          <Button
            aria-label={processesOpen ? "Hide processes" : "Show processes"}
            size="icon"
            variant="ghost"
            onClick={() => setProcessesOpen((open) => !open)}
          >
            {processesOpen ? (
              <PanelRightClose className="h-4 w-4" />
            ) : (
              <PanelRightOpen className="h-4 w-4" />
            )}
          </Button>
        </div>

        <div className="min-h-0 flex-1">
          <DaemonWorkspaceProvider
            baseUrl={baseUrl}
            transport={transport}
            workspaceCwd={workspaceCwd}
          >
            <DaemonSessionProvider
              key={selectedAgentId}
              autoReconnect
              sessionId={selectedAgentId}
              workspaceCwd={workspaceCwd}
            >
              <WebShell
                builtinAtProviders={false}
                chatMaxWidth={1040}
                collapseCompletedTurns={false}
                hiddenSlashCommands={[
                  "agents",
                  "auth",
                  "bug",
                  "docs",
                  "extensions",
                  "language",
                  "mcp",
                  "memory",
                  "model",
                  "new",
                  "release",
                  "reset",
                  "resume",
                  "settings",
                  "skills",
                  "tools",
                ]}
                language="zh-CN"
                messageTurnOutputs={["artifact", "file"]}
                sidebar={{
                  enabled: true,
                  branding: {
                    render: () => (
                      <div className="min-w-0 px-1">
                        <div className="text-sm font-semibold">Aflow</div>
                        <div className="truncate text-xs opacity-70">
                          {task.title}
                        </div>
                      </div>
                    ),
                  },
                  footer: false,
                }}
                style={{ height: "100%", width: "100%" }}
                bottomStatusItems={[
                  {
                    id: "aflow-agent",
                    label: `${selectedAgent?.role ?? "agent"} · ${selectedAgent?.status ?? task.status}`,
                    title: "Current Aflow agent process",
                    onClick: () => setProcessesOpen(true),
                  },
                ]}
                onRightPanelOpen={() => setProcessesOpen(true)}
                onSessionIdChange={(sessionId) => {
                  if (
                    sessionId &&
                    agents.some((agent) => agent.agent_task_id === sessionId)
                  ) {
                    setSelectedAgentId(sessionId);
                  }
                }}
              />
            </DaemonSessionProvider>
          </DaemonWorkspaceProvider>
        </div>
      </div>

      {processesOpen ? (
        <aside className="hidden w-80 shrink-0 overflow-y-auto border-l border-border bg-card xl:block">
          <ProcessPanel
            agents={agents}
            artifacts={artifacts}
            busy={busy}
            task={task}
            onCancel={onCancel}
            onRetry={onRetry}
            onSelectAgent={setSelectedAgentId}
          />
        </aside>
      ) : null}
    </div>
  );
}

function ProcessPanel({
  task,
  agents,
  artifacts,
  busy,
  onCancel,
  onRetry,
  onSelectAgent,
}: {
  task: V2Task;
  agents: V2AgentTask[];
  artifacts: V2Artifact[];
  busy: boolean;
  onCancel: () => void;
  onRetry: () => void;
  onSelectAgent: (agentId: string) => void;
}) {
  const terminal = ["completed", "failed", "cancelled"].includes(task.status);
  return (
    <div className="grid gap-5 p-4">
      <div className="grid gap-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-semibold">实时进程</h2>
          <StatusBadge status={task.status} />
        </div>
        <p className="text-xs text-muted-foreground">{task.goal}</p>
        <div className="flex gap-2 pt-1">
          {terminal ? (
            <Button
              disabled={busy}
              size="sm"
              variant="secondary"
              onClick={onRetry}
            >
              Retry
            </Button>
          ) : (
            <Button
              disabled={busy}
              size="sm"
              variant="secondary"
              onClick={onCancel}
            >
              Cancel
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-2">
        {agents.map((agent) => (
          <button
            key={agent.agent_task_id}
            className="grid gap-2 rounded-md border border-border p-3 text-left hover:bg-muted"
            type="button"
            onClick={() => onSelectAgent(agent.agent_task_id)}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{agent.role}</span>
              <StatusBadge status={agent.status} />
            </div>
            <div className="text-sm text-muted-foreground">{agent.title}</div>
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <span>{agent.adapter}</span>
              <ChevronRight className="h-3 w-3" />
              <span>
                {agent.depends_on.length ? agent.depends_on.join(", ") : "root"}
              </span>
            </div>
          </button>
        ))}
      </div>

      {artifacts.length ? (
        <div className="grid gap-2 border-t border-border pt-4">
          <h3 className="text-sm font-semibold">产物</h3>
          {artifacts.map((artifact) => (
            <a
              key={artifact.artifact_id}
              className="rounded-md border border-border p-2 text-sm hover:bg-muted"
              href={v2TaskArtifactHref(task.task_id, artifact.artifact_id)}
              rel="noreferrer"
              target="_blank"
            >
              <div className="font-medium">{artifact.name}</div>
              <div className="text-xs text-muted-foreground">
                {artifact.kind}
              </div>
            </a>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function AgentStatusDot({ status }: { status: string }) {
  const tone =
    status === "running"
      ? "bg-emerald-500"
      : status === "waiting_approval"
        ? "bg-amber-500"
        : status === "failed"
          ? "bg-red-500"
          : "bg-slate-400";
  return <span aria-hidden className={`h-2 w-2 rounded-full ${tone}`} />;
}

function taskWorkspace(task: V2Task) {
  const workspace = task.metadata?.workspace;
  if (workspace && typeof workspace === "object") {
    const sourcePath = (workspace as Record<string, unknown>).source_path;
    if (typeof sourcePath === "string" && sourcePath.trim()) {
      return sourcePath.trim();
    }
  }
  return `/aflow/tasks/${task.task_id}`;
}
