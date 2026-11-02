"use client";
import { useWorkspaceTime } from "@/lib/use-workspace-time";
import { useState } from "react";
import { Plus, Users, Copy, UserPlus } from "lucide-react";
import { useApi } from "@/lib/use-api";
import { useSession } from "@/lib/session";
import { api } from "@/lib/api";
import { Member } from "@/lib/types";
import {
  PageHeading,
  PanelHeading,
  FormDialog,
  CopyButton,
} from "@/components/page";
import { ErrorBox, Skeleton } from "@/components/ui";
type Invitation = {
  id: string;
  email: string;
  role: string;
  expires_at: string;
  accepted_at?: string | null;
  token_once?: string;
};
export default function Team() {
  const {fmtDateTime,timeZone}=useWorkspaceTime();
  const { workspaceId, session } = useSession();
  const members = useApi<Member[]>(`/workspaces/${workspaceId}/members`);
  const invitations = useApi<Invitation[]>(
    `/workspaces/${workspaceId}/invitations`,
  );
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("operator");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<Invitation | null>(null);
  const currentRole = session!.memberships.find(
    (m) => m.id === workspaceId,
  )?.role;
  const admin = ["admin", "owner"].includes(currentRole ?? "");
  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const r = await api<Invitation>(`/workspaces/${workspaceId}/invitations`, {
      method: "POST",
      workspaceId: workspaceId!,
      body: { email, role },
    });
    setBusy(false);
    if (!r.ok) {
      setError(r.error!.message);
      return;
    }
    setCreated(r.data!);
    void invitations.reload();
  }
  async function changeRole(m: Member, role: string) {
    const r = await api(`/workspaces/${workspaceId}/members/${m.user_id}`, {
      method: "PATCH",
      workspaceId: workspaceId!,
      body: { role },
    });
    if (!r.ok) setError(r.error!.message);
    else void members.reload();
  }
  return (
    <div className="space-y-6">
      <PageHeading
        title="Team members"
        description="Manage workspace access and invitations."
        action={
          admin ? (
            <button
              className="btn"
              onClick={() => {
                setOpen(true);
                setError("");
                setCreated(null);
              }}
            >
              <UserPlus size={14} />
              Invite member
            </button>
          ) : undefined
        }
      />
      {error && !open && <ErrorBox message={error} />}
      <section className="card overflow-hidden">
        <PanelHeading
          title="Workspace members"
          description={`${members.data?.length ?? 0} members in this workspace`}
        />
        {members.error ? (
          <div className="p-5">
            <ErrorBox message={members.error} retry={members.reload} />
          </div>
        ) : members.loading ? (
          <div className="p-5">
            <Skeleton rows={4} />
          </div>
        ) : (
          <div className="table-wrap">
            <table className="fs">
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Role</th>
                  <th>Joined</th>
                </tr>
              </thead>
              <tbody>
                {members.data?.map((m) => (
                  <tr key={m.user_id}>
                    <td>
                      <div className="flex items-center gap-3">
                        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--surface-2)] text-[11px] text-[var(--accent)]">
                          {(m.display_name || m.email)
                            .slice(0, 2)
                            .toUpperCase()}
                        </span>
                        <div>
                          <p className="font-medium">
                            {m.display_name || m.email.split("@")[0]}
                            {m.user_id === session!.id && (
                              <span className="muted ml-2 text-[10px]">
                                you
                              </span>
                            )}
                          </p>
                          <p className="muted mt-1 text-[10px]">{m.email}</p>
                        </div>
                      </div>
                    </td>
                    <td>
                      {currentRole === "owner" && m.user_id !== session!.id ? (
                        <select
                          aria-label={`Role for ${m.email}`}
                          className="!min-h-7 !w-28 !py-1 !text-xs"
                          value={m.role}
                          onChange={(e) => changeRole(m, e.target.value)}
                        >
                          {["owner", "admin", "operator", "viewer"].map((r) => (
                            <option key={r}>{r}</option>
                          ))}
                        </select>
                      ) : (
                        <span className="rounded border px-2 py-1 text-[10px] capitalize">
                          {m.role}
                        </span>
                      )}
                    </td>
                    <td className="muted whitespace-nowrap">
                      {fmtDateTime(m.joined_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {admin && (
        <section className="card overflow-hidden">
          <PanelHeading
            title="Pending invitations"
            description="Invitation links expire after seven days"
          />
          {invitations.error ? (
            <div className="p-5">
              <ErrorBox
                message={invitations.error}
                retry={invitations.reload}
              />
            </div>
          ) : invitations.data?.length ? (
            <div className="table-wrap">
              <table className="fs">
                <thead>
                  <tr>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Expires</th>
                  </tr>
                </thead>
                <tbody>
                  {invitations.data.map((i) => (
                    <tr key={i.id}>
                      <td>{i.email}</td>
                      <td className="capitalize muted">{i.role}</td>
                      <td className="muted">{fmtDateTime(i.expires_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted px-5 pb-6 text-xs">
              No pending invitations. Invite a teammate when you’re ready.
            </p>
          )}
        </section>
      )}
      <section className="grid gap-4 sm:grid-cols-3">
        {[
          [
            "Admin",
            "Manages integrations, alert rules, and workspace members.",
          ],
          ["Operator", "Investigates incidents and updates workflow metadata."],
          ["Viewer", "Reads workspace data without making changes."],
        ].map(([r, d]) => (
          <div key={r} className="rounded-lg border border-dashed p-4">
            <h3 className="text-xs font-medium">{r}</h3>
            <p className="muted mt-2 text-[11px] leading-6">{d}</p>
          </div>
        ))}
      </section>
      <FormDialog
        open={open}
        onOpenChange={(v) => {
          setOpen(v);
          if (!v) {
            setCreated(null);
            setEmail("");
          }
        }}
        title={created ? "Your invitation is ready" : "Invite a teammate"}
        description={
          created
            ? "Copy and share this one-time link with your teammate."
            : "Choose their email address and access level."
        }
      >
        {created ? (
          <div className="space-y-4">
            <p className="text-xs">
              Invited <strong>{created.email}</strong> as {created.role}.
            </p>
            <div className="rounded-lg bg-[var(--surface-2)] p-4">
              <code className="block break-all text-[11px] leading-6">{`${window.location.origin}/login?invite=${created.token_once}`}</code>
              <div className="mt-3">
                <CopyButton
                  value={`${window.location.origin}/login?invite=${created.token_once}`}
                />
              </div>
            </div>
            <p className="muted text-xs leading-6">
              This link is displayed only once. No invitation email has been
              sent.
            </p>
            <button
              className="btn"
              onClick={() => {
                setOpen(false);
                setCreated(null);
              }}
            >
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={invite} className="space-y-4">
            <label className="field">
              Email address
              <input
                className="input"
                required
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="teammate@company.com"
              />
            </label>
            <label className="field">
              Workspace role
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {["admin", "operator", "viewer"].map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </label>
            {error && <ErrorBox message={error} />}
            <div className="flex justify-end">
              <button className="btn" disabled={busy}>
                {busy ? "Creating…" : "Create invitation"}
              </button>
            </div>
          </form>
        )}
      </FormDialog>
    </div>
  );
}
