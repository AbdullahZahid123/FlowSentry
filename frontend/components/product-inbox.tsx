"use client";
import { useState } from "react";
import {
  Search,
  ChevronDown,
  ArrowUpRight,
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  Check,
  Clock3,
} from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
} from "@/components/ui/dropdown-menu";
import { StatusBadge, SeverityBadge } from "@/components/ui";
const runs = [
  {
    id: "1842",
    name: "Invoice processing",
    source: "Production",
    status: "failed",
    duration: "30.0 s",
    time: "14:32:08",
    node: "Charge payment",
    message: "Payment request timed out",
    output: '{ "statusCode": 504, "message": "Gateway Timeout" }',
  },
  {
    id: "1841",
    name: "Lead enrichment",
    source: "Production",
    status: "success",
    duration: "1.8 s",
    time: "14:31:52",
    node: "Update contact",
    message: "Contact updated successfully",
    output: '{ "contactId": "C-208", "updated": true }',
  },
  {
    id: "1840",
    name: "Daily reporting",
    source: "Operations",
    status: "success",
    duration: "4.2 s",
    time: "14:30:00",
    node: "Send report",
    message: "Report delivered",
    output: '{ "reportId": "R-032", "delivered": true }',
  },
  {
    id: "1839",
    name: "Invoice processing",
    source: "Production",
    status: "failed",
    duration: "30.0 s",
    time: "14:29:17",
    node: "Charge payment",
    message: "Payment request timed out",
    output: '{ "statusCode": 504, "message": "Gateway Timeout" }',
  },
];
const incidents = [
  {
    id: "INC-27",
    name: "Payment API timeout",
    workflow: "Invoice processing",
    severity: "high",
    status: "open",
    count: 12,
    owner: "Unassigned",
    time: "14:32:08",
    message: "Payment requests are exceeding the 30-second timeout.",
  },
  {
    id: "INC-26",
    name: "Enrichment API rate limit",
    workflow: "Lead enrichment",
    severity: "medium",
    status: "investigating",
    count: 4,
    owner: "Alex",
    time: "13:48:21",
    message:
      "The enrichment provider returned HTTP 429. Review its request limit.",
  },
  {
    id: "INC-25",
    name: "Report delivery failed",
    workflow: "Daily reporting",
    severity: "low",
    status: "resolved",
    count: 2,
    owner: "Sam",
    time: "12:05:44",
    message:
      "The mail service rejected two delivery attempts. Later delivery succeeded.",
  },
];
export default function ProductInbox({ destination }: { destination: string }) {
  const [view, setView] = useState("executions");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [runId, setRunId] = useState("1842");
  const [incidentId, setIncidentId] = useState("INC-27");
  const run = runs.find((r) => r.id === runId)!;
  const incident = incidents.find((i) => i.id === incidentId)!;
  const filteredRuns = runs.filter(
    (r) =>
      (filter === "all" || r.status === filter) &&
      `${r.name} ${r.id} ${r.source}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const filteredIncidents = incidents.filter((i) =>
    `${i.id} ${i.name} ${i.workflow}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  function changeView(value: string) {
    setView(value);
    setQuery("");
    setFilter("all");
  }
  return (
    <section id="product-preview" className="site-section">
      <div className="site-section-title">
        <div>
          <h2>Inspect a failed execution</h2>
          <p>
            Select a run to see its output, or follow recurring failures into an
            incident.
          </p>
        </div>
        <Link href="/guide" className="site-text-link">
          Connection guide
          <ArrowUpRight size={14} />
        </Link>
      </div>
      <div className="demo-inbox">
        <div className="demo-inbox-top">
          <div className="demo-window-dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </div>
          <span>FlowSentry / Production</span>
          <span className="demo-sample-label">
            Interactive demo · Sample data
          </span>
        </div>
        <div className="demo-inbox-toolbar">
          <Tabs value={view} onValueChange={changeView}>
            <TabsList aria-label="Demo inbox view">
              <TabsTrigger value="executions">
                Executions <span className="demo-count">4</span>
              </TabsTrigger>
              <TabsTrigger value="incidents">
                Incidents <span className="demo-count">3</span>
              </TabsTrigger>
            </TabsList>
          </Tabs>
          <div className="demo-filters">
            <div className="demo-search">
              <Search size={14} />
              <Input
                aria-label="Search sample records"
                placeholder="Search workflows…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            {view === "executions" && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm">
                    {filter === "all"
                      ? "All statuses"
                      : filter === "failed"
                        ? "Failed"
                        : "Success"}
                    <ChevronDown size={12} />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuRadioGroup
                    value={filter}
                    onValueChange={setFilter}
                  >
                    <DropdownMenuRadioItem value="all">
                      All statuses
                    </DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value="failed">
                      Failed
                    </DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value="success">
                      Success
                    </DropdownMenuRadioItem>
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        </div>
        <div className="demo-inbox-body">
          <div
            className="demo-records"
            aria-label={
              view === "executions" ? "Sample executions" : "Sample incidents"
            }
          >
            <div className="demo-list-heading">
              <span>
                {view === "executions"
                  ? "Workflow / execution"
                  : "Incident / workflow"}
              </span>
              <span>Latest</span>
            </div>
            {view === "executions"
              ? filteredRuns.map((r) => (
                  <button
                    key={r.id}
                    className={`demo-record ${runId === r.id ? "is-selected" : ""}`}
                    onClick={() => setRunId(r.id)}
                    aria-pressed={runId === r.id}
                  >
                    <span className={`demo-record-icon ${r.status}`}>
                      {r.status === "failed" ? (
                        <CircleAlert size={17} />
                      ) : (
                        <CheckCircle2 size={17} />
                      )}
                    </span>
                    <span className="demo-record-name">
                      <strong>{r.name}</strong>
                      <span>
                        #{r.id} <b>·</b> {r.source} <b>·</b> {r.duration}
                      </span>
                    </span>
                    <span className="demo-record-time">
                      {r.time}
                      <span>
                        {r.status === "failed" ? "Failed" : "Success"}
                      </span>
                    </span>
                  </button>
                ))
              : filteredIncidents.map((i) => (
                  <button
                    key={i.id}
                    className={`demo-record ${incidentId === i.id ? "is-selected" : ""}`}
                    onClick={() => setIncidentId(i.id)}
                    aria-pressed={incidentId === i.id}
                  >
                    <span
                      className={`demo-record-icon ${i.status === "resolved" ? "success" : "failed"}`}
                    >
                      {i.status === "resolved" ? (
                        <CheckCircle2 size={17} />
                      ) : (
                        <CircleAlert size={17} />
                      )}
                    </span>
                    <span className="demo-record-name">
                      <strong>{i.name}</strong>
                      <span>
                        {i.id} <b>·</b> {i.workflow}
                      </span>
                    </span>
                    <span className="demo-record-time">
                      {i.time}
                      <span>{i.count} occurrences</span>
                    </span>
                  </button>
                ))}
            {(view === "executions" ? filteredRuns : filteredIncidents)
              .length === 0 && (
              <div className="demo-empty">
                <Search size={20} />
                <p>No sample records match.</p>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setQuery("");
                    setFilter("all");
                  }}
                >
                  Clear filters
                </Button>
              </div>
            )}
          </div>
          <div className="demo-inspector" aria-live="polite">
            {view === "executions" ? (
              <>
                <div className="demo-inspector-heading">
                  <span className="mono">EXECUTION #{run.id}</span>
                  <StatusBadge status={run.status} />
                </div>
                <h3>{run.name}</h3>
                <p className="demo-inspector-sub">
                  {run.source} · Started at {run.time}
                </p>
                <div className={`demo-result ${run.status}`}>
                  <span>
                    {run.status === "failed" ? (
                      <CircleAlert size={15} />
                    ) : (
                      <Check size={15} />
                    )}{" "}
                    {run.message}
                  </span>
                  <p>
                    {run.status === "failed"
                      ? "The endpoint did not respond within 30 seconds."
                      : "All execution steps completed successfully."}
                  </p>
                </div>
                <dl className="demo-detail-list">
                  <div>
                    <dt>
                      {run.status === "failed" ? "Failed node" : "Last node"}
                    </dt>
                    <dd>{run.node}</dd>
                  </div>
                  <div>
                    <dt>Duration</dt>
                    <dd className="mono">{run.duration}</dd>
                  </div>
                </dl>
                <span className="demo-output-label">Node output</span>
                <pre className="demo-output">{run.output}</pre>
                {run.status === "failed" && (
                  <button
                    className="demo-incident-link"
                    onClick={() => {
                      changeView("incidents");
                      setIncidentId("INC-27");
                    }}
                  >
                    <span>
                      <span className="mono">INC-27</span> Payment API timeout
                    </span>
                    <ArrowRight size={15} />
                  </button>
                )}
              </>
            ) : (
              <>
                <div className="demo-inspector-heading">
                  <span className="mono">{incident.id}</span>
                  <StatusBadge status={incident.status} />
                </div>
                <h3>{incident.name}</h3>
                <p className="demo-inspector-sub">{incident.workflow}</p>
                <p className="demo-incident-message">{incident.message}</p>
                <dl className="demo-detail-list">
                  <div>
                    <dt>Severity</dt>
                    <dd>
                      <SeverityBadge severity={incident.severity} />
                    </dd>
                  </div>
                  <div>
                    <dt>Owner</dt>
                    <dd>{incident.owner}</dd>
                  </div>
                  <div>
                    <dt>Affected executions</dt>
                    <dd className="mono">{incident.count}</dd>
                  </div>
                </dl>
                <div className="demo-activity">
                  <span>
                    <Clock3 size={13} /> Latest occurrence
                  </span>
                  <p>
                    {incident.time} · Failure attached to {incident.id}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    changeView("executions");
                    setRunId(
                      incident.id === "INC-27"
                        ? "1842"
                        : incident.id === "INC-26"
                          ? "1841"
                          : "1840",
                    );
                  }}
                >
                  View workflow’s latest run
                  <ArrowRight size={13} />
                </Button>
              </>
            )}
          </div>
        </div>
        <div className="demo-inbox-footer">
          <span>
            Try the filters, select a run, or open its linked incident.
          </span>
          <Button asChild variant="ghost" size="sm">
            <Link href={destination}>
              Open your workspace
              <ArrowRight size={13} />
            </Link>
          </Button>
        </div>
      </div>
    </section>
  );
}
