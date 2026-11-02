# FlowSentry interface

An independent monitoring application for n8n: a public landing page, setup guide, and operations workspace for investigating failures across instances. A dotted workflow canvas and compact operational hierarchy keep execution details readable. The app does not edit or execute n8n workflows.

- n8n-inspired dark ink canvas, charcoal panels, coral primary actions, and restrained purple accents. Green, amber, and red communicate observed status. An optional light theme preserves the same hierarchy.
- Geist Sans for interface text, Geist Mono for IDs and diagnostic values. Titles 26–28px, body 13–14px, metadata 11–12px. Tabular numerals for metrics.
- Compact navigation, 28–32px desktop page padding, 16px mobile padding, 8px control radius, 10–12px panel radius. Borders carry the hierarchy; shadows are limited to overlays.
- One primary action per view. Overview leads with operational status, execution volume, and active incidents. Lists link to canonical details. Integration connection has API and webhook-only modes with a one-time token step.
- Loading, no-data, permission, network failure, and disconnected stream states are explicit. Empty metrics are never populated with fabricated production activity.
- Mobile navigation uses an accessible sheet. Dialogs use Radix focus trapping, Escape dismissal, and focus return. All controls have labels and visible focus rings; reduced motion disables decoration.
- The shell owns one SSE connection. Events and reconnect trigger canonical refetch; a timed fallback refresh handles unavailable streams.

## Component provenance

Source primitives come from the official MIT shadcn registry at https://ui.shadcn.com/r/styles/new-york/. React Flow supplies the workflow graph as an MIT package. License notices are included in THIRD_PARTY_NOTICES.md.

The landing uses direct product descriptions, shadcn tabs/tables/accordion/buttons, and an example execution with a failed node, HTTP response, and linked incident. The sidebar uses workspace/account dropdowns with a compact search control. Sample records are explicitly labelled. Decorative status pills and promotional sidebar tiles are omitted.
