"use client";
import { useWorkspaceTime } from "@/lib/use-workspace-time";
import Link from "next/link";
import { ArrowUpRight, ChevronLeft, ChevronRight } from "lucide-react";
import { Execution } from "@/lib/types";
import { fmtDuration } from "@/lib/api";
import { StatusBadge } from "@/components/ui";
export function ExecutionTable({ items }: { items: Execution[] }) {
  const {fmtDateTime}=useWorkspaceTime();
  return (
    <div className="table-wrap">
      <table className="fs">
        <thead>
          <tr>
            <th>Execution</th>
            <th>Workflow</th>
            <th>Status</th>
            <th>Duration</th>
            <th>Started</th>
            <th>Failed node</th>
            <th>
              <span className="sr-only">Details</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((e) => (
            <tr key={e.id}>
              <td>
                <Link href={`/executions/${e.id}`} className="mono font-medium">
                  #{e.external_id ?? e.id.slice(0, 8)}
                </Link>
              </td>
              <td>
                <Link href={`/executions/${e.id}`} className="font-medium">
                  {e.workflow?.name ?? "View execution"}
                </Link>
                <p className="muted mt-1 text-[10px]">
                  {e.integration?.name ?? "n8n"}
                </p>
              </td>
              <td>
                <StatusBadge status={e.status} />
              </td>
              <td className="mono muted whitespace-nowrap">
                {fmtDuration(e.duration_ms)}
              </td>
              <td className="muted whitespace-nowrap">
                {fmtDateTime(e.started_at)}
              </td>
              <td className="mono muted text-[11px]">{e.failed_node ?? "—"}</td>
              <td>
                <Link
                  aria-label={`Open execution ${e.external_id ?? e.id.slice(0, 8)}`}
                  href={`/executions/${e.id}`}
                >
                  <ArrowUpRight size={14} />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function Pagination({
  next,
  previous,
  onNext,
  onPrevious,
  count,
  loading = false,
}: {
  next?: string | null;
  previous: boolean;
  onNext: () => void;
  onPrevious: () => void;
  count: number;
  loading?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-t px-5 py-3">
      <span className="muted text-[11px]">
        {count} {count === 1 ? "result" : "results"} on this page
      </span>
      <div className="flex gap-2">
        <button
          aria-label="Previous page"
          className="btn btn-secondary !min-h-7 !px-2 !py-1"
          disabled={!previous || loading}
          onClick={onPrevious}
        >
          <ChevronLeft size={13} />
          Previous
        </button>
        <button
          aria-label="Next page"
          className="btn btn-secondary !min-h-7 !px-2 !py-1"
          disabled={!next || loading}
          onClick={onNext}
        >
          Next
          <ChevronRight size={13} />
        </button>
      </div>
    </div>
  );
}
