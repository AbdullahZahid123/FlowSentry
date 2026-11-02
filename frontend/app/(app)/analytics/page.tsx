"use client";
import { useWorkspaceTime } from "@/lib/use-workspace-time";
import Link from "next/link";
import { useState } from "react";
import {
  BarChart,
  Bar,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useApi } from "@/lib/use-api";
import { fmtDuration } from "@/lib/api";
import { PageHeading, PanelHeading } from "@/components/page";
import { ErrorBox, Skeleton, SeverityBadge } from "@/components/ui";
type Ranking = {
  workflow_id: string;
  name: string;
  criticality: string;
  total_executions: number;
  success_count: number;
  failure_count: number;
  success_rate: number | null;
  avg_duration_ms: number | null;
};
export default function Analytics() {
 const {timeZone}=useWorkspaceTime();
  const [hours, setHours] = useState(168);
  const ranking = useApi<Ranking[]>("/analytics/workflows", {
    window_hours: hours,
  });
  const trend = useApi<{
    incidents_created: number;
    incidents_resolved: number;
    mtta_seconds: number | null;
    mttr_seconds: number | null;
  }>("/analytics/incidents", { window_hours: hours });
  const series = useApi<{ bucket: string; success: number; failed: number }[]>(
    "/analytics/executions",
    { window_hours: hours, bucket_hours: Math.max(1, hours / 24) },
  );
  const t = trend.data;
  return (
    <div className="space-y-6">
      <PageHeading
        title="Analytics"
        description="Compare execution outcomes and failures over time."
        action={
          <select
            aria-label="Analytics time range"
            value={hours}
            className="!w-auto !text-xs"
            onChange={(e) => setHours(Number(e.target.value))}
          >
            <option value={24}>Last 24 hours</option>
            <option value={168}>Last 7 days</option>
            <option value={720}>Last 30 days</option>
          </select>
        }
      />
      {trend.error ? (
        <ErrorBox message={trend.error} retry={trend.reload} />
      ) : (
        <div className="metric-grid">
          {[
            [
              "Incidents created",
              t?.incidents_created ?? "—",
              "New incidents in this period",
            ],
            [
              "Incidents resolved",
              t?.incidents_resolved ?? "—",
              "Resolved in this period",
            ],
            [
              "Mean time to acknowledge",
              fmtDuration(
                t?.mtta_seconds != null ? t.mtta_seconds * 1000 : null,
              ),
              "From failure to acknowledgement",
            ],
            [
              "Mean time to resolution",
              fmtDuration(
                t?.mttr_seconds != null ? t.mttr_seconds * 1000 : null,
              ),
              "From failure to resolution",
            ],
          ].map(([label, value, foot]) => (
            <div className="metric-cell" key={label}>
              <p className="metric-label">{label}</p>
              <p className="metric-value">{value}</p>
              <p className="metric-foot">{foot}</p>
            </div>
          ))}
        </div>
      )}
      <section className="card">
        <PanelHeading
          title="Execution outcomes"
          description="Observed successes and failures, grouped over time"
        />
        {series.error ? (
          <div className="p-5">
            <ErrorBox message={series.error} retry={series.reload} />
          </div>
        ) : series.loading ? (
          <div className="p-5">
            <Skeleton rows={5} />
          </div>
        ) : series.data?.length ? (
          <div className="px-5 pb-5">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart
                data={series.data.map((s) => ({
                  ...s,
                  time: new Date(s.bucket).toLocaleString(undefined, {
                    timeZone,
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                  }),
                }))}
                margin={{ left: -20, right: 10, top: 15 }}
              >
                <CartesianGrid
                  vertical={false}
                  stroke="var(--border)"
                  strokeDasharray="3 3"
                />
                <XAxis
                  dataKey="time"
                  tick={{ fill: "var(--muted)", fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                  minTickGap={45}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fill: "var(--muted)", fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  contentStyle={{
                    fontSize: 11,
                    background: "var(--surface)",
                    borderColor: "var(--border)",
                    borderRadius: 8,
                  }}
                  cursor={{ fill: "var(--surface-2)" }}
                />
                <Bar
                  dataKey="success"
                  name="Successful"
                  fill="#91bca0"
                  stackId="r"
                  radius={[3, 3, 0, 0]}
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="failed"
                  name="Failed"
                  fill="#d68d7c"
                  stackId="r"
                  radius={[3, 3, 0, 0]}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
            <div className="flex justify-center gap-5 text-[11px] muted">
              <span className="flex items-center gap-2">
                <i className="h-2 w-2 rounded-sm bg-[#91bca0]" />
                Successful
              </span>
              <span className="flex items-center gap-2">
                <i className="h-2 w-2 rounded-sm bg-[#d68d7c]" />
                Failed
              </span>
            </div>
          </div>
        ) : (
          <p className="muted flex h-52 items-center justify-center text-xs">
            No execution data in this period.
          </p>
        )}
      </section>
      <section className="card overflow-hidden">
        <PanelHeading
          title="Workflow reliability"
          description="Ordered by failure count in the selected period"
        />
        {ranking.error ? (
          <div className="p-5">
            <ErrorBox message={ranking.error} retry={ranking.reload} />
          </div>
        ) : ranking.loading ? (
          <div className="p-5">
            <Skeleton rows={5} />
          </div>
        ) : ranking.data?.length ? (
          <div className="table-wrap">
            <table className="fs">
              <thead>
                <tr>
                  <th>Workflow</th>
                  <th>Criticality</th>
                  <th>Executions</th>
                  <th>Successful</th>
                  <th>Failed</th>
                  <th>Success rate</th>
                  <th>Avg. duration</th>
                </tr>
              </thead>
              <tbody>
                {ranking.data.map((w) => (
                  <tr key={w.workflow_id}>
                    <td>
                      <Link
                        className="font-medium"
                        href={`/workflows/${w.workflow_id}`}
                      >
                        {w.name}
                      </Link>
                    </td>
                    <td>
                      <SeverityBadge severity={w.criticality} />
                    </td>
                    <td className="mono">
                      {w.total_executions.toLocaleString()}
                    </td>
                    <td className="mono text-[var(--ok)]">
                      {w.success_count.toLocaleString()}
                    </td>
                    <td
                      className="mono"
                      style={{
                        color: w.failure_count ? "var(--err)" : "var(--muted)",
                      }}
                    >
                      {w.failure_count.toLocaleString()}
                    </td>
                    <td className="mono">
                      {w.success_rate != null
                        ? `${(w.success_rate * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                    <td className="mono muted">
                      {fmtDuration(w.avg_duration_ms)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted p-10 text-center text-xs">
            Connect an integration to start measuring workflow reliability.
          </p>
        )}
      </section>
      <p className="muted text-[11px] leading-6">
        Success rate = successful ÷ (successful + failed). Running, waiting, and
        unknown outcomes are excluded. A dash means there isn’t enough observed
        data.
      </p>
    </div>
  );
}
