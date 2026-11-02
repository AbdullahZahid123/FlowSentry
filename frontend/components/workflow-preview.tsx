"use client";
import { useEffect, useState } from "react";
import {
  ReactFlow,
  Background,
  Position,
  type Node,
  type Edge,
} from "@xyflow/react";

import {
  Webhook,
  CreditCard,
  FileText,
  Check,
  X,
  Minus,
  Loader2,
} from "lucide-react";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { StatusBadge, SeverityBadge } from "@/components/ui";
import { useIsMobile } from "@/hooks/use-mobile";

const steps = [
  {
    id: "order",
    title: "Order received",
    icon: Webhook,
    detail: "Webhook · Completed",
    description:
      "The webhook received an order and passed it to the payment step.",
    output: '{ "orderId": "ORD-1048", "amount": 12900, "currency": "USD" }',
  },
  {
    id: "payment",
    title: "Charge payment",
    icon: CreditCard,
    detail: "HTTP Request · Failed",
    description: "The payment endpoint did not respond within 30 seconds.",
    output: '{ "statusCode": 504, "message": "Gateway Timeout" }',
  },
  {
    id: "invoice",
    title: "Create invoice",
    icon: FileText,
    detail: "Not executed",
    description:
      "This node did not run because the payment request failed. No invoice was created.",
    output: "No output. Previous node failed.",
  },
];
export default function WorkflowPreview() {
  const mobile = useIsMobile();
  const [phase, setPhase] = useState(3);
  const [selected, setSelected] = useState("payment");
  const [view, setView] = useState("node");
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = setTimeout(
      () => setPhase((p) => (p + 1) % 4),
      [900, 1600, 700, 4500][phase],
    );
    return () => clearTimeout(timer);
  }, [phase]);
  const nodes: Node[] = steps.map((s, index) => {
    const state =
      phase === 0
        ? index === 0
          ? "running"
          : "waiting"
        : phase === 1
          ? index === 0
            ? "success"
            : index === 1
              ? "running"
              : "waiting"
          : index === 0
            ? "success"
            : index === 1
              ? "failed"
              : "skipped";
    return {
      id: s.id,
      type: index === 0 ? "input" : index === 2 ? "output" : "default",
      position: mobile ? { x: 0, y: index * 90 } : { x: index * 190, y: 0 },
      className: `preview-node-${state}${selected === s.id ? " preview-node-selected" : ""}`,
      sourcePosition: mobile ? Position.Bottom : Position.Right,
      targetPosition: mobile ? Position.Top : Position.Left,
      ariaLabel: `${s.title}: ${state}. Show node details`,
      data: {
        label: (
          <button
            type="button"
            aria-label={`Inspect ${s.title}`}
            aria-pressed={selected === s.id}
            onClick={() => {
              setSelected(s.id);
              setView("node");
            }}
            className="preview-node-label"
          >
            <s.icon size={18} />
            <div>
              <strong>{s.title}</strong>
              <span>
                {state === "running"
                  ? "Running sample…"
                  : state === "waiting"
                    ? "Waiting"
                    : s.detail}
              </span>
            </div>
            <span className="preview-node-status">
              {state === "running" ? (
                <Loader2 size={12} className="animate-spin" />
              ) : state === "success" ? (
                <Check size={12} />
              ) : state === "failed" ? (
                <X size={12} />
              ) : (
                <Minus size={12} />
              )}
            </span>
          </button>
        ),
      },
    };
  });
  const edges: Edge[] = [
    {
      id: "order-payment",
      source: "order",
      target: "payment",
      type: "smoothstep",
      animated: phase === 1,
      style: { stroke: phase === 0 ? "#616270" : "#6aab87", strokeWidth: 1.4 },
    },
    {
      id: "payment-invoice",
      source: "payment",
      target: "invoice",
      type: "smoothstep",
      style: { stroke: "#616270", strokeWidth: 1.2, strokeDasharray: "4 4" },
    },
  ];
  const step = steps.find((s) => s.id === selected)!;
  const pending =
    selected === "order"
      ? phase === 0
      : selected === "payment"
        ? phase < 2
        : phase < 2;
  return (
    <Card className="workflow-preview">
      <CardHeader className="workflow-preview-header">
        <div>
          <h2>Invoice processing</h2>
          <span className="mono">Execution #1842 · Sample data</span>
        </div>
        <span className="sample-label">Animated sample</span>
      </CardHeader>
      <div
        className="workflow-preview-canvas"
        aria-label="Interactive sample workflow"
      >
        <ReactFlow
          key={mobile ? "phone" : "desktop"}
          nodes={nodes}
          edges={edges}
          fitView
          fitViewOptions={{ padding: mobile ? 0.18 : 0.12 }}
          onNodeClick={(_, node) => {
            setSelected(node.id);
            setView("node");
          }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          nodesFocusable={false}
          edgesFocusable={false}
          panOnDrag={false}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
          preventScrolling={false}

        >
          <Background color="#3a3a46" gap={16} size={0.7} />
        </ReactFlow>
      </div>
      <div className="preview-run-status">
        {phase === 0
          ? "Receiving the sample order…"
          : phase === 1
            ? "Calling the payment endpoint…"
            : phase === 2
              ? "Request failed. Grouping the error…"
              : "Sample complete · 1 failed node · Linked to INC-27"}
        <span>Click a node to inspect it</span>
      </div>
      <CardContent className="workflow-preview-details">
        <Tabs value={view} onValueChange={setView}>
          <TabsList aria-label="Example execution details">
            <TabsTrigger value="node">Node details</TabsTrigger>
            <TabsTrigger value="incident">Linked incident</TabsTrigger>
          </TabsList>
          <TabsContent value="node">
            <Alert
              className={
                selected === "payment" && !pending
                  ? "preview-error"
                  : "preview-node-info"
              }
            >
              <AlertTitle>
                {pending
                  ? `${step.title} · Waiting for result`
                  : selected === "payment"
                    ? "Payment request timed out"
                    : step.title}
              </AlertTitle>
              <AlertDescription>
                {pending
                  ? "The sample is progressing through this execution. No external request is sent."
                  : step.description}
              </AlertDescription>
            </Alert>
            <dl className="preview-error-meta">
              <div>
                <dt>Selected node</dt>
                <dd>{step.title}</dd>
              </div>
              <div>
                <dt>Output</dt>
                <dd className="mono preview-output">
                  {pending ? "Pending…" : step.output}
                </dd>
              </div>
            </dl>
          </TabsContent>
          <TabsContent value="incident">
            <div className="preview-linked-incident">
              <span className="mono text-xs text-muted-foreground">INC-27</span>
              <h3>Payment API timeout</h3>
              <div className="flex gap-2">
                <StatusBadge status="open" />
                <SeverityBadge severity="high" />
              </div>
              <p>
                12 failed executions share this workflow, node, and error
                fingerprint.
              </p>
              <dl>
                <div>
                  <dt>Owner</dt>
                  <dd>Unassigned</dd>
                </div>
                <div>
                  <dt>Latest occurrence</dt>
                  <dd className="mono">14:32:08</dd>
                </div>
              </dl>
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
