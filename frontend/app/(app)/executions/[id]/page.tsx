"use client";
import { useWorkspaceTime } from "@/lib/use-workspace-time";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  ArrowUpRight,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useApi } from "@/lib/use-api";
import { Execution } from "@/lib/types";
import { fmtDuration } from "@/lib/api";
import {
  ErrorBox,
  Skeleton,
  StatusBadge,
  SeverityBadge,
} from "@/components/ui";
import { PageHeading, PanelHeading } from "@/components/page";
export default function ExecutionDetail() {
  const {fmtDateTime,timeZone}=useWorkspaceTime();
  const { id } = useParams<{ id: string }>();
  const result = useApi<Execution>(`/executions/${id}`);
  const events = useApi<
    {
      id: string;
      received_at: string;
      processing_status: string;
      payload_redacted: unknown;
    }[]
  >(`/executions/${id}/events`);
  const e = result.data;
  return (
    <div>
      <Link
        className="mb-5 inline-flex items-center gap-2 text-xs muted"
        href="/executions"
      >
        <ArrowLeft size={13} />
        Executions
      </Link>
      {result.error ? (
        <ErrorBox message={result.error} retry={result.reload} />
      ) : !e ? (
        <Skeleton rows={6} />
      ) : (
        <>
          <PageHeading
            title={`Execution #${e.external_id ?? e.id.slice(0, 8)}`}
            description={`${e.workflow?.name ?? "Workflow"} · ${e.integration?.name ?? "n8n"}`}
            action={
              <>
                <StatusBadge status={e.status} />
                {e.source_url && /^https?:\/\//.test(e.source_url) && (
                  <a
                    className="btn btn-secondary"
                    href={e.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open in n8n
                    <ArrowUpRight size={14} />
                  </a>
                )}
              </>
            }
          />
          <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
            <div className="space-y-5">
              <section className="card">
                <PanelHeading
                  title={
                    e.status === "failed"
                      ? "Failure details"
                      : "Execution result"
                  }
                />
                <div className="px-5 pb-5">
                  {e.error_message_redacted ? (
                    <div className="rounded-lg border border-[var(--err)] bg-[color-mix(in_srgb,var(--err)_4%,var(--surface))] p-4">
                      <div className="mb-3 flex items-center gap-2 text-xs font-medium text-[var(--err)]">
                        <TriangleAlert size={14} />
                        {e.error_class ?? "Workflow failure"}
                      </div>
                      <pre className="mono whitespace-pre-wrap break-words text-xs leading-7">
                        {e.error_message_redacted}
                      </pre>
                    </div>
                  ) : (
                    <p className="muted text-xs leading-6">
                      {e.status === "success"
                        ? "This workflow completed successfully. No error was reported."
                        : "No error details were provided by the source."}
                    </p>
                  )}
                  <div className="mt-5 grid grid-cols-2 gap-5">
                    <div>
                      <p className="muted text-[11px]">Failed node</p>
                      <p className="mono mt-2 text-xs">
                        {e.failed_node ?? "—"}
                      </p>
                    </div>
                    <div>
                      <p className="muted text-[11px]">Error code</p>
                      <p className="mono mt-2 text-xs">{e.error_code ?? "—"}</p>
                    </div>
                  </div>
                </div>
              </section>
              <section className="card">
                <PanelHeading
                  title="Observed events"
                  description="Redacted source payloads received for this execution"
                />
                {events.error ? (
                  <div className="p-5">
                    <ErrorBox message={events.error} retry={events.reload} />
                  </div>
                ) : events.data?.length ? (
                  events.data.map((ev) => (
                    <details className="border-t px-5 py-4" key={ev.id}>
                      <summary className="flex items-center justify-between gap-3 text-xs">
                        <span>{fmtDateTime(ev.received_at)}</span>
                        <StatusBadge status={ev.processing_status} />
                      </summary>
                      <pre className="mono mt-4 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-[var(--surface-2)] p-4 text-[11px] leading-6">
                        {JSON.stringify(ev.payload_redacted, null, 2)}
                      </pre>
                    </details>
                  ))
                ) : (
                  <p className="muted px-5 pb-5 text-xs">
                    No retained source events are available.
                  </p>
                )}
              </section>
            </div>
            <div className="space-y-5">
              <section className="card">
                <PanelHeading title="Run information" />
                <dl className="space-y-4 px-5 pb-5 text-xs">
                  {[
                    ["Started", fmtDateTime(e.started_at)],
                    ["Finished", fmtDateTime(e.finished_at)],
                    ["Duration", fmtDuration(e.duration_ms)],
                    ["First observed", fmtDateTime(e.first_observed_at)],
                    ["Last observed", fmtDateTime(e.last_observed_at)],
                  ].map(([label, value]) => (
                    <div key={label} className="flex justify-between gap-3">
                      <dt className="muted">{label}</dt>
                      <dd className="text-right">{value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
              <section className="card">
                <PanelHeading title="Related incidents" />
                {e.incidents?.length ? (
                  e.incidents.map((i) => (
                    <Link
                      key={i.id}
                      href={`/incidents/${i.id}`}
                      className="block border-t p-5"
                    >
                      <p className="text-xs font-medium leading-6">{i.title}</p>
                      <div className="mt-3 flex gap-3">
                        <SeverityBadge severity={i.severity} />
                        <StatusBadge status={i.status} />
                      </div>
                    </Link>
                  ))
                ) : (
                  <p className="muted px-5 pb-5 text-xs">
                    No linked incidents.
                  </p>
                )}
              </section>
              <div className="flex gap-3 rounded-lg border border-dashed p-4">
                <ShieldCheck size={18} className="muted shrink-0" />
                <p className="muted text-[11px] leading-6">
                  Recovery is available only when the source supports a
                  documented, verified retry capability. Open n8n to review
                  manual recovery options.
                </p>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
