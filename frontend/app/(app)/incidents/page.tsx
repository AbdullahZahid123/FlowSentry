"use client";
import { useWorkspaceTime } from "@/lib/use-workspace-time";
import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, CircleCheck, TriangleAlert } from "lucide-react";
import { useApi } from "@/lib/use-api";
import { Incident } from "@/lib/types";

import { PageHeading, SearchInput } from "@/components/page";
import {
  ErrorBox,
  Skeleton,
  SeverityBadge,
  StatusBadge,
  Empty,
} from "@/components/ui";
import { Pagination } from "@/components/data-table";
export default function IncidentsPage() {
  const {fmtDateTime,timeZone}=useWorkspaceTime();
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [search, setSearch] = useState("");
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const result = useApi<Incident[]>("/incidents", {
    status: status || undefined,
    severity: severity || undefined,
    search: search || undefined,
    limit: 20,
    cursor: cursors.at(-1),
  });
  const reset = () => setCursors([undefined]);
  return (
    <div>
      <PageHeading
        title="Incidents"
        description="Investigate grouped failures, assign owners, and track resolutions."
      />
      <div className="filter-bar">
        <SearchInput
          value={search}
          onChange={(v) => {
            setSearch(v);
            reset();
          }}
          placeholder="Search incidents…"
        />
        <select
          aria-label="Incident status"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            reset();
          }}
        >
          <option value="">All statuses</option>
          {[
            "open",
            "acknowledged",
            "investigating",
            "recovering",
            "resolved",
            "suppressed",
          ].map((s) => (
            <option key={s} value={s}>
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
        <select
          aria-label="Incident severity"
          value={severity}
          onChange={(e) => {
            setSeverity(e.target.value);
            reset();
          }}
        >
          <option value="">All severities</option>
          {["critical", "high", "medium", "low"].map((s) => (
            <option key={s} value={s}>
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
      </div>
      {result.error ? (
        <ErrorBox message={result.error} retry={result.reload} />
      ) : (
        <section className="card overflow-hidden">
          {result.loading ? (
            <div className="p-6">
              <Skeleton rows={7} />
            </div>
          ) : result.data?.length ? (
            <>
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
                        <span className="sr-only">Details</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.data.map((i) => (
                      <tr key={i.id}>
                        <td>
                          <Link
                            href={`/incidents/${i.id}`}
                            className="flex items-center gap-3"
                          >
                            <TriangleAlert
                              size={16}
                              className="shrink-0 text-[var(--warn)]"
                            />
                            <span>
                              <span className="font-medium">{i.title}</span>
                              <span className="muted mt-1 block text-[10px]">
                                {i.workflow?.name ?? "Workflow incident"}
                              </span>
                            </span>
                          </Link>
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
                            href={`/incidents/${i.id}`}
                            aria-label={`Investigate ${i.title}`}
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
            <div className="flex min-h-72 flex-col items-center justify-center p-8 text-center">
              <CircleCheck size={32} className="mb-4 text-[var(--ok)]" />
              <h2 className="font-semibold">
                {status || severity || search
                  ? "No matching incidents"
                  : "You’re all caught up"}
              </h2>
              <p className="muted mt-2 max-w-sm text-xs leading-6">
                {status || severity || search
                  ? "Adjust the filters to find what you’re looking for."
                  : "Workflow failures will be grouped into incidents here, ready to investigate."}
              </p>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
