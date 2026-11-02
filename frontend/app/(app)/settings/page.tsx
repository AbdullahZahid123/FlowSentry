"use client";
import { useWorkspaceTime } from "@/lib/use-workspace-time";
import { useEffect, useState } from "react";
import { Save, Plus, Monitor, Check, ArrowUpRight } from "lucide-react";
import { useApi } from "@/lib/use-api";
import { useSession } from "@/lib/session";
import { api } from "@/lib/api";
import { PageHeading, PanelHeading, FormDialog } from "@/components/page";
import { ErrorBox, Skeleton } from "@/components/ui";
type Audit = {
  id: string;
  action: string;
  actor_type: string;
  resource_type: string;
  created_at: string;
};
export default function Settings() {
  const {fmtDateTime,timeZone}=useWorkspaceTime();
  const { session, workspaceId, reload, setWorkspaceId } = useSession();
  const [tab, setTab] = useState("general");
  const [name, setName] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const workspace = useApi<{
    name: string;
    timezone: string;
    member_count: number;
  }>(`/workspaces/${workspaceId}`);
  const sessions =
    useApi<
      {
        id: string;
        user_agent: string;
        last_seen_at: string;
        expires_at: string;
      }[]
    >("/auth/sessions");
  const audit = useApi<Audit[]>("/audit-logs", { limit: 50 });
  const admin = ["owner", "admin"].includes(
    session!.memberships.find((m) => m.id === workspaceId)?.role ?? "",
  );
  useEffect(() => {
    if (workspace.data) {
      setName(workspace.data.name);
      setTimezone(workspace.data.timezone);
    }
  }, [workspace.data]);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    const r = await api(`/workspaces/${workspaceId}`, {
      method: "PATCH",
      workspaceId: workspaceId!,
      body: { name, timezone },
    });
    setBusy(false);
    if (!r.ok) {
      setError(r.error!.message);
      return;
    }
    await reload();
    setNotice("Workspace settings saved.");
    void workspace.reload();
  }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const r = await api<{ id: string }>("/workspaces", {
      method: "POST",
      body: {
        name: newName,
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
    setOpen(false);
    setNewName("");
  }
  return (
    <div>
      <PageHeading
        title="Settings"
        description="Manage workspace details, your account, and audit history."
        action={
          <button
            className="btn btn-secondary"
            onClick={() => {
              setError("");
              setOpen(true);
            }}
          >
            <Plus size={14} />
            New workspace
          </button>
        }
      />
      <div className="tab-list" role="tablist" aria-label="Settings">
        {["general", "account", "audit log"].map((t) => (
          <button
            className="capitalize"
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}
      {notice && (
        <p
          role="status"
          className="mb-4 flex items-center gap-2 text-xs text-[var(--ok)]"
        >
          <Check size={14} />
          {notice}
        </p>
      )}
      {tab === "general" ? (
        <section className="card max-w-3xl">
          <PanelHeading
            title="Workspace details"
            description="The name and timezone for this workspace"
          />
          {workspace.error ? (
            <div className="p-5">
              <ErrorBox message={workspace.error} retry={workspace.reload} />
            </div>
          ) : workspace.loading ? (
            <div className="p-5">
              <Skeleton rows={4} />
            </div>
          ) : (
            <form className="space-y-5 px-5 pb-5" onSubmit={save}>
              <label className="field max-w-md">
                Workspace name
                <input
                  className="input"
                  disabled={!admin}
                  required
                  maxLength={120}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label className="field max-w-md">
                Workspace timezone
                <select
                  disabled={!admin}
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                >
                  {Array.from(
                    new Set([
                      timezone,
                      "UTC",
                      ...Intl.supportedValuesOf("timeZone"),
                    ]),
                  ).map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </select>
                <span className="muted text-[11px] font-normal leading-5">
                  Execution timestamps and charts use this workspace timezone.
                </span>
              </label>
              <div className="flex items-center justify-between border-t pt-5">
                <span className="muted text-xs">
                  {workspace.data?.member_count ?? 0} workspace members
                </span>
                {admin && (
                  <button className="btn" disabled={busy}>
                    <Save size={13} />
                    {busy ? "Saving…" : "Save changes"}
                  </button>
                )}
              </div>
            </form>
          )}
        </section>
      ) : tab === "account" ? (
        <div className="max-w-3xl space-y-5">
          <section className="card">
            <PanelHeading title="Your profile" />
            <dl className="space-y-4 px-5 pb-5 text-xs">
              <div className="flex justify-between">
                <dt className="muted">Name</dt>
                <dd>{session!.name || "Not provided"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="muted">Email address</dt>
                <dd>{session!.email}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="muted">Workspace role</dt>
                <dd className="capitalize">
                  {session!.memberships.find((m) => m.id === workspaceId)?.role}
                </dd>
              </div>
            </dl>
          </section>
          <section className="card">
            <PanelHeading
              title="Active sessions"
              description="Devices currently signed into your account"
            />
            {sessions.error ? (
              <div className="p-5">
                <ErrorBox message={sessions.error} retry={sessions.reload} />
              </div>
            ) : (
              sessions.data?.map((s) => (
                <div
                  key={s.id}
                  className="flex items-center gap-3 border-t px-5 py-4"
                >
                  <Monitor size={17} className="muted shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs" title={s.user_agent}>
                      {s.user_agent || "Unknown device"}
                    </p>
                    <p className="muted mt-1 text-[10px]">
                      Last seen {fmtDateTime(s.last_seen_at)}
                    </p>
                  </div>
                  <button
                    className="text-xs text-[var(--err)]"
                    onClick={async () => {
                      const r = await api(`/auth/sessions/${s.id}`, {
                        method: "DELETE",
                      });
                      if (!r.ok) setError(r.error!.message);
                      else {
                        void sessions.reload();
                        await reload();
                      }
                    }}
                  >
                    Revoke
                  </button>
                </div>
              ))
            )}
          </section>
        </div>
      ) : (
        <section className="card overflow-hidden">
          <PanelHeading
            title="Workspace audit log"
            description="The most recent 50 recorded operations"
          />
          {audit.error ? (
            <div className="p-5">
              <ErrorBox message={audit.error} retry={audit.reload} />
            </div>
          ) : audit.loading ? (
            <div className="p-5">
              <Skeleton rows={5} />
            </div>
          ) : audit.data?.length ? (
            <div className="table-wrap">
              <table className="fs">
                <thead>
                  <tr>
                    <th>Action</th>
                    <th>Resource</th>
                    <th>Actor</th>
                    <th>Recorded</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.data.map((a) => (
                    <tr key={a.id}>
                      <td className="mono text-[11px]">{a.action}</td>
                      <td className="capitalize muted">{a.resource_type}</td>
                      <td className="capitalize muted">{a.actor_type}</td>
                      <td className="muted whitespace-nowrap">
                        {fmtDateTime(a.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted p-10 text-center text-xs">
              No audit activity recorded.
            </p>
          )}
        </section>
      )}
      <FormDialog
        open={open}
        onOpenChange={setOpen}
        title="Create workspace"
        description="Keep a separate set of integrations, incidents, and members."
      >
        <form onSubmit={create} className="space-y-4">
          <label className="field">
            Workspace name
            <input
              className="input"
              required
              maxLength={120}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </label>
          {error && <ErrorBox message={error} />}
          <button className="btn" disabled={busy}>
            {busy ? "Creating…" : "Create workspace"}
          </button>
        </form>
      </FormDialog>
    </div>
  );
}
