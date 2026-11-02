# n8n connection guide

## Connection modes

| Capability | API key + Error Workflow | Webhook only |
|---|---|---|
| Workflow discovery and grouped logic map | Yes | No; workflow identity comes from events |
| Saved execution reconciliation | Yes | No |
| Error Workflow failures | Yes | Yes |
| Trigger activation errors without execution ID | Yes | Yes |
| Native retry/replay | Disabled | Disabled |

The adapter uses public `/api/v1/workflows` and `/api/v1/executions` endpoints, `X-N8N-API-KEY`, and `nextCursor` pagination. It never calls n8n's private editor API. Grant `workflow:list`, `workflow:read`, `execution:list`, and `execution:read` where your n8n edition supports scoped keys. No workflow write/publish/execute permission is needed by FlowSentry. Rotate the key at n8n, then update the connection in FlowSentry. The credential is encrypted at rest and is not returned to the browser.

The workflow map stores node names, types, disabled flags, and graph edges. It excludes credentials, parameters, pinned data, and workflow settings. Linear chains are grouped into stages of up to four nodes; branch and merge boundaries remain separate. Labels describe the actual included nodes, not generated business interpretations. Expand a stage to inspect the original node names. Webhook-only connections cannot supply this definition.

## Configure an Error Workflow

1. In FlowSentry create a connection and copy its ingress URL and one-time token.
2. In n8n create a workflow with **Error Trigger → HTTP Request**.
3. Configure HTTP Request as `POST` to the ingress URL. Use a credential-backed `Authorization: Bearer <ingress-token>` header. Do not embed the token in a URL or share exported credentials.
4. Set content type to JSON and send the complete Error Trigger item as the JSON body, using `={{ $json }}` in expression mode.
5. Publish the Error Workflow, then select it as the Error Workflow in each monitored workflow's settings and publish that change. Wait for n8n's publication to complete before testing.
6. Trigger a production failure and verify the execution, incident, and notification in FlowSentry. Manual editor runs do not trigger n8n Error Workflows in the same way as production executions.

n8n sends either `workflow + execution` for an execution failure, or `workflow + trigger` for an activation failure. The latter may have no execution ID. FlowSentry accepts both and deduplicates repeated delivery. The ingress body limit is 256 KiB; avoid sending unrelated execution payloads. The token is shown once; use the rotate action if lost.

## Network and source limits

Private, loopback, link-local, and other non-public destinations are blocked unless `ALLOW_PRIVATE_NETWORK=true` is explicitly enabled for a trusted internal installation. Outbound requests resolve and validate addresses, pin the selected address, reject redirects, and cap decoded response size. Restrict egress at the network layer when private-network access is enabled. Do not point the connection at a load balancer that redirects API traffic; use the final HTTPS origin.

The default poll interval is 60 seconds. Polling only sees executions n8n saves. Webhooks reduce failure latency; polling reconciles missed webhook deliveries for saved executions. Permission errors, 429s, unavailability, and malformed responses are recorded as sync failures and retried with backoff. Large workflow/execution pages can exceed the response cap; reduce the configured backend poll page size or saved data volume.

## Compatibility verification

The local verification record in [release status](../release-status.md) identifies the n8n version actually exercised. Compatibility with an untested n8n release is not implied. Native recovery remains disabled pending a separately reviewed, version-specific operation and its durable recovery state machine.
