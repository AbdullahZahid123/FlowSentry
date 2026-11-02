"use client";
import Link from "next/link";
import { ThemeToggle } from "@/components/theme";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import {
  Activity,
  LayoutDashboard,
  Workflow,
  ListFilter,
  TriangleAlert,
  Bell,
  ChartNoAxesCombined,
  Unplug,
  Users,
  Settings,
  Search,
  ChevronDown,
  ChevronRight,
  HelpCircle,
  Moon,
  Sun,
  LogOut,
  Plus,
  ArrowUpRight,
  Loader2,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { useSession } from "@/lib/session";
import { api } from "@/lib/api";
import { Brand, FormDialog, SearchInput } from "@/components/page";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";

const nav = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/workflows", label: "Workflows", icon: Workflow },
  { href: "/executions", label: "Executions", icon: Activity },
  { href: "/incidents", label: "Incidents", icon: TriangleAlert },
  { href: "/alerts", label: "Alert rules", icon: Bell },
  { href: "/analytics", label: "Analytics", icon: ChartNoAxesCombined },
  { href: "/integrations", label: "Integrations", icon: Unplug },
  { href: "/team", label: "Team members", icon: Users },
  { href: "/settings", label: "Settings", icon: Settings },
];
const events = [
  "workflow.updated",
  "integrations.synced",
  "integration.updated",
  "execution.created",
  "executions.updated",
  "incident.created",
  "incident.updated",
  "incident.resolved",
  "notification.queued",
  "notification.delivered",
];
export default function AppLayout({ children }: { children: ReactNode }) {
  const { session, loading } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => {
    if (!loading && !session)
      router.replace("/login?next=" + encodeURIComponent(pathname));
  }, [loading, session, router, pathname]);
  if (loading || !session)
    return (
      <div className="flex min-h-svh items-center justify-center gap-2 text-sm muted">
        <Loader2 size={17} className="animate-spin" /> Opening your workspace…
      </div>
    );
  return (
    <SidebarProvider
      style={{ "--sidebar-width": "240px" } as React.CSSProperties}
    >
      <WorkspaceShell>{children}</WorkspaceShell>
    </SidebarProvider>
  );
}
function WorkspaceShell({ children }: { children: ReactNode }) {
  const { session, workspaceId, setWorkspaceId, reload } = useSession();
  const { setOpenMobile } = useSidebar();
  const pathname = usePathname();
  const [command, setCommand] = useState(false);
  const [search, setSearch] = useState("");
  const [help, setHelp] = useState(false);
  const [create, setCreate] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = nav.find((n) => pathname.startsWith(n.href));
  const membership = session!.memberships.find((m) => m.id === workspaceId);
  useEffect(() => {
    if (!workspaceId) return;
    const source = new EventSource(
      `/api/events/stream?workspace_id=${encodeURIComponent(workspaceId)}`,
    );
    let timeout: ReturnType<typeof setTimeout>;
    const refresh = () => {
      clearTimeout(timeout);
      timeout = setTimeout(
        () => window.dispatchEvent(new Event("fs:refresh")),
        300,
      );
    };
    source.onopen = () => {
      refresh();
    };
    events.forEach((event) => source.addEventListener(event, refresh));
    const fallback = setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, 30000);
    const focus = () => refresh();
    window.addEventListener("focus", focus);
    return () => {
      source.close();
      clearTimeout(timeout);
      clearInterval(fallback);
      window.removeEventListener("focus", focus);
    };
  }, [workspaceId]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setCommand((v) => !v);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  async function createWorkspace(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const r = await api<{ id: string }>("/workspaces", {
      method: "POST",
      body: {
        name,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      },
    });
    setBusy(false);
    if (!r.ok) {
      setError(r.error!.message);
      return;
    }
    await reload();
    setWorkspaceId(r.data!.id);
    setCreate(false);
    setName("");
  }
  return (
    <>
      <Sidebar className="border-r-0">
        <SidebarHeader className="gap-0 px-4 pb-3 pt-5">
          <Link href="/overview" className="sidebar-brand mb-5 px-1">
            <Brand small />
          </Link>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className="workspace-switcher"
                aria-label="Switch workspace"
              >
                <span className="workspace-monogram">
                  {membership?.name.slice(0, 1).toUpperCase() || "W"}
                </span>
                <span className="min-w-0 flex-1 truncate text-left">
                  {membership?.name || "Select workspace"}
                </span>
                <ChevronDown size={13} className="shrink-0 opacity-60" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              sideOffset={6}
              className="w-64 max-w-[calc(100vw-32px)]"
            >
              <DropdownMenuLabel className="text-xs text-muted-foreground">
                Workspaces
              </DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={workspaceId ?? ""}
                onValueChange={setWorkspaceId}
              >
                {session!.memberships.map((m) => (
                  <DropdownMenuRadioItem
                    value={m.id}
                    key={m.id}
                    className="items-start py-2 text-xs"
                  >
                    <span className="break-words">
                      {m.name}
                      <span className="mt-1 block text-[10px] capitalize text-muted-foreground">
                        {m.role}
                      </span>
                    </span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => setCreate(true)}
                className="text-xs"
              >
                <Plus size={14} className="mr-2" />
                New workspace
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <button
            onClick={() => setCommand(true)}
            className="sidebar-search"
            aria-label="Search pages"
          >
            <Search size={14} />
            <span>Search pages</span>
            <kbd>Ctrl K</kbd>
          </button>
        </SidebarHeader>
        <SidebarContent className="sidebar-nav gap-2 px-3">
          <SidebarGroup>
            <SidebarGroupLabel className="mb-1 text-[10px] font-medium text-[#73778c]">
              Monitor
            </SidebarGroupLabel>
            <SidebarMenu>
              {nav.slice(0, 6).map((n) => (
                <SidebarMenuItem key={n.href}>
                  <SidebarMenuButton
                    asChild
                    isActive={pathname.startsWith(n.href)}
                  >
                    <Link
                      href={n.href}
                      onClick={() => setOpenMobile(false)}
                      aria-current={
                        pathname.startsWith(n.href) ? "page" : undefined
                      }
                    >
                      <n.icon />
                      <span>{n.label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroup>
          <SidebarGroup>
            <SidebarGroupLabel className="mb-1 text-[10px] font-medium text-[#73778c]">
              Workspace
            </SidebarGroupLabel>
            <SidebarMenu>
              {nav.slice(6).map((n) => (
                <SidebarMenuItem key={n.href}>
                  <SidebarMenuButton
                    asChild
                    isActive={pathname.startsWith(n.href)}
                  >
                    <Link href={n.href} onClick={() => setOpenMobile(false)}>
                      <n.icon />
                      <span>{n.label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="gap-1 border-t border-sidebar-border px-3 py-3">
          <button onClick={() => setHelp(true)} className="sidebar-help">
            <HelpCircle size={15} />
            <span>Setup guide</span>
            <ArrowUpRight size={12} className="ml-auto" />
          </button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className="sidebar-profile"
                aria-label="Open account menu"
              >
                <span className="sidebar-avatar">
                  {(session!.name || session!.email).slice(0, 2).toUpperCase()}
                </span>
                <span className="min-w-0 flex-1 text-left">
                  <span className="block truncate text-xs font-medium">
                    {session!.name || session!.email.split("@")[0]}
                  </span>
                  <span className="mt-0.5 block text-[10px] capitalize text-muted-foreground">
                    {membership?.role || "Member"}
                  </span>
                </span>
                <ChevronDown
                  size={13}
                  className="shrink-0 text-muted-foreground"
                />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" className="w-60">
              <DropdownMenuLabel className="break-all text-xs font-normal text-muted-foreground">
                {session!.email}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild>
                <Link href="/settings" className="text-xs">
                  <Settings size={14} className="mr-2" />
                  Settings
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-xs"
                onSelect={async () => {
                  const r = await api("/auth/logout", { method: "POST" });
                  if (r.ok) window.location.href = "/login";
                  else setError(r.error!.message);
                }}
              >
                <LogOut size={14} className="mr-2" />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarFooter>
      </Sidebar>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="workspace-header flex h-[67px] shrink-0 items-center justify-between gap-4 border-b bg-[var(--surface)] px-4 md:px-8">
          <div className="flex min-w-0 items-center gap-3 text-xs">
            <SidebarTrigger className="md:hidden" />
            <span className="muted hidden sm:block">Workspace</span>
            <ChevronRight size={12} className="muted hidden sm:block" />
            <span className="truncate">{active?.label || "Overview"}</span>
          </div>
          <div className="flex items-center gap-2">
            <button aria-label="Open setup guide" className="icon-btn" onClick={()=>setHelp(true)}><HelpCircle size={16}/></button>
            <ThemeToggle/>
            <Link href="/incidents" aria-label="View incidents" className="icon-btn"><Bell size={16}/></Link>
          </div>
        </header>
        <main className="workspace-content min-w-0 flex-1 p-4 md:p-8">{children}</main>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-4 text-[10px] muted md:px-8"><span>FlowSentry · Self-hosted</span></footer>
      </div>
      <FormDialog
        open={command}
        onOpenChange={setCommand}
        title="Go to…"
        description="Jump to a page in your workspace."
      >
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Find a page…"
        />
        <div className="space-y-1">
          {nav
            .filter((n) => n.label.toLowerCase().includes(search.toLowerCase()))
            .map((n) => (
              <Link
                onClick={() => setCommand(false)}
                key={n.href}
                href={n.href}
                className="flex items-center gap-3 rounded-md px-3 py-2.5 hover:bg-[var(--surface-2)]"
              >
                <n.icon size={16} />
                {n.label}
                <ChevronRight size={12} className="ml-auto muted" />
              </Link>
            ))}
        </div>
      </FormDialog>
      <FormDialog
        open={help}
        onOpenChange={setHelp}
        title="Connect your first workflow"
        description="FlowSentry monitors your automation platform alongside your existing setup."
      >
        <ol className="space-y-5 py-2 text-sm leading-6">
          <li>
            <strong>1. Connect n8n</strong>
            <p className="muted text-xs">
              Add an instance URL and API key, or choose webhook-only
              monitoring.
            </p>
          </li>
          <li>
            <strong>2. Configure an Error Workflow</strong>
            <p className="muted text-xs">
              Send the Error Trigger payload to the ingest URL using your
              one-time ingress token in the Authorization: Bearer header.
            </p>
          </li>
          <li>
            <strong>3. Choose where alerts go</strong>
            <p className="muted text-xs">
              Add an email or Telegram channel, test delivery, then create an
              alert rule.
            </p>
          </li>
        </ol>
        <Link
          onClick={() => setHelp(false)}
          href="/integrations"
          className="btn"
        >
          Open integrations
          <ArrowUpRight size={14} />
        </Link>
      </FormDialog>
      <FormDialog
        open={create}
        onOpenChange={setCreate}
        title="New workspace"
        description="Keep integrations, incidents, and members in a separate workspace."
      >
        <form onSubmit={createWorkspace} className="space-y-4">
          <label className="field">
            Workspace name
            <input
              className="input"
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          {error && (
            <p role="alert" className="text-[var(--err)]">
              {error}
            </p>
          )}
          <button className="btn" disabled={busy}>
            {busy ? "Creating…" : "Create workspace"}
          </button>
        </form>
      </FormDialog>
    </>
  );
}
