"use client";
import { useWorkspaceTime } from "@/lib/use-workspace-time";
import Link from "next/link";
import dynamic from "next/dynamic";
const WorkflowLogicMap=dynamic(()=>import("@/components/workflow-logic-map"),{ssr:false,loading:()=> <div className="card mb-6 p-5 muted">Loading workflow logic…</div>});
import { useParams } from "next/navigation";
import { useState } from "react";
import { ArrowLeft, Settings2, Save } from "lucide-react";
import { useApi } from "@/lib/use-api";
import { useSession } from "@/lib/session";
import { api, fmtDuration } from "@/lib/api";
import { Workflow, Execution } from "@/lib/types";
import {
  ErrorBox,
  Skeleton,
  StatusBadge,
  SeverityBadge,
  Empty,
} from "@/components/ui";
import { PageHeading, PanelHeading, FormDialog } from "@/components/page";
import { ExecutionTable } from "@/components/data-table";
export default function WorkflowDetail() {
  const {fmtDateTime,timeZone}=useWorkspaceTime();
  const { id } = useParams<{ id: string }>();
  const { workspaceId, session } = useSession();
  const result = useApi<Workflow>(`/workflows/${id}`);
  const executions = useApi<Execution[]>(`/workflows/${id}/executions`, {
    limit: 20,
  });
  const health = useApi<{
    health_state: string;
    health_score: number | null;
    total_executions: number;
    success_rate: number | null;
    avg_duration_ms: number | null;
    signals: Record<string, unknown>;
  }>(`/workflows/${id}/health`);
  const [open, setOpen] = useState(false);
  const [monitoring, setMonitoring]=useState(true);
  const [env, setEnv] = useState("production");
  const [criticality, setCriticality] = useState("normal");
  const [interval, setInterval] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const w = result.data;
  const canEdit =
    session!.memberships.find((m) => m.id === workspaceId)?.role !== "viewer";
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const r = await api(`/workflows/${id}`, {
      method: "PATCH",
      workspaceId: workspaceId!,
      body: {
        monitoring_enabled: monitoring,
        environment: env,
        criticality,
        expected_interval_seconds: interval ? Number(interval) : null,
      },
    });
    setBusy(false);
    if (!r.ok) {
      setError(r.error!.message);
      return;
    }
    setOpen(false);
    window.dispatchEvent(new Event("fs:refresh"));
  }
  return (
    <div>
      <Link
        href="/workflows"
        className="mb-5 inline-flex items-center gap-2 text-xs muted"
      >
        <ArrowLeft size={13} />
        Workflows
      </Link>
      {result.error ? (
        <ErrorBox message={result.error} retry={result.reload} />
      ) : !w ? (
        <Skeleton rows={6} />
      ) : (
        <>
          <PageHeading
            title={w.name}
            description={`${w.integration?.name ?? "n8n"} · ${w.environment}`}
            action={
              <>
                <StatusBadge
                  status={health.data?.health_state ?? w.health?.state}
                />
                {canEdit && (
                  <button
                    className="btn btn-secondary"
                    onClick={() => {
                      setMonitoring(w.monitoring_enabled);
                      setEnv(w.environment);
                      setCriticality(w.criticality);
                      setInterval(
                        w.expected_interval_seconds?.toString() ?? "",
                      );
                      setOpen(true);
                    }}
                  >
                    <Settings2 size={14} />
                    Configure workflow
                  </button>
                )}
              </>
            }
          />
          {health.error && (
            <div className="mb-4">
              <ErrorBox message={health.error} retry={health.reload} />
            </div>
          )}
          <div className="metric-grid mb-6">
            {[
              [
                "Health score",
                health.data?.health_score != null
                  ? `${health.data.health_score}/100`
                  : "—",
              ],
              [
                "Success rate",
                health.data?.success_rate != null
                  ? `${(health.data.success_rate * 100).toFixed(1)}%`
                  : "—",
              ],
              ["Executions", health.data?.total_executions ?? "—"],
              ["Average duration", fmtDuration(health.data?.avg_duration_ms)],
            ].map(([label, value]) => (
              <div key={label} className="metric-cell">
                <p className="metric-label">{label}</p>
                <div className="metric-value">{value}</div>
                <p className="metric-foot">Trailing 24 hours</p>
              </div>
            ))}
          </div>
          <WorkflowLogicMap logic={w.logic}/>
          <div className="grid gap-5 lg:grid-cols-[1fr_300px]">
            <section className="card min-w-0 overflow-hidden">
              <PanelHeading
                title="Recent executions"
                action={
                  <Link
                    className="text-link"
                    href={`/executions?workflow_id=${id}`}
                  >
                    Execution history
                  </Link>
                }
              />
              {executions.error ? (
                <div className="p-5">
                  <ErrorBox
                    message={executions.error}
                    retry={executions.reload}
                  />
                </div>
              ) : executions.data?.length ? (
                <ExecutionTable
                  items={executions.data.map((e) => ({
                    ...e,
                    workflow: w,
                    integration: w.integration,
                  }))}
                />
              ) : (
                <Empty
                  title="No executions observed"
                  hint="Runs appear here after ingestion or reconciliation."
                />
              )}
            </section>
            <section className="card">
              <PanelHeading title="Workflow details" />
              <dl className="space-y-5 px-5 pb-5 text-xs">
                <div className="flex justify-between">
                  <dt className="muted">Criticality</dt>
                  <dd>
                    <SeverityBadge severity={w.criticality} />
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="muted">Source status</dt>
                  <dd>
                    {w.is_active === null
                      ? "Unknown"
                      : w.is_active
                        ? "Active"
                        : "Inactive"}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="muted">Expected interval</dt>
                  <dd>
                    {w.expected_interval_seconds
                      ? `${w.expected_interval_seconds}s`
                      : "Not configured"}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="muted">Last synced</dt>
                  <dd>{fmtDateTime(w.last_synced_at)}</dd>
                </div>
                <div>
                  <dt className="muted mb-2">Provider workflow ID</dt>
                  <dd className="mono break-all">{w.external_id}</dd>
                </div>
              </dl>
              <p className="muted border-t px-5 py-4 text-[11px] leading-6">
                Health uses the last 24 hours of known outcomes. Running and
                unknown-status executions are excluded from the success rate.
              </p>
            </section>
          </div>
        </>
      )}
      <FormDialog
        open={open}
        onOpenChange={setOpen}
        title="Workflow configuration"
        description="Add operational context to this workflow."
      >
        <form className="space-y-4" onSubmit={save}>
          <label className="flex items-start gap-3 rounded-md border p-3 text-xs"><input type="checkbox" className="mt-0.5 accent-[var(--accent)]" checked={monitoring} onChange={e=>setMonitoring(e.target.checked)}/><span>Monitor this workflow<span className="muted mt-1 block text-[11px] leading-5">Collect new executions and create incidents. Existing history is kept when monitoring is paused.</span></span></label>
          <label className="field">
            Environment
            <select value={env} onChange={(e) => setEnv(e.target.value)}>
              {["production", "staging", "development", "unknown"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Criticality
            <select
              value={criticality}
              onChange={(e) => setCriticality(e.target.value)}
            >
              {["critical", "high", "normal", "low"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Expected interval in seconds
            <input
              className="input"
              type="number"
              min={30}
              max={31536000}
              placeholder="Optional"
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
            />
          </label>
          {error && <ErrorBox message={error} />}
          <div className="flex justify-end">
            <button className="btn" disabled={busy}>
              <Save size={14} />
              {busy ? "Saving…" : "Save configuration"}
            </button>
          </div>
        </form>
      </FormDialog>
    </div>
  );
}
