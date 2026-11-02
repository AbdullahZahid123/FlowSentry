import Link from "next/link";
import { ThemeToggle } from "@/components/theme";
import { Button } from "@/components/ui/button";
import {
  ArrowLeft,
  ArrowUpRight,
  KeyRound,
  Webhook,
  Server,
  ShieldCheck,
} from "lucide-react";
import { Brand } from "@/components/page";
export default function Guide() {
  return (
    <div className="landing min-h-screen">
      <header className="landing-nav guide-nav">
        <Link href="/">
          <Brand />
        </Link>
        <div className="flex items-center gap-2"><ThemeToggle/><Link className="btn btn-secondary !text-xs" href="/overview">
          Open workspace
          <ArrowUpRight size={13} />
        </Link></div>
      </header>
      <main className="mx-auto max-w-4xl px-6 py-14">
        <Link
          className="mb-8 inline-flex items-center gap-2 text-xs text-muted-foreground"
          href="/"
        >
          <ArrowLeft size={13} />
          Back to FlowSentry
        </Link>
        <div className="text-xs text-muted-foreground">Documentation</div>
        <h1 className="mt-4 text-4xl font-semibold tracking-tight">
          Start watching your n8n workflows.
        </h1>
        <p className="mb-12 mt-5 max-w-xl text-sm leading-7 text-muted-foreground">
          FlowSentry connects through n8n Error Workflows and the documented
          public API. n8n continues to execute your automations.
        </p>
        <div className="space-y-6">
          {[
            {
              id: "connect",
              icon: KeyRound,
              title: "1. Connect an instance",
              text: "Create your owner account on first run. In Integrations, choose Connect n8n. Enter the instance name, public HTTPS URL, and n8n API key from Settings → n8n API. The instance must be reachable from the FlowSentry server. Private network access requires an explicit server configuration change.",
            },
            {
              id: "webhooks",
              icon: Webhook,
              title: "2. Configure failure webhooks",
              text: "After connecting, copy the ingress endpoint and one-time token. Add and publish an n8n Error Workflow with Error Trigger → HTTP Request. Send the trigger output as JSON with the Authorization: Bearer YOUR_TOKEN header. Select that Error Workflow in each monitored workflow’s settings and publish the change. Test with a production execution. Webhook-only monitoring does not include successful runs or reconciliation.",
            },
            {
              id: "alerts",
              icon: ShieldCheck,
              title: "3. Set up notifications",
              text: "In Alerts → Notification channels, add a destination. Email requires SMTP configuration on the server. Telegram requires a server-configured bot token and the destination chat ID. Test delivery, then create an alert rule and select the channel. Use a local log channel to validate the pipeline without external delivery.",
            },
            {
              id: "self-hosting",
              icon: Server,
              title: "4. Self-hosting and deployment",
              text: "Run the Next.js frontend, FastAPI API, and PostgreSQL on your infrastructure. The frontend proxies /api requests to the API, keeping browser sessions on the same origin. Configure a durable encryption key and application secret, and back up both the database and encryption key. See the project README for commands and current release limitations.",
            },
          ].map((s) => (
            <section
              id={s.id}
              key={s.id}
              className="scroll-mt-10 rounded-xl border bg-card p-6"
            >
              <s.icon size={22} className="mb-4 text-primary" />
              <h2 className="text-lg font-medium">{s.title}</h2>
              <p className="mt-3 text-xs leading-7 text-muted-foreground">{s.text}</p>
            </section>
          ))}
        </div>
        <div className="mt-10 rounded-xl border border-dashed border-border p-6">
          <h2 className="font-medium">A few things to know</h2>
          <p className="mt-3 text-xs leading-7 text-muted-foreground">
            Retry and replay stay unavailable until the connected source exposes
            a verified, supported capability. FlowSentry does not edit or
            execute your workflows. AI diagnosis is optional and outside the
            current monitoring interface. FlowSentry is independent software and
            is not affiliated with n8n.
          </p>
        </div>
        <Link href="/login" className="btn mt-8">
          Connect n8n
          <ArrowUpRight size={14} />
        </Link>
      </main>
    </div>
  );
}
