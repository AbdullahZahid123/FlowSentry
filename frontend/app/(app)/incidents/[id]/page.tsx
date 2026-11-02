"use client";
import { useWorkspaceTime } from "@/lib/use-workspace-time";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import {
  ArrowLeft,
  Check,
  CheckCheck,
  MessageSquare,
  Play,
  RotateCcw,
} from "lucide-react";
import { useApi } from "@/lib/use-api";
import { useSession } from "@/lib/session";
import { api } from "@/lib/api";
import { Incident, Execution, Member } from "@/lib/types";
import {
  ErrorBox,
  Skeleton,
  StatusBadge,
  SeverityBadge,
} from "@/components/ui";
import { PageHeading, PanelHeading, FormDialog } from "@/components/page";
import { Pagination } from "@/components/data-table";
export default function IncidentDetail() {
  const {fmtDateTime,timeZone}=useWorkspaceTime();
  const { id } = useParams<{ id: string }>();
  const { workspaceId, session } = useSession();
  const result = useApi<Incident>(`/incidents/${id}`);
  const [timelineCursors,setTimelineCursors]=useState<(string|undefined)[]>([undefined]);
  const [executionCursors,setExecutionCursors]=useState<(string|undefined)[]>([undefined]);
  const timeline = useApi<
    {
      id: string;
      message: string;
      event_type: string;
      actor_type: string;
      created_at: string;
    }[]
  >(`/incidents/${id}/timeline`,{limit:20,cursor:timelineCursors.at(-1)});
  const executions = useApi<Execution[]>(`/incidents/${id}/executions`, {
    limit: 20,
    cursor:executionCursors.at(-1),
  });
  const members = useApi<Member[]>(`/workspaces/${workspaceId}/members`);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [comment, setComment] = useState("");
  const [resolveOpen, setResolveOpen] = useState(false);
  const [note, setNote] = useState("");
  const i = result.data;
  const canAct =
    session!.memberships.find((m) => m.id === workspaceId)?.role !== "viewer";
  async function mutate(path: string, method: string, body?: unknown) {
    setBusy(true);
    setError("");
    const r = await api(`/incidents/${id}${path}`, {
      workspaceId: workspaceId!,
      method,
      body,
    });
    setBusy(false);
    if (!r.ok) {
      setError(r.error!.message);
      return false;
    }
    window.dispatchEvent(new Event("fs:refresh"));
    setTimelineCursors([undefined]);
    return true;
  }
  return (
    <div>
      <Link
        href="/incidents"
        className="mb-5 inline-flex items-center gap-2 text-xs muted"
      >
        <ArrowLeft size={13} />
        Incidents
      </Link>
      {result.error ? (
        <ErrorBox message={result.error} retry={result.reload} />
      ) : !i ? (
        <Skeleton rows={6} />
      ) : (
        <>
          <PageHeading
            title={i.title}
            description={`${i.workflow?.name ?? "Workflow incident"} · First seen ${fmtDateTime(i.first_seen_at)}`}
            action={
              canAct ? (
                <>
                  {i.status === "open" && (
                    <button
                      className="btn btn-secondary"
                      disabled={busy}
                      onClick={() => mutate("/acknowledge", "POST")}
                    >
                      <Check size={14} />
                      Acknowledge
                    </button>
                  )}
                  {["open", "acknowledged"].includes(i.status) && (
                    <button
                      className="btn btn-secondary"
                      disabled={busy}
                      onClick={() =>
                        mutate("", "PATCH", { status: "investigating" })
                      }
                    >
                      <Play size={12} />
                      Investigate
                    </button>
                  )}
                  {i.status !== "resolved" ? (
                    <button
                      className="btn"
                      disabled={busy}
                      onClick={() => setResolveOpen(true)}
                    >
                      <CheckCheck size={15} />
                      Resolve
                    </button>
                  ) : (
                    <button
                      className="btn btn-secondary"
                      disabled={busy}
                      onClick={() => mutate("", "PATCH", { status: "open" })}
                    >
                      <RotateCcw size={13} />
                      Reopen
                    </button>
                  )}
                </>
              ) : undefined
            }
          />
          {error && (
            <div className="mb-4">
              <ErrorBox message={error} />
            </div>
          )}
          <div className="mb-6 flex flex-wrap items-center gap-4">
            <StatusBadge status={i.status} />
            <SeverityBadge severity={i.severity} />
            <span className="muted border-l pl-4 text-xs">
              {i.occurrence_count} occurrence
              {i.occurrence_count === 1 ? "" : "s"}
            </span>
            <span className="muted text-xs">
              Last seen {fmtDateTime(i.last_seen_at)}
            </span>
          </div>
          <div className="grid items-start gap-5 lg:grid-cols-[1fr_300px]">
            <div className="min-w-0 space-y-5">
              {i.summary && (
                <section className="card">
                  <PanelHeading title="What happened" />
                  <p className="whitespace-pre-wrap break-words px-5 pb-5 text-xs leading-7">
                    {i.summary}
                  </p>
                </section>
              )}
              <section className="card">
                <PanelHeading
                  title="Activity"
                  description="The full history of this incident"
                />
                {timeline.error ? (
                  <div className="p-5">
                    <ErrorBox
                      message={timeline.error}
                      retry={timeline.reload}
                    />
                  </div>
                ) : (
                  <div className="px-6 pb-6">
                    {timeline.data?.length ? (
                      timeline.data.map((t) => (
                        <div key={t.id} className="timeline-item">
                          <div className="mb-1 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[10px] muted">
                            <span className="capitalize">
                              {t.event_type
                                .replaceAll("_", " ")
                                .replaceAll(".", " · ")}
                            </span>
                            <span>{fmtDateTime(t.created_at)}</span>
                          </div>
                          <p className="whitespace-pre-wrap break-words text-xs leading-6">
                            {t.message}
                          </p>
                        </div>
                      ))
                    ) : (
                      <p className="muted text-xs">No activity recorded.</p>
                    )}
                  </div>
                )}
                <Pagination count={timeline.data?.length??0} next={timeline.meta?.next_cursor} previous={timelineCursors.length>1} loading={timeline.loading} onNext={()=>setTimelineCursors([...timelineCursors,timeline.meta?.next_cursor??undefined])} onPrevious={()=>setTimelineCursors(timelineCursors.slice(0,-1))}/>
                {canAct && (
                  <form
                    onSubmit={async (e) => {
                      e.preventDefault();
                      if (
                        await mutate("/comments", "POST", {
                          body: comment,
                          is_internal: true,
                        })
                      )
                        setComment("");
                    }}
                    className="space-y-3 border-t p-5"
                  >
                    <label className="field">
                      Add a comment
                      <textarea
                        required
                        maxLength={8000}
                        rows={3}
                        placeholder="Share what you found or leave a handoff note…"
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                      />
                    </label>
                    <div className="flex justify-end">
                      <button
                        className="btn btn-secondary"
                        disabled={busy || !comment.trim()}
                      >
                        <MessageSquare size={13} />
                        Add comment
                      </button>
                    </div>
                  </form>
                )}
              </section>
              <section className="card overflow-hidden">
                <PanelHeading title="Affected executions" />
                {executions.error ? (
                  <div className="p-5">
                    <ErrorBox
                      message={executions.error}
                      retry={executions.reload}
                    />
                  </div>
                ) : executions.data?.length ? (
                  <div className="table-wrap">
                    <table className="fs">
                      <thead>
                        <tr>
                          <th>Execution</th>
                          <th>Status</th>
                          <th>Failed node</th>
                          <th>Started</th>
                        </tr>
                      </thead>
                      <tbody>
                        {executions.data.map((e) => (
                          <tr key={e.id}>
                            <td>
                              <Link
                                href={`/executions/${e.id}`}
                                className="mono"
                              >
                                #{e.external_id ?? e.id.slice(0, 8)}
                              </Link>
                            </td>
                            <td>
                              <StatusBadge status={e.status} />
                            </td>
                            <td className="mono muted">
                              {e.failed_node ?? "—"}
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
                  <p className="muted px-5 pb-5 text-xs">
                    No linked executions. Trigger failures may have no execution
                    ID.
                  </p>
                )}
                <Pagination count={executions.data?.length??0} next={executions.meta?.next_cursor} previous={executionCursors.length>1} loading={executions.loading} onNext={()=>setExecutionCursors([...executionCursors,executions.meta?.next_cursor??undefined])} onPrevious={()=>setExecutionCursors(executionCursors.slice(0,-1))}/>
              </section>
            </div>
            <section className="card">
              <PanelHeading title="Incident details" />
              <div className="space-y-5 px-5 pb-5">
                <label className="field">
                  Assigned to
                  <select
                    disabled={!canAct || busy}
                    value={i.assigned_to ?? ""}
                    onChange={(e) =>
                      mutate("", "PATCH", {
                        assigned_to: e.target.value || null,
                      })
                    }
                  >
                    <option value="">Unassigned</option>
                    {members.data?.map((m) => (
                      <option key={m.user_id} value={m.user_id}>
                        {m.display_name ?? m.email}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  Severity
                  <select
                    disabled={!canAct || busy}
                    value={i.severity}
                    onChange={(e) =>
                      mutate("", "PATCH", { severity: e.target.value })
                    }
                  >
                    {["critical", "high", "medium", "low"].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </label>
                <dl className="space-y-4 border-t pt-4 text-xs">
                  <div>
                    <dt className="muted mb-1.5">Workflow</dt>
                    <dd>
                      {i.workflow_id ? (
                        <Link
                          className="text-link"
                          href={`/workflows/${i.workflow_id}`}
                        >
                          {i.workflow?.name ?? "View workflow"}
                        </Link>
                      ) : (
                        "Trigger event"
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt className="muted mb-1.5">Integration</dt>
                    <dd>{i.integration?.name ?? "n8n"}</dd>
                  </div>
                  <div>
                    <dt className="muted mb-1.5">Acknowledged</dt>
                    <dd>{fmtDateTime(i.acknowledged_at)}</dd>
                  </div>
                  <div>
                    <dt className="muted mb-1.5">Resolved</dt>
                    <dd>{fmtDateTime(i.resolved_at)}</dd>
                  </div>
                </dl>
                {i.resolution_note && (
                  <div className="rounded-lg bg-[var(--surface-2)] p-3 text-xs leading-6">
                    <p className="mb-1 font-medium">Resolution note</p>
                    {i.resolution_note}
                  </div>
                )}
              </div>
            </section>
          </div>
        </>
      )}
      <FormDialog
        open={resolveOpen}
        onOpenChange={setResolveOpen}
        title="Resolve incident"
        description="Record the resolution so the next operator has the context."
      >
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (
              await mutate("/resolve", "POST", {
                resolution_note: note || null,
              })
            ) {
              setResolveOpen(false);
              setNote("");
            }
          }}
          className="space-y-4"
        >
          <label className="field">
            Resolution note <span className="muted font-normal">Optional</span>
            <textarea
              rows={4}
              maxLength={4000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="What changed, and how did you verify it?"
            />
          </label>
          {error && <ErrorBox message={error} />}
          <div className="flex justify-end">
            <button className="btn" disabled={busy}>
              {busy ? "Resolving…" : "Resolve incident"}
            </button>
          </div>
        </form>
      </FormDialog>
    </div>
  );
}
