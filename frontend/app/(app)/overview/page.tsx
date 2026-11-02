"use client";
import { useWorkspaceTime } from "@/lib/use-workspace-time";
import Link from "next/link";
import { useState } from "react";
import {
  Activity,
  CheckCheck,
  Workflow,
  TriangleAlert,
  Plus,
  CalendarDays,
  ChevronDown,
  ArrowUpRight,
  RefreshCw,
  CircleCheck,
  CircleAlert,
  ArrowRight,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useApi } from "@/lib/use-api";
import { fmtDuration } from "@/lib/api";
import {
  Empty,
  ErrorBox,
  Skeleton,
  SeverityBadge,
  StatusBadge,
} from "@/components/ui";
import {
  PageHeading,
  PanelHeading,
  SetupEmpty,
  ViewAll,
} from "@/components/page";

type Overview = {
  total_executions: number;
  successful_executions: number;
  failed_executions: number;
  success_rate: number | null;
  open_incidents: number;
  monitored_workflows: number;
  disconnected_integrations: number;
};
type Incident = {
  id: string;
  title: string;
  severity: string;
  status: string;
  last_seen_at: string;
  occurrence_count: number;
  workflow?: { name: string };
};
type Execution = {
  id: string;
  external_id: string | null;
  status: string;
  started_at: string | null;
  duration_ms: number | null;
  workflow?: { name: string };
  integration?: { name: string };
};
type Integration = {
  id: string;
  name: string;
  provider: string;
  status: string;
  webhook_only: boolean;
  last_successful_check_at: string | null;
};
export default function OverviewPage() {
  const {fmtDateTime,timeZone}=useWorkspaceTime();
  const [hours, setHours] = useState(24);
  const overview = useApi<Overview>("/analytics/overview", {
    window_hours: hours,
  });
  const series = useApi<{ bucket: string; success: number; failed: number }[]>(
    "/analytics/executions",
    { window_hours: hours, bucket_hours: Math.max(1, hours / 24) },
  );
  const incidents = useApi<Incident[]>("/incidents", {
    status: "open",
    limit: 4,
  });
  const executions = useApi<Execution[]>("/executions", { limit: 5 });
  const integrations = useApi<Integration[]>("/integrations");
  const failures = useApi<{
    failures_by_workflow: { workflow: string; count: number }[];
  }>("/analytics/failures", { window_hours: hours });
  const ov = overview.data;
  const chart = (series.data ?? []).map((s) => ({
    ...s,
    time: new Date(s.bucket).toLocaleString(undefined, {
      timeZone,
      ...(hours > 24
        ? { month: "short", day: "numeric" }
        : { hour: "2-digit", minute: "2-digit" }),
    }),
  }));
  const fmt = (n: number | undefined) =>
    n === undefined ? "—" : n.toLocaleString();
  const refresh = () => window.dispatchEvent(new Event("fs:refresh"));
  return (
    <div className="space-y-6">
      <PageHeading
        title="Overview"
        description="Execution activity, incidents, and connection health across your n8n instances."
        action={
          <>
            <div className="relative">
              <CalendarDays
                size={13}
                className="pointer-events-none absolute left-3 top-3 muted"
              />
              <select
                aria-label="Overview time range"
                className="!min-h-9 !w-auto !py-2 !pl-8 !text-xs"
                value={hours}
                onChange={(e) => setHours(Number(e.target.value))}
              >
                <option value={24}>Last 24 hours</option>
                <option value={168}>Last 7 days</option>
                <option value={720}>Last 30 days</option>
              </select>
            </div>
            <Link href="/integrations?connect=1" className="btn">
              <Plus size={14} />
              Connect integration
            </Link>
          </>
        }
      />
      {overview.error ? (
        <ErrorBox message={overview.error} retry={overview.reload} />
      ) : (
        <>
          <div
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3"
            style={{
              background: ov?.disconnected_integrations || ov?.open_incidents
                ? "color-mix(in srgb,var(--warn) 6%,var(--surface))"
                : "color-mix(in srgb,var(--ok) 5%,var(--surface))",
            }}
          >
            <div className="flex items-center gap-2.5">
              {ov?.disconnected_integrations || ov?.open_incidents ? (
                <CircleAlert size={16} color="var(--warn)" />
              ) : (
                <CircleCheck size={16} color="var(--ok)" />
              )}
              <span className="text-xs font-medium">
                {overview.loading
                  ? "Checking workflow health…"
                  : !ov?.monitored_workflows
                    ? "Ready when your workflows are."
                    : ov.disconnected_integrations
                      ? `${ov.disconnected_integrations} integration${ov.disconnected_integrations === 1 ? " needs" : "s need"} attention`
                      : ov.open_incidents
                        ? `${ov.open_incidents} active incident${ov.open_incidents === 1 ? "" : "s"} to investigate`
                        : "Your workflows are running smoothly."}
              </span>
              <span className="muted hidden border-l pl-3 text-[11px] lg:block">
                {ov?.monitored_workflows
                  ? `${ov.monitored_workflows} workflows monitored across ${integrations.data?.length ?? 0} integration${integrations.data?.length === 1 ? "" : "s"}`
                  : "Connect an integration to start monitoring."}
              </span>
            </div>
            <Link
              href={ov?.open_incidents ? "/incidents" : "/integrations"}
              className="text-link"
            >
              {ov?.open_incidents ? "View incidents" : "View integrations"}
              <ArrowRight size={13} />
            </Link>
          </div>
          <div className="metric-grid">
            {[
              {
                label: "Total executions",
                icon: Activity,
                value: fmt(ov?.total_executions),
                foot: `${fmt(ov?.successful_executions)} successful · ${fmt(ov?.failed_executions)} failed`,
                href: "/executions",
              },
              {
                label: "Success rate",
                icon: CheckCheck,
                value:
                  ov?.success_rate != null
                    ? `${(ov.success_rate * 100).toFixed(1)}%`
                    : "—",
                foot: "Of completed, known-status runs",
                href: "/analytics",
              },
              {
                label: "Active incidents",
                icon: TriangleAlert,
                value: fmt(ov?.open_incidents),
                foot: ov?.open_incidents
                  ? "Open, acknowledged, or investigating"
                  : "No active incidents",
                href: "/incidents",
              },
              {
                label: "Monitored workflows",
                icon: Workflow,
                value: fmt(ov?.monitored_workflows),
                foot: `Across ${integrations.data?.length ?? 0} configured instances`,
                href: "/workflows",
              },
            ].map((m) => (
              <Link
                href={m.href}
                key={m.label}
                className="metric-cell hover:bg-[var(--surface-2)]"
              >
                <div className="metric-label">
                  <m.icon size={14} />
                  {m.label}
                  <ArrowUpRight size={12} className="ml-auto opacity-50" />
                </div>
                <div
                  className="metric-value"
                  style={{
                    color:
                      m.label === "Active incidents" && ov?.open_incidents
                        ? "var(--warn)"
                        : undefined,
                  }}
                >
                  {m.value}
                </div>
                <p className="metric-foot">{m.foot}</p>
              </Link>
            ))}
          </div>
        </>
      )}
      <div className="grid gap-5 xl:grid-cols-[1fr_320px]">
        <section className="card min-w-0">
          <PanelHeading
            title="Execution activity"
            description="Successful and failed runs over time"
            action={
              <div className="flex items-center gap-3 text-[10px] muted">
                <span className="flex items-center gap-1.5">
                  <i className="h-2 w-2 rounded-sm bg-[#91bca0]" />
                  Success
                </span>
                <span className="flex items-center gap-1.5">
                  <i className="h-2 w-2 rounded-sm bg-[#d68d7c]" />
                  Failed
                </span>
                <button
                  className="icon-btn !h-6 !w-6"
                  aria-label="Refresh dashboard"
                  onClick={refresh}
                >
                  <RefreshCw size={12} />
                </button>
              </div>
            }
          />
          <div
            className="px-4 pb-3"
            role="img"
            aria-label="Execution activity chart"
          >
            {series.error ? (
              <ErrorBox message={series.error} retry={series.reload} />
            ) : series.loading ? (
              <div className="h-[225px] p-5">
                <Skeleton rows={4} />
              </div>
            ) : chart.length ? (
              <ResponsiveContainer width="100%" height={225}>
                <BarChart
                  data={chart}
                  margin={{ top: 12, right: 12, left: -22, bottom: 0 }}
                  barSize={hours > 24 ? 12 : 16}
                >
                  <CartesianGrid
                    stroke="var(--border)"
                    vertical={false}
                    strokeDasharray="3 3"
                  />
                  <XAxis
                    dataKey="time"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: "var(--muted)" }}
                    minTickGap={35}
                  />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    allowDecimals={false}
                    tick={{ fontSize: 10, fill: "var(--muted)" }}
                  />
                  <Tooltip
                    cursor={{ fill: "var(--surface-2)" }}
                    contentStyle={{
                      borderColor: "var(--border)",
                      borderRadius: 8,
                      fontSize: 11,
                      background: "var(--surface)",
                    }}
                  />
                  <Bar
                    dataKey="success"
                    name="Successful"
                    stackId="runs"
                    fill="#91bca0"
                    radius={[3, 3, 0, 0]}
                    isAnimationActive={false}
                  />
                  <Bar
                    dataKey="failed"
                    name="Failed"
                    stackId="runs"
                    fill="#d68d7c"
                    radius={[3, 3, 0, 0]}
                    isAnimationActive={false}
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="relative flex h-[225px] items-center justify-center">
                <div className="pointer-events-none absolute inset-5 flex flex-col justify-between opacity-60">
                  {[1, 2, 3, 4].map((i) => (
                    <div key={i} className="border-t border-dashed" />
                  ))}
                </div>
                <p className="muted relative bg-[var(--surface)] px-4 text-xs">
                  No executions in this time range
                </p>
              </div>
            )}
          </div>
          <div className="flex justify-between border-t px-5 py-3 text-[10px] muted">
            <span>Times shown in {timeZone}</span>
            <ViewAll href="/analytics">Explore analytics</ViewAll>
          </div>
        </section>
        <section className="card">
          <PanelHeading
            title="Integration health"
            action={<ViewAll href="/integrations" />}
          />
          {integrations.error ? (
            <div className="p-4">
              <ErrorBox
                message={integrations.error}
                retry={integrations.reload}
              />
            </div>
          ) : integrations.loading ? (
            <div className="p-5">
              <Skeleton rows={3} />
            </div>
          ) : integrations.data?.length ? (
            <div>
              {integrations.data.slice(0, 4).map((i) => (
                <Link key={i.id} href="/integrations" className="activity-row">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border bg-[var(--surface-2)] text-sm font-semibold text-[#bc6e62]">
                    n8n
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium">{i.name}</p>
                    <p className="muted mt-1 text-[10px]">
                      {i.webhook_only
                        ? "Webhook monitoring"
                        : i.last_successful_check_at
                          ? `Checked ${fmtDateTime(i.last_successful_check_at)}`
                          : "Awaiting first health check"}
                    </p>
                  </div>
                  <StatusBadge status={i.status} />
                </Link>
              ))}
              <div className="m-4 rounded-md bg-[var(--surface-2)] px-3 py-3 text-[11px] leading-5 muted">
                Connection health reflects the last source check. Webhook-only
                sources have no polling coverage.
              </div>
            </div>
          ) : (
            <div className="px-5 pb-5">
              <p className="muted mb-4 text-xs leading-6">
                Bring your n8n instances together. Monitor failures without
                changing how your workflows run.
              </p>
              <Link
                href="/integrations?connect=1"
                className="btn btn-secondary w-full"
              >
                <Plus size={14} />
                Connect n8n
              </Link>
            </div>
          )}
        </section>
      </div>
      <section className="card overflow-hidden">
        <PanelHeading
          title="Open incidents"
          description="Failures that need a closer look"
          action={<ViewAll href="/incidents" />}
        />
        {incidents.error ? (
          <div className="p-4">
            <ErrorBox message={incidents.error} retry={incidents.reload} />
          </div>
        ) : incidents.loading ? (
          <div className="p-5">
            <Skeleton rows={3} />
          </div>
        ) : incidents.data?.length ? (
          <div className="table-wrap">
            <table className="fs">
              <thead>
                <tr>
                  <th>Incident</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Occurrences</th>
                  <th>Last seen</th>
                  <th>
                    <span className="sr-only">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {incidents.data.map((i) => (
                  <tr key={i.id}>
                    <td>
                      <Link href={`/incidents/${i.id}`} className="font-medium">
                        {i.title}
                      </Link>
                      <p className="muted mt-1 text-[10px]">
                        {i.workflow?.name || "Workflow unavailable"}
                      </p>
                    </td>
                    <td>
                      <SeverityBadge severity={i.severity} />
                    </td>
                    <td>
                      <StatusBadge status={i.status} />
                    </td>
                    <td className="mono">{i.occurrence_count}</td>
                    <td className="muted whitespace-nowrap">
                      {fmtDateTime(i.last_seen_at)}
                    </td>
                    <td>
                      <Link
                        aria-label={`Investigate ${i.title}`}
                        href={`/incidents/${i.id}`}
                      >
                        <ArrowUpRight size={14} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex items-center gap-4 border-t px-6 py-7">
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--surface-2)]">
              <CircleCheck size={20} color="var(--ok)" />
            </span>
            <div>
              <h3 className="text-xs font-medium">
                Nothing needs your attention
              </h3>
              <p className="muted mt-1 text-[11px]">
                New workflow failures will appear here as incidents.
              </p>
            </div>
          </div>
        )}
      </section>
      <div className="grid gap-5 xl:grid-cols-[1fr_320px]">
        <section className="card min-w-0 overflow-hidden">
          <PanelHeading
            title="Recent executions"
            action={<ViewAll href="/executions" />}
          />
          {executions.error ? (
            <div className="p-4">
              <ErrorBox message={executions.error} retry={executions.reload} />
            </div>
          ) : executions.loading ? (
            <div className="p-5">
              <Skeleton rows={3} />
            </div>
          ) : executions.data?.length ? (
            <div className="table-wrap">
              <table className="fs">
                <thead>
                  <tr>
                    <th>Workflow</th>
                    <th>Status</th>
                    <th>Duration</th>
                    <th>Started</th>
                  </tr>
                </thead>
                <tbody>
                  {executions.data.map((e) => (
                    <tr key={e.id}>
                      <td>
                        <Link
                          href={`/executions/${e.id}`}
                          className="font-medium"
                        >
                          {e.workflow?.name || e.external_id || "Execution"}
                        </Link>
                        <p className="mono muted mt-1 text-[10px]">
                          #{e.external_id ?? e.id.slice(0, 8)}
                        </p>
                      </td>
                      <td>
                        <StatusBadge status={e.status} />
                      </td>
                      <td className="mono muted">
                        {fmtDuration(e.duration_ms)}
                      </td>
                      <td className="muted whitespace-nowrap">
                        {fmtDateTime(e.started_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <SetupEmpty
              title="No executions yet"
              description="Connect n8n to see workflow runs, durations, and error details."
            />
          )}
        </section>
        <section className="card">
          <PanelHeading
            title="Failures by workflow"
            description={`In the last ${hours === 24 ? "24 hours" : hours === 168 ? "7 days" : "30 days"}`}
          />
          {failures.error ? (
            <div className="p-4">
              <ErrorBox message={failures.error} retry={failures.reload} />
            </div>
          ) : failures.data?.failures_by_workflow.length ? (
            <div className="space-y-4 px-5 pb-5">
              {failures.data.failures_by_workflow.slice(0, 5).map((w) => (
                <div key={w.workflow}>
                  <div className="mb-2 flex justify-between gap-3 text-xs">
                    <span className="truncate">{w.workflow}</span>
                    <span className="mono muted">{w.count}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-[var(--surface-2)]">
                    <div
                      className="h-full rounded-full bg-[#d4a18b]"
                      style={{
                        width: `${(w.count / failures.data!.failures_by_workflow[0].count) * 100}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex min-h-40 flex-col items-center justify-center gap-2 px-5 pb-5">
              <CheckCheck size={23} className="muted" />
              <p className="muted text-xs">
                No failures recorded in this period
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
