"use client";
import { useWorkspaceTime } from "@/lib/use-workspace-time";
import { useState } from "react";
import {
  Plus,
  Bell,
  Mail,
  Send,
  Webhook,
  Terminal,
  Check,
  Loader2,
  CircleCheck,
} from "lucide-react";
import { useApi } from "@/lib/use-api";
import { useSession } from "@/lib/session";
import { api } from "@/lib/api";
import { PageHeading, PanelHeading, FormDialog } from "@/components/page";
import { ErrorBox, Skeleton, StatusBadge } from "@/components/ui";
type Rule = {
  id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  event_types: string[];
  severity_minimum: string | null;
  cooldown_seconds: number;
  channel_ids: string[];
};
type Channel = {
  id: string;
  name: string;
  channel_type: string;
  destination_label: string | null;
  enabled: boolean;
  last_tested_at: string | null;
  last_test_status: string | null;
};
type Notification = {
  id: string;
  status: string;
  subject: string;
  created_at: string;
  last_error: string | null;
  attempt_count: number;
};
export default function Alerts() {
  const {fmtDateTime,timeZone}=useWorkspaceTime();
  const [tab, setTab] = useState("rules");
  const rules = useApi<Rule[]>("/alert-rules");
  const channels = useApi<Channel[]>("/notification-channels");
  const history = useApi<Notification[]>("/notifications", { limit: 30 });
  const { workspaceId, session } = useSession();
  const admin = ["owner", "admin"].includes(
    session!.memberships.find((m) => m.id === workspaceId)?.role ?? "",
  );
  const [dialog, setDialog] = useState<"rule" | "channel" | null>(null);
  const [name, setName] = useState("");
  const [channelType, setChannelType] = useState("email");
  const [destination, setDestination] = useState("");
  const [event, setEvent] = useState("incident.created");
  const [severity, setSeverity] = useState("");
  const [cooldown, setCooldown] = useState("300");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [testId, setTestId] = useState("");
  function start(kind: "rule" | "channel") {
    setName("");
    setDestination("");
    setSelected([]);
    setError("");
    setDialog(kind);
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const body =
      dialog === "rule"
        ? {
            name,
            event_types: [event],
            severity_minimum: severity || null,
            cooldown_seconds: Number(cooldown),
            channel_ids: selected,
          }
        : {
            name,
            channel_type: channelType,
            configuration:
              channelType === "email"
                ? { to: destination }
                : channelType === "telegram"
                  ? { chat_id: destination }
                  : channelType === "webhook"
                    ? { url: destination }
                    : {},
          };
    const r = await api(
      dialog === "rule" ? "/alert-rules" : "/notification-channels",
      { method: "POST", workspaceId: workspaceId!, body },
    );
    setBusy(false);
    if (!r.ok) {
      setError(r.error!.message);
      return;
    }
    setDialog(null);
    setNotice(
      dialog === "rule"
        ? "Alert rule created."
        : "Notification channel created.",
    );
    window.dispatchEvent(new Event("fs:refresh"));
  }
  async function toggle(rule: Rule) {
    const r = await api(`/alert-rules/${rule.id}`, {
      method: "PATCH",
      workspaceId: workspaceId!,
      body: { enabled: !rule.enabled },
    });
    if (!r.ok) setError(r.error!.message);
    else void rules.reload();
  }
  async function test(c: Channel) {
    setTestId(c.id);
    setError("");
    setNotice("");
    const r = await api<{ status: string; error?: string }>(
      `/notification-channels/${c.id}/test`,
      { method: "POST", workspaceId: workspaceId! },
    );
    setTestId("");
    if (!r.ok) setError(r.error!.message);
    else if (r.data?.status === "failed")
      setError(
        r.data.error ??
          "Test delivery failed. Check server notification configuration.",
      );
    else
      setNotice(
        "Test delivery requested. Review the channel’s delivery status below.",
      );
    void channels.reload();
  }
  const err = error || rules.error || channels.error;
  return (
    <div>
      <PageHeading
        title="Alerts"
        description="Choose which events send notifications and check delivery results."
        action={
          admin ? (
            <button
              className="btn"
              onClick={() => start(tab === "channels" ? "channel" : "rule")}
            >
              <Plus size={14} />
              {tab === "channels" ? "Add channel" : "Create alert rule"}
            </button>
          ) : undefined
        }
      />
      <div className="tab-list" role="tablist" aria-label="Alert configuration">
        {[
          { id: "rules", label: "Alert rules", count: rules.data?.length },
          {
            id: "channels",
            label: "Notification channels",
            count: channels.data?.length,
          },
          { id: "history", label: "Delivery history" },
        ].map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.count !== undefined && (
              <span className="ml-2 rounded bg-[var(--surface-2)] px-1.5 py-0.5 text-[10px] muted">
                {t.count}
              </span>
            )}
          </button>
        ))}
      </div>
      {err && (
        <div className="mb-4">
          <ErrorBox message={err} />
        </div>
      )}
      {notice && (
        <p
          role="status"
          className="mb-4 flex items-center gap-2 text-xs text-[var(--ok)]"
        >
          <CircleCheck size={14} />
          {notice}
        </p>
      )}
      {tab === "rules" ? (
        <section className="card overflow-hidden">
          {rules.loading ? (
            <div className="p-5">
              <Skeleton rows={5} />
            </div>
          ) : rules.data?.length ? (
            <div className="table-wrap">
              <table className="fs">
                <thead>
                  <tr>
                    <th>Rule</th>
                    <th>Events</th>
                    <th>Channels</th>
                    <th>Cooldown</th>
                    <th>Status</th>
                    {admin && <th>Action</th>}
                  </tr>
                </thead>
                <tbody>
                  {rules.data.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <p className="font-medium">{r.name}</p>
                        <p className="muted mt-1 text-[10px]">
                          {r.severity_minimum
                            ? `${r.severity_minimum} and above`
                            : "All severities"}
                        </p>
                      </td>
                      <td className="text-[11px] muted">
                        {r.event_types
                          .map((s) => s.replaceAll(".", " "))
                          .join(", ")}
                      </td>
                      <td className="muted">
                        {r.channel_ids
                          .map(
                            (id) =>
                              channels.data?.find((c) => c.id === id)?.name ??
                              "Unknown channel",
                          )
                          .join(", ") || "None"}
                      </td>
                      <td className="mono muted">{r.cooldown_seconds}s</td>
                      <td>
                        <StatusBadge
                          status={r.enabled ? "active" : "inactive"}
                        />
                      </td>
                      {admin && (
                        <td>
                          <button
                            className="text-link"
                            onClick={() => toggle(r)}
                          >
                            {r.enabled ? "Pause" : "Enable"}
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <AlertEmpty
              icon={Bell}
              title="No alert rules yet"
              description="Create a rule to notify your team when an incident is created, a workflow fails, or a source disconnects."
              action={
                admin ? (
                  <button
                    className="btn btn-secondary"
                    onClick={() => start("rule")}
                  >
                    <Plus size={13} />
                    Create your first rule
                  </button>
                ) : undefined
              }
            />
          )}
        </section>
      ) : tab === "channels" ? (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {channels.loading ? (
            <Skeleton rows={4} />
          ) : channels.data?.length ? (
            channels.data.map((c) => {
              const Icon =
                (
                  {
                    email: Mail,
                    telegram: Send,
                    webhook: Webhook,
                    log: Terminal,
                  } as Record<string, typeof Mail>
                )[c.channel_type] ?? Bell;
              return (
                <section className="card p-5" key={c.id}>
                  <div className="flex items-center gap-3">
                    <span className="rounded-lg border bg-[var(--surface-2)] p-2.5">
                      <Icon size={18} className="muted" />
                    </span>
                    <div className="flex-1">
                      <h2 className="text-sm font-semibold">{c.name}</h2>
                      <p className="muted mt-1 text-[11px] capitalize">
                        {c.channel_type}
                      </p>
                    </div>
                    <StatusBadge status={c.enabled ? "active" : "inactive"} />
                  </div>
                  <p className="mono muted my-5 break-all rounded-md bg-[var(--surface-2)] p-3 text-[11px]">
                    {c.destination_label ?? "Server log"}
                  </p>
                  <div className="flex items-center justify-between gap-3 border-t pt-4">
                    <span className="muted text-[10px]">
                      {c.last_tested_at
                        ? `${c.last_test_status} · ${fmtDateTime(c.last_tested_at)}`
                        : "No test delivery yet"}
                    </span>
                    {admin && (
                      <button
                        className="btn btn-secondary !min-h-7 !py-1 !text-[11px]"
                        disabled={!!testId}
                        onClick={() => test(c)}
                      >
                        {testId === c.id ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <Send size={12} />
                        )}
                        Test delivery
                      </button>
                    )}
                  </div>
                </section>
              );
            })
          ) : (
            <section className="card lg:col-span-2">
              <AlertEmpty
                icon={Mail}
                title="No notification channels yet"
                description="Send notifications by email, Telegram, or webhook. Use a log channel to test the pipeline locally."
                action={
                  admin ? (
                    <button
                      className="btn btn-secondary"
                      onClick={() => start("channel")}
                    >
                      <Plus size={13} />
                      Add notification channel
                    </button>
                  ) : undefined
                }
              />
            </section>
          )}
        </div>
      ) : (
        <section className="card overflow-hidden">
          <PanelHeading
            title="Recent notification deliveries"
            description="Delivery results and retry activity"
          />
          {history.error ? (
            <div className="p-5">
              <ErrorBox message={history.error} retry={history.reload} />
            </div>
          ) : history.data?.length ? (
            <div className="table-wrap">
              <table className="fs">
                <thead>
                  <tr>
                    <th>Notification</th>
                    <th>Status</th>
                    <th>Attempts</th>
                    <th>Created</th>
                    <th>Last error</th>
                  </tr>
                </thead>
                <tbody>
                  {history.data.map((n) => (
                    <tr key={n.id}>
                      <td>{n.subject ?? "Alert notification"}</td>
                      <td>
                        <StatusBadge status={n.status} />
                      </td>
                      <td className="mono">{n.attempt_count ?? 0}</td>
                      <td className="muted">{fmtDateTime(n.created_at)}</td>
                      <td className="muted">{n.last_error ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <AlertEmpty
              icon={Send}
              title="No deliveries yet"
              description="Notifications appear here when an alert rule matches an event."
            />
          )}
        </section>
      )}
      <FormDialog
        open={dialog !== null}
        onOpenChange={(v) => !v && setDialog(null)}
        title={
          dialog === "rule" ? "Create alert rule" : "Add notification channel"
        }
        description={
          dialog === "rule"
            ? "Choose the event, severity, and destinations for this alert."
            : "Configure where your workspace notifications are delivered."
        }
      >
        <form onSubmit={submit} className="space-y-4">
          <label className="field">
            Name
            <input
              className="input"
              required
              maxLength={120}
              placeholder={
                dialog === "rule"
                  ? "e.g. Critical workflow failures"
                  : "e.g. Engineering email"
              }
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          {dialog === "channel" ? (
            <>
              <label className="field">
                Channel type
                <select
                  value={channelType}
                  onChange={(e) => {
                    setChannelType(e.target.value);
                    setDestination("");
                  }}
                >
                  {["email", "telegram", "webhook", "log"].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
              {channelType !== "log" && (
                <label className="field">
                  {channelType === "email"
                    ? "Recipient email"
                    : channelType === "telegram"
                      ? "Telegram chat ID"
                      : "Webhook URL"}
                  <input
                    className="input"
                    required
                    type={
                      channelType === "email"
                        ? "email"
                        : channelType === "webhook"
                          ? "url"
                          : "text"
                    }
                    value={destination}
                    onChange={(e) => setDestination(e.target.value)}
                  />
                </label>
              )}
              <p className="muted rounded-md bg-[var(--surface-2)] p-3 text-[11px] leading-6">
                {channelType === "email"
                  ? "SMTP credentials must be configured on the FlowSentry server."
                  : channelType === "telegram"
                    ? "The Telegram bot token must be configured on the FlowSentry server."
                    : channelType === "log"
                      ? "Writes alerts to the local server log. No external delivery."
                      : "The endpoint must be reachable and pass the server’s outbound network policy."}
              </p>
            </>
          ) : (
            <>
              <label className="field">
                Trigger event
                <select
                  value={event}
                  onChange={(e) => setEvent(e.target.value)}
                >
                  {[
                    "incident.created",
                    "incident.escalated",
                    "incident.resolved",
                    "execution.failed",
                    "integration.disconnected",
                    "workflow.inactive",
                  ].map((s) => (
                    <option key={s} value={s}>
                      {s.replaceAll(".", " ")}
                    </option>
                  ))}
                </select>
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="field">
                  Minimum severity
                  <select
                    value={severity}
                    onChange={(e) => setSeverity(e.target.value)}
                  >
                    <option value="">All severities</option>
                    {["critical", "high", "medium", "low"].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  Cooldown (seconds)
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={86400}
                    required
                    value={cooldown}
                    onChange={(e) => setCooldown(e.target.value)}
                  />
                </label>
              </div>
              <fieldset>
                <legend className="mb-2 text-xs font-medium">
                  Notify channels
                </legend>
                {channels.data?.length ? (
                  channels.data
                    .filter((c) => c.enabled)
                    .map((c) => (
                      <label
                        key={c.id}
                        className="mb-2 flex items-center gap-2 rounded-md border p-3 text-xs"
                      >
                        <input
                          type="checkbox"
                          checked={selected.includes(c.id)}
                          onChange={(e) =>
                            setSelected((p) =>
                              e.target.checked
                                ? [...p, c.id]
                                : p.filter((id) => id !== c.id),
                            )
                          }
                        />
                        {c.name}
                        <span className="muted ml-auto">{c.channel_type}</span>
                      </label>
                    ))
                ) : (
                  <p className="muted text-xs leading-6">
                    Add a notification channel first so this rule has a
                    destination.
                  </p>
                )}
              </fieldset>
            </>
          )}
          {error && <ErrorBox message={error} />}
          <div className="flex justify-end gap-2 border-t pt-4">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setDialog(null)}
            >
              Cancel
            </button>
            <button
              className="btn"
              disabled={busy || (dialog === "rule" && !selected.length)}
            >
              {busy
                ? "Saving…"
                : dialog === "rule"
                  ? "Create rule"
                  : "Add channel"}
            </button>
          </div>
        </form>
      </FormDialog>
    </div>
  );
}
function AlertEmpty({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: typeof Bell;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-72 flex-col items-center justify-center px-6 py-10 text-center">
      <span className="mb-4 rounded-xl border bg-[var(--surface-2)] p-3">
        <Icon size={22} className="muted" />
      </span>
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="muted mt-2 max-w-sm text-xs leading-6">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
