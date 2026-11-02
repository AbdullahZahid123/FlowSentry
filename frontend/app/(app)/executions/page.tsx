"use client";
import { useEffect, useState } from "react";
import { Download, Activity } from "lucide-react";
import { useApi } from "@/lib/use-api";
import { Execution, Integration, Workflow } from "@/lib/types";
import { PageHeading, SetupEmpty } from "@/components/page";
import { ErrorBox, Skeleton } from "@/components/ui";
import { ExecutionTable, Pagination } from "@/components/data-table";
export default function ExecutionsPage() {
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const [workflow, setWorkflow] = useState("");
  useEffect(() => {
    setWorkflow(
      new URLSearchParams(window.location.search).get("workflow_id") || "",
    );
  }, []);
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const result = useApi<Execution[]>("/executions", {
    status: status || undefined,
    integration_id: source || undefined,
    workflow_id: workflow || undefined,
    limit: 20,
    cursor: cursors.at(-1),
  });
  const integrations = useApi<Integration[]>("/integrations");
  const workflows = useApi<Workflow[]>("/workflows", { limit: 200 });
  const reset = () => setCursors([undefined]);
  function download() {
    const items = result.data ?? [];
    const cell = (v: unknown) =>
      `"${String(v ?? "")
        .replaceAll('"', '""')
        .replace(/^[=+@-]/, "'$&")}"`;
    const csv = [
      [
        "Execution",
        "Workflow",
        "Status",
        "Started",
        "Duration ms",
        "Failed node",
      ],
      ...items.map((e) => [
        e.external_id ?? e.id,
        e.workflow?.name,
        e.status,
        e.started_at,
        e.duration_ms,
        e.failed_node,
      ]),
    ]
      .map((row) => row.map(cell).join(","))
      .join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(
      new Blob([csv], { type: "text/csv;charset=utf-8" }),
    );
    a.download = "flowsentry-executions-page.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }
  return (
    <div>
      <PageHeading
        title="Executions"
        description="Search runs and inspect their status, duration, and error details."
        action={
          <button
            className="btn btn-secondary"
            disabled={!result.data?.length}
            onClick={download}
          >
            <Download size={14} />
            Export page
          </button>
        }
      />
      <div className="filter-bar">
        <select
          aria-label="Execution status"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            reset();
          }}
        >
          <option value="">All statuses</option>
          {[
            "success",
            "failed",
            "running",
            "waiting",
            "canceled",
            "unknown",
          ].map((s) => (
            <option key={s} value={s}>
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
        <select
          aria-label="Execution integration"
          value={source}
          onChange={(e) => {
            setSource(e.target.value);
            reset();
          }}
        >
          <option value="">All integrations</option>
          {integrations.data?.map((i) => (
            <option key={i.id} value={i.id}>
              {i.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Execution workflow"
          value={workflow}
          onChange={(e) => {
            setWorkflow(e.target.value);
            reset();
          }}
        >
          <option value="">All workflows</option>
          {workflows.data?.map((i) => (
            <option key={i.id} value={i.id}>
              {i.name}
            </option>
          ))}
        </select>
        <span className="muted ml-auto flex items-center gap-1.5 text-[11px]">
          <Activity size={12} />
          Most recent first
        </span>
      </div>
      {result.error ? (
        <ErrorBox message={result.error} retry={result.reload} />
      ) : (
        <section className="card overflow-hidden">
          {result.loading ? (
            <div className="p-6">
              <Skeleton rows={8} />
            </div>
          ) : result.data?.length ? (
            <>
              <ExecutionTable items={result.data} />
              <Pagination
                count={result.data.length}
                next={result.meta?.next_cursor}
                previous={cursors.length > 1}
                onNext={() =>
                  setCursors((p) => [
                    ...p,
                    result.meta?.next_cursor ?? undefined,
                  ])
                }
                onPrevious={() => setCursors((p) => p.slice(0, -1))}
              />
            </>
          ) : (
            <SetupEmpty
              title={
                status || source || workflow
                  ? "No matching executions"
                  : "No executions yet"
              }
              description={
                status || source || workflow
                  ? "Try a different status, source, or workflow."
                  : "Workflow executions appear after an integration syncs runs or receives a webhook."
              }
            />
          )}
        </section>
      )}
    </div>
  );
}
