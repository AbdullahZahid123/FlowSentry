"use client";
import Link from "next/link";
import { ThemeToggle } from "@/components/theme";
import dynamic from "next/dynamic";
import { useState } from "react";
import { ArrowRight, ArrowUpRight, Menu } from "lucide-react";
import { Brand } from "@/components/page";
import { Button } from "@/components/ui/button";
import ProductInbox from "@/components/product-inbox";
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from "@/components/ui/accordion";

import {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";

import { useSession } from "@/lib/session";

const WorkflowPreview = dynamic(() => import("@/components/workflow-preview"), {
  ssr: false,
  loading: () => (
    <div className="workflow-preview-loading">Loading example execution…</div>
  ),
});
export function Landing() {
  const { session } = useSession();
  const destination = session ? "/overview" : "/login";
  const [mobile, setMobile] = useState(false);
  const links = (
    <>
      <a href="#product-preview" onClick={() => setMobile(false)}>
        Product
      </a>
      <a href="#how-it-works" onClick={() => setMobile(false)}>
        Setup
      </a>
      <a href="#self-hosted" onClick={() => setMobile(false)}>
        Self-hosting
      </a>
      <Link href="/guide" onClick={() => setMobile(false)}>
        Documentation
      </Link>
    </>
  );
  return (
    <div className="landing">
      <header className="landing-nav">
        <Link href="/" aria-label="FlowSentry home">
          <Brand />
        </Link>
        <nav aria-label="Website navigation" className="landing-links">
          {links}
        </nav>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <Link href={destination} className="site-signin">
            {session ? "Workspace" : "Sign in"}
          </Link>
          <Button asChild size="sm" className="site-nav-cta">
            <Link href={destination}>
              {session ? "Open app" : "Get started"}
              <ArrowUpRight size={14} />
            </Link>
          </Button>
          <Sheet open={mobile} onOpenChange={setMobile}>
            <SheetTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="md:hidden"
                aria-label="Open website navigation"
              >
                <Menu size={19} />
              </Button>
            </SheetTrigger>
            <SheetContent side="right" className="w-[280px]">
              <SheetTitle>FlowSentry</SheetTitle>
              <SheetDescription>
                Product and setup information.
              </SheetDescription>
              <nav
                className="site-mobile-links"
                aria-label="Mobile website navigation"
              >
                {links}
              </nav>
            </SheetContent>
          </Sheet>
        </div>
      </header>
      <main>
        <section className="landing-hero">
          <div className="hero-copy">
            <h1>
              Monitoring for
              <br />
              <span>n8n workflows.</span>
            </h1>
            <p>
              Track failed executions across your n8n instances. Group recurring
              errors into incidents, assign an owner, and keep the investigation
              in one place.
            </p>
            <div className="hero-actions">
              <Button asChild size="lg">
                <Link href={destination}>
                  Connect n8n
                  <ArrowRight size={15} />
                </Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <a href="#product-preview">View example</a>
              </Button>
            </div>
            <p className="hero-note">
              Self-hosted. Connect with an API key or an Error Workflow.
            </p>
          </div>
          <WorkflowPreview />
        </section>
        <ProductInbox destination={destination} />
        <section id="features" className="site-section site-details">
          <div>
            <h2>What FlowSentry records</h2>
            <p className="site-description">
              Execution status and error details from n8n, with a shared
              incident history for your team.
            </p>
            <Link href="/guide" className="site-text-link mt-6">
              Read the documentation
              <ArrowUpRight size={14} />
            </Link>
          </div>
          <Accordion
            type="single"
            collapsible
            defaultValue="history"
            className="site-accordion"
          >
            <AccordionItem value="history">
              <AccordionTrigger>
                Execution history across instances
              </AccordionTrigger>
              <AccordionContent>
                API polling collects workflow and execution history. Error
                Workflows report failures as they happen. Search by workflow,
                filter by status or instance, and inspect the failed node,
                duration, and redacted source event.
              </AccordionContent>
            </AccordionItem>
            <AccordionItem value="grouping">
              <AccordionTrigger>
                Recurring failures grouped into incidents
              </AccordionTrigger>
              <AccordionContent>
                Failures with the same workflow, node, and error fingerprint
                share an incident. Each incident keeps its occurrence count,
                affected executions, assigned owner, comments, and status
                changes.
              </AccordionContent>
            </AccordionItem>
            <AccordionItem value="alerts">
              <AccordionTrigger>
                Alert rules and delivery history
              </AccordionTrigger>
              <AccordionContent>
                Choose the events and severity levels that should trigger an
                alert. Send notifications through email, Telegram, or a webhook.
                Set a cooldown and inspect delivery attempts when a message
                fails.
              </AccordionContent>
            </AccordionItem>
            <AccordionItem value="limits">
              <AccordionTrigger>
                What webhook-only monitoring covers
              </AccordionTrigger>
              <AccordionContent>
                Error Workflows provide failure events. Successful runs,
                execution totals, and reconciliation require public API access.
                Retry and replay are unavailable until a supported source
                capability is verified.
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </section>
        <section id="how-it-works" className="site-section site-setup">
          <div className="site-section-title">
            <div>
              <h2>Connect your first n8n instance</h2>
              <p>
                n8n runs your workflows. FlowSentry receives events and reads
                execution history.
              </p>
            </div>
          </div>
          <ol className="site-setup-list">
            <li>
              <span>1</span>
              <div>
                <h3>Add the instance</h3>
                <p>
                  Enter its URL and public API key, or choose webhook-only
                  monitoring.
                </p>
              </div>
            </li>
            <li>
              <span>2</span>
              <div>
                <h3>Send failure events</h3>
                <p>
                  Connect an n8n Error Workflow to your ingress endpoint with
                  its bearer token.
                </p>
              </div>
            </li>
            <li>
              <span>3</span>
              <div>
                <h3>Test an alert</h3>
                <p>
                  Add a notification channel, test delivery, then choose which
                  incidents should notify your team.
                </p>
              </div>
            </li>
          </ol>
        </section>
        <section id="self-hosted" className="site-section site-hosting">
          <div>
            <h2>Run it on your infrastructure</h2>
            <p>
              Keep execution records and incident history in your own PostgreSQL
              database. Integration credentials are encrypted at rest, and
              sensitive event fields are redacted before storage.
            </p>
            <Button asChild variant="outline">
              <Link href="/guide#self-hosting">
                Self-hosting guide
                <ArrowUpRight size={14} />
              </Link>
            </Button>
          </div>
          <dl>
            <div>
              <dt>Deployment</dt>
              <dd>Next.js, FastAPI, and PostgreSQL</dd>
            </div>
            <div>
              <dt>n8n connection</dt>
              <dd>Public API and Error Workflows</dd>
            </div>
            <div>
              <dt>Notifications</dt>
              <dd>Email, Telegram, and webhooks</dd>
            </div>
            <div>
              <dt>AI dependency</dt>
              <dd>None for core monitoring</dd>
            </div>
          </dl>
        </section>
        <section className="site-section site-final">
          <div>
            <h2>Start with one workflow.</h2>
            <p>
              Connect an instance, send a failure event, and inspect the
              resulting incident.
            </p>
          </div>
          <Button asChild size="lg">
            <Link href={destination}>
              Open FlowSentry
              <ArrowRight size={15} />
            </Link>
          </Button>
        </section>
      </main>
      <footer className="landing-footer">
        <Link href="/">
          <Brand small />
        </Link>
        <span>Independent software. Not affiliated with n8n.</span>
        <div>
          <Link href="/guide">Documentation</Link>
          <Link href={destination}>Workspace</Link>
        </div>
      </footer>
    </div>
  );
}
