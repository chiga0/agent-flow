import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Boxes,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  HelpCircle,
  Languages,
  LogOut,
  Menu,
  Moon,
  Network,
  Server,
  ShieldCheck,
  Sun,
  UserCog,
  Users,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Badge, Button, StatusBadge } from "./ui";
import {
  extractPermissionRequest,
  permissionEventId,
  resolvedPermissionIds,
  runtimeApi,
  type RuntimeEvent,
  type RunState,
} from "../lib/api";
import { useI18n, type I18nKey } from "../lib/i18n";
import { cn } from "../lib/utils";

const navItems = [
  {
    to: "/admin",
    labelKey: "nav.overview",
    icon: Activity,
    roles: ["owner", "operator", "auditor"],
  },
  {
    to: "/admin/runs",
    labelKey: "nav.runs",
    icon: ClipboardList,
    roles: ["owner", "operator", "auditor"],
  },
  {
    to: "/admin/units",
    labelKey: "nav.units",
    icon: Network,
    roles: ["owner", "operator", "auditor"],
  },
  {
    to: "/admin/executors",
    labelKey: "nav.executors",
    icon: Server,
    roles: ["owner", "operator", "auditor"],
  },
  {
    to: "/admin/missions",
    labelKey: "nav.missions",
    icon: Boxes,
    roles: ["owner", "operator", "auditor"],
  },
  {
    to: "/admin/profiles",
    labelKey: "nav.profiles",
    icon: UserCog,
    roles: ["owner", "operator"],
  },
  {
    to: "/admin/access",
    labelKey: "nav.access",
    icon: Users,
    roles: ["owner"],
  },
  {
    to: "/admin/operations",
    labelKey: "nav.operations",
    icon: ShieldCheck,
    roles: ["owner", "operator"],
  },
] as const;

export function Shell() {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: runtimeApi.session,
  });
  const roles = session.data?.principal?.roles ?? [];
  const isAdmin = isAdminPath(pathname);
  const canUseAdmin = roles.some((role) =>
    ["owner", "operator", "auditor"].includes(role),
  );
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur">
        <div className="flex h-14 items-center justify-between gap-3 px-4 lg:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <Button
              aria-label={t("nav.open")}
              className={isAdmin ? "lg:hidden" : "hidden"}
              size="icon"
              variant="ghost"
              onClick={() => setOpen(true)}
            >
              <Menu className="h-4 w-4" />
            </Button>
            <div className="grid min-w-0">
              <div className="truncate text-sm font-semibold">
                {isAdmin ? t("nav.adminTitle") : t("nav.title")}
              </div>
              <div className="truncate text-xs text-muted-foreground">
                {isAdmin ? t("nav.adminSubtitle") : t("nav.consumerSubtitle")}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {isAdmin ? (
              <LinkButton to="/" label={t("nav.userApp")} />
            ) : canUseAdmin ? (
              <LinkButton to="/admin" label={t("nav.admin")} />
            ) : null}
            <DocsLink />
            <LanguageToggle />
            <ThemeToggle />
            <SignOutButton />
          </div>
        </div>
      </header>

      <div
        className={isAdmin ? "grid lg:grid-cols-[240px_minmax(0,1fr)]" : "grid"}
      >
        {isAdmin ? (
          <aside className="sticky top-14 hidden h-[calc(100vh-3.5rem)] border-r border-border bg-card lg:block">
            <Navigation />
          </aside>
        ) : null}
        {open ? (
          <div className="fixed inset-0 z-40 bg-background/80 backdrop-blur lg:hidden">
            <div className="h-full w-72 border-r border-border bg-card">
              <div className="flex h-14 items-center justify-between border-b border-border px-4">
                <span className="text-sm font-semibold">{t("navLabel")}</span>
                <Button
                  aria-label={t("nav.close")}
                  size="icon"
                  variant="ghost"
                  onClick={() => setOpen(false)}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
              <Navigation onNavigate={() => setOpen(false)} />
            </div>
          </div>
        ) : null}
        <main
          className={
            isAdmin
              ? "min-w-0 p-4 pb-36 lg:p-6 lg:pb-36"
              : "min-w-0 px-4 py-5 pb-24 sm:px-6 lg:px-8"
          }
        >
          <Outlet />
        </main>
      </div>
      {isAdmin ? <ActiveRunDock /> : null}
    </div>
  );
}

function LinkButton({ to, label }: { to: string; label: string }) {
  return (
    <Link
      className="inline-flex h-9 items-center justify-center rounded-md border border-border px-3 text-sm font-medium hover:bg-muted"
      to={to}
    >
      {label}
    </Link>
  );
}

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useI18n();
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: runtimeApi.session,
  });
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const roles = session.data?.principal?.roles ?? [];
  const visibleItems = navItems.filter((item) => {
    if (!("roles" in item)) {
      return true;
    }
    return item.roles.some((role) => roles.includes(role));
  });
  return (
    <nav className="grid gap-1 p-3">
      {visibleItems.map((item) => {
        const Icon = item.icon;
        const active =
          pathname === item.to ||
          (item.to !== "/admin" && pathname.startsWith(item.to));
        return (
          <Link
            key={item.to}
            className={cn(
              "flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground",
              active && "bg-muted text-foreground",
            )}
            to={item.to}
            onClick={onNavigate}
          >
            <Icon className="h-4 w-4" />
            {t(item.labelKey as I18nKey)}
          </Link>
        );
      })}
    </nav>
  );
}

function isAdminPath(pathname: string) {
  return pathname.startsWith("/admin") && pathname !== "/admin-login";
}

function DocsLink() {
  const { t } = useI18n();
  return (
    <a
      aria-label={t("common.docs")}
      className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-transparent px-2 text-xs font-medium transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary sm:px-3 sm:text-sm"
      href="https://chiga0.github.io/aflow/architecture/"
      rel="noreferrer"
      target="_blank"
    >
      <HelpCircle className="h-4 w-4" />
      <span className="hidden sm:inline">{t("common.docs")}</span>
    </a>
  );
}

function SignOutButton() {
  const client = useQueryClient();
  const [pending, setPending] = useState(false);
  const { t } = useI18n();
  return (
    <Button
      aria-label={t("nav.signOut")}
      disabled={pending}
      size="icon"
      variant="ghost"
      onClick={async () => {
        setPending(true);
        try {
          await runtimeApi.logout();
        } finally {
          await client.invalidateQueries({ queryKey: ["auth", "session"] });
        }
      }}
    >
      <LogOut className="h-4 w-4" />
    </Button>
  );
}

function ThemeToggle() {
  const { t } = useI18n();
  const [dark, setDark] = useState(() =>
    document.documentElement.classList.contains("dark"),
  );
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("cloud-agents-theme", dark ? "dark" : "light");
  }, [dark]);
  return (
    <Button
      aria-label={t("nav.theme")}
      size="icon"
      variant="ghost"
      onClick={() => setDark((value) => !value)}
    >
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}

export function LanguageToggle() {
  const { locale, t, toggleLocale } = useI18n();
  return (
    <Button
      aria-label={t("language.toggle")}
      size="sm"
      variant="ghost"
      onClick={toggleLocale}
    >
      <Languages className="h-4 w-4" />
      {locale === "zh"
        ? t("language.switchToEnglish")
        : t("language.switchToChinese")}
    </Button>
  );
}

function ActiveRunDock() {
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(() =>
    typeof window.matchMedia === "function"
      ? window.matchMedia("(max-width: 640px)").matches
      : false,
  );
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: runtimeApi.runs,
    refetchInterval: 5000,
  });
  const activeRuns = (runs.data?.runs ?? [])
    .filter((run) => !["completed", "failed", "cancelled"].includes(run.status))
    .slice(0, 3);
  if (!activeRuns.length) {
    return null;
  }
  return (
    <div className="fixed inset-x-3 bottom-3 z-20 grid gap-2 sm:left-auto sm:w-[360px]">
      <div className="rounded-md border border-border bg-card/95 p-3 shadow-lg backdrop-blur">
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="text-sm font-semibold">{t("dock.activeRuns")}</div>
          <div className="flex items-center gap-2">
            <Badge tone="info">{activeRuns.length}</Badge>
            <Button
              aria-label={collapsed ? t("dock.expand") : t("dock.collapse")}
              size="icon"
              variant="ghost"
              onClick={() => setCollapsed((value) => !value)}
            >
              {collapsed ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
        {!collapsed ? (
          <div className="grid gap-2">
            {activeRuns.map((run) => (
              <ActiveRunLink key={run.run_id} run={run} />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ActiveRunLink({ run }: { run: RunState }) {
  const { t } = useI18n();
  const events = useQuery({
    queryKey: ["runs", run.run_id, "events"],
    queryFn: () => runtimeApi.runEvents(run.run_id),
    refetchInterval: 2500,
    retry: 1,
  });
  const eventList = events.data?.events ?? [];
  const permission = dockPendingPermission(eventList);
  const preview = dockRunPreview(eventList) ?? run.spec.prompt;
  const status = dockRunStatus(run.status, eventList);
  return (
    <Link
      className="grid gap-1 rounded-md border border-border p-2 text-sm hover:bg-muted"
      to="/admin/runs/$runId"
      params={{ runId: run.run_id }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-xs">{run.run_id}</span>
        <div className="flex shrink-0 items-center gap-1">
          {permission ? (
            <Badge tone="warn">{t("dock.permission")}</Badge>
          ) : null}
          <StatusBadge status={status} />
        </div>
      </div>
      <div className="line-clamp-1 text-xs text-muted-foreground">
        {preview || run.spec.adapter || t("dock.openChat")}
      </div>
      <div className="text-xs text-primary">{t("dock.openChat")}</div>
    </Link>
  );
}

function dockPendingPermission(events: RuntimeEvent[]) {
  if (events.some((event) => dockTerminalStatus(event.type))) {
    return undefined;
  }
  const resolved = resolvedPermissionIds(events);
  const submitted = dockSubmittedPermissionIds(events);
  return events
    .map(extractPermissionRequest)
    .find(
      (request) =>
        request &&
        !resolved.has(request.permission_id) &&
        !submitted.has(request.permission_id),
    );
}

function dockSubmittedPermissionIds(events: RuntimeEvent[]) {
  const ids = new Set<string>();
  for (const event of events) {
    if (event.type !== "permission.resolve_requested") {
      continue;
    }
    const id = permissionEventId(event);
    if (id) {
      ids.add(id);
    }
  }
  return ids;
}

function dockRunStatus(status: string, events: RuntimeEvent[]) {
  for (const event of [...events].reverse()) {
    const terminal = dockTerminalStatus(event.type);
    if (terminal) {
      return terminal;
    }
  }
  return status;
}

function dockTerminalStatus(eventType: string) {
  if (eventType === "run.completed") {
    return "completed";
  }
  if (eventType === "run.failed") {
    return "failed";
  }
  if (eventType === "run.cancelled") {
    return "cancelled";
  }
  return undefined;
}

function dockRunPreview(events: RuntimeEvent[]) {
  for (const event of [...events].reverse()) {
    const text = eventPreviewText(event);
    if (text) {
      return text.length > 140 ? `${text.slice(0, 140)}...` : text;
    }
  }
  return undefined;
}

function eventPreviewText(event: RuntimeEvent) {
  const direct =
    stringValue(event.data.text) ??
    stringValue(event.data.message) ??
    stringValue(event.data.output) ??
    stringValue(event.data.prompt_preview);
  if (direct) {
    return direct;
  }
  const raw = recordValue(event.data.raw);
  const data = recordValue(raw?.data);
  const update = recordValue(data?.update) ?? data;
  const content = recordValue(update?.content);
  return stringValue(content?.text) ?? stringValue(update?.rawOutput);
}

function recordValue(value: unknown) {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value : undefined;
}

export const __shellTestUtils = {
  dockPendingPermission,
  dockRunStatus,
  dockRunPreview,
  eventPreviewText,
};
