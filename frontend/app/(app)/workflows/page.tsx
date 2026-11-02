"use client";
import { useWorkspaceTime } from "@/lib/use-workspace-time";
import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, Plus, Workflow as WorkflowIcon } from "lucide-react";
import { useApi } from "@/lib/use-api";
import { Workflow, Integration } from "@/lib/types";

import { PageHeading, SearchInput, SetupEmpty } from "@/components/page";
import {
  Skeleton,
  ErrorBox,
  StatusBadge,
  SeverityBadge,
} from "@/components/ui";
import { Pagination } from "@/components/data-table";
export default function WorkflowsPage() {
  const {fmtDateTime,timeZone}=useWorkspaceTime();
  const [search, setSearch] = useState("");
  const [env, setEnv] = useState("");
  const [source, setSource] = useState("");
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const cursor = cursors.at(-1);
  const workflows = useApi<Workflow[]>("/workflows", {
    search: search || undefined,
    environment: env || undefined,
    integration_id: source || undefined,
    limit: 20,
    cursor,
  });
  const integrations = useApi<Integration[]>("/integrations");
  const reset = () => setCursors([undefined]);
  return (
    <div>
      <PageHeading
        title="Workflows"
        description="View workflow health, recent runs, and monitoring settings."
        action={
          <Link href="/integrations?connect=1" className="btn">
            <Plus size={14} />
            Connect integration
          </Link>
        }
      />
      <div className="filter-bar">
        <SearchInput
          value={search}
          onChange={(v) => {
            setSearch(v);
            reset();
          }}
          placeholder="Search workflows…"
        />
        <select
          aria-label="Environment filter"
          value={env}
          onChange={(e) => {
            setEnv(e.target.value);
            reset();
          }}
        >
          <option value="">All environments</option>
          {["production", "staging", "development", "unknown"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select
          aria-label="Integration filter"
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
      </div>
      {workflows.error ? (
        <ErrorBox message={workflows.error} retry={workflows.reload} />
      ) : (
        <section className="card overflow-hidden">
          {workflows.loading ? (
            <div className="p-6">
              <Skeleton rows={7} />
            </div>
          ) : workflows.data?.length ? (
            <>
              <div className="table-wrap">
                <table className="fs">
                  <thead>
                    <tr>
                      <th>Workflow</th>
                      <th>Health</th>
                      <th>Environment</th>
                      <th>Criticality</th>
                      <th>Last synced</th>
                      <th>
                        <span className="sr-only">Details</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {workflows.data.map((w) => (
                      <tr key={w.id}>
                        <td>
                          <Link
                            href={`/workflows/${w.id}`}
                            className="flex items-center gap-3"
                          >
                            <span className="flex h-8 w-8 items-center justify-center rounded-lg border bg-[var(--surface-2)]">
                              <WorkflowIcon size={15} className="muted" />
                            </span>
                            <span>
                              <span className="font-medium">{w.name}</span>
                              <span className="muted mt-1 block text-[10px]">
                                {w.integration?.name ??
                                  integrations.data?.find(
                                    (i) => i.id === w.integration_id,
                                  )?.name ??
                                  "n8n"}
                              </span>
                            </span>
                          </Link>
                        </td>
                        <td>
                          <StatusBadge status={w.health?.state ?? "unknown"} />
                        </td>
                        <td className="capitalize muted">{w.environment}</td>
                        <td>
                          <SeverityBadge severity={w.criticality} />
                        </td>
                        <td className="muted whitespace-nowrap">
                          {fmtDateTime(w.last_synced_at)}
                        </td>
                        <td>
                          <Link
                            href={`/workflows/${w.id}`}
                            aria-label={`Open ${w.name}`}
                          >
                            <ArrowUpRight size={14} />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination
                count={workflows.data.length}
                next={workflows.meta?.next_cursor}
                previous={cursors.length > 1}
                onNext={() =>
                  setCursors((p) => [
                    ...p,
                    workflows.meta?.next_cursor ?? undefined,
                  ])
                }
                onPrevious={() => setCursors((p) => p.slice(0, -1))}
              />
            </>
          ) : (
            <SetupEmpty
              title={
                search || env || source
                  ? "No matching workflows"
                  : "Your workflows belong here"
              }
              description={
                search || env || source
                  ? "Adjust your search or filters to see more workflows."
                  : "Connect an n8n instance to discover workflows and monitor their reliability."
              }
            />
          )}
        </section>
      )}
    </div>
  );
}
