import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowUp, MessageSquarePlus, Settings2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button, Select, StatusBadge, Textarea } from "./components/ui";
import { runtimeApi } from "./lib/api";

export function ClientHome() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [goal, setGoal] = useState("");
  const [mode, setMode] = useState("auto");
  const [adapter, setAdapter] = useState("auto");
  const tasks = useQuery({
    queryKey: ["v2", "tasks"],
    queryFn: runtimeApi.v2Tasks,
    refetchInterval: 3000,
  });
  const createTask = useMutation({
    mutationFn: runtimeApi.v2CreateTask,
    onSuccess: async (task) => {
      await queryClient.invalidateQueries({ queryKey: ["v2", "tasks"] });
      await navigate({
        to: "/tasks/$taskId",
        params: { taskId: task.task_id },
      });
    },
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!goal.trim()) return;
    createTask.mutate({
      goal: goal.trim(),
      mode,
      adapter,
      channel: "web",
      metadata: { product_surface: "webshell" },
    });
  };

  return (
    <div className="mx-auto flex min-h-[calc(100vh-8rem)] w-full max-w-4xl flex-col justify-center gap-10 py-8">
      <div className="grid gap-3 text-center">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          今天想完成什么？
        </h1>
        <p className="text-muted-foreground">
          描述目标，Aflow 会选择执行单元并直接进入实时 Agent 对话。
        </p>
      </div>

      <form
        aria-label="New conversation"
        className="rounded-2xl border border-border bg-card p-3 shadow-sm"
        onSubmit={submit}
      >
        <Textarea
          autoFocus
          className="min-h-32 resize-none border-0 bg-transparent text-base shadow-none focus-visible:ring-0"
          placeholder="例如：审计这个仓库的部署链路，修复问题并给出可验证的交付产物"
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <div className="flex items-end justify-between gap-3 border-t border-border pt-3">
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground">
              <Settings2 className="h-4 w-4" />
              设置
            </summary>
            <div className="absolute z-20 mt-2 grid w-64 gap-3 rounded-lg border border-border bg-card p-3 shadow-xl">
              <label className="grid gap-1 text-xs text-muted-foreground">
                Agent 模式
                <Select
                  value={mode}
                  onChange={(event) => setMode(event.target.value)}
                >
                  <option value="auto">自动</option>
                  <option value="single">单 Agent</option>
                  <option value="multi-agent">多 Agent</option>
                </Select>
              </label>
              <label className="grid gap-1 text-xs text-muted-foreground">
                执行 Agent
                <Select
                  value={adapter}
                  onChange={(event) => setAdapter(event.target.value)}
                >
                  <option value="auto">自动选择</option>
                  <option value="qwen">qwen-code</option>
                  <option value="codex">codex</option>
                  <option value="opencode">opencode</option>
                </Select>
              </label>
            </div>
          </details>
          <Button
            aria-label="Start conversation"
            disabled={!goal.trim() || createTask.isPending}
            size="icon"
            type="submit"
          >
            <ArrowUp className="h-4 w-4" />
          </Button>
        </div>
      </form>

      {(tasks.data?.tasks.length ?? 0) > 0 ? (
        <div className="grid gap-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <MessageSquarePlus className="h-4 w-4" />
            最近对话
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {tasks.data?.tasks.slice(0, 6).map((task) => (
              <Link
                key={task.task_id}
                className="grid gap-2 rounded-lg border border-border bg-card p-3 hover:bg-muted"
                params={{ taskId: task.task_id }}
                to="/tasks/$taskId"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">
                    {task.title}
                  </span>
                  <StatusBadge status={task.status} />
                </div>
                <p className="line-clamp-2 text-xs text-muted-foreground">
                  {task.goal}
                </p>
              </Link>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
