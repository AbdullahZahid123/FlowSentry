"use client";
import { useWorkspaceTime } from "@/lib/use-workspace-time";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  Plus,
  ArrowUpRight,
  RefreshCw,
  Unplug,
  Check,
  KeyRound,
  Webhook,
  CircleCheck,
  Loader2,
} from "lucide-react";
import { useApi } from "@/lib/use-api";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Integration } from "@/lib/types";
import { PageHeading, FormDialog, CopyButton } from "@/components/page";
import { ErrorBox, Skeleton, StatusBadge } from "@/components/ui";
export default function IntegrationsPage() {
  return (
    <Suspense fallback={<Skeleton rows={4} />}>
      <Integrations />
    </Suspense>
  );
}
function Integrations() {
  const {fmtDateTime,timeZone}=useWorkspaceTime();
  const result = useApi<Integration[]>("/integrations");
  const { workspaceId, session } = useSession();
  const params = useSearchParams();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("api");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<Integration | null>(null);
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const admin = ["admin", "owner"].includes(
    session!.memberships.find((m) => m.id === workspaceId)?.role ?? "",
  );
  useEffect(() => {
    if (params.get("connect") === "1") setOpen(true);
  }, [params]);
  function close(v: boolean) {
    setOpen(v);
    if (!v) {
      setKey("");
      setCreated(null);
      setError("");
      setName("");
      setUrl("");
      if (params.has("connect")) router.replace("/integrations");
    }
  }
  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const r = await api<Integration>("/integrations", {
      method: "POST",
      workspaceId: workspaceId!,
      body: {
        provider: "n8n",
        name,
        base_url: mode === "api" ? url : null,
        api_key: mode === "api" ? key : null,
      },
    });
    setBusy(false);
    if (!r.ok) {
      setError(r.error!.message);
      return;
    }
    setKey("");
    setCreated(r.data!);
    void result.reload();
  }
  async function action(i: Integration, kind: "test" | "sync" | "toggle") {
    setPending(i.id + kind);
    setError("");
    setNotice("");
    const r = await api<{
      connection?: string;
      error_code?: string;
      message?: string;
    }>(`/integrations/${i.id}${kind === "toggle" ? "" : "/" + kind}`, {
      workspaceId: workspaceId!,
      method: kind === "toggle" ? "PATCH" : "POST",
      ...(kind === "toggle" ? { body: { enabled: !i.enabled } } : {}),
    });
    setPending("");
    if (!r.ok) setError(r.error!.message);
    else if (r.data?.connection === "failed")
      setError(
        `Connection failed: ${r.data.error_code?.replaceAll("_", " ")}. Check the instance URL and API key.`,
      );
    else
      setNotice(
        kind === "test"
          ? "Connection verified."
          : kind === "sync"
            ? "Sync queued. Workflow data will update when the worker finishes."
            : i.enabled
              ? "Integration paused."
              : "Integration resumed.",
      );
    void result.reload();
  }
  const endpoint =
    created && typeof window !== "undefined"
      ? `${window.location.origin}/api/ingest/${created.id}/n8n`
      : "";
  return (
    <div>
      <PageHeading
        title="Integrations"
        description="Connect n8n instances and check synchronization status."
        action={
          admin ? (
            <button className="btn" onClick={() => setOpen(true)}>
              <Plus size={14} />
              Connect integration
            </button>
          ) : undefined
        }
      />
      {(error || result.error) && (
        <div className="mb-4">
          <ErrorBox
            message={error || result.error!}
            retry={result.error ? result.reload : undefined}
          />
        </div>
      )}
      {notice && (
        <p
          role="status"
          className="mb-4 flex items-center gap-2 rounded-lg border bg-[var(--surface)] p-3 text-xs"
        >
          <CircleCheck size={15} color="var(--ok)" />
          {notice}
        </p>
      )}
      <div className="mb-6 flex items-center gap-2 border-b pb-3">
        <span className="font-medium">Connected sources</span>
        <span className="rounded bg-[var(--surface-2)] px-1.5 py-0.5 text-[10px] muted">
          {result.data?.length ?? 0}
        </span>
        <span className="ml-auto text-[11px] muted">n8n supported</span>
      </div>
      {result.loading ? (
        <Skeleton rows={5} />
      ) : result.data?.length ? (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {result.data.map((i) => (
            <section className="card overflow-hidden" key={i.id}>
              <div className="p-5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-[#ecd8d0] bg-[#fcf1eb] text-base font-semibold text-[#ba6b58]">
                      n8n
                    </span>
                    <div>
                      <h2 className="text-sm font-semibold">{i.name}</h2>
                      <p className="muted mt-1 text-[11px]">
                        {i.webhook_only ? "Webhook only" : "API + webhooks"}
                      </p>
                    </div>
                  </div>
                  <StatusBadge status={!i.enabled ? "inactive" : i.status} />
                </div>
                <p className="mono muted mt-5 truncate rounded-md bg-[var(--surface-2)] px-3 py-2.5 text-[11px]">
                  {i.base_url ?? "Receives n8n Error Workflow events"}
                </p>
                <div className="mt-4 flex justify-between text-[11px]">
                  <span className="muted">Last successful check</span>
                  <span>{fmtDateTime(i.last_successful_check_at)}</span>
                </div>
                <div className="mt-3 flex justify-between text-[11px]">
                  <span className="muted">Polling interval</span>
                  <span>
                    {i.webhook_only
                      ? "Not available"
                      : `${i.poll_interval_seconds} seconds`}
                  </span>
                </div>
                {i.last_error_code && (
                  <p className="mt-3 text-[11px] text-[var(--err)]">
                    {i.last_error_code.replaceAll("_", " ")}
                  </p>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2 border-t bg-[var(--bg)] px-5 py-3">
                <button
                  className="btn btn-secondary !min-h-7 !px-2.5 !py-1 !text-[11px]"
                  onClick={() => setExpanded(expanded === i.id ? null : i.id)}
                >
                  {expanded === i.id ? "Hide details" : "Connection details"}
                </button>
                {admin && (
                  <>
                    <button
                      disabled={i.webhook_only || !!pending || !i.enabled}
                      className="btn btn-secondary !min-h-7 !px-2.5 !py-1 !text-[11px]"
                      onClick={() => action(i, "test")}
                    >
                      {pending === i.id + "test" ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Check size={12} />
                      )}
                      Test
                    </button>
                    <button
                      disabled={i.webhook_only || !!pending || !i.enabled}
                      className="btn btn-secondary !min-h-7 !px-2.5 !py-1 !text-[11px]"
                      onClick={() => action(i, "sync")}
                    >
                      <RefreshCw size={11} />
                      Sync
                    </button>
                    <button
                      disabled={!!pending}
                      className="ml-auto text-[11px] muted hover:underline"
                      onClick={() => action(i, "toggle")}
                    >
                      {i.enabled ? "Pause" : "Resume"}
                    </button>
                  </>
                )}
              </div>
              {expanded === i.id && <ConnectionDetails id={i.id} />}
            </section>
          ))}
        </div>
      ) : (
        <section className="card flex min-h-80 flex-col items-center justify-center p-8 text-center">
          <span className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl border bg-[var(--surface-2)]">
            <Unplug size={25} className="muted" />
          </span>
          <h2 className="text-base font-semibold">
            Your automation, connected.
          </h2>
          <p className="muted mt-2 max-w-sm text-xs leading-6">
            Add an n8n instance to discover workflows, track executions, and
            catch failures as they happen.
          </p>
          {admin && (
            <button className="btn mt-5" onClick={() => setOpen(true)}>
              <Plus size={14} />
              Connect n8n
            </button>
          )}
        </section>
      )}
      <div className="mt-6 flex items-start gap-3 rounded-lg border border-dashed p-4">
        <KeyRound size={16} className="muted mt-0.5 shrink-0" />
        <p className="muted text-xs leading-6">
          API credentials are encrypted at rest. Webhook-only monitoring is
          available when you don’t have access to the n8n public API.
        </p>
      </div>
      <FormDialog
        open={open}
        onOpenChange={close}
        title={created ? "Your integration is connected" : "Connect n8n"}
        description={
          created
            ? "Save your ingress token now. It is shown only once."
            : "Monitor an instance through its public API or receive failure webhooks."
        }
      >
        {created ? (
          <div className="space-y-5">
            <div className="rounded-lg bg-[var(--surface-2)] p-4">
              <p className="mb-2 text-xs font-medium">Webhook endpoint</p>
              <code className="block break-all text-xs leading-6">
                {endpoint}
              </code>
              <div className="mt-3">
                <CopyButton value={endpoint} />
              </div>
            </div>
            <div className="rounded-lg border border-[var(--warn)] p-4">
              <p className="mb-2 text-xs font-medium">One-time ingress token</p>
              <code className="block break-all text-xs">
                {created.ingress_token_once}
              </code>
              <div className="mt-3">
                <CopyButton value={created.ingress_token_once ?? ""} />
              </div>
            </div>
            <p className="muted text-xs leading-6">
              In your n8n Error Workflow, send the Error Trigger payload to this
              endpoint with <code>Authorization: Bearer YOUR_TOKEN</code>. The
              endpoint must be reachable from n8n.
            </p>
            <button className="btn w-full" onClick={() => close(false)}>
              I’ve saved the token
              <Check size={14} />
            </button>
          </div>
        ) : (
          <form onSubmit={connect} className="space-y-4">
            <div className="grid grid-cols-2 gap-2">
              {[
                { id: "api", icon: KeyRound, title: "API + webhooks" },
                { id: "webhook", icon: Webhook, title: "Webhooks only" },
              ].map((m) => (
                <button
                  type="button"
                  aria-pressed={mode === m.id}
                  onClick={() => setMode(m.id)}
                  className={`flex items-center justify-center gap-2 rounded-lg border p-3 text-xs ${mode === m.id ? "border-[var(--accent)] bg-[var(--surface-2)]" : ""}`}
                  key={m.id}
                >
                  <m.icon size={14} />
                  {m.title}
                </button>
              ))}
            </div>
            <label className="field">
              Integration name
              <input
                className="input"
                required
                maxLength={120}
                placeholder="e.g. Production n8n"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            {mode === "api" ? (
              <>
                <label className="field">
                  Instance URL
                  <input
                    className="input"
                    type="url"
                    required
                    placeholder="https://n8n.example.com"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                  />
                </label>
                <label className="field">
                  n8n API key
                  <input
                    className="input"
                    type="password"
                    required
                    autoComplete="off"
                    placeholder="Your instance API key"
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                  />
                  <span className="muted text-[11px] font-normal">
                    Create a key in n8n → Settings → n8n API.
                  </span>
                </label>
              </>
            ) : (
              <p className="rounded-lg bg-[var(--surface-2)] p-3 text-xs leading-6 muted">
                Receives failure events from an n8n Error Workflow. Workflow
                discovery and reconciliation require API access.
              </p>
            )}
            {error && <ErrorBox message={error} />}
            <div className="flex justify-end gap-2 border-t pt-4">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => close(false)}
              >
                Cancel
              </button>
              <button className="btn" disabled={busy || !admin}>
                {busy ? "Connecting…" : "Connect n8n"}
                <ArrowUpRight size={14} />
              </button>
            </div>
          </form>
        )}
      </FormDialog>
    </div>
  );
}
function ConnectionDetails({ id }: { id: string }) {
 const {fmtDateTime}=useWorkspaceTime();
  const result = useApi<{
    polling: {
      resource_type: string;
      last_success_at: string | null;
      last_error: string | null;
    }[];
    capabilities: Record<string, boolean>;
  }>(`/integrations/${id}/health`);
  return (
    <div className="space-y-3 border-t p-5">
      {result.loading ? (
        <Skeleton rows={3} />
      ) : result.error ? (
        <ErrorBox message={result.error} retry={result.reload} />
      ) : (
        <>
          <p className="text-xs font-medium">Source capabilities</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(result.data?.capabilities ?? {}).map(([k, v]) => (
              <span
                key={k}
                className="rounded border px-2 py-1 text-[10px]"
                style={{ color: v ? "var(--ok)" : "var(--muted)" }}
              >
                {k.replaceAll("_", " ")}: {v ? "Supported" : "Unavailable"}
              </span>
            ))}
          </div>
          {result.data?.polling.map((p) => (
            <div
              key={p.resource_type}
              className="flex justify-between gap-3 text-[11px] muted"
            >
              <span className="capitalize">{p.resource_type}</span>
              <span>{p.last_error ?? fmtDateTime(p.last_success_at)}</span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
